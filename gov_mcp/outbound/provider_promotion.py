"""Dry-run-to-live promotion contract for outbound providers."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from gov_mcp.outbound.models import OutboundRiskTier, normalize_enum_value
from gov_mcp.outbound.provider_adapter import ProviderExecutionRequest, request_from_mapping
from gov_mcp.outbound.provider_guard_stack import evaluate_provider_guard_stack, owner_required_by_risk_tier
from gov_mcp.outbound.provider_manifest import manifest_to_capability


def dry_run_receipt_passed(receipt: Mapping[str, Any]) -> bool:
    return bool(
        receipt
        and receipt.get("receipt_type", "dry_run_receipt") == "dry_run_receipt"
        and receipt.get("real_message_sent") is False
        and receipt.get("provider_called", receipt.get("external_provider_called", False)) is False
        and receipt.get("execution_status", "dry_run_completed") in {"dry_run_completed", "dry_run_ready", "send_gated_dry_run"}
    )


def validate_receipt_separation(receipt: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    if receipt.get("receipt_type") == "dry_run_receipt" and receipt.get("live_receipt_created") is True:
        errors.append("dry_run_receipt_cannot_be_live_receipt")
    if receipt.get("receipt_type") == "live_execution_receipt" and receipt.get("real_message_sent") is not True:
        errors.append("live_execution_receipt_requires_real_message_sent_true")
    if receipt.get("receipt_type") == "live_execution_receipt" and receipt.get("provider_called") is not True:
        errors.append("live_execution_receipt_requires_provider_called_true")
    return errors


def evaluate_dry_run_to_live_promotion(
    request: ProviderExecutionRequest | Mapping[str, Any],
    provider_manifest: Mapping[str, Any],
    guard_context: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    req = request if isinstance(request, ProviderExecutionRequest) else request_from_mapping(request)
    capability = manifest_to_capability(provider_manifest)
    guard_result = evaluate_provider_guard_stack(req, provider_manifest, guard_context)
    risk_tier = normalize_enum_value(req.action_intent.risk_tier)
    owner_required = owner_required_by_risk_tier(risk_tier)
    reason_codes: list[str] = []

    if not dry_run_receipt_passed(req.dry_run_receipt):
        reason_codes.append("dry_run_pass_required")
    if not capability.live_ready():
        reason_codes.append(provider_manifest.get("live_execution_blocked_reason", "provider_not_live_ready"))
    if not guard_result["allowed_for_live_execution"]:
        reason_codes.append("provider_guard_stack_not_passed")
    if owner_required and not req.owner_approval_present:
        reason_codes.append("owner_approval_required_by_risk_tier")
    reason_codes.extend(validate_receipt_separation(req.dry_run_receipt))

    promotion_allowed = not reason_codes
    return {
        "artifact_id": "gov_mcp_dry_run_to_live_promotion_contract_result",
        "action_id": req.action_intent.action_id,
        "promotion_allowed": promotion_allowed,
        "provider_mode": capability.mode_value(),
        "dry_run_passed": dry_run_receipt_passed(req.dry_run_receipt),
        "provider_live_ready": capability.live_ready(),
        "owner_approval_required_by_risk_tier": owner_required,
        "reason_codes": list(dict.fromkeys(reason_codes)) or ["dry_run_to_live_promotion_passed"],
        "external_provider_called": False,
        "real_message_sent": False,
        "live_receipt_created": False,
    }


def promotion_contract_requirements() -> Dict[str, Any]:
    return {
        "contract_id": "gov_mcp_outbound_dry_run_to_live_promotion_v1",
        "required": [
            "dry_run pass",
            "provider capability live_ready",
            "provider tests pass",
            "risk tier autonomous allowed or allowed_with_limits",
            "suppression clear",
            "idempotency key present and unused",
            "rate limit available",
            "audit receipt enabled",
            "no-go checks pass",
            "owner approval only if required by risk tier",
        ],
        "live_promotion_enabled_in_e21": False,
        "no_external_api_call_in_e21": True,
    }
