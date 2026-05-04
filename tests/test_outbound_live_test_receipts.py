from gov_mcp.outbound.live_test_receipts import (
    accept_as_production_live_receipt,
    build_live_test_receipt,
    validate_live_test_receipt,
)


def test_live_test_receipt_is_non_production_and_no_effect():
    receipt = build_live_test_receipt(action_id="act_1", idempotency_key="idem_1")
    assert validate_live_test_receipt(receipt) == []
    assert receipt["receipt_type"] == "live_test_receipt"
    assert receipt["external_effect"] is False
    assert receipt["production_live_receipt_created"] is False
    assert accept_as_production_live_receipt(receipt) is False


def test_live_test_receipt_cannot_be_mistaken_for_live_receipt():
    receipt = build_live_test_receipt(action_id="act_1", idempotency_key="idem_1")
    altered = dict(receipt)
    altered["production_live_receipt"] = True
    assert "live_test_receipt_cannot_be_production_live_receipt" in validate_live_test_receipt(altered)
