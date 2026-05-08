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
            "receipt_type": "dry_run_receipt" if receipt.get("execution_mode") != "deny" else "dry_run_failure_receipt",
            "provider_adapter_mode": "local_no_send",
            "external_provider_called": False,
            "provider_action_executed": False,
            "external_side_effect": False,
            "network_required": False,
            "login_required": False,
            "credential_required": False,
            "send_blocked_until_owner_activation": True,
            "no_send_invariant": True,
        }
    )
    intelligence_metadata = _intelligence_metadata(action_intent.metadata, guard_context)
    if intelligence_metadata:
        receipt["intelligence_loop_metadata"] = intelligence_metadata
        receipt["intelligence_loop_id"] = intelligence_metadata.get("intelligence_loop_id", "")
        receipt["selected_candidate_id"] = intelligence_metadata.get("selected_candidate_id", "")
        receipt["YstarGov_intelligence_decision"] = intelligence_metadata.get(
            "YstarGov_intelligence_decision", ""
        )
    return receipt


def _intelligence_metadata(
    intent_metadata: Mapping[str, Any],
    guard_context: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    """Extract CEO intelligence-loop metadata without changing no-send behavior."""

    source: Dict[str, Any] = {}
    if isinstance(intent_metadata, Mapping):
        source.update(dict(intent_metadata.get("intelligence_loop_metadata", {})))
        for key in (
            "intelligence_loop_id",
            "selected_candidate_id",
            "YstarGov_intelligence_decision",
            "commercial_sharpness_summary",
            "owner_approval_state",
        ):
            if key in intent_metadata:
                source[key] = intent_metadata[key]
    if isinstance(guard_context, Mapping):
        source.update(dict(guard_context.get("intelligence_loop_metadata", {})))
        for key in (
            "intelligence_loop_id",
            "selected_candidate_id",
            "YstarGov_intelligence_decision",
            "commercial_sharpness_summary",
            "owner_approval_state",
        ):
            if key in guard_context:
                source[key] = guard_context[key]

    if not source:
        return {}
    source.setdefault("provider_called", False)
    source.setdefault("provider_action_executed", False)
    source.setdefault("external_side_effect", False)
    source.setdefault("no_send_invariant", True)
    return source
