from gov_mcp.outbound.live_test_config import build_live_test_config_profile
from gov_mcp.outbound.live_test_gate import evaluate_live_readiness_v2
from gov_mcp.outbound.live_test_receipts import build_live_test_receipt


def _gate(**overrides):
    params = {
        "live_test_config": build_live_test_config_profile(),
        "persistent_idempotency_test_result": {
            "live_test_persistent_ready": True,
            "duplicate_protection_passed": True,
            "corrupted_store_blocked": True,
            "missing_store_blocked": True,
        },
        "kill_switch_test_result": {"allow_profile_passed": True, "block_profile_passed": True},
        "live_test_receipt": build_live_test_receipt(action_id="act_1", idempotency_key="idem_1"),
        "dry_run_receipt_history_present": True,
        "sandbox_receipt_history_present": True,
        "ceo_kg_route_supported": True,
    }
    params.update(overrides)
    return evaluate_live_readiness_v2(**params)


def test_live_test_gate_ready_but_production_live_stays_blocked():
    result = _gate()
    assert result["dry_run_ready"] is True
    assert result["sandbox_ready"] is True
    assert result["live_test_gate_ready"] is True
    assert result["production_live_ready"] is False
    assert result["production_live_blocked"] is True
    assert result["production_live_receipt_count"] == 0
    assert "production_live_enabled_false" in result["production_live_blocked_reasons"]
    assert "production_persistent_idempotency_not_configured" in result["production_live_blocked_reasons"]


def test_live_test_gate_blocks_when_kill_switch_tests_are_missing():
    result = _gate(kill_switch_test_result={"allow_profile_passed": False, "block_profile_passed": True})
    assert result["live_test_gate_ready"] is False
    assert "kill_switch_allow_profile_not_proven" in result["live_test_gate_blocked_reasons"]
