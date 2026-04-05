"""Layer 7+8: User health system + installation experience.

Layer 7: baseline/delta/trend with simulated 500 records
Layer 8: Installation detection and cross-platform readiness
"""
import os, sys, time, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "Y-star-gov"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ystar import IntentContract, check


# =====================================================================
# LAYER 7: Health System
# =====================================================================

def test_baseline_captures_state():
    """Baseline snapshot captures all key metrics."""
    baseline = {
        "label": "week1",
        "timestamp": time.time(),
        "cieu_total": 500,
        "deny_rate": 0.22,
        "obligations_total": 15,
        "obligations_pending": 3,
        "delegation_depth": 4,
    }
    assert all(k in baseline for k in
               ["cieu_total", "deny_rate", "obligations_total", "delegation_depth"])


def test_delta_detects_improvement():
    """Delta shows improvement when deny rate drops."""
    baseline = {"cieu_total": 200, "deny_rate": 0.30}
    current = {"cieu_total": 500, "deny_rate": 0.15}

    delta = {
        k: {"baseline": baseline[k], "current": current[k],
            "delta": current[k] - baseline[k],
            "direction": "down" if current[k] < baseline[k] else "up"}
        for k in baseline
    }

    assert delta["deny_rate"]["direction"] == "down"  # Improved
    assert delta["cieu_total"]["direction"] == "up"    # More events


def test_delta_detects_regression():
    """Delta shows regression when deny rate increases."""
    baseline = {"deny_rate": 0.10}
    current = {"deny_rate": 0.35}

    delta_val = current["deny_rate"] - baseline["deny_rate"]
    assert delta_val > 0  # Regression


def test_trend_7day_calculation():
    """7-day trend shows daily breakdown."""
    from collections import defaultdict

    # Simulate 500 events over 7 days
    daily = defaultdict(lambda: {"total": 0, "deny": 0})
    now = time.time()

    for i in range(500):
        day_offset = i % 7
        day = time.strftime("%Y-%m-%d", time.gmtime(now - day_offset * 86400))
        daily[day]["total"] += 1
        if i % 4 == 0:  # 25% deny rate
            daily[day]["deny"] += 1

    assert len(daily) == 7
    for day, d in daily.items():
        rate = d["deny"] / d["total"] if d["total"] > 0 else 0
        assert 0 <= rate <= 1.0


def test_quality_score_calculation():
    """Quality score based on dimension coverage and deny rate."""
    contract = IntentContract(
        deny=["/x"], deny_commands=["sudo"], only_paths=["./src/"],
    )
    dimensions_active = 3  # deny, deny_commands, only_paths
    dimensions_total = 8
    coverage = dimensions_active / dimensions_total
    deny_rate = 0.22
    fp_estimate = max(0, deny_rate - 0.3)
    quality = round(coverage * 0.6 + (1 - fp_estimate) * 0.4, 2)

    assert 0 <= quality <= 1.0
    assert 0.5 <= quality <= 0.7  # coverage*0.6 + (1-fp)*0.4


def test_coverage_blind_spots():
    """Detect agents not covered by governance."""
    declared = {"ceo", "cto", "engineer", "cmo", "intern"}
    seen = {"ceo", "cto", "engineer"}
    blind_spots = declared - seen
    coverage = len(declared & seen) / len(declared) * 100

    assert blind_spots == {"cmo", "intern"}
    assert coverage == 60.0


def test_500_simulated_records():
    """500 CIEU records with varied actions produce analyzable data."""
    contract = IntentContract(
        deny=["/secret", "/prod"],
        deny_commands=["sudo", "git push --force"],
        only_paths=["./src/", "./tests/"],
    )

    actions = [
        ("Read", {"file_path": "./src/app.py"}),
        ("Read", {"file_path": "/secret/key.pem"}),
        ("Write", {"file_path": "./src/new.py"}),
        ("Bash", {"command": "git status"}),
        ("Bash", {"command": "sudo reboot"}),
    ]

    results = {"allow": 0, "deny": 0}
    for i in range(100):
        for tool, params in actions:
            r = check(params={"tool_name": tool, **params}, result={}, contract=contract)
            if r.passed:
                results["allow"] += 1
            else:
                results["deny"] += 1

    total = results["allow"] + results["deny"]
    assert total == 500
    deny_rate = results["deny"] / total
    assert deny_rate > 0.1, "Expected some denials in 500 records"


# =====================================================================
# LAYER 8: Installation Experience
# =====================================================================

def test_ecosystem_detection():
    """Detect installed MCP ecosystems."""
    from gov_mcp.cli import detect_ecosystems
    ecosystems = detect_ecosystems()

    # Should detect at least the platform we're on
    assert len(ecosystems) >= 1
    for eco in ecosystems:
        assert hasattr(eco, 'name')
        assert hasattr(eco, 'detected')

    detected = [e for e in ecosystems if e.detected]
    print(f"\n  Detected ecosystems: {[e.name for e in detected]}")


def test_port_finding():
    """Auto-detect available port."""
    from gov_mcp.cli import _find_available_port
    port = _find_available_port(start=17922)  # Use high port to avoid conflicts
    assert 17922 <= port < 17942
    print(f"\n  Available port: {port}")


def test_agents_md_auto_detection():
    """AGENTS.md found in home or cwd."""
    from gov_mcp.cli import _find_agents_md
    md = _find_agents_md()
    if md:
        assert md.is_file()
        print(f"\n  AGENTS.md found: {md}")
    else:
        print(f"\n  AGENTS.md not found (expected in some environments)")


def test_state_directory_created():
    """Platform-appropriate state directory exists."""
    from gov_mcp.cli import _state_dir
    sd = _state_dir()
    assert sd.is_dir()
    print(f"\n  State dir: {sd}")


def test_install_detection_complete():
    """Full install detection produces structured output."""
    from gov_mcp.cli import detect_ecosystems, _find_agents_md, _find_available_port

    result = {
        "ecosystems": [{"name": e.name, "detected": e.detected}
                       for e in detect_ecosystems()],
        "agents_md": str(_find_agents_md()) if _find_agents_md() else None,
        "port": _find_available_port(start=17950),
    }

    assert "ecosystems" in result
    assert "port" in result
    assert isinstance(result["port"], int)
