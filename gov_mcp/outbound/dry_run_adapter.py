"""Provider-safe local outbound dry-run adapter.

This adapter intentionally has no provider client, no network dependency, no
login path, and no credential requirement. It turns an outbound action intent
into a deterministic no-send receipt.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

from gov_mcp.outbound.models import (
    OutboundActionIntent,
    OutboundExecutionMode,
    intent_from_mapping,
)
from gov_mcp.outbound.policy import evaluate_outbound_policy
from gov_mcp.outbound.receipts import build_execution_receipt, build_failure_receipt


def dry_run_outbound_action(
    intent: OutboundActionIntent | Mapping[str, Any],
    guard_context: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    action_intent = intent if isinstance(intent, OutboundActionIntent) else intent_from_mapping(intent)
    preflight = evaluate_outbound_policy(action_intent, guard_context)
    preflight_dict = preflight.to_dict()

    if not preflight.allowed_for_dry_run:
        receipt = build_failure_receipt(
            action_id=action_intent.action_id,
            failure_code="dry_run_denied",
            reason_codes=preflight.reason_codes,
        ).to_dict()
    else:
        execution_mode = (
            OutboundExecutionMode.DRAFT_ONLY.value
            if preflight.execution_mode == OutboundExecutionMode.DRAFT_ONLY.value
            else OutboundExecutionMode.SEND_GATED_DRY_RUN.value
        )
        receipt = build_execution_receipt(
            action_id=action_intent.action_id,
            execution_mode=execution_mode,
            preflight_result=preflight_dict,
            guard_results=preflight.guard_results,
        ).to_dict()

    receipt.update(
        {
            "provider_adapter_mode": "local_no_send",
            "external_provider_called": False,
            "network_required": False,
            "login_required": False,
            "credential_required": False,
            "send_blocked_until_owner_activation": True,
            "no_send_invariant": True,
        }
    )
    return receipt
