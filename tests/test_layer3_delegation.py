"""Layer 3 Experiment: DelegationChain four-level privilege hierarchy.

Hypothesis: CEO→CTO→Engineer→Intern chain enforces strict monotonic
privilege reduction. Every escalation attempt is denied. gov_escalate
produces complete CIEU audit trail.
"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "Y-star-gov"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ystar import IntentContract, DelegationChain, DelegationContract, check

ETC = "/" + "etc"
PROD = "/" + "production"


def _build_four_level_chain():
    """Build CEO→CTO→Engineer→Intern delegation chain."""
    ceo_contract = IntentContract(
        deny=[ETC, PROD],
        deny_commands=["sudo"],
        only_paths=["./"],
    )
    cto_contract = IntentContract(
        deny=[ETC, PROD],
        deny_commands=["sudo", "git push --force"],
        only_paths=["./src/", "./tests/", "./docs/"],
    )
    eng_contract = IntentContract(
        deny=[ETC, PROD],
        deny_commands=["sudo", "git push --force"],
        only_paths=["./src/core/", "./tests/"],
    )
    intern_contract = IntentContract(
        deny=[ETC, PROD],
        deny_commands=["sudo", "git push --force", "git push"],
        only_paths=["./src/core/utils/"],
    )

    chain = DelegationChain()
    chain.append(DelegationContract(
        principal="board", actor="ceo", contract=ceo_contract,
        allow_redelegate=True, delegation_depth=3,
    ))
    chain.append(DelegationContract(
        principal="ceo", actor="cto", contract=cto_contract,
        allow_redelegate=True, delegation_depth=2,
    ))
    chain.append(DelegationContract(
        principal="cto", actor="engineer", contract=eng_contract,
        allow_redelegate=True, delegation_depth=1,
    ))
    chain.append(DelegationContract(
        principal="engineer", actor="intern", contract=intern_contract,
        allow_redelegate=False, delegation_depth=0,
    ))

    return chain, {
        "ceo": ceo_contract,
        "cto": cto_contract,
        "engineer": eng_contract,
        "intern": intern_contract,
    }


def _get_contract(chain, agent_id, contracts):
    for link in reversed(chain.links):
        if link.actor == agent_id:
            return link.contract
    return contracts.get(agent_id, IntentContract())


# =====================================================================
# Test 1: Each level can access its own scope
# =====================================================================

def test_each_level_allowed_in_scope():
    chain, contracts = _build_four_level_chain()

    # CEO: can access everything under ./
    r = check(params={"tool_name": "Write", "file_path": "./config/settings.py"},
              result={}, contract=contracts["ceo"])
    assert r.passed, "CEO should access ./config/"

    # CTO: can access ./src/, ./tests/, ./docs/
    r = check(params={"tool_name": "Write", "file_path": "./src/main.py"},
              result={}, contract=contracts["cto"])
    assert r.passed, "CTO should access ./src/"

    # Engineer: can access ./src/core/, ./tests/
    r = check(params={"tool_name": "Write", "file_path": "./src/core/engine.py"},
              result={}, contract=contracts["engineer"])
    assert r.passed, "Engineer should access ./src/core/"

    # Intern: can access ./src/core/utils/ only
    r = check(params={"tool_name": "Write", "file_path": "./src/core/utils/helper.py"},
              result={}, contract=contracts["intern"])
    assert r.passed, "Intern should access ./src/core/utils/"


# =====================================================================
# Test 2: Each level DENIED outside scope
# =====================================================================

def test_each_level_denied_outside_scope():
    chain, contracts = _build_four_level_chain()

    # CTO cannot access ./config/ (outside only_paths)
    r = check(params={"tool_name": "Write", "file_path": "./config/settings.py"},
              result={}, contract=contracts["cto"])
    assert not r.passed, "CTO should NOT access ./config/"

    # Engineer cannot access ./src/utils/ (outside ./src/core/)
    r = check(params={"tool_name": "Write", "file_path": "./src/utils/helpers.py"},
              result={}, contract=contracts["engineer"])
    assert not r.passed, "Engineer should NOT access ./src/utils/"

    # Intern cannot access ./src/core/engine.py (outside ./src/core/utils/)
    r = check(params={"tool_name": "Write", "file_path": "./src/core/engine.py"},
              result={}, contract=contracts["intern"])
    assert not r.passed, "Intern should NOT access ./src/core/engine.py"

    # All levels denied /etc
    for agent, contract in contracts.items():
        r = check(params={"tool_name": "Read", "file_path": ETC + "/passwd"},
                  result={}, contract=contract)
        assert not r.passed, f"{agent} should NOT access {ETC}"


# =====================================================================
# Test 3: Monotonicity validation
# =====================================================================

def test_monotonicity_valid():
    """Valid chain: each child is subset of parent."""
    chain, _ = _build_four_level_chain()
    issues = chain.validate()

    # Check for monotonicity issues (ignore continuity — our chain is linear)
    mono_issues = [i for i in issues if "monotonicity" in i.lower() or "subset" in i.lower()
                   or "wider" in i.lower() or "drops" in i.lower()]
    assert len(mono_issues) == 0, f"Monotonicity violations: {mono_issues}"


def test_invalid_escalation_detected():
    """Attempt to give child MORE permissions than parent."""
    chain = DelegationChain()
    parent_contract = IntentContract(
        only_paths=["./src/core/"],
        deny=[ETC],
    )
    # Child tries to access wider scope
    child_contract = IntentContract(
        only_paths=["./src/"],  # WIDER than parent's ./src/core/
        deny=[ETC],
    )

    chain.append(DelegationContract(
        principal="cto", actor="engineer", contract=parent_contract,
    ))
    chain.append(DelegationContract(
        principal="engineer", actor="intern", contract=child_contract,
    ))

    issues = chain.validate()
    # Should detect that intern has wider scope than engineer
    assert len(issues) > 0, "Should detect privilege escalation"


# =====================================================================
# Test 4: Deny rule monotonicity
# =====================================================================

def test_child_cannot_drop_deny_rules():
    """Child removing parent's deny rules is detected."""
    chain = DelegationChain()

    parent = IntentContract(deny=[ETC, PROD, "/.env"])
    child = IntentContract(deny=[ETC])  # Dropped /production and /.env

    chain.append(DelegationContract(
        principal="cto", actor="engineer", contract=parent,
    ))
    chain.append(DelegationContract(
        principal="engineer", actor="intern", contract=child,
    ))

    issues = chain.validate()
    drop_issues = [i for i in issues if "drop" in i.lower() or "deny" in i.lower()]
    assert len(drop_issues) > 0, "Should detect dropped deny rules"


# =====================================================================
# Test 5: Four-level escalation attempts
# =====================================================================

def test_intern_cannot_escalate():
    """Intern cannot do what engineer can."""
    _, contracts = _build_four_level_chain()

    # Engineer CAN write to ./tests/
    r = check(params={"tool_name": "Write", "file_path": "./tests/test_new.py"},
              result={}, contract=contracts["engineer"])
    assert r.passed

    # Intern CANNOT write to ./tests/
    r = check(params={"tool_name": "Write", "file_path": "./tests/test_new.py"},
              result={}, contract=contracts["intern"])
    assert not r.passed


def test_engineer_cannot_do_cto_actions():
    """Engineer cannot git push --force but that's in deny_commands for both.
    Engineer cannot access ./docs/ which CTO can."""
    _, contracts = _build_four_level_chain()

    # CTO CAN write to ./docs/
    r = check(params={"tool_name": "Write", "file_path": "./docs/api.md"},
              result={}, contract=contracts["cto"])
    assert r.passed

    # Engineer CANNOT write to ./docs/
    r = check(params={"tool_name": "Write", "file_path": "./docs/api.md"},
              result={}, contract=contracts["engineer"])
    assert not r.passed


def test_cto_cannot_do_ceo_actions():
    """CTO cannot access ./config/ which CEO can."""
    _, contracts = _build_four_level_chain()

    r_ceo = check(params={"tool_name": "Write", "file_path": "./config/deploy.yaml"},
                  result={}, contract=contracts["ceo"])
    assert r_ceo.passed

    r_cto = check(params={"tool_name": "Write", "file_path": "./config/deploy.yaml"},
                  result={}, contract=contracts["cto"])
    assert not r_cto.passed


# =====================================================================
# Test 6: gov_escalate simulation
# =====================================================================

def test_escalation_within_principal_authority():
    """Engineer requests ./tests/ (CTO has it) — should be approvable."""
    _, contracts = _build_four_level_chain()

    # CTO's contract includes ./tests/ in only_paths
    cto = contracts["cto"]
    requested = "./tests/"

    # Check if requested path is within CTO's scope
    within_scope = any(
        requested == p or requested.startswith(p)
        for p in cto.only_paths
    )
    assert within_scope, "CTO should have ./tests/ in scope"


def test_escalation_beyond_principal_authority():
    """Engineer requests ./config/ (CTO doesn't have it) — should be denied."""
    _, contracts = _build_four_level_chain()

    cto = contracts["cto"]
    requested = "./config/"

    within_scope = any(
        requested == p or requested.startswith(p)
        for p in cto.only_paths
    )
    assert not within_scope, "CTO should NOT have ./config/ in scope"
