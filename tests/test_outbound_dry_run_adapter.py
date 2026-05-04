from gov_mcp.outbound.dry_run_adapter import dry_run_outbound_action
from gov_mcp.outbound.models import (
    OutboundActionIntent,
    OutboundAuthorizationState,
    OutboundCapabilityDomain,
    OutboundExecutionMode,
    OutboundRiskTier,
)


def valid_intent(**overrides):
    data = dict(
        action_id="act_dry_1",
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


def test_dry_run_adapter_returns_provider_safe_no_send_receipt():
    receipt = dry_run_outbound_action(valid_intent())
    assert receipt["provider_adapter_mode"] == "local_no_send"
    assert receipt["external_action_executed"] is False
    assert receipt["external_provider_called"] is False
    assert receipt["real_message_sent"] is False
    assert receipt["network_required"] is False
    assert receipt["login_required"] is False
    assert receipt["credential_required"] is False
    assert receipt["send_blocked_until_owner_activation"] is True


def test_dry_run_adapter_denies_invalid_intent_without_send():
    receipt = dry_run_outbound_action(valid_intent(ai_transparency_present=False))
    assert receipt["execution_mode"] == "deny"
    assert receipt["external_action_executed"] is False
    assert "ai_transparency_missing" in receipt["reason_codes"]
