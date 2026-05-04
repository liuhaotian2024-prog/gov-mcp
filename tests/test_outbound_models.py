from gov_mcp.outbound.models import (
    OutboundActionIntent,
    OutboundAuthorizationState,
    OutboundCapabilityDomain,
    OutboundExecutionMode,
    OutboundRiskTier,
    canonical_execution_mode,
)


def test_outbound_enums_include_canonical_values():
    assert OutboundRiskTier.TIER_2_TRANSPARENT_LOW_RISK_EXTERNAL_VALIDATION.value
    assert OutboundExecutionMode.GOV_MCP_EXECUTE_AFTER_ACTIVATION.value == "gov_mcp_execute_after_activation"
    assert canonical_execution_mode("mcp_execute_after_activation") == "gov_mcp_execute_after_activation"


def test_outbound_action_intent_serializes_enum_values():
    intent = OutboundActionIntent(
        action_id="act_1",
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
    data = intent.to_dict()
    assert data["capability_domain"] == "external_validation_message"
    assert data["risk_tier"] == "TIER_2_TRANSPARENT_LOW_RISK_EXTERNAL_VALIDATION"
