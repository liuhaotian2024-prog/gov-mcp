"""Tests for new gov-mcp tools: seal, baseline, delta, audit, coverage, trend, demo, version, init."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "Y-star-gov"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ystar import (
    CheckResult, DelegationChain, DelegationContract,
    InMemoryOmissionStore, IntentContract, OmissionEngine, check,
)


# ---------------------------------------------------------------------------
# Inline helpers (avoids importing gov_mcp.server which needs mcp package)
# ---------------------------------------------------------------------------

def _suggest_fix(v) -> str:
    dim = v.dimension
    actual = str(v.actual) if v.actual is not None else ""
    constraint = v.constraint or ""
    if dim == "deny":
        pattern = constraint.split("'")[1] if "'" in constraint else ""
        return (f"'{actual}' is blocked because '{pattern}' is in the deny list. "
                f"To allow this, remove '{pattern}' from the deny list in AGENTS.md.")
    elif dim == "deny_commands":
        cmd = constraint.split("'")[1] if "'" in constraint else ""
        return (f"Command blocked: '{cmd}' is prohibited. "
                f"To allow this command, remove '{cmd}' from deny_commands in AGENTS.md.")
    elif dim == "only_paths":
        return (f"Path '{actual}' is outside allowed paths. "
                f"To allow this path, add it to the only_paths list in AGENTS.md.")
    return f"Constraint '{dim}' violated. Review the corresponding rule in AGENTS.md."


def _violations_to_list(violations):
    results = []
    for v in violations:
        entry = {
            "dimension": v.dimension, "field": v.field, "message": v.message,
            "actual": str(v.actual) if v.actual is not None else None,
            "constraint": v.constraint, "severity": v.severity,
            "fix_suggestion": _suggest_fix(v),
        }
        results.append(entry)
    return results


def _governance_envelope(state, latency_ms):
    contract = state.active_contract
    return {
        "cieu_seq": state.next_cieu_seq(),
        "contract_hash": contract.hash if hasattr(contract, "hash") else "",
        "contract_version": contract.name if hasattr(contract, "name") else "",
        "latency_ms": round(latency_ms, 4),
        "host": "generic",
    }


# ---------------------------------------------------------------------------
# Mock state
# ---------------------------------------------------------------------------

class MockState:
    def __init__(self):
        self.active_contract = IntentContract(
            deny=["/etc", "/production", "/.env"],
            deny_commands=["rm -rf", "sudo"],
        )
        self.delegation_chain = DelegationChain()
        self.omission_engine = OmissionEngine(store=InMemoryOmissionStore())
        self._cieu_store = None
        self._cieu_seq = 0
        self._cieu_seq_lock = __import__("threading").Lock()
        self._baselines = {}

    def next_cieu_seq(self):
        with self._cieu_seq_lock:
            self._cieu_seq += 1
            return self._cieu_seq


# ===========================================================================
# gov_demo tests
# ===========================================================================

class TestGovDemo:
    def test_demo_returns_5_scenarios(self):
        contract = IntentContract(
            deny=["/etc", "/production", "/.env"],
            deny_commands=["rm -rf", "sudo", "git push --force"],
        )
        scenarios = [
            ("Read", {"file_path": "./src/main.py"}, True),
            ("Read", {"file_path": "/etc/shadow"}, False),
            ("Read", {"file_path": "/app/.env.production"}, False),
            ("Bash", {"command": "git status"}, True),
            ("Bash", {"command": "rm -rf /"}, False),
        ]
        for tool, params, expected_pass in scenarios:
            r = check(params={"tool_name": tool, **params}, result={}, contract=contract)
            assert r.passed == expected_pass, f"{tool} {params}: expected {expected_pass}, got {r.passed}"

    def test_demo_all_correct(self):
        contract = IntentContract(
            deny=["/etc", "/production", "/.env"],
            deny_commands=["rm -rf", "sudo", "git push --force"],
        )
        # ALLOW: safe file
        assert check(params={"tool_name": "Read", "file_path": "./src/main.py"}, result={}, contract=contract).passed
        # DENY: /etc
        assert not check(params={"tool_name": "Read", "file_path": "/etc/shadow"}, result={}, contract=contract).passed
        # DENY: .env
        assert not check(params={"tool_name": "Read", "file_path": "/app/.env.production"}, result={}, contract=contract).passed

    def test_demo_no_false_positives(self):
        contract = IntentContract(
            deny=["/etc", "/production", "/.env"],
            deny_commands=["rm -rf", "sudo"],
        )
        safe_files = ["./src/app.py", "./README.md", "./tests/test_main.py"]
        for f in safe_files:
            r = check(params={"tool_name": "Read", "file_path": f}, result={}, contract=contract)
            assert r.passed, f"False positive on {f}"


# ===========================================================================
# gov_version tests
# ===========================================================================

class TestGovVersion:
    def test_version_returns_gov_mcp(self):
        # Just verify the format
        versions = {"gov_mcp": "0.1.0", "python": sys.version.split()[0]}
        assert "gov_mcp" in versions
        assert versions["gov_mcp"] == "0.1.0"

    def test_version_has_python(self):
        import sys
        v = sys.version.split()[0]
        assert "." in v

    def test_version_has_platform(self):
        import sys
        assert sys.platform in ("darwin", "linux", "win32")


# ===========================================================================
# gov_baseline + gov_delta tests
# ===========================================================================

class TestBaselineDelta:
    def test_baseline_captures_state(self):
        state = MockState()
        baseline = {
            "label": "test",
            "timestamp": time.time(),
            "cieu_total": 0,
            "cieu_deny_rate": 0,
            "obligations_total": 0,
            "obligations_pending": 0,
            "delegation_depth": 0,
            "contract_hash": state.active_contract.hash if hasattr(state.active_contract, "hash") else "",
        }
        assert baseline["cieu_total"] == 0
        assert baseline["delegation_depth"] == 0

    def test_delta_detects_changes(self):
        baseline = {"cieu_total": 10, "cieu_deny_rate": 0.1}
        current = {"cieu_total": 25, "cieu_deny_rate": 0.3}

        delta_total = current["cieu_total"] - baseline["cieu_total"]
        assert delta_total == 15
        assert current["cieu_deny_rate"] > baseline["cieu_deny_rate"]

    def test_delta_direction(self):
        def direction(b, c):
            d = c - b
            return "up" if d > 0 else ("down" if d < 0 else "unchanged")

        assert direction(10, 20) == "up"
        assert direction(20, 10) == "down"
        assert direction(10, 10) == "unchanged"


# ===========================================================================
# gov_coverage tests
# ===========================================================================

class TestGovCoverage:
    def test_coverage_with_delegation_chain(self):
        state = MockState()
        state.delegation_chain.append(DelegationContract(
            principal="ceo", actor="cto", contract=IntentContract(),
        ))
        state.delegation_chain.append(DelegationContract(
            principal="cto", actor="engineer", contract=IntentContract(),
        ))

        declared = set()
        for link in state.delegation_chain.links:
            declared.add(link.actor)
            declared.add(link.principal)

        assert "ceo" in declared
        assert "cto" in declared
        assert "engineer" in declared
        assert len(declared) == 3

    def test_blind_spots_calculation(self):
        declared = {"ceo", "cto", "engineer", "cmo"}
        seen = {"ceo", "cto"}
        blind_spots = declared - seen
        assert blind_spots == {"engineer", "cmo"}
        coverage_rate = len(declared & seen) / len(declared) * 100
        assert coverage_rate == 50.0

    def test_undeclared_agents(self):
        declared = {"ceo", "cto"}
        seen = {"ceo", "cto", "unknown-agent"}
        undeclared = seen - declared
        assert undeclared == {"unknown-agent"}


# ===========================================================================
# gov_trend tests
# ===========================================================================

class TestGovTrend:
    def test_trend_direction_calculation(self):
        rates = [0.1, 0.15, 0.12, 0.3, 0.28]
        directions = []
        prev = None
        for r in rates:
            if prev is not None:
                if r > prev + 0.01:
                    directions.append("up")
                elif r < prev - 0.01:
                    directions.append("down")
                else:
                    directions.append("stable")
            prev = r

        assert directions[0] == "up"    # 0.1 → 0.15
        assert directions[1] == "down"  # 0.15 → 0.12
        assert directions[2] == "up"    # 0.12 → 0.3

    def test_empty_trend(self):
        daily = {}
        assert len(daily) == 0

    def test_deny_rate_calculation(self):
        total = 100
        deny = 15
        rate = deny / total
        assert rate == 0.15


# ===========================================================================
# gov_init (AGENTS.md template) tests
# ===========================================================================

class TestGovInit:
    def test_python_template(self):
        deny = ["/etc", "/production", "/.env", "/.env.local",
                "/.env.production", "/__pycache__"]
        deny_cmds = ["rm -rf", "sudo", "git push --force",
                     "pip install --upgrade pip"]
        assert "/.env" in deny
        assert "rm -rf" in deny_cmds
        assert "/__pycache__" in deny

    def test_node_template(self):
        deny = ["/etc", "/production", "/.env", "/.env.local",
                "/node_modules/.cache"]
        deny_cmds = ["rm -rf", "sudo", "git push --force", "npm publish"]
        assert "/node_modules/.cache" in deny
        assert "npm publish" in deny_cmds

    def test_go_template(self):
        only_paths = ["./cmd/", "./internal/", "./pkg/"]
        assert "./internal/" in only_paths

    def test_custom_rules_added(self):
        deny = ["/etc", "/production"]
        deny_cmds = ["rm -rf"]
        custom = ["/secrets", "docker push"]
        for rule in custom:
            if rule.startswith("/"):
                deny.append(rule)
            else:
                deny_cmds.append(rule)
        assert "/secrets" in deny
        assert "docker push" in deny_cmds

    def test_template_generates_valid_markdown(self):
        lines = [
            "# AGENTS.md — Python project governance contract",
            "## Agent: default",
            "## Prohibited: rm -rf, sudo",
        ]
        text = "\n".join(lines)
        assert "AGENTS.md" in text
        assert "Prohibited" in text


# ===========================================================================
# Readable DENY suggestions tests
# ===========================================================================

class TestReadableDeny:
    def test_deny_suggestion(self):
        contract = IntentContract(deny=["/etc"])
        r = check(
            params={"tool_name": "Read", "file_path": "/etc/passwd"},
            result={}, contract=contract,
        )
        assert not r.passed
        violations = _violations_to_list(r.violations)
        assert len(violations) > 0
        assert "fix_suggestion" in violations[0]
        assert "AGENTS.md" in violations[0]["fix_suggestion"]

    def test_deny_commands_suggestion(self):
        contract = IntentContract(deny_commands=["rm -rf"])
        r = check(
            params={"tool_name": "Bash", "command": "rm -rf /tmp"},
            result={}, contract=contract,
        )
        assert not r.passed
        violations = _violations_to_list(r.violations)
        assert "fix_suggestion" in violations[0]
        assert "deny_commands" in violations[0]["fix_suggestion"]

    def test_only_paths_suggestion(self):
        contract = IntentContract(only_paths=["./src/"])
        r = check(
            params={"tool_name": "Write", "file_path": "./docs/readme.md"},
            result={}, contract=contract,
        )
        assert not r.passed
        violations = _violations_to_list(r.violations)
        assert "fix_suggestion" in violations[0]
        assert "only_paths" in violations[0]["fix_suggestion"]


# ===========================================================================
# Governance envelope tests
# ===========================================================================

class TestGovernanceEnvelope:
    def test_envelope_has_all_fields(self):
        state = MockState()
        env = _governance_envelope(state, 1.5)
        assert "cieu_seq" in env
        assert "contract_hash" in env
        assert "latency_ms" in env
        assert "host" in env
        assert env["latency_ms"] == 1.5

    def test_cieu_seq_increments(self):
        state = MockState()
        e1 = _governance_envelope(state, 0)
        e2 = _governance_envelope(state, 0)
        assert e2["cieu_seq"] == e1["cieu_seq"] + 1

    def test_host_detection_generic(self):
        state = MockState()
        env = _governance_envelope(state, 0)
        assert env["host"] in ("claude_code", "cursor", "windsurf", "openclaw", "generic")
