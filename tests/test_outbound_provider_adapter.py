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

from gov_mcp.outbound.provider_adapter import (
    DisabledLiveProviderAdapter,
    DryRunProviderSimulator,
    ProviderExecutionRequest,
    validate_provider_execution_result,
)


def test_disabled_live_scaffold_blocks_without_send():
    result = DisabledLiveProviderAdapter().execute(ProviderExecutionRequest(action_intent=valid_intent()))
    payload = result.to_dict()
    assert payload["execution_status"] == "blocked"
    assert payload["external_provider_called"] is False
    assert payload["real_message_sent"] is False
    assert payload["live_receipt_created"] is False
    assert "live_provider_disabled" in payload["reason_codes"]
    assert validate_provider_execution_result(payload) == []


def test_dry_run_provider_simulator_creates_dry_run_receipt_only():
    result = DryRunProviderSimulator().execute(ProviderExecutionRequest(action_intent=valid_intent()))
    payload = result.to_dict()
    assert payload["receipt_type"] == "dry_run_receipt"
    assert payload["external_provider_called"] is False
    assert payload["real_message_sent"] is False
    assert payload["live_receipt_created"] is False
