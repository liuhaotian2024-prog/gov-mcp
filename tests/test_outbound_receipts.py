from gov_mcp.outbound.models import (
    OutboundActionIntent,
    OutboundAuthorizationState,
    OutboundCapabilityDomain,
    OutboundExecutionMode,
    OutboundRiskTier,
)
from gov_mcp.outbound.policy import evaluate_outbound_policy
from gov_mcp.outbound.receipts import build_execution_receipt, build_failure_receipt, validate_no_send_receipt


def valid_intent(**overrides):
    data = dict(
        action_id="act_receipt_1",
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


def test_execution_receipt_preserves_no_send_invariant():
    preflight = evaluate_outbound_policy(valid_intent())
    receipt = build_execution_receipt(
        action_id="act_receipt_1",
        execution_mode="send_gated_dry_run",
        preflight_result=preflight.to_dict(),
        guard_results=preflight.guard_results,
    ).to_dict()
    assert validate_no_send_receipt(receipt) == []
    assert receipt["feedback_wait_state"] == "not_waiting_feedback_until_real_send_receipt"


def test_failure_receipt_preserves_no_send_invariant():
    receipt = build_failure_receipt("act_receipt_2", "guard_failed", ["global_kill_switch"]).to_dict()
    assert validate_no_send_receipt(receipt) == []
    assert receipt["failure_code"] == "guard_failed"
