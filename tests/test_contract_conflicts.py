"""Tests for gov_contract_conflicts — detect contradictions in contracts."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "Y-star-gov"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ystar import IntentContract


def _find_conflicts(contract):
    """Inline conflict detection (mirrors server.py logic)."""
    conflicts = []
    deny = list(getattr(contract, 'deny', []))
    only_paths = list(getattr(contract, 'only_paths', []))
    deny_cmds = list(getattr(contract, 'deny_commands', []))

    for dp in deny:
        for ap in only_paths:
            if dp.lower() in ap.lower():
                conflicts.append(("deny_blocks_allowed_path", dp, ap))
            if ap.lower() in dp.lower():
                conflicts.append(("allowed_path_in_deny", dp, ap))
    if not deny and not deny_cmds:
        conflicts.append(("empty_contract",))
    if only_paths and not deny:
        conflicts.append(("paths_without_deny",))
    for cmd in deny_cmds:
        if len(cmd) <= 2:
            conflicts.append(("overly_broad", cmd))
    return conflicts


def test_clean_contract_no_conflicts():
    c = IntentContract(deny=["/secret"], deny_commands=["sudo"], only_paths=["./src/"])
    conflicts = _find_conflicts(c)
    assert len(conflicts) == 0


def test_deny_blocks_allowed_path():
    """deny='/src' blocks only_paths='./src/' — conflict detected."""
    c = IntentContract(deny=["/src"], only_paths=["./src/"])
    conflicts = _find_conflicts(c)
    overlap = [x for x in conflicts if x[0] == "deny_blocks_allowed_path"]
    assert len(overlap) >= 1


def test_empty_contract_flagged():
    c = IntentContract()
    conflicts = _find_conflicts(c)
    empty = [x for x in conflicts if x[0] == "empty_contract"]
    assert len(empty) == 1


def test_paths_without_deny_flagged():
    c = IntentContract(only_paths=["./src/"])
    conflicts = _find_conflicts(c)
    pwd = [x for x in conflicts if x[0] == "paths_without_deny"]
    assert len(pwd) == 1


def test_overly_broad_command_flagged():
    c = IntentContract(deny_commands=["rm"])  # Too short — catches "rm" in any command
    conflicts = _find_conflicts(c)
    broad = [x for x in conflicts if x[0] == "overly_broad"]
    assert len(broad) == 1


def test_no_false_conflict_on_separate_paths():
    """deny='/etc' and only_paths='./src/' should NOT conflict."""
    c = IntentContract(deny=["/etc"], only_paths=["./src/"])
    conflicts = _find_conflicts(c)
    assert len(conflicts) == 0
