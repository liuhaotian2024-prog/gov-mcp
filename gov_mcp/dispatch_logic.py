"""Dispatch and acknowledge logic extracted from server.py.

This module provides governance dispatch logic without MCP dependencies,
making it testable without a running MCP server.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Dict, Tuple, List, Optional

from ystar.kernel.dimensions import DelegationChain
from ystar.governance.omission_models import (
    ObligationRecord,
    GovernanceEvent,
    GEventType,
    ObligationStatus,
    OmissionType,
    Severity,
)
from ystar.governance.omission_engine import OmissionEngine


def check_delegation_authority(
    dispatcher_id: str,
    target_agent: str,
    chain: DelegationChain,
) -> Tuple[bool, List[str]]:
    """Check if dispatcher has authority over target_agent.

    Returns:
        (has_authority: bool, authority_path: List[str])
    """
    has_authority = False
    authority_path = []

    # Tree mode: check if target_agent is in dispatcher's subtree
    if chain.root is not None:
        dispatcher_node = chain.all_contracts.get(dispatcher_id)
        if dispatcher_node:
            def is_descendant(node, target):
                if node.actor == target:
                    return True
                for child in node.children:
                    if is_descendant(child, target):
                        return True
                return False

            has_authority = is_descendant(dispatcher_node, target_agent)
            if has_authority:
                authority_path = [dispatcher_id, target_agent]

    # Linear mode: check if dispatcher->target link exists
    if not has_authority:
        for link in chain.links:
            if link.principal == dispatcher_id and link.actor == target_agent:
                has_authority = True
                authority_path = [dispatcher_id, target_agent]
                break

    return has_authority, authority_path


def check_hard_overdue_gate(
    dispatcher_id: str,
    engine: OmissionEngine,
) -> List[ObligationRecord]:
    """Check if dispatcher has HARD_OVERDUE obligations.

    Returns:
        List of HARD_OVERDUE obligations (empty if none)
    """
    return engine.store.list_obligations(
        actor_id=dispatcher_id,
        status=ObligationStatus.HARD_OVERDUE,
    )


def create_dispatch_obligation(
    task_id: str,
    target_agent: str,
    trigger_event_id: str,
    acknowledge_within_secs: float,
    now: float,
) -> ObligationRecord:
    """Create acknowledgement obligation for dispatched task.

    Args:
        task_id: Task identifier
        target_agent: Agent who must acknowledge
        trigger_event_id: UUID of dispatch event
        acknowledge_within_secs: Deadline for acknowledgement
        now: Current timestamp

    Returns:
        ObligationRecord ready to be stored
    """
    obligation_id = str(uuid.uuid4())
    return ObligationRecord(
        obligation_id=obligation_id,
        entity_id=task_id,
        actor_id=target_agent,
        obligation_type=OmissionType.REQUIRED_ACKNOWLEDGEMENT.value,
        trigger_event_id=trigger_event_id,
        required_event_types=[
            GEventType.TASK_ACKNOWLEDGED,
            GEventType.TASK_REJECTED,
        ],
        due_at=now + acknowledge_within_secs,
        grace_period_secs=0.0,
        hard_overdue_secs=acknowledge_within_secs * 0.5,
        status=ObligationStatus.PENDING,
        severity=Severity.HIGH,
        created_at=now,
        updated_at=now,
    )


def dispatch_task(
    dispatcher_id: str,
    target_agent: str,
    task_id: str,
    task_description: str,
    chain: DelegationChain,
    engine: OmissionEngine,
    channel: str = "unknown",
    acknowledge_within_secs: float = 300.0,
) -> Dict:
    """Core dispatch logic without MCP server dependency.

    Three-layer enforcement:
    1. Delegation chain authority check
    2. HARD_OVERDUE gate (blocks dispatcher with overdue obligations)
    3. Obligation creation for acknowledgement

    Returns:
        Dict with decision (ALLOW/DENY), obligation_id if allowed, reason if denied
    """
    t0 = time.perf_counter()
    now = time.time()

    # Layer 1: Check delegation chain authority
    has_authority, authority_path = check_delegation_authority(
        dispatcher_id, target_agent, chain
    )

    if not has_authority:
        latency_ms = (time.perf_counter() - t0) * 1000
        return {
            "decision": "DENY",
            "reason": f"Agent '{dispatcher_id}' has no delegation authority over '{target_agent}'",
            "dispatcher_id": dispatcher_id,
            "target_agent": target_agent,
            "task_id": task_id,
            "authority_path": [],
            "latency_ms": round(latency_ms, 4),
        }

    # Layer 2: Check for HARD_OVERDUE obligations (blocks dispatch)
    dispatcher_obs = check_hard_overdue_gate(dispatcher_id, engine)
    if dispatcher_obs:
        latency_ms = (time.perf_counter() - t0) * 1000
        return {
            "decision": "DENY",
            "reason": f"Dispatcher '{dispatcher_id}' has {len(dispatcher_obs)} HARD_OVERDUE obligations",
            "dispatcher_id": dispatcher_id,
            "target_agent": target_agent,
            "task_id": task_id,
            "hard_overdue_obligations": [ob.obligation_id for ob in dispatcher_obs],
            "latency_ms": round(latency_ms, 4),
        }

    # Layer 3: ALLOW — record dispatch event and create obligation
    dispatch_event_id = str(uuid.uuid4())
    dispatch_event = GovernanceEvent(
        event_id=dispatch_event_id,
        event_type=GEventType.TASK_DISPATCHED,
        entity_id=task_id,
        actor_id=dispatcher_id,
        ts=now,
        payload={
            "target_agent": target_agent,
            "task_description": task_description,
            "channel": channel,
            "acknowledge_within_secs": acknowledge_within_secs,
        },
        source="gov_dispatch",
    )
    engine.store.add_event(dispatch_event)

    # Create acknowledgement obligation
    obligation = create_dispatch_obligation(
        task_id=task_id,
        target_agent=target_agent,
        trigger_event_id=dispatch_event_id,
        acknowledge_within_secs=acknowledge_within_secs,
        now=now,
    )
    engine.store.add_obligation(obligation)

    latency_ms = (time.perf_counter() - t0) * 1000

    return {
        "decision": "ALLOW",
        "dispatcher_id": dispatcher_id,
        "target_agent": target_agent,
        "task_id": task_id,
        "obligation_id": obligation.obligation_id,
        "acknowledge_due_at": obligation.due_at,
        "authority_path": authority_path,
        "channel": channel,
        "latency_ms": round(latency_ms, 4),
    }


def acknowledge_task(
    agent_id: str,
    task_id: str,
    engine: OmissionEngine,
    accepted: bool = True,
    rejection_reason: str = "",
) -> Dict:
    """Acknowledge or reject a dispatched task.

    Fulfills the REQUIRED_ACKNOWLEDGEMENT obligation created by dispatch_task.

    Args:
        agent_id: Agent acknowledging the task
        task_id: Task identifier
        engine: OmissionEngine instance
        accepted: True to accept, False to reject
        rejection_reason: Why task was rejected (if accepted=False)

    Returns:
        Dict with status (ACKNOWLEDGED/REJECTED/NOT_FOUND), obligation_fulfilled flag
    """
    now = time.time()

    # Find pending acknowledgement obligation for this task
    obligations = engine.store.list_obligations(
        entity_id=task_id,
        actor_id=agent_id,
    )

    matching_ob = None
    for ob in obligations:
        status_val = str(getattr(ob.status, 'value', ob.status))
        ob_type_val = str(getattr(ob.obligation_type, 'value', ob.obligation_type))
        if (
            status_val in ('pending', 'soft_overdue', 'hard_overdue')
            and ob_type_val == OmissionType.REQUIRED_ACKNOWLEDGEMENT.value
        ):
            matching_ob = ob
            break

    if not matching_ob:
        return {
            "status": "NOT_FOUND",
            "agent_id": agent_id,
            "task_id": task_id,
            "reason": f"No pending acknowledgement obligation found for task '{task_id}' and agent '{agent_id}'",
            "obligation_fulfilled": False,
        }

    # Record acknowledgement event
    ack_event_id = str(uuid.uuid4())
    event_type = GEventType.TASK_ACKNOWLEDGED if accepted else GEventType.TASK_REJECTED

    ack_event = GovernanceEvent(
        event_id=ack_event_id,
        event_type=event_type,
        entity_id=task_id,
        actor_id=agent_id,
        ts=now,
        payload={
            "accepted": accepted,
            "rejection_reason": rejection_reason if not accepted else "",
            "obligation_id": matching_ob.obligation_id,
        },
        source="gov_acknowledge",
    )
    engine.store.add_event(ack_event)

    # Fulfill obligation
    matching_ob.status = ObligationStatus.FULFILLED
    matching_ob.fulfilled_by_event_id = ack_event_id
    matching_ob.fulfilled_at = now
    matching_ob.updated_at = now
    engine.store.update_obligation(matching_ob)

    return {
        "status": "ACKNOWLEDGED" if accepted else "REJECTED",
        "agent_id": agent_id,
        "task_id": task_id,
        "accepted": accepted,
        "obligation_fulfilled": True,
        "obligation_id": matching_ob.obligation_id,
        "rejection_reason": rejection_reason if not accepted else "",
    }
