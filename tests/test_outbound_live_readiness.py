from gov_mcp.outbound.live_config import build_live_provider_config
from gov_mcp.outbound.live_kill_switch import build_live_kill_switch, evaluate_live_kill_switch
from gov_mcp.outbound.live_readiness import evaluate_live_readiness
from gov_mcp.outbound.live_receipts import evaluate_live_receipt_boundary
from gov_mcp.outbound.persistent_idempotency import build_persistent_idempotency_status
from gov_mcp.outbound.provider_manifest import build_provider_capability_manifest


def test_live_readiness_blocks_current_disabled_live_state():
    result = evaluate_live_readiness(
        live_config=build_live_provider_config(required_credential_variable_names=["YSTAR_OUTBOUND_PROVIDER_API_KEY"]),
        provider_manifest=build_provider_capability_manifest(),
        persistent_idempotency_status=build_persistent_idempotency_status(persistent_ready=False),
        kill_switch_result=evaluate_live_kill_switch(build_live_kill_switch()),
        live_receipt_boundary=evaluate_live_receipt_boundary({}),
        promotion_result={"promotion_allowed": False, "reason_codes": ["live_provider_config_required"]},
        dry_run_receipt_history_present=True,
        sandbox_receipt_history_present=True,
        ceo_kg_route_supported=True,
    )
    assert result["live_ready"] is False
    assert result["live_ready_action_count"] == 0
    assert "live_enabled_false" in result["reason_codes"]
    assert "persistent_idempotency_required_for_live_promotion" in result["reason_codes"]
    assert result["live_receipt_created"] is False
