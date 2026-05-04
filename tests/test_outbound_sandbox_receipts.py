from gov_mcp.outbound.models import OutboundActionIntent, OutboundAuthorizationState, OutboundCapabilityDomain, OutboundExecutionMode, OutboundRiskTier

def valid_intent(**overrides):
    data = dict(action_id="act_sandbox_1", capability_domain=OutboundCapabilityDomain.EXTERNAL_VALIDATION_MESSAGE, risk_tier=OutboundRiskTier.TIER_2_TRANSPARENT_LOW_RISK_EXTERNAL_VALIDATION, execution_mode=OutboundExecutionMode.SEND_GATED_DRY_RUN, authorization_state=OutboundAuthorizationState.OWNER_REVIEW_REQUIRED, target_id="target_1", target_identity_sufficient=True, message_hash="hash_1", idempotency_key="idem_12345678901234567890", ai_transparency_present=True, opt_out_language_present=True, suppression_clear=True, rate_limit_clear=True, hard_gates_absent=True)
    data.update(overrides)
    return OutboundActionIntent(**data)

from gov_mcp.outbound.sandbox_receipts import build_sandbox_receipt, validate_sandbox_receipt

def test_sandbox_receipt_is_not_live_or_dry_run():
    receipt = build_sandbox_receipt("act_sandbox_1", "idem_12345678901234567890")
    assert receipt["receipt_type"] == "sandbox_receipt"
    assert receipt["receipt_type"] != "dry_run_receipt"
    assert receipt["receipt_type"] != "live_execution_receipt"
    assert receipt["live_receipt_created"] is False
    assert receipt["real_message_sent"] is False
    assert validate_sandbox_receipt(receipt) == []

def test_live_receipt_cannot_be_created_in_sandbox_mode():
    receipt = build_sandbox_receipt("act_sandbox_1", "idem_12345678901234567890")
    receipt["live_receipt_created"] = True
    assert "sandbox_receipt_cannot_create_live_receipt" in validate_sandbox_receipt(receipt)
