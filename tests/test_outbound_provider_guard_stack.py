from gov_mcp.outbound.models import (
    OutboundActionIntent,
    OutboundAuthorizationState,
    OutboundCapabilityDomain,
    OutboundExecutionMode,
    OutboundRiskTier,
)


def valid_intent(**overrides):
    data = dict(
        action_id="act_provider_1",
        capability_domain=OutboundCapabilityDomain.EXTERNAL_VALIDATION_MESSAGE,
        risk_tier=OutboundRiskTier.TIER_2_TRANSPARENT_LOW_RISK_EXTERNAL_VALIDATION,
        execution_mode=OutboundExecutionMode.SEND_GATED_DRY_RUN,
        authorization_state=OutboundAuthorizationState.OWNER_REVIEW_REQUIRED,
        target_id="target_1",
        target_identity_sufficient=True,
        message_hash="hash_1",
        idempotency_key="idem_12345678901234567890",
        ai_transparency_present=True,
        opt_out_language_present=True,
        suppression_clear=True,
        rate_limit_clear=True,
        hard_gates_absent=True,
    )
    data.update(overrides)
    return OutboundActionIntent(**data)

from gov_mcp.outbound.idempotency import IdempotencyRegistry
from gov_mcp.outbound.models import OutboundRiskTier
from gov_mcp.outbound.provider_adapter import ProviderExecutionRequest
from gov_mcp.outbound.provider_capability import ProviderMode
from gov_mcp.outbound.provider_guard_stack import evaluate_provider_guard_stack
from gov_mcp.outbound.provider_manifest import build_provider_capability_manifest


def live_manifest():
    return build_provider_capability_manifest(provider_mode=ProviderMode.LIVE_READY, supports_live=True)


def test_low_risk_send_does_not_require_owner_approval_by_itself():
    result = evaluate_provider_guard_stack(
        ProviderExecutionRequest(action_intent=valid_intent(), promotion_contract_passed=True),
        live_manifest(),
    )
    assert result["owner_approval_required"] is False
    assert result["owner_approval_required_by_risk_tier"] is False
    assert "owner_approval_required_by_risk_tier" not in result["reason_codes"]


def test_live_execution_blocks_without_live_ready_provider():
    result = evaluate_provider_guard_stack(
        ProviderExecutionRequest(action_intent=valid_intent(), promotion_contract_passed=True),
        build_provider_capability_manifest(),
    )
    assert result["allowed_for_live_execution"] is False
    assert "live_provider_scaffolded_but_disabled" in result["reason_codes"]


def test_owner_approval_required_for_high_risk_actions():
    result = evaluate_provider_guard_stack(
        ProviderExecutionRequest(
            action_intent=valid_intent(risk_tier=OutboundRiskTier.TIER_4_COMMERCIAL_LEGAL_PRODUCTION_HIGH_RISK),
            promotion_contract_passed=True,
            owner_approval_present=False,
        ),
        live_manifest(),
    )
    assert result["owner_approval_required"] is True
    assert "owner_approval_required_by_risk_tier" in result["reason_codes"]


def test_quota_idempotency_and_suppression_blocks_are_explicit():
    request = ProviderExecutionRequest(action_intent=valid_intent(), promotion_contract_passed=True)
    quota = evaluate_provider_guard_stack(request, live_manifest(), {"actions_today": 1, "max_actions_per_day": 1})
    assert "quota_or_rate_limit_unavailable" in quota["reason_codes"]

    registry = IdempotencyRegistry()
    first = evaluate_provider_guard_stack(request, live_manifest(), registry=registry)
    second = evaluate_provider_guard_stack(request, live_manifest(), registry=registry)
    assert first["checks"]["idempotency_check"] == "pass"
    assert "duplicate_idempotency_key" in second["reason_codes"]

    suppressed = evaluate_provider_guard_stack(request, live_manifest(), {"do_not_contact": True})
    assert "suppression_or_do_not_contact_active" in suppressed["reason_codes"]
