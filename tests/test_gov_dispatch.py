"""Test suite for gov_dispatch and gov_acknowledge logic.

Tests the three-layer governance for task delegation:
1. Delegation chain authority check
2. HARD_OVERDUE gate
3. Obligation creation and fulfillment

Uses extracted dispatch_logic.py module to avoid MCP server dependencies.
"""
import time
from pathlib import Path

import pytest

from ystar.kernel.dimensions import DelegationChain, DelegationContract, IntentContract
from ystar.governance.omission_models import (
    ObligationStatus, OmissionType, Severity,
    ObligationRecord,
)
from ystar.governance.omission_store import InMemoryOmissionStore
from ystar.governance.omission_engine import OmissionEngine

from gov_mcp.dispatch_logic import (
    dispatch_task,
    acknowledge_task,
    check_delegation_authority,
    check_hard_overdue_gate,
)


@pytest.fixture
def delegation_chain():
    """Setup delegation chain with board->ceo->cto->eng-kernel."""
    chain = DelegationChain()

    # Add links as per test requirements
    # board -> ceo (full authority)
    ceo_contract = DelegationContract(
        principal="board",
        actor="ceo",
        contract=IntentContract(),
        allow_redelegate=True,
        delegation_depth=5,
    )
    chain.append(ceo_contract)

    # ceo -> cto (scope: src/,tests/)
    cto_contract = DelegationContract(
        principal="ceo",
        actor="cto",
        contract=IntentContract(),
        allow_redelegate=True,
        delegation_depth=4,
    )
    chain.append(cto_contract)

    # cto -> eng-kernel (scope: ystar/kernel/)
    kernel_contract = DelegationContract(
        principal="cto",
        actor="eng-kernel",
        contract=IntentContract(),
        allow_redelegate=False,
        delegation_depth=0,
    )
    chain.append(kernel_contract)

    return chain


@pytest.fixture
def omission_engine():
    """Setup OmissionEngine with in-memory store."""
    store = InMemoryOmissionStore()
    return OmissionEngine(store=store)


def test_dispatch_with_valid_authority(delegation_chain, omission_engine):
    """Test dispatch from CEO to CTO (valid delegation)."""
    result = dispatch_task(
        dispatcher_id="ceo",
        target_agent="cto",
        task_id="task-001",
        task_description="Fix critical bug in kernel",
        chain=delegation_chain,
        engine=omission_engine,
        channel="agent_tool",
        acknowledge_within_secs=300.0,
    )

    assert result["decision"] == "ALLOW"
    assert result["dispatcher_id"] == "ceo"
    assert result["target_agent"] == "cto"
    assert result["task_id"] == "task-001"
    assert "obligation_id" in result
    assert result["authority_path"] == ["ceo", "cto"]

    # Verify obligation was created
    obligations = omission_engine.store.list_obligations(
        entity_id="task-001",
        actor_id="cto",
    )
    assert len(obligations) == 1
    assert obligations[0].status == ObligationStatus.PENDING
    assert obligations[0].obligation_type == OmissionType.REQUIRED_ACKNOWLEDGEMENT.value


def test_dispatch_without_authority(delegation_chain, omission_engine):
    """Test dispatch from CEO to eng-kernel (no direct delegation)."""
    result = dispatch_task(
        dispatcher_id="ceo",
        target_agent="eng-kernel",
        task_id="task-002",
        task_description="Implement new feature",
        chain=delegation_chain,
        engine=omission_engine,
        channel="agent_tool",
    )

    assert result["decision"] == "DENY"
    assert "no delegation authority" in result["reason"]
    assert result["dispatcher_id"] == "ceo"
    assert result["target_agent"] == "eng-kernel"

    # Verify no obligation was created
    obligations = omission_engine.store.list_obligations(
        entity_id="task-002",
    )
    assert len(obligations) == 0


def test_dispatch_blocked_by_hard_overdue(delegation_chain, omission_engine):
    """Test dispatch blocked when dispatcher has HARD_OVERDUE obligations."""
    # Create a HARD_OVERDUE obligation for CEO
    now = time.time()
    overdue_ob = ObligationRecord(
        entity_id="old-task",
        actor_id="ceo",
        obligation_type=OmissionType.REQUIRED_ACKNOWLEDGEMENT.value,
        required_event_types=["acknowledgement_event"],
        due_at=now - 1000,  # 1000 seconds overdue
        status=ObligationStatus.HARD_OVERDUE,
        severity=Severity.CRITICAL,
        created_at=now - 2000,
        updated_at=now - 500,
    )
    omission_engine.store.add_obligation(overdue_ob)

    # CEO tries to dispatch to CTO
    result = dispatch_task(
        dispatcher_id="ceo",
        target_agent="cto",
        task_id="task-003",
        task_description="New task",
        chain=delegation_chain,
        engine=omission_engine,
        channel="agent_tool",
    )

    assert result["decision"] == "DENY"
    assert "HARD_OVERDUE" in result["reason"]
    assert overdue_ob.obligation_id in result["hard_overdue_obligations"]


def test_cto_to_eng_kernel_dispatch(delegation_chain, omission_engine):
    """Test dispatch from CTO to eng-kernel (valid delegation)."""
    result = dispatch_task(
        dispatcher_id="cto",
        target_agent="eng-kernel",
        task_id="task-004",
        task_description="Refactor dimensions.py",
        chain=delegation_chain,
        engine=omission_engine,
        channel="telegram",
    )

    assert result["decision"] == "ALLOW"
    assert result["dispatcher_id"] == "cto"
    assert result["target_agent"] == "eng-kernel"
    assert result["authority_path"] == ["cto", "eng-kernel"]


def test_acknowledge_task(delegation_chain, omission_engine):
    """Test acknowledging a dispatched task."""
    # First dispatch a task
    dispatch_result = dispatch_task(
        dispatcher_id="ceo",
        target_agent="cto",
        task_id="task-005",
        task_description="Review code",
        chain=delegation_chain,
        engine=omission_engine,
        channel="agent_tool",
    )
    assert dispatch_result["decision"] == "ALLOW"
    obligation_id = dispatch_result["obligation_id"]

    # CTO acknowledges the task
    ack_result = acknowledge_task(
        agent_id="cto",
        task_id="task-005",
        engine=omission_engine,
        accepted=True,
    )

    assert ack_result["status"] == "ACKNOWLEDGED"
    assert ack_result["agent_id"] == "cto"
    assert ack_result["task_id"] == "task-005"
    assert ack_result["accepted"] is True
    assert ack_result["obligation_fulfilled"] is True

    # Verify obligation was fulfilled
    ob = omission_engine.store.get_obligation(obligation_id)
    assert ob.status == ObligationStatus.FULFILLED
    assert ob.fulfilled_by_event_id is not None


def test_reject_task(delegation_chain, omission_engine):
    """Test rejecting a dispatched task."""
    # Dispatch task
    dispatch_task(
        dispatcher_id="ceo",
        target_agent="cto",
        task_id="task-006",
        task_description="Impossible task",
        chain=delegation_chain,
        engine=omission_engine,
        channel="agent_tool",
    )

    # CTO rejects the task
    reject_result = acknowledge_task(
        agent_id="cto",
        task_id="task-006",
        engine=omission_engine,
        accepted=False,
        rejection_reason="Insufficient resources",
    )

    assert reject_result["status"] == "REJECTED"
    assert reject_result["accepted"] is False
    assert reject_result["obligation_fulfilled"] is True
    assert reject_result["rejection_reason"] == "Insufficient resources"


def test_acknowledge_nonexistent_task(delegation_chain, omission_engine):
    """Test acknowledging a task that doesn't exist."""
    result = acknowledge_task(
        agent_id="cto",
        task_id="nonexistent-task",
        engine=omission_engine,
        accepted=True,
    )

    assert result["status"] == "NOT_FOUND"
    assert "No pending acknowledgement obligation" in result["reason"]


def test_dispatch_obligation_timeout_detection(delegation_chain, omission_engine):
    """Test that overdue acknowledgements are detected."""
    # Dispatch with very short timeout
    dispatch_task(
        dispatcher_id="ceo",
        target_agent="cto",
        task_id="task-007",
        task_description="Urgent task",
        chain=delegation_chain,
        engine=omission_engine,
        acknowledge_within_secs=0.1,  # 100ms timeout
    )

    # Wait for timeout
    time.sleep(0.2)

    # Check if obligation is now overdue
    obligations = omission_engine.store.list_obligations(
        entity_id="task-007",
        actor_id="cto",
    )
    assert len(obligations) == 1
    ob = obligations[0]

    # Manually check overdue (in real system, scanner would do this)
    now = time.time()
    assert now > ob.due_at
    assert ob.is_overdue(now)


def test_check_delegation_authority_function(delegation_chain):
    """Test check_delegation_authority helper function."""
    # Valid authority
    has_auth, path = check_delegation_authority("ceo", "cto", delegation_chain)
    assert has_auth is True
    assert path == ["ceo", "cto"]

    # Invalid authority
    has_auth, path = check_delegation_authority("ceo", "eng-kernel", delegation_chain)
    assert has_auth is False
    assert path == []


def test_check_hard_overdue_gate_function(omission_engine):
    """Test check_hard_overdue_gate helper function."""
    now = time.time()

    # No overdue obligations
    overdue = check_hard_overdue_gate("ceo", omission_engine)
    assert len(overdue) == 0

    # Add HARD_OVERDUE obligation
    ob = ObligationRecord(
        entity_id="test-task",
        actor_id="ceo",
        obligation_type=OmissionType.REQUIRED_ACKNOWLEDGEMENT.value,
        required_event_types=["ack"],
        due_at=now - 1000,
        status=ObligationStatus.HARD_OVERDUE,
        severity=Severity.CRITICAL,
        created_at=now - 2000,
        updated_at=now - 500,
    )
    omission_engine.store.add_obligation(ob)

    # Should now detect it
    overdue = check_hard_overdue_gate("ceo", omission_engine)
    assert len(overdue) == 1
    assert overdue[0].obligation_id == ob.obligation_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
