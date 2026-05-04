"""Outbound receipt builders with no-send invariants."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Mapping

from gov_mcp.outbound.models import (
    OutboundExecutionMode,
    OutboundExecutionReceipt,
    OutboundFailureReceipt,
)


def receipt_id(action_id: str, execution_mode: str, suffix: str = "dry_run") -> str:
    digest = hashlib.sha256(f"{action_id}:{execution_mode}:{suffix}".encode("utf-8")).hexdigest()[:16]
    return f"outbound_receipt_{digest}"


def build_execution_receipt(
    *,
    action_id: str,
    execution_mode: str,
    preflight_result: Mapping[str, Any],
    guard_results: Mapping[str, str],
    execution_status: str = "dry_run_completed",
) -> OutboundExecutionReceipt:
    return OutboundExecutionReceipt(
        receipt_id=receipt_id(action_id, execution_mode),
        action_id=action_id,
        execution_mode=execution_mode,
        preflight_result=dict(preflight_result),
        guard_results=dict(guard_results),
        execution_status=execution_status,
        external_action_executed=False,
        provider_called=False,
        real_message_sent=False,
        ledger_transition="draft_or_dry_run_receipt_recorded",
        feedback_wait_state="not_waiting_feedback_until_real_send_receipt",
        reason_codes=list(preflight_result.get("reason_codes", [])),
    )


def build_failure_receipt(action_id: str, failure_code: str, reason_codes: List[str]) -> OutboundFailureReceipt:
    return OutboundFailureReceipt(
        receipt_id=receipt_id(action_id, OutboundExecutionMode.DENY.value, failure_code),
        action_id=action_id,
        failure_code=failure_code,
        execution_mode=OutboundExecutionMode.DENY.value,
        reason_codes=reason_codes,
        external_action_executed=False,
        provider_called=False,
        real_message_sent=False,
    )


def validate_no_send_receipt(receipt: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    for flag in ["external_action_executed", "provider_called", "real_message_sent"]:
        if receipt.get(flag) is not False:
            errors.append(f"{flag}_must_be_false")
    if not receipt.get("receipt_id"):
        errors.append("receipt_id_missing")
    if not receipt.get("action_id"):
        errors.append("action_id_missing")
    if receipt.get("execution_mode") == OutboundExecutionMode.GOV_MCP_EXECUTE_AFTER_ACTIVATION.value:
        errors.append("activated_real_execution_receipt_not_allowed_in_e16g")
    return errors
