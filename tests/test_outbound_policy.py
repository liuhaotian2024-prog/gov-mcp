from gov_mcp.outbound.models import (
    OutboundActionIntent,
    OutboundAuthorizationState,
    OutboundCapabilityDomain,
    OutboundExecutionMode,
    OutboundRiskTier,
)
from gov_mcp.outbound.policy import evaluate_outbound_policy


def valid_intent(**overrides):
    data = dict(
        action_id="act_policy_1",
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


def test_policy_allows_dry_run_when_owner_authorization_missing():
    result = evaluate_outbound_policy(valid_intent())
    assert result.allowed_for_dry_run is True
    assert result.allowed_for_real_send is False
    assert result.decision == "send_gated_pending_authorization"
    assert "owner_authorization_not_activated" in result.reason_codes


def test_policy_allows_real_execution_only_after_activation_and_guards_pass():
    result = evaluate_outbound_policy(valid_intent(authorization_state=OutboundAuthorizationState.ACTIVATED))
    assert result.allowed_for_real_send is True
    assert result.execution_mode == "gov_mcp_execute_after_activation"
    assert result.external_action_executed is False


def test_policy_denies_hard_gate_actions():
    result = evaluate_outbound_policy(
        valid_intent(requested_action="payment", authorization_state=OutboundAuthorizationState.ACTIVATED)
    )
    assert result.decision == "deny"
    assert result.allowed_for_real_send is False
    assert "hard_gate_blocks_outbound" in result.reason_codes
