"""Deterministic guard stack for governed provider execution."""

from __future__ import annotations

from typing import Any, Dict, Mapping

from gov_mcp.outbound.idempotency import IdempotencyRegistry, validate_idempotency_key
from gov_mcp.outbound.models import OutboundRiskTier, hard_gate_reason_codes, normalize_enum_value
from gov_mcp.outbound.provider_adapter import ProviderExecutionRequest, request_from_mapping
from gov_mcp.outbound.provider_manifest import manifest_to_capability

LOW_RISK_AUTONOMOUS_TIERS = {
    OutboundRiskTier.TIER_1_PUBLIC_READ_ONLY.value,
    OutboundRiskTier.TIER_2_TRANSPARENT_LOW_RISK_EXTERNAL_VALIDATION.value,
}
HIGH_RISK_OWNER_TIERS = {OutboundRiskTier.TIER_4_COMMERCIAL_LEGAL_PRODUCTION_HIGH_RISK.value}


def owner_required_by_risk_tier(risk_tier: str) -> bool:
    return risk_tier in HIGH_RISK_OWNER_TIERS


def evaluate_provider_guard_stack(
    request: ProviderExecutionRequest | Mapping[str, Any],
    provider_manifest: Mapping[str, Any],
    guard_context: Mapping[str, Any] | None = None,
    registry: IdempotencyRegistry | None = None,
) -> Dict[str, Any]:
    req = request if isinstance(request, ProviderExecutionRequest) else request_from_mapping(request)
    intent = req.action_intent
    capability = manifest_to_capability(provider_manifest)
    ctx = dict(guard_context or {})
    risk_tier = normalize_enum_value(intent.risk_tier)
    reason_codes: list[str] = []
    checks: Dict[str, str] = {}

    hard_gate_reasons = hard_gate_reason_codes(intent)
    checks["risk_tier_check"] = "pass" if risk_tier in LOW_RISK_AUTONOMOUS_TIERS or risk_tier in HIGH_RISK_OWNER_TIERS else "fail"
    if checks["risk_tier_check"] == "fail":
        reason_codes.append("risk_tier_not_provider_executable")

    checks["policy_compatibility_check"] = "fail" if hard_gate_reasons else "pass"
    reason_codes.extend(hard_gate_reasons)

    quota_available = req.quota_available and int(ctx.get("actions_today", 0)) < int(ctx.get("max_actions_per_day", 1))
    checks["quota_rate_limit_check"] = "pass" if quota_available else "fail"
    if not quota_available:
        reason_codes.append("quota_or_rate_limit_unavailable")

    idempotency_errors = validate_idempotency_key(intent.idempotency_key)
    if registry is not None and not idempotency_errors:
        check = registry.check_new(intent.idempotency_key, intent.action_id)
        if check["decision"] != "allow":
            idempotency_errors.extend(check["reason_codes"])
    if not req.idempotency_clear:
        idempotency_errors.append("idempotency_not_clear")
    checks["idempotency_check"] = "pass" if not idempotency_errors else "fail"
    reason_codes.extend(idempotency_errors)

    suppression_clear = req.suppression_clear and intent.suppression_clear and not ctx.get("do_not_contact", False)
    checks["suppression_check"] = "pass" if suppression_clear else "fail"
    if not suppression_clear:
        reason_codes.append("suppression_or_do_not_contact_active")

    evidence_ok = req.evidence_sufficient and intent.target_identity_sufficient and bool(intent.target_id)
    checks["target_evidence_check"] = "pass" if evidence_ok else "fail"
    if not evidence_ok:
        reason_codes.append("target_evidence_insufficient")

    message_ok = req.message_safety_passed and bool(intent.message_hash) and intent.ai_transparency_present and intent.opt_out_language_present
    checks["message_safety_check"] = "pass" if message_ok else "fail"
    if not message_ok:
        reason_codes.append("message_safety_or_transparency_missing")

    owner_required = owner_required_by_risk_tier(risk_tier) or bool(ctx.get("explicit_owner_gate", False))
    checks["owner_approval_check"] = "pass" if (not owner_required or req.owner_approval_present) else "fail"
    if owner_required and not req.owner_approval_present:
        reason_codes.append("owner_approval_required_by_risk_tier")

    provider_ready = capability.live_ready()
    checks["provider_capability_check"] = "pass" if provider_ready else "fail"
    if not provider_ready:
        reason_codes.append(provider_manifest.get("live_execution_blocked_reason", "provider_not_live_ready"))

    promotion_ok = bool(req.promotion_contract_passed)
    checks["dry_run_to_live_promotion_check"] = "pass" if promotion_ok else "fail"
    if not promotion_ok:
        reason_codes.append("dry_run_to_live_promotion_not_satisfied")

    all_passed = all(value == "pass" for value in checks.values())
    return {
        "artifact_id": "gov_mcp_provider_guard_stack_result",
        "action_id": intent.action_id,
        "allowed_for_live_execution": all_passed,
        "owner_approval_required": owner_required,
        "owner_approval_required_by_risk_tier": owner_required_by_risk_tier(risk_tier),
        "checks": checks,
        "reason_codes": list(dict.fromkeys(reason_codes)) or ["provider_guard_stack_passed"],
        "external_provider_called": False,
        "real_message_sent": False,
        "live_receipt_created": False,
    }
