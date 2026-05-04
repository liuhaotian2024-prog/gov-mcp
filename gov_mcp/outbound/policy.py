"""Canonical outbound policy for low-risk validation messaging."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from gov_mcp.outbound.models import (
    OutboundActionIntent,
    OutboundAuthorizationState,
    OutboundCapabilityDomain,
    OutboundExecutionMode,
    OutboundPreflightResult,
    OutboundRiskTier,
    canonical_execution_mode,
    hard_gate_reason_codes,
    normalize_enum_value,
)
from gov_mcp.outbound.safety_guards import evaluate_safety_guards


def _basic_reason_codes(intent: OutboundActionIntent) -> List[str]:
    reasons: List[str] = []
    if normalize_enum_value(intent.risk_tier) != OutboundRiskTier.TIER_2_TRANSPARENT_LOW_RISK_EXTERNAL_VALIDATION.value:
        reasons.append("risk_tier_not_tier_2_low_risk_validation")
    if normalize_enum_value(intent.capability_domain) != OutboundCapabilityDomain.EXTERNAL_VALIDATION_MESSAGE.value:
        reasons.append("capability_domain_not_external_validation_message")
    if not intent.ai_transparency_present:
        reasons.append("ai_transparency_missing")
    if not intent.opt_out_language_present:
        reasons.append("opt_out_language_missing")
    if not intent.target_identity_sufficient or not intent.target_id:
        reasons.append("target_identity_insufficient")
    if not intent.message_hash:
        reasons.append("message_hash_missing")
    if not intent.idempotency_key:
        reasons.append("idempotency_key_missing")
    if not intent.suppression_clear:
        reasons.append("suppression_not_clear")
    if not intent.rate_limit_clear:
        reasons.append("rate_limit_not_clear")
    reasons.extend(hard_gate_reason_codes(intent))
    return reasons


def evaluate_outbound_policy(
    intent: OutboundActionIntent,
    guard_context: Mapping[str, Any] | None = None,
) -> OutboundPreflightResult:
    reason_codes = _basic_reason_codes(intent)
    guard_eval = evaluate_safety_guards(intent, guard_context)
    failed_guards = list(guard_eval["failed_guards"])
    authorization_state = normalize_enum_value(intent.authorization_state)
    requested_mode = canonical_execution_mode(normalize_enum_value(intent.execution_mode))

    if hard_gate_reason_codes(intent):
        decision = "deny"
        mode = OutboundExecutionMode.DENY.value
        allowed_real = False
        allowed_dry = False
        reason_codes.append("hard_gate_blocks_outbound")
    elif reason_codes:
        decision = "deny"
        mode = OutboundExecutionMode.DENY.value
        allowed_real = False
        allowed_dry = False
    elif authorization_state != OutboundAuthorizationState.ACTIVATED.value:
        decision = "send_gated_pending_authorization"
        mode = (
            OutboundExecutionMode.DRAFT_ONLY.value
            if requested_mode == OutboundExecutionMode.DRAFT_ONLY.value
            else OutboundExecutionMode.SEND_GATED_DRY_RUN.value
        )
        allowed_real = False
        allowed_dry = True
        reason_codes.append("owner_authorization_not_activated")
    elif failed_guards:
        decision = "deny"
        mode = OutboundExecutionMode.DENY.value
        allowed_real = False
        allowed_dry = False
        reason_codes.extend([f"guard_failed_{name}" for name in failed_guards])
    else:
        decision = "gov_mcp_execute_after_activation"
        mode = OutboundExecutionMode.GOV_MCP_EXECUTE_AFTER_ACTIVATION.value
        allowed_real = True
        allowed_dry = True
        reason_codes.append("activated_envelope_and_guards_passed")

    return OutboundPreflightResult(
        action_id=intent.action_id,
        decision=decision,
        execution_mode=mode,
        authorization_state=authorization_state,
        allowed_for_real_send=allowed_real,
        allowed_for_dry_run=allowed_dry,
        reason_codes=list(dict.fromkeys(reason_codes)),
        guard_results=dict(guard_eval["guard_results"]),
        external_action_executed=False,
        provider_called=False,
        real_message_sent=False,
    )


def outbound_policy_summary() -> Dict[str, Any]:
    return {
        "policy_id": "gov_mcp_outbound_low_risk_validation_messaging_policy",
        "allowable_only_if": [
            "risk_tier == TIER_2_TRANSPARENT_LOW_RISK_EXTERNAL_VALIDATION",
            "capability_domain == external_validation_message",
            "AI transparency present",
            "opt-out language present",
            "target identity sufficient",
            "message hash present",
            "idempotency key present",
            "suppression clear",
            "rate-limit clear",
            "hard gates absent",
            "authorization activated for real send",
        ],
        "not_activated_behavior": "draft-only or send-gated dry-run allowed; real send denied",
        "always_deny": [
            "payment",
            "contract",
            "legal obligation",
            "financial commitment",
            "customer system access",
            "regulated/government/tax/immigration/identity forms",
            "credential disclosure",
            "core brain/CIEU/memory writeback",
            "publication",
            "account creation",
            "login",
            "form submission",
        ],
        "no_send_invariant": True,
    }
