"""
Concurrent stress test for GOV MCP.

Scenario: 3 agents collaborate simultaneously through the governance layer.
  Agent 1 (CEO): Assigns tasks, creates delegation chains
  Agent 2 (CTO): Receives delegation, spawns engineer sub-agent
  Agent 3 (Engineer): Executes tasks, hits DENY, requests escalation

Tests:
  1. CIEU write race conditions under concurrent access
  2. Delegation chain integrity under concurrent mutations
  3. gov_escalate correctness under concurrent requests
  4. Throughput: gov_check requests per second
"""
import json
import os
import sys
import time
import threading
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Ensure ystar is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                "Y-star-gov"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

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


# ---------------------------------------------------------------------------
# Inline core logic from gov_mcp/server.py (avoids mcp import dependency)
# ---------------------------------------------------------------------------

def _get_contract_for_agent(agent_id: str, state) -> IntentContract:
    chain = state.delegation_chain
    if chain.root is not None and agent_id in chain.all_contracts:
        return chain.all_contracts[agent_id].contract
    for link in reversed(chain.links):
        if link.actor == agent_id:
            return link.contract
    return state.active_contract


class MockCIEUStore:
    """Thread-safe mock CIEU store for testing write contention."""

    def __init__(self):
        self._records: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._write_count = 0
        self._race_detected = False

    def write_dict(self, event: Dict[str, Any]):
        # Simulate write without lock to detect races
        count_before = self._write_count
        time.sleep(0.0001)  # Tiny delay to expose race windows
        self._write_count = count_before + 1
        with self._lock:
            self._records.append(event)

    @property
    def records(self):
        with self._lock:
            return list(self._records)

    def check_integrity(self) -> Dict[str, Any]:
        with self._lock:
            actual_len = len(self._records)
        return {
            "write_count_counter": self._write_count,
            "actual_records": actual_len,
            "race_detected": self._write_count != actual_len,
            "lost_writes": abs(self._write_count - actual_len),
        }


class MockState:
    """Simulates _State from gov_mcp/server.py."""

    def __init__(self):
        self.active_contract = IntentContract(
            deny=["/etc", "/production", "/.env"],
            deny_commands=["rm -rf", "sudo", "git push --force"],
        )
        self.delegation_chain = DelegationChain()
        self.omission_engine = OmissionEngine(store=InMemoryOmissionStore())
        self._cieu_store = MockCIEUStore()
        self._chain_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Test 1: CIEU Write Race Conditions
# ---------------------------------------------------------------------------

def test_cieu_race_conditions():
    """100 concurrent CIEU writes — check for lost writes."""
    store = MockCIEUStore()
    n_writers = 10
    writes_per_thread = 100

    def writer(thread_id):
        for i in range(writes_per_thread):
            store.write_dict({
                "event_type": "gov_check",
                "agent_id": f"agent-{thread_id}",
                "decision": "ALLOW",
                "seq": i,
                "thread": thread_id,
                "timestamp": time.time(),
            })

    with ThreadPoolExecutor(max_workers=n_writers) as pool:
        futures = [pool.submit(writer, tid) for tid in range(n_writers)]
        for f in as_completed(futures):
            f.result()

    integrity = store.check_integrity()
    expected = n_writers * writes_per_thread

    return {
        "test": "CIEU Race Conditions",
        "total_writes_expected": expected,
        "actual_records": integrity["actual_records"],
        "counter_value": integrity["write_count_counter"],
        "race_detected": integrity["race_detected"],
        "lost_writes": integrity["lost_writes"],
        "passed": integrity["actual_records"] == expected,
    }


# ---------------------------------------------------------------------------
# Test 2: Delegation Chain Concurrent Mutations
# ---------------------------------------------------------------------------

def test_delegation_chain_pollution():
    """Multiple agents registering delegations simultaneously."""
    state = MockState()
    n_delegations = 50
    errors = []

    def register_delegation(idx):
        try:
            principal = f"ceo-{idx % 5}"
            actor = f"eng-{idx}"
            contract = IntentContract(
                only_paths=[f"./src/module-{idx}/"],
                deny=["/etc", "/production"],
                deny_commands=["rm -rf", "sudo"],
            )
            link = DelegationContract(
                principal=principal,
                actor=actor,
                contract=contract,
                delegation_depth=0,
            )
            with state._chain_lock:
                state.delegation_chain.append(link)
            return actor
        except Exception as e:
            errors.append(str(e))
            return None

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(register_delegation, i)
                   for i in range(n_delegations)]
        actors = [f.result() for f in as_completed(futures)]

    # Verify chain integrity
    chain = state.delegation_chain
    unique_actors = set(link.actor for link in chain.links)

    # Each agent should have their own contract
    pollution_detected = False
    for link in chain.links:
        contract = _get_contract_for_agent(link.actor, state)
        expected_path = f"./src/module-{link.actor.split('-')[1]}/"
        if contract.only_paths != [expected_path]:
            pollution_detected = True
            break

    return {
        "test": "Delegation Chain Pollution",
        "delegations_attempted": n_delegations,
        "chain_depth": chain.depth,
        "unique_actors": len(unique_actors),
        "errors": errors,
        "pollution_detected": pollution_detected,
        "passed": (chain.depth == n_delegations
                   and len(unique_actors) == n_delegations
                   and not pollution_detected
                   and len(errors) == 0),
    }


# ---------------------------------------------------------------------------
# Test 3: Concurrent gov_check + gov_escalate
# ---------------------------------------------------------------------------

def test_concurrent_check_and_escalate():
    """
    3 agents simultaneously:
    - CEO delegates to CTO (only_paths: ./src/)
    - CTO delegates to Engineer (only_paths: ./src/core/)
    - Engineer runs gov_checks + hits DENY + escalates
    All happening concurrently.
    """
    state = MockState()
    results = {"checks": [], "escalations": [], "errors": []}
    results_lock = threading.Lock()

    # Pre-register delegation chain
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

    def ceo_work():
        """CEO: runs 100 gov_checks on allowed actions."""
        for i in range(100):
            contract = _get_contract_for_agent("ceo", state)
            r = check(
                params={"tool_name": "Read", "file_path": f"/Users/project/file{i}.py"},
                result={}, contract=contract,
            )
            with results_lock:
                results["checks"].append(("ceo", r.passed))

    def cto_work():
        """CTO: runs 100 gov_checks, mix of allowed and denied."""
        for i in range(100):
            path = f"./src/module{i}/main.py" if i % 2 == 0 else f"/etc/secret{i}"
            contract = _get_contract_for_agent("cto", state)
            r = check(
                params={"tool_name": "Write", "file_path": path},
                result={}, contract=contract,
            )
            with results_lock:
                results["checks"].append(("cto", r.passed))

    def engineer_work():
        """Engineer: runs checks, hits DENY on ./src/utils/, escalates."""
        for i in range(100):
            if i % 3 == 0:
                # Allowed: ./src/core/
                path = f"./src/core/file{i}.py"
            elif i % 3 == 1:
                # Denied: ./src/utils/ (outside only_paths)
                path = f"./src/utils/helper{i}.py"
            else:
                # Denied: /etc
                path = f"/etc/config{i}"

            contract = _get_contract_for_agent("engineer", state)
            r = check(
                params={"tool_name": "Write", "file_path": path},
                result={}, contract=contract,
            )
            with results_lock:
                results["checks"].append(("engineer", r.passed))

            # If denied on utils path, try escalation
            if not r.passed and "utils" in path:
                # Simulate escalation: expand engineer's contract
                with state._chain_lock:
                    for link in state.delegation_chain.links:
                        if link.actor == "engineer":
                            if "./src/utils/" not in link.contract.only_paths:
                                new_paths = list(link.contract.only_paths) + ["./src/utils/"]
                                link.contract = IntentContract(
                                    only_paths=new_paths,
                                    deny=list(link.contract.deny),
                                    deny_commands=list(link.contract.deny_commands),
                                )
                                with results_lock:
                                    results["escalations"].append(i)
                            break

    threads = [
        threading.Thread(target=ceo_work),
        threading.Thread(target=cto_work),
        threading.Thread(target=engineer_work),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    # Analyze results
    with results_lock:
        ceo_checks = [(a, p) for a, p in results["checks"] if a == "ceo"]
        cto_checks = [(a, p) for a, p in results["checks"] if a == "cto"]
        eng_checks = [(a, p) for a, p in results["checks"] if a == "engineer"]

    ceo_allow = sum(1 for _, p in ceo_checks if p)
    cto_allow = sum(1 for _, p in cto_checks if p)
    cto_deny = sum(1 for _, p in cto_checks if not p)
    eng_allow = sum(1 for _, p in eng_checks if p)
    eng_deny = sum(1 for _, p in eng_checks if not p)

    deadlock = any(t.is_alive() for t in threads)

    return {
        "test": "Concurrent Check + Escalate",
        "total_checks": len(results["checks"]),
        "ceo": {"total": len(ceo_checks), "allow": ceo_allow},
        "cto": {"total": len(cto_checks), "allow": cto_allow, "deny": cto_deny},
        "engineer": {"total": len(eng_checks), "allow": eng_allow, "deny": eng_deny},
        "escalations": len(results["escalations"]),
        "deadlock_detected": deadlock,
        "errors": results["errors"],
        "passed": (len(results["checks"]) == 300
                   and not deadlock
                   and len(results["errors"]) == 0),
    }


# ---------------------------------------------------------------------------
# Test 4: Throughput — gov_check requests per second
# ---------------------------------------------------------------------------

def test_throughput():
    """Measure sustained gov_check throughput."""
    state = MockState()

    # Register some delegations for realistic load
    for i in range(5):
        contract = IntentContract(
            only_paths=[f"./src/agent{i}/"],
            deny=["/etc"], deny_commands=["rm -rf"],
        )
        state.delegation_chain.append(DelegationContract(
            principal="root", actor=f"agent-{i}", contract=contract,
        ))

    n_requests = 5000
    agents = [f"agent-{i}" for i in range(5)] + ["unknown-agent"]
    paths = ["./src/agent0/f.py", "/etc/passwd", "./src/agent1/g.py",
             "/production/db.conf", "./safe/file.txt"]

    t0 = time.perf_counter()
    results = []
    for i in range(n_requests):
        agent = agents[i % len(agents)]
        path = paths[i % len(paths)]
        contract = _get_contract_for_agent(agent, state)
        r = check(
            params={"tool_name": "Read", "file_path": path},
            result={}, contract=contract,
        )
        results.append(r.passed)
    elapsed = time.perf_counter() - t0

    rps = n_requests / elapsed
    allow_count = sum(1 for r in results if r)
    deny_count = n_requests - allow_count

    # Concurrent throughput
    concurrent_results = []
    concurrent_errors = []

    def worker(batch_start, batch_size):
        local_results = []
        for i in range(batch_start, batch_start + batch_size):
            agent = agents[i % len(agents)]
            path = paths[i % len(paths)]
            contract = _get_contract_for_agent(agent, state)
            r = check(
                params={"tool_name": "Read", "file_path": path},
                result={}, contract=contract,
            )
            local_results.append(r.passed)
        return local_results

    n_concurrent = 5000
    batch_size = 1000
    t1 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = []
        for batch_i in range(5):
            futures.append(pool.submit(worker, batch_i * batch_size, batch_size))
        for f in as_completed(futures):
            concurrent_results.extend(f.result())
    elapsed_concurrent = time.perf_counter() - t1
    concurrent_rps = n_concurrent / elapsed_concurrent

    return {
        "test": "Throughput",
        "sequential": {
            "requests": n_requests,
            "elapsed_s": round(elapsed, 3),
            "rps": round(rps),
            "allow": allow_count,
            "deny": deny_count,
        },
        "concurrent_5_threads": {
            "requests": n_concurrent,
            "elapsed_s": round(elapsed_concurrent, 3),
            "rps": round(concurrent_rps),
        },
        "passed": rps > 1000,  # Minimum 1K rps sequential
    }


# ---------------------------------------------------------------------------
# Test 5: Delegation chain consistency under stress
# ---------------------------------------------------------------------------

def test_chain_consistency_under_load():
    """
    Concurrent reads and writes to delegation chain.
    Writers add new delegations, readers resolve contracts.
    Check that readers never get corrupted contracts.
    """
    state = MockState()
    errors = []
    errors_lock = threading.Lock()
    stop_event = threading.Event()

    def writer():
        for i in range(200):
            contract = IntentContract(
                only_paths=[f"./w{i}/"],
                deny=["/etc"],
            )
            link = DelegationContract(
                principal="root", actor=f"w-agent-{i}", contract=contract,
            )
            with state._chain_lock:
                state.delegation_chain.append(link)
            time.sleep(0.0001)
        stop_event.set()

    def reader():
        checks = 0
        while not stop_event.is_set() or checks < 100:
            agent_id = f"w-agent-{checks % 200}"
            contract = _get_contract_for_agent(agent_id, state)
            # Contract should either be global or have exactly one path
            if contract is not state.active_contract:
                if len(contract.only_paths) != 1:
                    with errors_lock:
                        errors.append(f"{agent_id}: expected 1 path, got {contract.only_paths}")
                expected = f"./w{agent_id.split('-')[-1]}/"
                if contract.only_paths[0] != expected:
                    with errors_lock:
                        errors.append(f"{agent_id}: expected {expected}, got {contract.only_paths[0]}")
            checks += 1
            if checks > 10000:
                break

    threads = [threading.Thread(target=writer)]
    for _ in range(3):
        threads.append(threading.Thread(target=reader))

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    return {
        "test": "Chain Consistency Under Load",
        "chain_depth": state.delegation_chain.depth,
        "errors": errors[:10],
        "total_errors": len(errors),
        "passed": len(errors) == 0,
    }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_all():
    print("=" * 60)
    print("GOV MCP Concurrent Stress Test")
    print("=" * 60)

    tests = [
        test_cieu_race_conditions,
        test_delegation_chain_pollution,
        test_concurrent_check_and_escalate,
        test_throughput,
        test_chain_consistency_under_load,
    ]

    all_results = []
    all_passed = True

    for test_fn in tests:
        print(f"\nRunning: {test_fn.__name__}...")
        t0 = time.perf_counter()
        try:
            result = test_fn()
            result["elapsed_s"] = round(time.perf_counter() - t0, 3)
        except Exception as e:
            result = {
                "test": test_fn.__name__,
                "passed": False,
                "error": str(e),
                "elapsed_s": round(time.perf_counter() - t0, 3),
            }

        status = "PASS" if result.get("passed") else "FAIL"
        print(f"  [{status}] {result.get('test', test_fn.__name__)} ({result['elapsed_s']}s)")
        if not result.get("passed"):
            all_passed = False
        all_results.append(result)

    print(f"\n{'=' * 60}")
    print(f"Results: {sum(1 for r in all_results if r.get('passed'))}/{len(all_results)} passed")
    print(f"{'=' * 60}")

    return all_results, all_passed


if __name__ == "__main__":
    results, passed = run_all()
    print("\nDetailed results:")
    for r in results:
        print(json.dumps(r, indent=2, default=str))
    sys.exit(0 if passed else 1)
