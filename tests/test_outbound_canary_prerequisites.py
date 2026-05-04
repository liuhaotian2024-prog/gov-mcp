from gov_mcp.outbound.canary_prerequisites import (
    build_canary_prerequisite_matrix,
    validate_canary_prerequisite_matrix,
)
from gov_mcp.outbound.live_test_config import build_live_test_config_profile
from gov_mcp.outbound.live_test_gate import evaluate_live_readiness_v2
from gov_mcp.outbound.live_test_receipts import build_live_test_receipt


def test_canary_prerequisite_matrix_is_plan_only():
    gate = evaluate_live_readiness_v2(
        live_test_config=build_live_test_config_profile(),
        persistent_idempotency_test_result={"live_test_persistent_ready": True, "duplicate_protection_passed": True},
        kill_switch_test_result={"allow_profile_passed": True, "block_profile_passed": True},
        live_test_receipt=build_live_test_receipt(action_id="act_1", idempotency_key="idem_1"),
        dry_run_receipt_history_present=True,
        sandbox_receipt_history_present=True,
        ceo_kg_route_supported=True,
    )
    matrix = build_canary_prerequisite_matrix(
        selected_revenue_path="rev_path_readiness_review_ai_consultancies",
        selected_action_candidate="act_1",
        kg_support_nodes_edges=["node:rev_path", "edge:requires_live_test_gate"],
        target_evidence=["operations/external_validation/e18_revenue_validation_batch.json"],
        message_content_reference="operations/external_validation/e22_outbound_envelopes.json",
        provider_category="email_provider",
        channel="email",
        risk_tier="T2_low_medium_limited_outbound",
        dry_run_history_present=True,
        sandbox_history_present=True,
        live_test_gate_result=gate,
    )
    assert validate_canary_prerequisite_matrix(matrix) == []
    assert matrix["canary_matrix_created"] is True
    assert matrix["canary_executed"] is False
    assert matrix["production_live_receipt_count"] == 0
    assert matrix["real_customer_contact"] is False
    assert matrix["live_ready_action_count"] == 0
    assert matrix["live_blocked_action_count"] == 1
