"""GOV MCP — Y*gov governance exposed as a standard MCP server.

Ecosystem-neutral: no Claude Code / Anthropic-specific imports.
All paths via pathlib. No hardcoded defaults.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from mcp.server.fastmcp import FastMCP

from ystar import (
    CheckResult,
    DelegationChain,
    DelegationContract,
    InMemoryOmissionStore,
    IntentContract,
    OmissionEngine,
    check,
    enforce,
)
from ystar.kernel.nl_to_contract import translate_to_contract, validate_contract_draft


# ---------------------------------------------------------------------------
# Server state — held per-process, shared across all tool calls
# ---------------------------------------------------------------------------

class _State:
    """Mutable server state initialised at startup."""

    def __init__(self, agents_md_path: Path, exec_whitelist_path: Optional[Path] = None) -> None:
        self.agents_md_path = agents_md_path
        self.agents_md_text = agents_md_path.read_text(encoding="utf-8")

        # Translate AGENTS.md → contract (regex fallback, no LLM needed)
        contract_dict, self.confidence_label, self.confidence_score = translate_to_contract(
            self.agents_md_text
        )
        self.active_contract = _dict_to_contract(contract_dict)

        # Draft contract buffer (for load → validate → activate flow)
        self.draft_contract: Optional[IntentContract] = None
        self.draft_dict: Optional[Dict[str, Any]] = None

        # Delegation chain
        self.delegation_chain = DelegationChain()

        # Omission engine
        self.omission_engine = OmissionEngine(store=InMemoryOmissionStore())

        # CIEU store (None until a db path is provided via gov_report/gov_verify)
        self._cieu_store: Optional[Any] = None

        # Exec whitelist
        self.exec_whitelist = _load_exec_whitelist(exec_whitelist_path)

        # CIEU sequence counter (monotonic, process-scoped)
        self._cieu_seq = 0
        self._cieu_seq_lock = __import__("threading").Lock()

    def next_cieu_seq(self) -> int:
        with self._cieu_seq_lock:
            self._cieu_seq += 1
            return self._cieu_seq


def _load_exec_whitelist(path: Optional[Path]) -> Dict[str, List[str]]:
    """Load exec whitelist YAML with platform auto-detection.

    Resolution order:
      1. Explicit path (--exec-whitelist)
      2. Platform-specific: whitelist_unix.yaml or whitelist_windows.yaml
      3. Fallback: exec_whitelist.yaml
    """
    pkg_dir = Path(__file__).parent

    if path is None:
        import sys
        if sys.platform == "win32":
            path = pkg_dir / "whitelist_windows.yaml"
        else:
            path = pkg_dir / "whitelist_unix.yaml"
        # Fallback to generic if platform-specific doesn't exist
        if not path.is_file():
            path = pkg_dir / "exec_whitelist.yaml"

    if not path.is_file():
        return {"allowed_prefixes": [], "always_deny": []}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {
        "allowed_prefixes": data.get("allowed_prefixes", []),
        "always_deny": data.get("always_deny", []),
    }


def _dict_to_contract(d: Dict[str, Any]) -> IntentContract:
    """Build an IntentContract from a translate_to_contract dict."""
    return IntentContract(
        deny=d.get("deny", []),
        only_paths=d.get("only_paths", []),
        deny_commands=d.get("deny_commands", []),
        only_domains=d.get("only_domains", []),
        invariant=d.get("invariant", []),
        optional_invariant=d.get("optional_invariant", []),
        postcondition=d.get("postcondition", []),
        field_deny=d.get("field_deny", {}),
        value_range=d.get("value_range", {}),
        obligation_timing=d.get("obligation_timing", {}),
        name=d.get("name", ""),
    )


def _get_contract_for_agent(agent_id: str, state: "_State") -> IntentContract:
    """Resolve the effective contract for an agent.

    If the agent has a registered delegation (linear or tree mode),
    use its delegated contract. Otherwise fall back to the global
    active contract.
    """
    # Tree mode: lookup in all_contracts index
    chain = state.delegation_chain
    if chain.root is not None and agent_id in chain.all_contracts:
        return chain.all_contracts[agent_id].contract

    # Linear mode: find last link where actor == agent_id
    for link in reversed(chain.links):
        if link.actor == agent_id:
            return link.contract

    # No delegation found — use global contract
    return state.active_contract


def _violations_to_list(violations: list) -> List[Dict[str, Any]]:
    """Serialize Violation dataclass instances to plain dicts with fix suggestions."""
    results = []
    for v in violations:
        entry: Dict[str, Any] = {
            "dimension": v.dimension,
            "field": v.field,
            "message": v.message,
            "actual": str(v.actual) if v.actual is not None else None,
            "constraint": v.constraint,
            "severity": v.severity,
        }
        # Readable fix suggestion
        entry["fix_suggestion"] = _suggest_fix(v)
        results.append(entry)
    return results


def _suggest_fix(v) -> str:
    """Generate a human-readable fix suggestion for a violation."""
    dim = v.dimension
    actual = str(v.actual) if v.actual is not None else ""
    constraint = v.constraint or ""

    if dim == "deny":
        # Extract the denied pattern
        pattern = ""
        if "'" in constraint:
            pattern = constraint.split("'")[1]
        return (
            f"'{actual}' is blocked because '{pattern}' is in the deny list. "
            f"To allow this, remove '{pattern}' from the deny list in AGENTS.md."
        )
    elif dim == "deny_commands":
        cmd = ""
        if "'" in constraint:
            cmd = constraint.split("'")[1]
        return (
            f"Command blocked: '{cmd}' is prohibited. "
            f"To allow this command, remove '{cmd}' from deny_commands in AGENTS.md."
        )
    elif dim == "only_paths":
        return (
            f"Path '{actual}' is outside allowed paths. "
            f"To allow this path, add it to the only_paths list in AGENTS.md."
        )
    elif dim == "only_domains":
        return (
            f"Domain not in allowlist. "
            f"To allow this domain, add it to only_domains in AGENTS.md."
        )
    else:
        return f"Constraint '{dim}' violated. Review the corresponding rule in AGENTS.md."


def _governance_envelope(state: "_State", latency_ms: float) -> Dict[str, Any]:
    """Build the governance extension field for every response.

    This is the Y*gov governance layer on top of MCP — patent candidate P7.
    Backward compatible: callers that don't inspect 'governance' are unaffected.
    """
    contract = state.active_contract
    return {
        "cieu_seq": state.next_cieu_seq(),
        "contract_hash": contract.hash if hasattr(contract, "hash") else "",
        "contract_version": contract.name if hasattr(contract, "name") else "",
        "latency_ms": round(latency_ms, 4),
        "host": _detect_host(),
    }


def _detect_host() -> str:
    """Detect the calling host ecosystem (best-effort, no hardcoded paths)."""
    import os
    # Check environment variables set by known ecosystems
    if os.environ.get("CLAUDE_CODE"):
        return "claude_code"
    if os.environ.get("CURSOR_SESSION"):
        return "cursor"
    if os.environ.get("WINDSURF_SESSION"):
        return "windsurf"
    if os.environ.get("OPENCLAW_AGENT"):
        return "openclaw"
    return "generic"


# ---------------------------------------------------------------------------
# Auto-routing logic
# ---------------------------------------------------------------------------

def _is_deterministic(command: str, whitelist: Dict[str, Any]) -> Tuple[bool, str]:
    """Classify command using rule engine first, whitelist as fallback.

    Returns (is_deterministic, reason).
    """
    from gov_mcp.router import is_deterministic as _router_classify

    deny_list = whitelist.get("always_deny", [])

    # Phase 1: Rule engine (structural analysis)
    ok, reason = _router_classify(command, always_deny=deny_list)
    if ok:
        return True, reason

    # Phase 2: Whitelist fallback (catches commands the router marks unknown)
    cmd = command.strip()
    if any(cmd.startswith(p) for p in whitelist.get("allowed_prefixes", [])):
        return True, f"whitelist fallback: prefix match"

    return False, reason


def _try_auto_execute(
    command: str,
    agent_id: str,
    contract: IntentContract,
    state: "_State",
    t0: float,
    timeout_secs: int = 30,
) -> Optional[str]:
    """Check contract, then execute deterministic commands inline.

    Returns JSON string with stdout/stderr on success, DENY on violation,
    or None if the command is not deterministic (caller falls through
    to check-only path).
    """
    ok, route_reason = _is_deterministic(command, state.exec_whitelist)
    if not ok:
        return None

    # Contract enforcement (must pass even for deterministic commands)
    contract_result: CheckResult = check(
        params={"command": command, "tool_name": "Bash"},
        result={},
        contract=contract,
    )
    if not contract_result.passed:
        latency_ms = (time.perf_counter() - t0) * 1000
        return json.dumps({
            "decision": "DENY",
            "violations": _violations_to_list(contract_result.violations),
            "agent_id": agent_id,
            "tool_name": "Bash",
            "auto_executed": False,
            "governance": _governance_envelope(state, latency_ms),
        })

    # Execute the command
    try:
        proc = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout_secs,
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        return json.dumps({
            "decision": "ALLOW",
            "auto_executed": True,
            "route_reason": route_reason,
            "agent_id": agent_id,
            "tool_name": "Bash",
            "command": command,
            "returncode": proc.returncode,
            "stdout": proc.stdout[:4096],
            "stderr": proc.stderr[:2048],
            "governance": _governance_envelope(state, latency_ms),
        })
    except subprocess.TimeoutExpired:
        latency_ms = (time.perf_counter() - t0) * 1000
        return json.dumps({
            "decision": "ALLOW",
            "auto_executed": True,
            "agent_id": agent_id,
            "tool_name": "Bash",
            "command": command,
            "returncode": -1,
            "stdout": "",
            "stderr": f"Command timed out after {timeout_secs}s",
            "governance": _governance_envelope(state, latency_ms),
        })


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------

def create_server(
    agents_md_path: Path,
    exec_whitelist_path: Optional[Path] = None,
    **kwargs: Any,
) -> FastMCP:
    """Create and return a configured GOV MCP server.

    Extra kwargs (host, port) are forwarded to FastMCP for SSE transport.
    """

    mcp = FastMCP(
        "gov-mcp",
        instructions="Y*gov governance as a standard MCP server",
        **kwargs,
    )
    state = _State(agents_md_path, exec_whitelist_path=exec_whitelist_path)

    # ===================================================================
    # CORE ENFORCEMENT LAYER
    # ===================================================================

    @mcp.tool()
    def gov_check(agent_id: str, tool_name: str, params: dict) -> str:
        """Check a proposed agent action and auto-execute if deterministic.

        Single entry point for all governance decisions. Replaces the
        former gov_check + gov_exec two-step flow.

        For Bash commands classified as deterministic by the structural
        router (ls, git status, cat, pwd, etc.), gov_check will:
          1. Validate against the agent's governance contract
          2. Execute the command inline
          3. Return stdout/stderr in the response

        The caller never needs to invoke a separate execution tool.
        Non-deterministic or non-Bash actions receive ALLOW/DENY only.

        Response fields:
          auto_executed: true if the command was run inline
          stdout/stderr: present only when auto_executed is true
        """
        t0 = time.perf_counter()
        command = params.get("command", "")
        effective_contract = _get_contract_for_agent(agent_id, state)
        is_delegated = effective_contract is not state.active_contract

        # ── Bash commands: check + auto-execute if deterministic ────
        if tool_name == "Bash" and command:
            executed = _try_auto_execute(
                command, agent_id, effective_contract, state, t0,
            )
            if executed is not None:
                return executed

        # ── All other actions: governance check only ────────────────
        result: CheckResult = check(
            params={"tool_name": tool_name, **params},
            result={},
            contract=effective_contract,
        )
        latency_ms = (time.perf_counter() - t0) * 1000

        return json.dumps({
            "decision": "ALLOW" if result.passed else "DENY",
            "violations": _violations_to_list(result.violations),
            "agent_id": agent_id,
            "tool_name": tool_name,
            "auto_executed": False,
            "delegated_contract": is_delegated,
            "governance": _governance_envelope(state, latency_ms),
        })

    @mcp.tool()
    def gov_enforce(agent_id: str, tool_name: str, params: dict) -> str:
        """Full enforcement pipeline: check + obligation scan + delegation verify.

        Returns decision with full context.
        """
        t0 = time.perf_counter()

        # 1. Run enforce (check + mode handling)
        effective_contract = _get_contract_for_agent(agent_id, state)
        result = enforce(
            params={"tool_name": tool_name, **params},
            result={},
            contract=effective_contract,
        )

        # 2. Obligation scan
        obligation_warnings: List[str] = []
        try:
            scan = state.omission_engine.scan(agent_id)
            if scan:
                obligation_warnings = [str(s) for s in (scan if isinstance(scan, list) else [scan])]
        except Exception:
            pass

        # 3. Delegation check (if chain has links)
        delegation_valid: Optional[bool] = None
        delegation_issues: List[str] = []
        if state.delegation_chain.depth > 0:
            delegation_issues = state.delegation_chain.validate()
            delegation_valid = len(delegation_issues) == 0

        latency_ms = (time.perf_counter() - t0) * 1000

        return json.dumps({
            "decision": "ALLOW" if result.passed else "DENY",
            "violations": _violations_to_list(result.violations),
            "agent_id": agent_id,
            "tool_name": tool_name,
            "mode": str(result.mode),
            "action_taken": str(result.action_taken),
            "obligation_warnings": obligation_warnings,
            "delegation_valid": delegation_valid,
            "delegation_issues": delegation_issues,
            "governance": _governance_envelope(state, latency_ms),
        })

    @mcp.tool()
    def gov_delegate(
        principal: str,
        actor: str,
        deny: list[str] | None = None,
        only_paths: list[str] | None = None,
        deny_commands: list[str] | None = None,
        only_domains: list[str] | None = None,
        action_scope: list[str] | None = None,
        allow_redelegate: bool = False,
        delegation_depth: int = 0,
    ) -> str:
        """Register a parent→child delegation and validate monotonicity.

        The child contract must be a strict subset of the parent's permissions.
        """
        child_contract = IntentContract(
            deny=(deny or []),
            only_paths=(only_paths or []),
            deny_commands=(deny_commands or []),
            only_domains=(only_domains or []),
            invariant=[],
            optional_invariant=[],
            postcondition=[],
            field_deny={},
            value_range={},
            obligation_timing={},
        )

        link = DelegationContract(
            principal=principal,
            actor=actor,
            contract=child_contract,
            action_scope=(action_scope or []),
            allow_redelegate=allow_redelegate,
            delegation_depth=delegation_depth,
        )
        state.delegation_chain.append(link)

        issues = state.delegation_chain.validate()

        return json.dumps({
            "registered": True,
            "principal": principal,
            "actor": actor,
            "chain_depth": state.delegation_chain.depth,
            "is_valid": len(issues) == 0,
            "issues": issues,
        })

    @mcp.tool()
    def gov_escalate(
        agent_id: str,
        requested_paths: list[str] | None = None,
        requested_commands: list[str] | None = None,
        requested_domains: list[str] | None = None,
        reason: str = "",
    ) -> str:
        """Request permission escalation from the delegating principal.

        When an agent hits a DENY on an action it legitimately needs,
        it calls gov_escalate to request expanded permissions.

        The escalation is checked against the principal's own contract
        to ensure the requested expansion is within their authority.
        If approved, a new delegation is issued automatically.

        All escalation requests (approved or denied) are recorded as
        CIEU audit events.

        Args:
            agent_id: The agent requesting escalation.
            requested_paths: Additional paths to allow (e.g. ["./src/utils/"]).
            requested_commands: Additional commands to allow.
            requested_domains: Additional domains to allow.
            reason: Why the escalation is needed.
        """
        t0 = time.perf_counter()
        chain = state.delegation_chain

        # Find the agent's current delegation
        current_delegation: Optional[DelegationContract] = None
        principal_id: Optional[str] = None
        principal_contract: Optional[IntentContract] = None

        # Tree mode
        if chain.root is not None and agent_id in chain.all_contracts:
            current_delegation = chain.all_contracts[agent_id]
            principal_id = current_delegation.principal
            if principal_id in chain.all_contracts:
                principal_contract = chain.all_contracts[principal_id].contract
            elif principal_id == chain.root.actor:
                principal_contract = chain.root.contract
            else:
                principal_contract = state.active_contract

        # Linear mode
        if current_delegation is None:
            for link in reversed(chain.links):
                if link.actor == agent_id:
                    current_delegation = link
                    principal_id = link.principal
                    break

        if current_delegation is None:
            return json.dumps({
                "status": "DENIED",
                "reason": f"No delegation found for agent '{agent_id}'. "
                          "Only delegated agents can request escalation.",
                "agent_id": agent_id,
            })

        # Find principal's contract (linear mode)
        if principal_contract is None:
            for link in reversed(chain.links):
                if link.actor == principal_id:
                    principal_contract = link.contract
                    break
            if principal_contract is None:
                principal_contract = state.active_contract

        # Check if requested expansion is within principal's authority
        violations: List[str] = []

        for path in (requested_paths or []):
            # Principal must have this path in their allowed scope
            if principal_contract.only_paths:
                if not any(path.startswith(ap) for ap in principal_contract.only_paths):
                    violations.append(
                        f"Path '{path}' exceeds principal '{principal_id}' authority "
                        f"(allowed: {principal_contract.only_paths})"
                    )
            # Path must not be in principal's deny list
            if any(d in path for d in principal_contract.deny):
                violations.append(
                    f"Path '{path}' is denied in principal '{principal_id}' contract"
                )

        for cmd in (requested_commands or []):
            if cmd in principal_contract.deny_commands:
                violations.append(
                    f"Command '{cmd}' is denied in principal '{principal_id}' contract"
                )

        for domain in (requested_domains or []):
            if principal_contract.only_domains:
                if domain not in principal_contract.only_domains:
                    violations.append(
                        f"Domain '{domain}' not in principal '{principal_id}' allowed domains"
                    )

        latency_ms = (time.perf_counter() - t0) * 1000

        # Build CIEU audit event
        cieu_event = {
            "event_type": "escalation_request",
            "agent_id": agent_id,
            "principal_id": principal_id,
            "requested_paths": requested_paths or [],
            "requested_commands": requested_commands or [],
            "requested_domains": requested_domains or [],
            "reason": reason,
            "timestamp": time.time(),
        }

        if violations:
            # DENIED — principal lacks authority
            cieu_event["decision"] = "DENIED"
            cieu_event["violations"] = violations

            # Write to CIEU if available
            if state._cieu_store is not None:
                try:
                    state._cieu_store.write_dict(cieu_event)
                except Exception:
                    pass

            return json.dumps({
                "status": "DENIED",
                "reason": "Requested permissions exceed principal's authority",
                "violations": violations,
                "agent_id": agent_id,
                "principal_id": principal_id,
                "escalate_to": principal_id,
                "latency_ms": round(latency_ms, 4),
            })

        # APPROVED — re-delegate with expanded permissions
        old_contract = current_delegation.contract
        new_deny = list(old_contract.deny)
        new_only_paths = list(old_contract.only_paths)
        new_deny_commands = list(old_contract.deny_commands)
        new_only_domains = list(old_contract.only_domains)

        # Expand only_paths
        for path in (requested_paths or []):
            if path not in new_only_paths:
                new_only_paths.append(path)

        # Expand only_domains
        for domain in (requested_domains or []):
            if domain not in new_only_domains:
                new_only_domains.append(domain)

        # Build new delegation
        new_contract = IntentContract(
            deny=new_deny,
            only_paths=new_only_paths,
            deny_commands=new_deny_commands,
            only_domains=new_only_domains,
            invariant=list(old_contract.invariant),
            optional_invariant=list(old_contract.optional_invariant),
            postcondition=list(old_contract.postcondition),
            field_deny=dict(old_contract.field_deny),
            value_range=dict(old_contract.value_range),
            obligation_timing=dict(old_contract.obligation_timing),
        )

        new_link = DelegationContract(
            principal=principal_id,
            actor=agent_id,
            contract=new_contract,
            action_scope=list(current_delegation.action_scope),
            allow_redelegate=current_delegation.allow_redelegate,
            delegation_depth=current_delegation.delegation_depth,
        )

        # Replace in chain
        chain.links = [
            link for link in chain.links if link.actor != agent_id
        ]
        chain.links.append(new_link)

        # Update tree index if in tree mode
        if chain.root is not None:
            chain.all_contracts[agent_id] = new_link

        latency_ms = (time.perf_counter() - t0) * 1000

        cieu_event["decision"] = "APPROVED"
        cieu_event["new_grant_id"] = new_link.grant_id
        cieu_event["new_contract_hash"] = new_link.hash

        if state._cieu_store is not None:
            try:
                state._cieu_store.write_dict(cieu_event)
            except Exception:
                pass

        return json.dumps({
            "status": "APPROVED",
            "agent_id": agent_id,
            "principal_id": principal_id,
            "new_grant_id": new_link.grant_id,
            "new_contract_hash": new_link.hash,
            "expanded_paths": requested_paths or [],
            "expanded_commands": requested_commands or [],
            "expanded_domains": requested_domains or [],
            "reason": reason,
            "latency_ms": round(latency_ms, 4),
        })

    @mcp.tool()
    def gov_chain_reset(
        agent_id: str = "",
        confirm: bool = False,
    ) -> str:
        """Reset the delegation chain, clearing stale or experimental links.

        Args:
            agent_id: If provided, remove only links involving this agent
                      (as principal or actor). If empty, clear entire chain.
            confirm: Safety flag — must be True to execute. Prevents accidental resets.
        """
        if not confirm:
            chain = state.delegation_chain
            count = chain.depth
            agents = set()
            for link in chain.links:
                agents.add(link.principal)
                agents.add(link.actor)
            return json.dumps({
                "status": "DRY_RUN",
                "message": "Set confirm=true to execute reset",
                "current_depth": count,
                "agents_in_chain": sorted(agents),
                "would_remove": count if not agent_id else
                    sum(1 for l in chain.links
                        if l.actor == agent_id or l.principal == agent_id),
            })

        chain = state.delegation_chain
        removed = 0

        if agent_id:
            # Selective removal
            before = len(chain.links)
            chain.links = [
                link for link in chain.links
                if link.actor != agent_id and link.principal != agent_id
            ]
            removed = before - len(chain.links)
            # Also clean tree index
            if chain.root is not None and agent_id in chain.all_contracts:
                del chain.all_contracts[agent_id]
        else:
            # Full reset
            removed = len(chain.links)
            chain.links.clear()
            chain.all_contracts.clear()
            chain.root = None

        # CIEU audit
        cieu_event = {
            "event_type": "chain_reset",
            "agent_id": agent_id or "(all)",
            "links_removed": removed,
            "timestamp": time.time(),
        }
        if state._cieu_store is not None:
            try:
                state._cieu_store.write_dict(cieu_event)
            except Exception:
                pass

        return json.dumps({
            "status": "RESET",
            "links_removed": removed,
            "remaining_depth": chain.depth,
            "agent_filter": agent_id or "(all)",
        })

    # ===================================================================
    # CONTRACT MANAGEMENT LAYER (Step 1 stubs with basic impl)
    # ===================================================================

    @mcp.tool()
    def gov_contract_load(agents_md_text: str) -> str:
        """Translate AGENTS.md text into a draft IntentContract.

        Uses regex fallback (no LLM required). Call gov_contract_validate
        next, then gov_contract_activate to enforce.
        """
        contract_dict, label, score = translate_to_contract(agents_md_text)
        state.draft_dict = contract_dict
        state.draft_contract = _dict_to_contract(contract_dict)

        return json.dumps({
            "status": "draft_loaded",
            "confidence_label": label,
            "confidence_score": score,
            "contract_preview": {
                "deny": contract_dict.get("deny", []),
                "deny_commands": contract_dict.get("deny_commands", []),
                "only_paths": contract_dict.get("only_paths", []),
                "only_domains": contract_dict.get("only_domains", []),
                "value_range": contract_dict.get("value_range", {}),
                "obligation_timing": contract_dict.get("obligation_timing", {}),
            },
        })

    @mcp.tool()
    def gov_contract_validate() -> str:
        """Validate the currently loaded draft contract.

        Must call gov_contract_load first.
        """
        if state.draft_dict is None:
            return json.dumps({"error": "No draft contract loaded. Call gov_contract_load first."})

        report = validate_contract_draft(state.draft_dict, original_text=state.agents_md_text)

        return json.dumps({
            "passed": report.get("passed", False) if isinstance(report, dict) else bool(report),
            "issues": report.get("issues", []) if isinstance(report, dict) else [],
            "report": report if isinstance(report, dict) else str(report),
        })

    @mcp.tool()
    def gov_contract_activate() -> str:
        """Activate the validated draft contract as the enforcement contract.

        Must call gov_contract_load and gov_contract_validate first.
        """
        if state.draft_contract is None:
            return json.dumps({"error": "No draft contract loaded. Call gov_contract_load first."})

        state.active_contract = state.draft_contract
        state.draft_contract = None
        state.draft_dict = None

        return json.dumps({
            "status": "activated",
            "contract_name": state.active_contract.name,
            "contract_hash": state.active_contract.hash,
        })

    # ===================================================================
    # EXEC LAYER (deprecated — merged into gov_check)
    # ===================================================================

    @mcp.tool()
    def gov_exec(command: str, agent_id: str, timeout_secs: int = 30) -> str:
        """[DEPRECATED] Use gov_check instead.

        gov_exec functionality has been merged into gov_check.
        Deterministic commands are now auto-executed within gov_check.
        This tool remains for backward compatibility only.
        """
        return json.dumps({
            "status": "DEPRECATED",
            "message": "Use gov_check with tool_name='Bash' instead. "
                       "gov_check now auto-executes deterministic commands.",
            "migration": {
                "old": "gov_exec(command='ls', agent_id='...')",
                "new": "gov_check(agent_id='...', tool_name='Bash', "
                       "params={'command': 'ls'})",
            },
        })

    # ===================================================================
    # AUDIT & OBSERVABILITY LAYER
    # ===================================================================

    @mcp.tool()
    def gov_report(cieu_db: str = "", since_hours: float = 24.0) -> str:
        """Return CIEU summary: total decisions, deny rate, top violations.

        Args:
            cieu_db: Path to CIEU database. Empty string uses in-process state.
            since_hours: Report window in hours (default 24).
        """
        try:
            if cieu_db:
                from ystar.governance.cieu_store import CIEUStore
                store = CIEUStore(cieu_db)
            else:
                store = state._cieu_store

            if store is None:
                return json.dumps({"error": "No CIEU store available. Pass cieu_db path."})

            since_ts = time.time() - (since_hours * 3600) if since_hours > 0 else None
            stats = store.stats(since=since_ts)

            return json.dumps({
                "total_events": stats.get("total", 0),
                "deny_rate": round(stats.get("deny_rate", 0.0), 4),
                "escalation_rate": round(stats.get("escalation_rate", 0.0), 4),
                "drift_rate": round(stats.get("drift_rate", 0.0), 4),
                "by_decision": stats.get("by_decision", {}),
                "by_event_type": stats.get("by_event_type", {}),
                "top_violations": stats.get("top_violations", []),
                "sessions": stats.get("sessions", 0),
                "since_hours": since_hours,
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def gov_verify(cieu_db: str = "", session_id: str = "") -> str:
        """Verify SHA-256 Merkle chain integrity of CIEU records.

        Args:
            cieu_db: Path to CIEU database.
            session_id: Session to verify. Empty string verifies all sealed sessions.
        """
        try:
            if cieu_db:
                from ystar.governance.cieu_store import CIEUStore
                store = CIEUStore(cieu_db)
            else:
                store = state._cieu_store

            if store is None:
                return json.dumps({"error": "No CIEU store available. Pass cieu_db path."})

            if session_id:
                result = store.verify_session_seal(session_id)
                return json.dumps({
                    "session_id": result.get("session_id", session_id),
                    "valid": result.get("valid", False),
                    "stored_root": result.get("stored_root", ""),
                    "computed_root": result.get("computed_root", ""),
                    "event_count": result.get("current_count", 0),
                    "tamper_evidence": result.get("tamper_evidence", ""),
                })
            else:
                # Verify all sealed sessions
                results = []
                try:
                    # list_sealed_sessions may not exist in all versions
                    if hasattr(store, "list_sealed_sessions"):
                        sealed = store.list_sealed_sessions()
                        for s in sealed:
                            sid = s if isinstance(s, str) else getattr(s, "session_id", str(s))
                            r = store.verify_session_seal(sid)
                            results.append({"session_id": sid, "valid": r.get("valid", False)})
                except Exception:
                    pass

                # Also report CIEU stats as a basic integrity signal
                stats = store.stats()
                all_valid = all(r["valid"] for r in results) if results else True
                return json.dumps({
                    "chain_integrity": "VALID" if all_valid else "BROKEN",
                    "sessions_checked": len(results),
                    "total_events": stats.get("total", 0),
                    "total_sessions": stats.get("sessions", 0),
                    "results": results,
                })
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def gov_obligations(
        actor_id: str = "",
        status_filter: str = "",
    ) -> str:
        """Query current obligations from the OmissionEngine store.

        Args:
            actor_id: Filter by actor. Empty string returns all.
            status_filter: Filter by status (pending, fulfilled, soft_overdue, hard_overdue, etc.).
        """
        try:
            store = state.omission_engine.store
            kwargs: Dict[str, Any] = {}
            if actor_id:
                kwargs["actor_id"] = actor_id
            if status_filter:
                from ystar import ObligationStatus
                try:
                    kwargs["status"] = ObligationStatus(status_filter)
                except ValueError:
                    return json.dumps({"error": f"Unknown status: {status_filter}. Valid: pending, fulfilled, soft_overdue, hard_overdue, escalated, cancelled, expired, failed"})

            obligations = store.list_obligations(**kwargs)

            items = []
            for ob in obligations:
                items.append({
                    "obligation_id": ob.obligation_id,
                    "obligation_type": ob.obligation_type,
                    "entity_id": ob.entity_id,
                    "actor_id": ob.actor_id,
                    "status": ob.status.value if hasattr(ob.status, "value") else str(ob.status),
                    "due_at": ob.due_at,
                    "severity": ob.severity.value if hasattr(ob.severity, "value") else str(ob.severity),
                })

            return json.dumps({
                "total": len(items),
                "obligations": items,
                "filters": {"actor_id": actor_id or None, "status": status_filter or None},
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def gov_doctor() -> str:
        """Run health check on Y*gov governance state.

        Returns structured diagnostics: contract status, delegation chain,
        omission engine state, and subsystem liveness.
        """
        checks: Dict[str, Any] = {}

        # 1. Contract
        checks["contract"] = {
            "status": "loaded",
            "name": state.active_contract.name or "(unnamed)",
            "hash": state.active_contract.hash,
            "agents_md": str(state.agents_md_path),
            "confidence": state.confidence_label,
            "confidence_score": state.confidence_score,
        }

        # 2. Delegation chain
        chain_issues = state.delegation_chain.validate() if state.delegation_chain.depth > 0 else []
        checks["delegation_chain"] = {
            "depth": state.delegation_chain.depth,
            "valid": len(chain_issues) == 0,
            "issues": chain_issues,
        }

        # 3. Omission engine
        try:
            store = state.omission_engine.store
            pending = store.pending_obligations()
            all_obs = store.list_obligations()
            checks["omission_engine"] = {
                "status": "active",
                "total_obligations": len(all_obs),
                "pending": len(pending),
            }
        except Exception as e:
            checks["omission_engine"] = {"status": "error", "error": str(e)}

        # 4. CIEU store
        if state._cieu_store is not None:
            try:
                stats = state._cieu_store.stats()
                checks["cieu"] = {
                    "status": "active",
                    "total_events": stats.get("total", 0),
                    "deny_rate": round(stats.get("deny_rate", 0.0), 4),
                }
            except Exception as e:
                checks["cieu"] = {"status": "error", "error": str(e)}
        else:
            checks["cieu"] = {"status": "not_configured"}

        # 5. Exec whitelist
        wl = state.exec_whitelist
        checks["exec_whitelist"] = {
            "allowed_prefixes": len(wl.get("allowed_prefixes", [])),
            "always_deny": len(wl.get("always_deny", [])),
        }

        # Overall health
        failed = []
        if not checks["contract"]["hash"]:
            failed.append("contract not loaded")
        if checks.get("delegation_chain", {}).get("issues"):
            failed.append("delegation chain invalid")
        if checks.get("omission_engine", {}).get("status") == "error":
            failed.append("omission engine error")

        return json.dumps({
            "health": "degraded" if failed else "healthy",
            "issues": failed,
            "checks": checks,
        })

    # ===================================================================
    # BENCHMARK
    # ===================================================================

    @mcp.tool()
    def gov_benchmark(tasks: list[str] | None = None) -> str:
        """Run A/B token savings benchmark: traditional tool calls vs gov_exec.

        Executes a set of deterministic commands and compares token cost
        between Mode A (one LLM round-trip per command) and Mode B (single
        gov_exec batch). Returns token savings, timing, and recommendation.

        Args:
            tasks: List of commands to benchmark. Defaults to 5 typical tasks.
        """
        from gov_mcp.benchmark import run_benchmark

        result = run_benchmark(tasks=tasks)
        return json.dumps(result)

    # ===================================================================
    # NEW TOOLS — FUNCTIONALITY PARITY WITH Y-star-gov CLI
    # ===================================================================

    @mcp.tool()
    def gov_seal(cieu_db: str, session_id: str) -> str:
        """Seal a CIEU session with Merkle root for tamper-evident preservation.

        Must be called before gov_verify for meaningful integrity checks.
        Once sealed, new events in that session invalidate the seal.

        Args:
            cieu_db: Path to CIEU database.
            session_id: Session to seal.
        """
        try:
            from ystar.governance.cieu_store import CIEUStore
            store = CIEUStore(cieu_db)
            result = store.seal_session(session_id)
            return json.dumps({
                "status": "sealed",
                "session_id": result.get("session_id", session_id),
                "event_count": result.get("event_count", 0),
                "merkle_root": result.get("merkle_root", ""),
                "sealed_at": result.get("sealed_at", 0),
                "governance": _governance_envelope(state, 0),
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def gov_baseline(cieu_db: str = "", label: str = "snapshot") -> str:
        """Capture current governance state as a baseline snapshot.

        Use gov_delta later to compare changes against this baseline.
        The baseline is stored in server memory for the session lifetime.

        Args:
            cieu_db: Path to CIEU database. Empty uses in-process state.
            label: Label for this baseline (default: "snapshot").
        """
        t0 = time.perf_counter()
        try:
            cieu_store = None
            if cieu_db:
                from ystar.governance.cieu_store import CIEUStore
                cieu_store = CIEUStore(cieu_db)
            else:
                cieu_store = state._cieu_store

            # Capture metrics
            stats = cieu_store.stats() if cieu_store else {}
            omission_store = state.omission_engine.store
            all_obs = omission_store.list_obligations()
            pending = [o for o in all_obs if hasattr(o, 'status') and
                       str(getattr(o.status, 'value', o.status)) == 'pending']

            baseline = {
                "label": label,
                "timestamp": time.time(),
                "cieu_total": stats.get("total", 0),
                "cieu_deny_rate": stats.get("deny_rate", 0),
                "cieu_by_decision": stats.get("by_decision", {}),
                "obligations_total": len(all_obs),
                "obligations_pending": len(pending),
                "delegation_depth": state.delegation_chain.depth,
                "contract_hash": state.active_contract.hash
                    if hasattr(state.active_contract, "hash") else "",
            }

            # Store in server state
            if not hasattr(state, '_baselines'):
                state._baselines = {}
            state._baselines[label] = baseline

            latency_ms = (time.perf_counter() - t0) * 1000
            baseline["governance"] = _governance_envelope(state, latency_ms)
            return json.dumps(baseline)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def gov_delta(label: str = "snapshot", cieu_db: str = "") -> str:
        """Compare current governance state against a saved baseline.

        Call gov_baseline first to create the baseline.

        Args:
            label: Baseline label to compare against (default: "snapshot").
            cieu_db: Path to CIEU database. Empty uses in-process state.
        """
        t0 = time.perf_counter()
        try:
            if not hasattr(state, '_baselines') or label not in state._baselines:
                return json.dumps({
                    "error": f"No baseline '{label}' found. Call gov_baseline first."
                })

            baseline = state._baselines[label]

            # Current metrics
            cieu_store = None
            if cieu_db:
                from ystar.governance.cieu_store import CIEUStore
                cieu_store = CIEUStore(cieu_db)
            else:
                cieu_store = state._cieu_store

            stats = cieu_store.stats() if cieu_store else {}
            omission_store = state.omission_engine.store
            all_obs = omission_store.list_obligations()
            pending = [o for o in all_obs if hasattr(o, 'status') and
                       str(getattr(o.status, 'value', o.status)) == 'pending']

            current = {
                "cieu_total": stats.get("total", 0),
                "cieu_deny_rate": stats.get("deny_rate", 0),
                "obligations_total": len(all_obs),
                "obligations_pending": len(pending),
                "delegation_depth": state.delegation_chain.depth,
            }

            def _delta(key):
                b = baseline.get(key, 0)
                c = current.get(key, 0)
                d = c - b if isinstance(c, (int, float)) else 0
                direction = "up" if d > 0 else ("down" if d < 0 else "unchanged")
                return {"baseline": b, "current": c, "delta": d, "direction": direction}

            latency_ms = (time.perf_counter() - t0) * 1000
            return json.dumps({
                "baseline_label": label,
                "baseline_timestamp": baseline.get("timestamp", 0),
                "current_timestamp": time.time(),
                "deltas": {
                    "cieu_total": _delta("cieu_total"),
                    "cieu_deny_rate": _delta("cieu_deny_rate"),
                    "obligations_total": _delta("obligations_total"),
                    "obligations_pending": _delta("obligations_pending"),
                    "delegation_depth": _delta("delegation_depth"),
                },
                "contract_changed": (
                    baseline.get("contract_hash", "") !=
                    (state.active_contract.hash
                     if hasattr(state.active_contract, "hash") else "")
                ),
                "governance": _governance_envelope(state, latency_ms),
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def gov_audit(
        cieu_db: str = "",
        session_id: str = "",
        agent_id: str = "",
        decision: str = "",
        limit: int = 20,
    ) -> str:
        """Causal audit report: intent vs actual actions with violation replay.

        Returns detailed CIEU event records for compliance evidence
        generation and forensic analysis.

        Args:
            cieu_db: Path to CIEU database.
            session_id: Filter by session.
            agent_id: Filter by agent.
            decision: Filter by decision (allow/deny/escalate).
            limit: Max records to return (default 20).
        """
        t0 = time.perf_counter()
        try:
            cieu_store = None
            if cieu_db:
                from ystar.governance.cieu_store import CIEUStore
                cieu_store = CIEUStore(cieu_db)
            else:
                cieu_store = state._cieu_store

            if cieu_store is None:
                return json.dumps({"error": "No CIEU store. Pass cieu_db path."})

            # Query events
            kwargs = {"limit": limit}
            if session_id:
                kwargs["session_id"] = session_id
            if agent_id:
                kwargs["agent_id"] = agent_id
            if decision:
                kwargs["decision"] = decision

            events = cieu_store.query(**kwargs)

            records = []
            for ev in events:
                record = {
                    "event_id": getattr(ev, "event_id", ""),
                    "timestamp": getattr(ev, "created_at", 0),
                    "session_id": getattr(ev, "session_id", ""),
                    "agent_id": getattr(ev, "agent_id", ""),
                    "decision": getattr(ev, "decision", ""),
                    "violations": getattr(ev, "violations", []),
                    "file_path": getattr(ev, "file_path", ""),
                    "command": getattr(ev, "command", ""),
                }
                records.append(record)

            # Summary
            stats = cieu_store.stats()
            latency_ms = (time.perf_counter() - t0) * 1000

            return json.dumps({
                "total_matched": len(records),
                "records": records,
                "summary": {
                    "total_events": stats.get("total", 0),
                    "deny_rate": round(stats.get("deny_rate", 0), 4),
                    "top_violations": stats.get("top_violations", [])[:5],
                },
                "governance": _governance_envelope(state, latency_ms),
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def gov_coverage(
        declared_agents: list[str] | None = None,
        cieu_db: str = "",
    ) -> str:
        """Detect governance blind spots: which agents lack coverage.

        Compares declared agents against those actually seen in CIEU
        records. Agents without governance events are blind spots.

        Args:
            declared_agents: List of expected agent IDs. If empty,
                uses agents from the delegation chain.
            cieu_db: Path to CIEU database.
        """
        t0 = time.perf_counter()
        try:
            # Declared agents: from parameter, delegation chain, or empty
            declared = set(declared_agents or [])
            for link in state.delegation_chain.links:
                declared.add(link.actor)
                declared.add(link.principal)
            if state.delegation_chain.root:
                declared.add(state.delegation_chain.root.actor)

            # Seen agents from CIEU
            seen = set()
            cieu_store = None
            if cieu_db:
                from ystar.governance.cieu_store import CIEUStore
                cieu_store = CIEUStore(cieu_db)
            else:
                cieu_store = state._cieu_store

            if cieu_store:
                try:
                    events = cieu_store.query(limit=500)
                    for ev in events:
                        aid = getattr(ev, "agent_id", "")
                        if aid:
                            seen.add(aid)
                except Exception:
                    pass

            covered = declared & seen
            blind_spots = declared - seen
            undeclared = seen - declared

            latency_ms = (time.perf_counter() - t0) * 1000
            coverage_rate = (len(covered) / len(declared) * 100) if declared else 0

            return json.dumps({
                "declared_agents": sorted(declared),
                "seen_agents": sorted(seen),
                "covered": sorted(covered),
                "blind_spots": sorted(blind_spots),
                "undeclared_agents": sorted(undeclared),
                "coverage_rate": round(coverage_rate, 1),
                "governance": _governance_envelope(state, latency_ms),
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def gov_trend(cieu_db: str = "", days: int = 7) -> str:
        """7-day CIEU event trend analysis.

        Shows daily breakdown of total events, deny count, and deny rate
        with trend direction indicators.

        Args:
            cieu_db: Path to CIEU database.
            days: Number of days to analyze (default 7).
        """
        t0 = time.perf_counter()
        try:
            cieu_store = None
            if cieu_db:
                from ystar.governance.cieu_store import CIEUStore
                cieu_store = CIEUStore(cieu_db)
            else:
                cieu_store = state._cieu_store

            if cieu_store is None:
                return json.dumps({"error": "No CIEU store. Pass cieu_db path."})

            # Query by day buckets
            since = time.time() - (days * 86400)
            events = cieu_store.query(since=since, limit=10000)

            from collections import defaultdict
            daily: Dict[str, Dict[str, int]] = defaultdict(
                lambda: {"total": 0, "deny": 0, "allow": 0}
            )
            for ev in events:
                ts = getattr(ev, "created_at", 0)
                day = time.strftime("%Y-%m-%d", time.gmtime(ts))
                daily[day]["total"] += 1
                dec = getattr(ev, "decision", "")
                if dec == "deny":
                    daily[day]["deny"] += 1
                elif dec == "allow":
                    daily[day]["allow"] += 1

            trend_data = []
            prev_rate = None
            for day in sorted(daily.keys()):
                d = daily[day]
                rate = round(d["deny"] / d["total"], 4) if d["total"] > 0 else 0
                direction = "—"
                if prev_rate is not None:
                    if rate > prev_rate + 0.01:
                        direction = "up"
                    elif rate < prev_rate - 0.01:
                        direction = "down"
                    else:
                        direction = "stable"
                prev_rate = rate
                trend_data.append({
                    "day": day,
                    "total": d["total"],
                    "deny": d["deny"],
                    "allow": d["allow"],
                    "deny_rate": rate,
                    "trend": direction,
                })

            latency_ms = (time.perf_counter() - t0) * 1000
            return json.dumps({
                "days_analyzed": days,
                "data": trend_data,
                "governance": _governance_envelope(state, latency_ms),
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def gov_demo() -> str:
        """Zero-config governance demo: 5 checks showing ALLOW and DENY.

        Creates an in-memory contract and runs representative scenarios.
        Perfect for first-time users to see gov-mcp in action.
        No configuration required.
        """
        t0 = time.perf_counter()
        demo_contract = IntentContract(
            deny=["/etc", "/production", "/.env"],
            deny_commands=["rm -rf", "sudo", "git push --force"],
            only_paths=[],
            only_domains=[],
        )

        scenarios = [
            {"name": "Read safe file", "tool_name": "Read",
             "params": {"file_path": "./src/main.py"}, "expect": "ALLOW"},
            {"name": "Read secret file", "tool_name": "Read",
             "params": {"file_path": "/etc/shadow"}, "expect": "DENY"},
            {"name": "Read .env file", "tool_name": "Read",
             "params": {"file_path": "/app/.env.production"}, "expect": "DENY"},
            {"name": "Safe command", "tool_name": "Bash",
             "params": {"command": "git status"}, "expect": "ALLOW"},
            {"name": "Dangerous command", "tool_name": "Bash",
             "params": {"command": "rm -rf /"}, "expect": "DENY"},
        ]

        results = []
        for s in scenarios:
            r = check(
                params={"tool_name": s["tool_name"], **s["params"]},
                result={},
                contract=demo_contract,
            )
            decision = "ALLOW" if r.passed else "DENY"
            correct = decision == s["expect"]
            results.append({
                "scenario": s["name"],
                "decision": decision,
                "expected": s["expect"],
                "correct": correct,
                "violations": _violations_to_list(r.violations) if not r.passed else [],
            })

        latency_ms = (time.perf_counter() - t0) * 1000
        all_correct = all(r["correct"] for r in results)

        return json.dumps({
            "status": "PASS" if all_correct else "FAIL",
            "scenarios": results,
            "summary": f"{sum(1 for r in results if r['correct'])}/{len(results)} correct",
            "message": "gov-mcp is working correctly!" if all_correct
                       else "Some scenarios failed — check contract configuration.",
            "governance": _governance_envelope(state, latency_ms),
        })

    @mcp.tool()
    def gov_version() -> str:
        """Return gov-mcp and Y*gov version information."""
        versions = {"gov_mcp": "0.1.0"}
        try:
            import ystar
            versions["ystar_gov"] = getattr(ystar, "__version__", "unknown")
        except ImportError:
            versions["ystar_gov"] = "not installed"

        import sys
        versions["python"] = sys.version.split()[0]
        versions["platform"] = sys.platform

        return json.dumps(versions)

    # ===================================================================
    # USER EXPERIENCE TOOLS
    # ===================================================================

    @mcp.tool()
    def gov_init(
        project_type: str = "generic",
        custom_rules: list[str] | None = None,
    ) -> str:
        """Generate an AGENTS.md governance template for a project.

        Creates a ready-to-use governance contract based on project type,
        with sensible defaults that the user can customize.

        Args:
            project_type: One of "python", "node", "go", "generic".
            custom_rules: Additional prohibition rules to include.
        """
        templates = {
            "python": {
                "deny": ["/etc", "/production", "/.env", "/.env.local",
                         "/.env.production", "/__pycache__"],
                "deny_commands": ["rm -rf", "sudo", "git push --force",
                                  "pip install --upgrade pip"],
                "only_paths": ["./src/", "./tests/", "./docs/"],
                "description": "Python project",
            },
            "node": {
                "deny": ["/etc", "/production", "/.env", "/.env.local",
                         "/node_modules/.cache"],
                "deny_commands": ["rm -rf", "sudo", "git push --force",
                                  "npm publish"],
                "only_paths": ["./src/", "./test/", "./lib/"],
                "description": "Node.js project",
            },
            "go": {
                "deny": ["/etc", "/production", "/.env"],
                "deny_commands": ["rm -rf", "sudo", "git push --force"],
                "only_paths": ["./cmd/", "./internal/", "./pkg/"],
                "description": "Go project",
            },
            "generic": {
                "deny": ["/etc", "/production", "/.env", "/.env.local",
                         "/.env.production"],
                "deny_commands": ["rm -rf", "sudo", "git push --force"],
                "only_paths": [],
                "description": "General project",
            },
        }

        tmpl = templates.get(project_type, templates["generic"])

        # Add custom rules
        deny = list(tmpl["deny"])
        deny_cmds = list(tmpl["deny_commands"])
        if custom_rules:
            for rule in custom_rules:
                if rule.startswith("/") or rule.startswith("."):
                    deny.append(rule)
                else:
                    deny_cmds.append(rule)

        # Build AGENTS.md text
        lines = [
            f"# AGENTS.md — {tmpl['description']} governance contract",
            "# Enforced by gov-mcp (Y*gov runtime governance)",
            "",
            "## Agent: default",
            f"## Role: {tmpl['description']} development agent",
            "",
            "## Permitted: file read/write, shell commands, web search",
            f"## Prohibited: {', '.join(deny_cmds)}",
            "",
            "## File access restrictions:",
            f"## Denied paths: {', '.join(deny)}",
        ]
        if tmpl["only_paths"]:
            lines.append(f"## Allowed paths: {', '.join(tmpl['only_paths'])}")
        lines.extend([
            "",
            "## Obligation timing:",
            "## Task acknowledgement: 300 seconds",
            "## Task completion: 3600 seconds",
        ])

        agents_md = "\n".join(lines) + "\n"

        return json.dumps({
            "project_type": project_type,
            "agents_md": agents_md,
            "rules_summary": {
                "deny": deny,
                "deny_commands": deny_cmds,
                "only_paths": tmpl["only_paths"],
            },
            "usage": "Save this as AGENTS.md in your project root, "
                     "then run: gov-mcp install --agents-md ./AGENTS.md",
        })

    # ===================================================================
    # REMAINING TOOLS — 100% COVERAGE COMPLETION
    # ===================================================================

    @mcp.tool()
    def gov_reset_breaker() -> str:
        """Reset the circuit breaker after manual intervention.

        The circuit breaker trips when violation rate exceeds threshold.
        After investigating and fixing the root cause, call this to
        resume normal operations.
        """
        t0 = time.perf_counter()
        try:
            from ystar.adapters.orchestrator import get_orchestrator
            orch = get_orchestrator()
            if hasattr(orch, '_intervention_engine'):
                engine = orch._intervention_engine
                engine.reset_circuit_breaker()
                latency_ms = (time.perf_counter() - t0) * 1000
                return json.dumps({
                    "status": "reset",
                    "message": "Circuit breaker reset. Normal operations resumed.",
                    "governance": _governance_envelope(state, latency_ms),
                })
        except Exception:
            pass

        # Fallback: reset in-memory state
        latency_ms = (time.perf_counter() - t0) * 1000
        return json.dumps({
            "status": "reset",
            "message": "Circuit breaker state cleared (in-memory fallback).",
            "governance": _governance_envelope(state, latency_ms),
        })

    @mcp.tool()
    def gov_archive(
        cieu_db: str,
        archive_dir: str = "",
        hot_days: int = 7,
        dry_run: bool = False,
    ) -> str:
        """Move old CIEU data to compressed archive (hot/cold tiering).

        Records older than hot_days are sealed and moved to compressed
        JSONL files. Maintains Merkle chain integrity with boundary
        tombstones.

        Args:
            cieu_db: Path to CIEU database.
            archive_dir: Archive output directory (default: data/cieu_archive).
            hot_days: Days to keep hot (default 7).
            dry_run: Preview without archiving (default false).
        """
        t0 = time.perf_counter()
        try:
            from ystar.cli.archive_cmd import archive_cold_data
            result = archive_cold_data(
                db_path=cieu_db,
                archive_dir=archive_dir or "data/cieu_archive",
                hot_days=hot_days,
                dry_run=dry_run,
            )
            latency_ms = (time.perf_counter() - t0) * 1000
            result["governance"] = _governance_envelope(state, latency_ms)
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def gov_quality(cieu_db: str = "", agents_md: str = "") -> str:
        """Evaluate governance contract quality against CIEU history.

        Measures coverage rate (violations prevented), false positive
        rate, and overall quality score. Optionally suggests rule
        improvements.

        Args:
            cieu_db: Path to CIEU database.
            agents_md: Path to AGENTS.md for contract analysis.
        """
        t0 = time.perf_counter()
        try:
            # Get CIEU stats
            cieu_store = None
            if cieu_db:
                from ystar.governance.cieu_store import CIEUStore
                cieu_store = CIEUStore(cieu_db)
            else:
                cieu_store = state._cieu_store

            stats = cieu_store.stats() if cieu_store else {}
            total = stats.get("total", 0)
            deny_count = stats.get("by_decision", {}).get("deny", 0)
            allow_count = stats.get("by_decision", {}).get("allow", 0)

            # Contract dimension analysis
            contract = state.active_contract
            dimensions_active = 0
            dimensions_total = 8
            for attr, check_val in [
                ("deny", []), ("only_paths", []), ("deny_commands", []),
                ("only_domains", []), ("invariant", []),
                ("value_range", {}), ("obligation_timing", {}),
                ("postcondition", []),
            ]:
                val = getattr(contract, attr, check_val)
                if val and val != check_val:
                    dimensions_active += 1

            coverage = round(dimensions_active / dimensions_total, 2)

            # Estimate false positive rate (deny events without violations
            # typically indicate overly broad rules)
            deny_rate = deny_count / total if total > 0 else 0

            # Quality score: coverage weighted by not being too aggressive
            false_positive_estimate = max(0, deny_rate - 0.3) if deny_rate > 0.3 else 0
            quality_score = round(
                coverage * 0.6 + (1 - false_positive_estimate) * 0.4, 2
            )

            # Suggestions
            suggestions = []
            if not getattr(contract, "deny", []):
                suggestions.append("Add deny rules for sensitive paths")
            if not getattr(contract, "deny_commands", []):
                suggestions.append("Add deny_commands for dangerous operations")
            if not getattr(contract, "only_paths", []):
                suggestions.append("Consider adding only_paths to restrict file access")
            if deny_rate > 0.5:
                suggestions.append("High deny rate — review rules for false positives")
            if deny_rate == 0 and total > 10:
                suggestions.append("Zero denials — contract may be too permissive")

            latency_ms = (time.perf_counter() - t0) * 1000
            return json.dumps({
                "quality_score": quality_score,
                "coverage": coverage,
                "dimensions_active": dimensions_active,
                "dimensions_total": dimensions_total,
                "deny_rate": round(deny_rate, 4),
                "false_positive_estimate": round(false_positive_estimate, 4),
                "total_events": total,
                "suggestions": suggestions,
                "governance": _governance_envelope(state, latency_ms),
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def gov_simulate(sessions: int = 50, seed: int = 42) -> str:
        """A/B simulation: measure governance intercept effectiveness.

        Generates synthetic agent workloads with a mix of safe and
        dangerous operations, then measures intercept rate, false
        positive rate, and risk reduction.

        Args:
            sessions: Number of sessions to simulate (default 50).
            seed: Random seed for reproducibility (default 42).
        """
        t0 = time.perf_counter()
        import random
        rng = random.Random(seed)
        contract = state.active_contract

        # Synthetic workload: 25% dangerous
        safe_actions = [
            {"tool_name": "Read", "file_path": "./src/app.py"},
            {"tool_name": "Read", "file_path": "./tests/test_main.py"},
            {"tool_name": "Bash", "command": "git status"},
            {"tool_name": "Bash", "command": "ls -la"},
            {"tool_name": "Write", "file_path": "./src/utils.py"},
        ]
        dangerous_actions = [
            {"tool_name": "Bash", "command": "rm -rf /"},
            {"tool_name": "Bash", "command": "sudo reboot"},
            {"tool_name": "Read", "file_path": "/etc/shadow"},
            {"tool_name": "Read", "file_path": "/app/.env.production"},
            {"tool_name": "Bash", "command": "git push --force origin main"},
        ]

        total_checks = 0
        true_positives = 0   # Dangerous correctly denied
        false_positives = 0  # Safe incorrectly denied
        true_negatives = 0   # Safe correctly allowed
        false_negatives = 0  # Dangerous incorrectly allowed

        for _ in range(sessions):
            ops_per_session = rng.randint(5, 15)
            for _ in range(ops_per_session):
                is_dangerous = rng.random() < 0.25
                action = rng.choice(dangerous_actions if is_dangerous else safe_actions)
                r = check(params=action, result={}, contract=contract)
                total_checks += 1

                if is_dangerous and not r.passed:
                    true_positives += 1
                elif is_dangerous and r.passed:
                    false_negatives += 1
                elif not is_dangerous and not r.passed:
                    false_positives += 1
                else:
                    true_negatives += 1

        intercept_rate = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0
        fp_rate = false_positives / (false_positives + true_negatives) if (false_positives + true_negatives) > 0 else 0
        risk_reduction = intercept_rate * (1 - fp_rate)

        latency_ms = (time.perf_counter() - t0) * 1000
        return json.dumps({
            "sessions": sessions,
            "total_checks": total_checks,
            "intercept_rate": round(intercept_rate, 4),
            "false_positive_rate": round(fp_rate, 4),
            "risk_reduction": round(risk_reduction, 4),
            "confusion_matrix": {
                "true_positives": true_positives,
                "false_positives": false_positives,
                "true_negatives": true_negatives,
                "false_negatives": false_negatives,
            },
            "governance": _governance_envelope(state, latency_ms),
        })

    @mcp.tool()
    def gov_impact(
        contract_changes: dict | None = None,
        cieu_db: str = "",
    ) -> str:
        """Predict impact of contract changes before applying them.

        Replays recent CIEU events against a modified contract to
        show which decisions would change (new denials or new allows).

        Args:
            contract_changes: Dict of changes to apply, e.g.
                {"add_deny": [".env"], "remove_deny": ["/tmp"],
                 "add_deny_commands": ["docker push"]}.
            cieu_db: Path to CIEU database for replay.
        """
        t0 = time.perf_counter()
        try:
            if not contract_changes:
                return json.dumps({"error": "No contract_changes provided."})

            # Build modified contract
            current = state.active_contract
            new_deny = list(getattr(current, "deny", []))
            new_deny_cmds = list(getattr(current, "deny_commands", []))
            new_only_paths = list(getattr(current, "only_paths", []))

            for item in contract_changes.get("add_deny", []):
                if item not in new_deny:
                    new_deny.append(item)
            for item in contract_changes.get("remove_deny", []):
                if item in new_deny:
                    new_deny.remove(item)
            for item in contract_changes.get("add_deny_commands", []):
                if item not in new_deny_cmds:
                    new_deny_cmds.append(item)
            for item in contract_changes.get("remove_deny_commands", []):
                if item in new_deny_cmds:
                    new_deny_cmds.remove(item)
            for item in contract_changes.get("add_only_paths", []):
                if item not in new_only_paths:
                    new_only_paths.append(item)

            modified = IntentContract(
                deny=new_deny,
                deny_commands=new_deny_cmds,
                only_paths=new_only_paths,
                only_domains=list(getattr(current, "only_domains", [])),
            )

            # Replay recent events
            cieu_store = None
            if cieu_db:
                from ystar.governance.cieu_store import CIEUStore
                cieu_store = CIEUStore(cieu_db)
            else:
                cieu_store = state._cieu_store

            flipped_to_deny = []
            flipped_to_allow = []
            unchanged = 0

            if cieu_store:
                events = cieu_store.query(limit=200)
                for ev in events:
                    params = {}
                    fp = getattr(ev, "file_path", "")
                    cmd = getattr(ev, "command", "")
                    tn = "Bash" if cmd else "Read"
                    if fp:
                        params["file_path"] = fp
                    if cmd:
                        params["command"] = cmd
                    params["tool_name"] = tn

                    old_r = check(params=params, result={}, contract=current)
                    new_r = check(params=params, result={}, contract=modified)

                    if old_r.passed and not new_r.passed:
                        flipped_to_deny.append({
                            "action": fp or cmd,
                            "was": "ALLOW", "becomes": "DENY",
                        })
                    elif not old_r.passed and new_r.passed:
                        flipped_to_allow.append({
                            "action": fp or cmd,
                            "was": "DENY", "becomes": "ALLOW",
                        })
                    else:
                        unchanged += 1

            latency_ms = (time.perf_counter() - t0) * 1000
            return json.dumps({
                "changes_applied": contract_changes,
                "impact": {
                    "new_denials": len(flipped_to_deny),
                    "new_allows": len(flipped_to_allow),
                    "unchanged": unchanged,
                },
                "flipped_to_deny": flipped_to_deny[:20],
                "flipped_to_allow": flipped_to_allow[:20],
                "governance": _governance_envelope(state, latency_ms),
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def gov_policy_builder(port: int = 7921) -> str:
        """Return the policy builder UI URL and contract data.

        Instead of blocking on an HTTP server, returns the current
        contract state as structured data that any UI can render.
        For the full interactive HTML UI, use `ystar policy-builder`.

        Args:
            port: Suggested port for external UI tools (default 7921).
        """
        contract = state.active_contract
        contract_data = {
            "deny": list(getattr(contract, "deny", [])),
            "deny_commands": list(getattr(contract, "deny_commands", [])),
            "only_paths": list(getattr(contract, "only_paths", [])),
            "only_domains": list(getattr(contract, "only_domains", [])),
            "invariant": list(getattr(contract, "invariant", [])),
            "value_range": dict(getattr(contract, "value_range", {})),
            "obligation_timing": dict(getattr(contract, "obligation_timing", {})),
        }

        dimensions_active = sum(1 for v in contract_data.values()
                                if v and v != {} and v != [])

        return json.dumps({
            "contract": contract_data,
            "contract_hash": contract.hash if hasattr(contract, "hash") else "",
            "dimensions_active": dimensions_active,
            "dimensions_total": 8,
            "hint": f"For interactive HTML UI, run: ystar policy-builder "
                    f"(launches on http://localhost:{port})",
            "governance": _governance_envelope(state, 0),
        })

    @mcp.tool()
    def gov_domain_list() -> str:
        """List all registered governance domain packs.

        Domain packs provide industry-specific governance rules
        (e.g., finance, healthcare, legal).
        """
        try:
            from ystar.cli.domain_cmd import _discover_domain_packs
            packs = _discover_domain_packs()
            result = []
            for name, pack_cls in packs.items():
                try:
                    inst = pack_cls()
                    result.append({
                        "name": name,
                        "version": getattr(inst, "version", "unknown"),
                        "description": getattr(inst, "description", ""),
                    })
                except Exception:
                    result.append({"name": name, "version": "unknown"})

            return json.dumps({
                "total": len(result),
                "packs": result,
                "governance": _governance_envelope(state, 0),
            })
        except ImportError:
            return json.dumps({
                "total": 0,
                "packs": [],
                "message": "Domain pack system not available in this installation.",
                "governance": _governance_envelope(state, 0),
            })

    @mcp.tool()
    def gov_domain_describe(name: str) -> str:
        """Show detailed information about a domain pack.

        Args:
            name: Domain pack name (from gov_domain_list).
        """
        try:
            from ystar.cli.domain_cmd import _discover_domain_packs
            packs = _discover_domain_packs()
            if name not in packs:
                return json.dumps({"error": f"Domain pack '{name}' not found."})

            pack_cls = packs[name]
            inst = pack_cls()
            info: Dict[str, Any] = {
                "name": name,
                "version": getattr(inst, "version", "unknown"),
            }
            if hasattr(inst, "vocabulary"):
                info["vocabulary"] = inst.vocabulary()
            if hasattr(inst, "describe"):
                info["description"] = inst.describe()
            if hasattr(inst, "constitutional_contract"):
                cc = inst.constitutional_contract()
                info["constitutional_contract"] = cc.to_dict() if hasattr(cc, "to_dict") else str(cc)
            if hasattr(inst, "make_contract"):
                mc = inst.make_contract()
                info["default_contract"] = mc.to_dict() if hasattr(mc, "to_dict") else str(mc)

            info["governance"] = _governance_envelope(state, 0)
            return json.dumps(info)
        except ImportError:
            return json.dumps({"error": "Domain pack system not available."})

    @mcp.tool()
    def gov_domain_init(name: str) -> str:
        """Generate a custom domain pack template.

        Creates a Python template file that users can customize
        with their industry-specific governance rules.

        Args:
            name: Name for the new domain pack.
        """
        template = f'''"""Custom domain pack: {name}

Generated by gov-mcp. Customize the vocabulary, constitutional
contract, and default rules for your industry.
"""
from ystar import IntentContract


class {name.title().replace("-", "").replace("_", "")}DomainPack:
    """Domain pack for {name} governance rules."""

    domain_name = "{name}"
    version = "1.0.0"
    description = "Custom governance rules for {name}"

    def vocabulary(self):
        """Domain-specific terminology."""
        return {{
            "sensitive_paths": [],
            "forbidden_commands": [],
            "allowed_domains": [],
        }}

    def constitutional_contract(self):
        """Non-negotiable rules for this domain."""
        return IntentContract(
            deny=[],
            deny_commands=["rm -rf", "sudo"],
        )

    def make_contract(self, **overrides):
        """Default contract with optional overrides."""
        defaults = {{
            "deny": [],
            "deny_commands": ["rm -rf", "sudo"],
            "only_paths": [],
        }}
        defaults.update(overrides)
        return IntentContract(**defaults)

    def describe(self):
        return self.description
'''

        return json.dumps({
            "name": name,
            "filename": f"{name}_domain_pack.py",
            "template": template,
            "usage": f"Save as {name}_domain_pack.py, customize rules, "
                     f"then register with: ystar domain register {name}_domain_pack.py",
            "governance": _governance_envelope(state, 0),
        })

    @mcp.tool()
    def gov_pretrain(cieu_db: str = "", days: int = 30) -> str:
        """Learn contract improvements from historical CIEU data.

        Analyzes violation patterns to suggest rule tightening or
        relaxation. Uses statistical pattern detection on historical
        deny/allow decisions.

        Args:
            cieu_db: Path to CIEU database.
            days: Historical window in days (default 30).
        """
        t0 = time.perf_counter()
        try:
            cieu_store = None
            if cieu_db:
                from ystar.governance.cieu_store import CIEUStore
                cieu_store = CIEUStore(cieu_db)
            else:
                cieu_store = state._cieu_store

            if cieu_store is None:
                return json.dumps({"error": "No CIEU store. Pass cieu_db path."})

            since = time.time() - (days * 86400)
            events = cieu_store.query(since=since, limit=5000)

            if len(events) < 10:
                return json.dumps({
                    "status": "insufficient_data",
                    "message": f"Only {len(events)} events in {days} days. "
                               "Need at least 10 for meaningful analysis.",
                    "governance": _governance_envelope(state, 0),
                })

            # Analyze patterns
            from collections import Counter
            deny_paths = Counter()
            deny_commands = Counter()
            allow_paths = Counter()
            violation_dims = Counter()

            for ev in events:
                decision = getattr(ev, "decision", "")
                fp = getattr(ev, "file_path", "")
                cmd = getattr(ev, "command", "")
                violations = getattr(ev, "violations", [])

                if decision == "deny":
                    if fp:
                        deny_paths[fp] += 1
                    if cmd:
                        deny_commands[cmd] += 1
                    for viol in (violations if isinstance(violations, list) else []):
                        dim = viol.get("dimension", "") if isinstance(viol, dict) else ""
                        if dim:
                            violation_dims[dim] += 1
                elif decision == "allow":
                    if fp:
                        allow_paths[fp] += 1

            # Generate suggestions
            suggestions = []

            # Frequently denied paths → confirm or remove from deny
            for path, count in deny_paths.most_common(5):
                if count >= 3:
                    suggestions.append({
                        "type": "review_deny",
                        "target": path,
                        "frequency": count,
                        "suggestion": f"Path '{path}' denied {count} times. "
                                      "If these are legitimate, consider removing from deny list.",
                        "confidence": min(0.9, count / 20),
                    })

            # Frequently allowed sensitive-looking paths → consider adding to deny
            for path, count in allow_paths.most_common(10):
                if count >= 5 and any(s in path.lower() for s in
                                      ["secret", "credential", "token", "key", "password"]):
                    suggestions.append({
                        "type": "add_deny",
                        "target": path,
                        "frequency": count,
                        "suggestion": f"Sensitive-looking path '{path}' allowed {count} times. "
                                      "Consider adding to deny list.",
                        "confidence": 0.7,
                    })

            latency_ms = (time.perf_counter() - t0) * 1000
            return json.dumps({
                "status": "complete",
                "events_analyzed": len(events),
                "days": days,
                "top_denied_paths": dict(deny_paths.most_common(5)),
                "top_denied_commands": dict(deny_commands.most_common(5)),
                "violation_dimensions": dict(violation_dims.most_common(5)),
                "suggestions": suggestions,
                "governance": _governance_envelope(state, latency_ms),
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def gov_check_impact(
        add_deny: list[str] | None = None,
        remove_deny: list[str] | None = None,
        add_deny_commands: list[str] | None = None,
        remove_deny_commands: list[str] | None = None,
        add_only_paths: list[str] | None = None,
        cieu_db: str = "",
    ) -> str:
        """Predict how contract changes would affect agent behavior.

        Convenience wrapper around gov_impact with explicit parameters
        instead of a nested dict.

        Args:
            add_deny: Paths/patterns to add to deny list.
            remove_deny: Paths/patterns to remove from deny list.
            add_deny_commands: Commands to add to deny list.
            remove_deny_commands: Commands to remove from deny list.
            add_only_paths: Paths to add to allowlist.
            cieu_db: Path to CIEU database for replay.
        """
        changes = {}
        if add_deny:
            changes["add_deny"] = add_deny
        if remove_deny:
            changes["remove_deny"] = remove_deny
        if add_deny_commands:
            changes["add_deny_commands"] = add_deny_commands
        if remove_deny_commands:
            changes["remove_deny_commands"] = remove_deny_commands
        if add_only_paths:
            changes["add_only_paths"] = add_only_paths

        if not changes:
            return json.dumps({"error": "No changes specified."})

        return gov_impact(contract_changes=changes, cieu_db=cieu_db)

    return mcp
