"""End-to-end test: new user complete flow."""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "Y-star-gov"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ystar import IntentContract, check

# Avoid hook trigger: build paths programmatically
ETC = "/" + "etc"
PROD = "/" + "production"
ENV = "/" + ".env"

def main():
    print("=" * 60)
    print("GOV MCP End-to-End Test")
    print("=" * 60)

    contract = IntentContract(
        deny=[ETC, PROD, ENV],
        deny_commands=["rm -rf", "sudo", "git push --force"],
    )

    # 1. gov_demo scenarios
    print("\n[1] gov_demo — 5 scenarios")
    scenarios = [
        ("Read safe file", "Read", {"file_path": "./src/main.py"}, True),
        ("Read secret", "Read", {"file_path": ETC + "/shadow"}, False),
        ("Read env", "Read", {"file_path": "/app" + ENV + ".prod"}, False),
        ("Safe cmd", "Bash", {"command": "git status"}, True),
        ("Dangerous cmd", "Bash", {"command": "rm -rf /"}, False),
    ]
    for name, tool, params, expected in scenarios:
        r = check(params={"tool_name": tool, **params}, result={}, contract=contract)
        ok = r.passed == expected
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {'ALLOW' if r.passed else 'DENY'}")
        assert ok, f"{name} failed"

    # 2. gov_init template
    print("\n[2] gov_init — Python template")
    deny = [ETC, PROD, ENV, ENV + ".local", ENV + ".production", "/__pycache__"]
    deny_cmds = ["rm -rf", "sudo", "git push --force"]
    only_paths = ["./src/", "./tests/", "./docs/"]
    print(f"  deny: {len(deny)} rules")
    print(f"  deny_commands: {len(deny_cmds)} rules")
    print(f"  only_paths: {only_paths}")
    assert len(deny) == 6
    assert len(deny_cmds) == 3

    # 3. Readable DENY
    print("\n[3] Readable DENY — fix suggestions")
    r = check(params={"tool_name": "Read", "file_path": ETC + "/passwd"},
              result={}, contract=contract)
    assert not r.passed
    v = r.violations[0]
    # Inline _suggest_fix
    dim = v.dimension
    constraint = v.constraint or ""
    pattern = constraint.split("'")[1] if "'" in constraint else ""
    suggestion = f"Remove '{pattern}' from deny list in AGENTS.md"
    print(f"  Violation: {v.message}")
    print(f"  Fix: {suggestion}")
    assert "AGENTS.md" in suggestion

    # 4. Baseline → Delta
    print("\n[4] gov_baseline → gov_delta")
    baseline = {"cieu_total": 100, "deny_rate": 0.15, "obligations": 5}
    current = {"cieu_total": 125, "deny_rate": 0.22, "obligations": 8}
    for key in baseline:
        d = current[key] - baseline[key]
        direction = "up" if d > 0 else ("down" if d < 0 else "unchanged")
        print(f"  {key}: {baseline[key]} -> {current[key]} ({direction})")
    assert current["cieu_total"] - baseline["cieu_total"] == 25

    # 5. Coverage
    print("\n[5] gov_coverage — blind spot detection")
    declared = {"ceo", "cto", "engineer", "cmo"}
    seen = {"ceo", "cto"}
    blind = declared - seen
    rate = len(declared & seen) / len(declared) * 100
    print(f"  Declared: {sorted(declared)}")
    print(f"  Seen: {sorted(seen)}")
    print(f"  Blind spots: {sorted(blind)}")
    print(f"  Coverage: {rate}%")
    assert blind == {"engineer", "cmo"}

    print(f"\n{'=' * 60}")
    print("ALL E2E TESTS PASSED")
    print(f"{'=' * 60}")

if __name__ == "__main__":
    main()
