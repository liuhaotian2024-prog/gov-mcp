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

from gov_mcp.outbound.models import OutboundRiskTier
from gov_mcp.outbound.provider_adapter import ProviderExecutionRequest
from gov_mcp.outbound.provider_capability import ProviderMode
from gov_mcp.outbound.provider_manifest import build_provider_capability_manifest
from gov_mcp.outbound.provider_promotion import (
    evaluate_dry_run_to_live_promotion,
    promotion_contract_requirements,
    validate_receipt_separation,
)


def dry_run_receipt():
    return {
        "receipt_type": "dry_run_receipt",
        "execution_status": "dry_run_completed",
        "provider_called": False,
        "real_message_sent": False,
        "live_receipt_created": False,
    }


def test_promotion_contract_blocks_missing_provider_capability():
    result = evaluate_dry_run_to_live_promotion(
        ProviderExecutionRequest(
            action_intent=valid_intent(),
            dry_run_receipt=dry_run_receipt(),
            promotion_contract_passed=True,
        ),
        build_provider_capability_manifest(),
    )
    assert result["promotion_allowed"] is False
    assert "live_provider_scaffolded_but_disabled" in result["reason_codes"]
    assert result["external_provider_called"] is False


def test_promotion_can_pass_only_with_live_ready_manifest_and_guards():
    result = evaluate_dry_run_to_live_promotion(
        ProviderExecutionRequest(
            action_intent=valid_intent(),
            provider_mode=ProviderMode.LIVE_READY,
            dry_run_receipt=dry_run_receipt(),
            promotion_contract_passed=True,
        ),
        build_provider_capability_manifest(provider_mode=ProviderMode.LIVE_READY, supports_live=True),
    )
    assert result["promotion_allowed"] is True
    assert result["real_message_sent"] is False


def test_high_risk_promotion_requires_owner_approval():
    result = evaluate_dry_run_to_live_promotion(
        ProviderExecutionRequest(
            action_intent=valid_intent(risk_tier=OutboundRiskTier.TIER_4_COMMERCIAL_LEGAL_PRODUCTION_HIGH_RISK),
            provider_mode=ProviderMode.LIVE_READY,
            dry_run_receipt=dry_run_receipt(),
            promotion_contract_passed=True,
            owner_approval_present=False,
        ),
        build_provider_capability_manifest(provider_mode=ProviderMode.LIVE_READY, supports_live=True),
    )
    assert "owner_approval_required_by_risk_tier" in result["reason_codes"]


def test_live_receipt_cannot_be_created_from_dry_run_receipt():
    errors = validate_receipt_separation({"receipt_type": "dry_run_receipt", "live_receipt_created": True})
    assert "dry_run_receipt_cannot_be_live_receipt" in errors
    assert promotion_contract_requirements()["live_promotion_enabled_in_e21"] is False
