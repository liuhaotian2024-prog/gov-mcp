"""Tests for gov_mcp delegation-aware enforcement (Gap 1) and escalation (Gap 2).

These tests verify:
  Gap 1: gov_check uses delegated contract when agent has registered delegation
  Gap 2: gov_escalate allows permission expansion within principal's authority
"""
import json
import pytest

from ystar import (
    CheckResult,
    DelegationChain,
    DelegationContract,
    IntentContract,
    check,
)


# ---------------------------------------------------------------------------
# Inline _get_contract_for_agent (mirrors gov_mcp/server.py logic)
# Avoids importing gov_mcp.server which requires mcp package
# ---------------------------------------------------------------------------

def _get_contract_for_agent(agent_id, state):
    chain = state.delegation_chain
    if chain.root is not None and agent_id in chain.all_contracts:
        return chain.all_contracts[agent_id].contract
    for link in reversed(chain.links):
        if link.actor == agent_id:
            return link.contract
    return state.active_contract


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _MockState:
    """Minimal _State stub for testing contract resolution."""

    def __init__(self):
        self.active_contract = IntentContract(
            deny=["/etc", "/production"],
            deny_commands=["rm -rf", "sudo"],
        )
        self.delegation_chain = DelegationChain()


# ---------------------------------------------------------------------------
# Gap 1: delegation-aware contract resolution
# ---------------------------------------------------------------------------

class TestGetContractForAgent:

    def test_no_delegation_returns_global(self):
        state = _MockState()
        contract = _get_contract_for_agent("unknown-agent", state)
        assert contract is state.active_contract

    def test_linear_delegation_returns_delegated_contract(self):
        state = _MockState()
        eng_contract = IntentContract(
            deny=["/etc", "/production"],
            only_paths=["./src/core/"],
            deny_commands=["rm -rf", "sudo"],
        )
        link = DelegationContract(
            principal="cto",
            actor="engineer",
            contract=eng_contract,
        )
        state.delegation_chain.append(link)

        resolved = _get_contract_for_agent("engineer", state)
        assert resolved is eng_contract
        assert resolved is not state.active_contract

    def test_unregistered_agent_gets_global(self):
        """Agent not in delegation chain gets global contract."""
        state = _MockState()
        eng_contract = IntentContract(only_paths=["./src/core/"])
        link = DelegationContract(
            principal="cto", actor="engineer", contract=eng_contract,
        )
        state.delegation_chain.append(link)

        # "cmo" is not delegated — should get global
        resolved = _get_contract_for_agent("cmo", state)
        assert resolved is state.active_contract

    def test_delegated_contract_enforced_by_check(self):
        """Verify check() actually uses the delegated contract, not global."""
        state = _MockState()
        eng_contract = IntentContract(only_paths=["./src/core/"])
        link = DelegationContract(
            principal="cto", actor="engineer", contract=eng_contract,
        )
        state.delegation_chain.append(link)

        contract = _get_contract_for_agent("engineer", state)

        # Write to ./src/core/ → ALLOW
        r1 = check(
            params={"tool_name": "Write", "file_path": "./src/core/parser.py"},
            result={},
            contract=contract,
        )
        assert r1.passed

        # Write to ./src/utils/ → DENY (not in only_paths)
        r2 = check(
            params={"tool_name": "Write", "file_path": "./src/utils/helpers.py"},
            result={},
            contract=contract,
        )
        assert not r2.passed

    def test_multiple_agents_different_contracts(self):
        state = _MockState()

        cto_contract = IntentContract(only_paths=["./src/"])
        eng_contract = IntentContract(only_paths=["./src/core/"])

        state.delegation_chain.append(DelegationContract(
            principal="ceo", actor="cto", contract=cto_contract,
        ))
        state.delegation_chain.append(DelegationContract(
            principal="cto", actor="engineer", contract=eng_contract,
        ))

        assert _get_contract_for_agent("cto", state).only_paths == ["./src/"]
        assert _get_contract_for_agent("engineer", state).only_paths == ["./src/core/"]
        assert _get_contract_for_agent("ceo", state) is state.active_contract


# ---------------------------------------------------------------------------
# Gap 1: the actual deadlock scenario from Board
# ---------------------------------------------------------------------------

class TestDelegationDeadlockScenario:
    """
    CEO → CTO (only ./src/)
      CTO → Engineer (only ./src/core/)
        Engineer writes ./src/utils/ → DENY
    """

    def test_engineer_denied_outside_scope(self):
        state = _MockState()

        cto_contract = IntentContract(
            only_paths=["./src/"],
            deny=["/etc", "/production"],
            deny_commands=["rm -rf", "sudo"],
        )
        eng_contract = IntentContract(
            only_paths=["./src/core/"],
            deny=["/etc", "/production"],
            deny_commands=["rm -rf", "sudo"],
        )

        state.delegation_chain.append(DelegationContract(
            principal="ceo", actor="cto", contract=cto_contract,
            allow_redelegate=True, delegation_depth=1,
        ))
        state.delegation_chain.append(DelegationContract(
            principal="cto", actor="engineer", contract=eng_contract,
        ))

        contract = _get_contract_for_agent("engineer", state)

        # Engineer writes to allowed path → ALLOW
        r1 = check(
            params={"tool_name": "Write", "file_path": "./src/core/parser.py"},
            result={}, contract=contract,
        )
        assert r1.passed

        # Engineer writes outside scope → DENY
        r2 = check(
            params={"tool_name": "Write", "file_path": "./src/utils/helpers.py"},
            result={}, contract=contract,
        )
        assert not r2.passed
        assert any("only_paths" in v.dimension for v in r2.violations)


# ---------------------------------------------------------------------------
# Monotonicity Rejection (2026-04-13 Fix: P1 Root Cause grant 4a5fd844)
# ---------------------------------------------------------------------------

class TestDelegationMonotonicityRejection:
    """
    Test that gov_delegate REJECTS grants that violate monotonicity at registration time.

    Background: Grant 4a5fd844 (cto→eng-platform) violated monotonicity but was
    accepted with warnings. Fix (v0.49.0) validates BEFORE appending to chain.

    Root cause report: reports/p1_delegation_monotonicity_rootcause_20260413.md
    """

    def test_gov_delegate_accepts_valid_subset(self):
        """Valid child grant (subset of parent) should be accepted."""
        state = _MockState()

        # Parent grant: ceo→cto
        parent_contract = IntentContract(
            deny=[],
            only_paths=["reports/", "scripts/"],
            deny_commands=["--no-verify", "sudo"],
        )
        parent_link = DelegationContract(
            principal="ceo",
            actor="cto",
            contract=parent_contract,
            action_scope=["read", "write"],
            allow_redelegate=True,
            delegation_depth=2,
        )
        state.delegation_chain.append(parent_link)

        # Child grant: cto→eng-platform (valid subset)
        child_contract = IntentContract(
            deny=[],
            only_paths=["reports/proposals/"],  # ← Subset of parent
            deny_commands=["--no-verify", "sudo", "git push"],  # ← Superset deny OK
        )
        child_link = DelegationContract(
            principal="cto",
            actor="eng-platform",
            contract=child_contract,
            action_scope=["read"],  # ← Subset of parent
            allow_redelegate=False,
            delegation_depth=0,
        )

        # Validate before append (mimics server.py fix)
        temp_chain = DelegationChain(links=state.delegation_chain.links.copy())
        temp_chain.append(child_link)
        issues = temp_chain.validate()

        assert len(issues) == 0, f"Valid grant rejected: {issues}"

        # Should accept
        state.delegation_chain.append(child_link)
        assert state.delegation_chain.depth == 2

    def test_gov_delegate_rejects_expanded_paths(self):
        """Child grant that expands only_paths should be REJECTED."""
        state = _MockState()

        # Parent grant: ceo→cto
        parent_contract = IntentContract(
            deny=[],
            only_paths=["reports/", "scripts/"],
            deny_commands=["--no-verify", "sudo"],
        )
        parent_link = DelegationContract(
            principal="ceo",
            actor="cto",
            contract=parent_contract,
            action_scope=["read", "write"],
            allow_redelegate=True,
            delegation_depth=2,
        )
        state.delegation_chain.append(parent_link)

        # Child grant: cto→eng-platform (VIOLATES monotonicity)
        child_contract = IntentContract(
            deny=[],
            only_paths=["/workspace/", "/Y-star-gov/"],  # ← Expanded beyond parent
            deny_commands=["--no-verify", "sudo"],
        )
        child_link = DelegationContract(
            principal="cto",
            actor="eng-platform",
            contract=child_contract,
            action_scope=["read", "write"],
            allow_redelegate=False,
            delegation_depth=0,
        )

        # Validate before append (mimics server.py fix)
        temp_chain = DelegationChain(links=state.delegation_chain.links.copy())
        temp_chain.append(child_link)
        issues = temp_chain.validate()

        # Should have monotonicity violation
        assert len(issues) > 0, "Expected monotonicity violation"
        assert any("only_paths" in issue.lower() or "subset" in issue.lower() for issue in issues)

        # Should NOT append to real chain
        # (In server.py, this would return {"registered": False})
        assert state.delegation_chain.depth == 1  # Only parent

    def test_gov_delegate_rejects_expanded_action_scope(self):
        """Child grant that expands action_scope should be REJECTED."""
        state = _MockState()

        # Parent grant: ceo→cto
        parent_contract = IntentContract(deny=[], only_paths=["reports/"])
        parent_link = DelegationContract(
            principal="ceo",
            actor="cto",
            contract=parent_contract,
            action_scope=["read", "write"],  # ← Limited scope
            allow_redelegate=True,
            delegation_depth=2,
        )
        state.delegation_chain.append(parent_link)

        # Child grant: cto→eng-platform (VIOLATES action_scope monotonicity)
        child_contract = IntentContract(deny=[], only_paths=["reports/"])
        child_link = DelegationContract(
            principal="cto",
            actor="eng-platform",
            contract=child_contract,
            action_scope=["read", "write", "bash", "git_commit"],  # ← Expanded
            allow_redelegate=False,
            delegation_depth=0,
        )

        # Validate before append
        temp_chain = DelegationChain(links=state.delegation_chain.links.copy())
        temp_chain.append(child_link)
        issues = temp_chain.validate()

        # Should detect action_scope expansion
        assert len(issues) > 0, "Expected action_scope violation"
        assert any("action_scope" in issue.lower() for issue in issues)

        # Should NOT append
        assert state.delegation_chain.depth == 1

    def test_gov_delegate_rejects_removed_deny_restrictions(self):
        """Child grant that removes parent's deny restrictions should be REJECTED."""
        state = _MockState()

        # Parent grant: ceo→cto
        parent_contract = IntentContract(
            deny=[],
            deny_commands=["--no-verify", "sudo"],  # ← Parent restricts these
        )
        parent_link = DelegationContract(
            principal="ceo",
            actor="cto",
            contract=parent_contract,
            allow_redelegate=True,
            delegation_depth=2,
        )
        state.delegation_chain.append(parent_link)

        # Child grant: cto→eng-platform (removes deny_commands restriction)
        child_contract = IntentContract(
            deny=[],
            deny_commands=["--no-verify"],  # ← Missing "sudo" = expansion
        )
        child_link = DelegationContract(
            principal="cto",
            actor="eng-platform",
            contract=child_contract,
            allow_redelegate=False,
            delegation_depth=0,
        )

        # Validate
        temp_chain = DelegationChain(links=state.delegation_chain.links.copy())
        temp_chain.append(child_link)
        issues = temp_chain.validate()

        # Should detect deny_commands violation
        assert len(issues) > 0, "Expected deny_commands violation"

        # Should NOT append
        assert state.delegation_chain.depth == 1

    def test_historical_grant_4a5fd844_scenario(self):
        """
        Reproduce the exact grant 4a5fd844 violation scenario.

        Parent (ceo→cto):
          only_paths=["reports/", "scripts/", "governance/", ".ystar_session.json"]
          action_scope=["read", "write"]

        Child (cto→eng-platform):
          only_paths=[workspace root, Y-star-gov repo]  ← EXPANDED
          action_scope=["bash", "git_commit", "read", "write"]  ← EXPANDED

        This grant was accepted in old code (append-then-warn).
        New code (validate-then-reject) must REJECT it.
        """
        state = _MockState()

        # Parent grant (ceo→cto)
        parent_contract = IntentContract(
            deny=[],
            only_paths=["reports/", "scripts/", "governance/", ".ystar_session.json"],
            deny_commands=["--no-verify", "chmod +x", "git push", "sudo"],
        )
        parent_link = DelegationContract(
            principal="ceo",
            actor="cto",
            contract=parent_contract,
            action_scope=["read", "write"],
            allow_redelegate=True,
            delegation_depth=2,
        )
        state.delegation_chain.append(parent_link)

        # Child grant (cto→eng-platform) — GRANT 4a5fd844
        child_contract = IntentContract(
            deny=[],
            only_paths=[
                "/Users/haotianliu/.openclaw/workspace/ystar-company/",
                "/Users/haotianliu/.openclaw/workspace/Y-star-gov/",
            ],  # ← Expanded to workspace roots
            deny_commands=["--no-verify", "chmod +x", "git push", "sudo"],
        )
        child_link = DelegationContract(
            principal="cto",
            actor="eng-platform",
            contract=child_contract,
            action_scope=["bash", "git_commit", "read", "write"],  # ← Expanded
            allow_redelegate=False,
            delegation_depth=0,
        )

        # Validate before append
        temp_chain = DelegationChain(links=state.delegation_chain.links.copy())
        temp_chain.append(child_link)
        issues = temp_chain.validate()

        # MUST reject (multiple violations: only_paths + action_scope)
        assert len(issues) > 0, "Grant 4a5fd844 must be rejected"

        # Check specific violations
        issues_str = " ".join(issues).lower()
        assert ("only_paths" in issues_str or "subset" in issues_str), \
            f"Expected only_paths violation, got: {issues}"
        assert "action_scope" in issues_str, \
            f"Expected action_scope violation, got: {issues}"

        # Chain must remain depth=1 (only parent)
        assert state.delegation_chain.depth == 1
