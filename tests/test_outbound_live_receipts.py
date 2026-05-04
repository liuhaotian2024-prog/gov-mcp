from gov_mcp.outbound.live_receipts import build_live_receipt, evaluate_live_receipt_boundary, validate_receipt_boundary


def test_live_receipt_boundary_blocks_without_all_live_flags():
    result = evaluate_live_receipt_boundary({"live_mode_enabled": False})
    assert result["live_receipt_allowed"] is False
    assert result["live_receipt_created"] is False
    receipt = build_live_receipt(action_id="act", idempotency_key="idem_12345678901234567890", context={"live_mode_enabled": False})
    assert receipt["receipt_type"] == "blocked_receipt"
    assert receipt["live_receipt_created"] is False


def test_non_live_receipts_cannot_be_marked_live():
    assert validate_receipt_boundary({"receipt_type": "sandbox_receipt", "live_receipt_created": True}) == ["non_live_receipt_cannot_create_live_receipt"]
    live = build_live_receipt(
        action_id="act",
        idempotency_key="idem_12345678901234567890",
        context={flag: True for flag in [
            "live_mode_enabled", "provider_live_ready", "persistent_idempotency_ready", "kill_switch_clear",
            "suppression_clear", "compliance_clear", "rate_limit_available", "live_tests_passed",
            "promotion_allowed", "external_effect_confirmed"
        ]},
    )
    assert live["receipt_type"] == "live_receipt"
    assert validate_receipt_boundary(live) == []
