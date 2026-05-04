from gov_mcp.outbound.models import (
    OutboundActionIntent,
    OutboundAuthorizationState,
    OutboundCapabilityDomain,
    OutboundExecutionMode,
    OutboundRiskTier,
)
from gov_mcp.outbound.safety_guards import evaluate_safety_guards, safety_guard_matrix


def valid_intent(**overrides):
    data = dict(
        action_id="act_guard_1",
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


def test_safety_guards_include_required_guard_names():
    matrix = safety_guard_matrix()
    for name in [
        "global_kill_switch",
        "batch_kill_switch",
        "target_suppression",
        "do_not_contact",
        "max_actions_per_day",
        "max_actions_per_target",
        "no_followup_without_positive_signal",
        "no_send_if_missing_target_identity",
        "no_send_if_message_unreviewed",
        "no_send_if_envelope_not_active",
        "no_send_if_hard_gate_detected",
        "no_send_if_owner_activation_missing",
        "no_send_if_idempotency_key_missing",
    ]:
        assert name in matrix["guard_names"]


def test_safety_guards_block_inactive_envelope_for_real_send():
    result = evaluate_safety_guards(valid_intent())
    assert result["guard_results"]["no_send_if_envelope_not_active"] == "fail"
    assert result["guard_results"]["no_send_if_owner_activation_missing"] == "fail"
    assert result["external_action_executed"] is False


def test_safety_guards_pass_for_activated_low_risk_intent():
    result = evaluate_safety_guards(valid_intent(authorization_state=OutboundAuthorizationState.ACTIVATED))
    assert result["all_guards_passed_for_real_send"] is True
