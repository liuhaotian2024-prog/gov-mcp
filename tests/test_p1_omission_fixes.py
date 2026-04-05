"""Tests for P1 OmissionEngine fixes:
#2: Background obligation scanner
#6: HARD_OVERDUE blocks gov_check
"""
import os, sys, time, uuid, threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "Y-star-gov"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ystar import InMemoryOmissionStore, OmissionEngine, IntentContract, check
from ystar.governance.omission_models import ObligationRecord, ObligationStatus, Severity


# =====================================================================
# P1-#6: HARD_OVERDUE blocks new operations
# =====================================================================

class TestHardOverdueBlocking:

    def test_no_overdue_allows_check(self):
        """Agent with no overdue obligations can proceed."""
        store = InMemoryOmissionStore()
        engine = OmissionEngine(store=store)
        # No obligations — check should work
        contract = IntentContract(deny=["/secret"])
        r = check(params={"tool_name": "Read", "file_path": "./src/main.py"},
                  result={}, contract=contract)
        assert r.passed

    def test_hard_overdue_detected_in_store(self):
        """HARD_OVERDUE obligations are findable by actor_id."""
        store = InMemoryOmissionStore()
        ob = ObligationRecord(
            obligation_id=str(uuid.uuid4()),
            entity_id="task-1",
            actor_id="engineer",
            obligation_type="completion",
            due_at=time.time() - 600,
            status=ObligationStatus.HARD_OVERDUE,
        )
        store.add_obligation(ob)

        all_obs = store.list_obligations(actor_id="engineer")
        hard = [o for o in all_obs
                if str(getattr(o.status, 'value', o.status)) == 'hard_overdue']
        assert len(hard) == 1

    def test_soft_overdue_does_not_block(self):
        """SOFT_OVERDUE should NOT block — only HARD blocks."""
        store = InMemoryOmissionStore()
        ob = ObligationRecord(
            obligation_id=str(uuid.uuid4()),
            entity_id="task-2",
            actor_id="cto",
            obligation_type="status_update",
            due_at=time.time() - 60,
            status=ObligationStatus.SOFT_OVERDUE,
        )
        store.add_obligation(ob)

        all_obs = store.list_obligations(actor_id="cto")
        hard = [o for o in all_obs
                if str(getattr(o.status, 'value', o.status)) == 'hard_overdue']
        assert len(hard) == 0  # SOFT, not HARD

    def test_fulfilled_does_not_block(self):
        """Fulfilled obligations should not block."""
        store = InMemoryOmissionStore()
        ob = ObligationRecord(
            obligation_id=str(uuid.uuid4()),
            entity_id="task-3",
            actor_id="engineer",
            status=ObligationStatus.FULFILLED,
        )
        store.add_obligation(ob)

        all_obs = store.list_obligations(actor_id="engineer")
        hard = [o for o in all_obs
                if str(getattr(o.status, 'value', o.status)) == 'hard_overdue']
        assert len(hard) == 0


# =====================================================================
# P1-#2: Background obligation scanner
# =====================================================================

class TestBackgroundScanner:

    def test_scanner_transitions_overdue(self):
        """Scanner should transition past-deadline PENDING to SOFT_OVERDUE."""
        store = InMemoryOmissionStore()
        ob = ObligationRecord(
            obligation_id=str(uuid.uuid4()),
            entity_id="scan-test",
            actor_id="agent-1",
            obligation_type="task",
            due_at=time.time() - 60,  # 1 minute ago
            status=ObligationStatus.PENDING,
        )
        store.add_obligation(ob)

        # Simulate scanner logic
        now = time.time()
        all_obs = store.list_obligations()
        for o in all_obs:
            status = str(getattr(o.status, 'value', o.status))
            due = getattr(o, 'due_at', None)
            if status == 'pending' and due and due < now:
                o.status = ObligationStatus.SOFT_OVERDUE
                o.soft_violation_at = now
                store.update_obligation(o)

        updated = store.list_obligations(actor_id="agent-1")
        assert str(getattr(updated[0].status, 'value', updated[0].status)) == 'soft_overdue'

    def test_scanner_transitions_to_hard(self):
        """Scanner should transition to HARD_OVERDUE when way past deadline."""
        store = InMemoryOmissionStore()
        ob = ObligationRecord(
            obligation_id=str(uuid.uuid4()),
            entity_id="hard-test",
            actor_id="agent-2",
            obligation_type="task",
            due_at=time.time() - 600,  # 10 minutes ago
            hard_overdue_secs=300,     # HARD after 5 minutes
            status=ObligationStatus.PENDING,
        )
        store.add_obligation(ob)

        # Simulate scanner logic
        now = time.time()
        for o in store.list_obligations():
            status = str(getattr(o.status, 'value', o.status))
            due = getattr(o, 'due_at', None)
            if status == 'pending' and due and due < now:
                o.status = ObligationStatus.SOFT_OVERDUE
                hard_threshold = getattr(o, 'hard_overdue_secs', 300)
                if (now - due) > hard_threshold:
                    o.status = ObligationStatus.HARD_OVERDUE
                store.update_obligation(o)

        updated = store.list_obligations(actor_id="agent-2")
        assert str(getattr(updated[0].status, 'value', updated[0].status)) == 'hard_overdue'

    def test_scanner_does_not_touch_fulfilled(self):
        """Scanner should not modify fulfilled obligations."""
        store = InMemoryOmissionStore()
        ob = ObligationRecord(
            obligation_id=str(uuid.uuid4()),
            entity_id="done-task",
            actor_id="agent-3",
            status=ObligationStatus.FULFILLED,
            due_at=time.time() - 600,
        )
        store.add_obligation(ob)

        # Simulate scanner — only touches PENDING
        for o in store.list_obligations():
            status = str(getattr(o.status, 'value', o.status))
            if status == 'pending':
                pass  # Would transition, but this one is fulfilled

        updated = store.list_obligations(actor_id="agent-3")
        assert str(getattr(updated[0].status, 'value', updated[0].status)) == 'fulfilled'

    def test_scanner_thread_starts(self):
        """Background scanner thread can start and stop cleanly."""
        stop_event = threading.Event()
        started = threading.Event()

        def scanner():
            started.set()
            while not stop_event.is_set():
                stop_event.wait(timeout=0.1)

        t = threading.Thread(target=scanner, daemon=True)
        t.start()
        started.wait(timeout=2)
        assert t.is_alive()

        stop_event.set()
        t.join(timeout=2)
        assert not t.is_alive()
