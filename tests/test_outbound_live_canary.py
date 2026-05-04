from gov_mcp.outbound.live_canary import build_one_action_live_canary_plan, validate_canary_plan


def test_one_action_canary_plan_is_never_execution():
    plan = build_one_action_live_canary_plan(
        selected_revenue_path="rev_path_readiness_review_ai_consultancies",
        action_id="e26_live_canary_candidate_1",
        channel="email",
        provider_category="outbound_message_provider",
        risk_tier="T2_low_medium_limited_outbound",
        kg_support=["rev_path_readiness_review_ai_consultancies"],
        message_reference="operations/external_validation/e17_final_message_package.json",
        target_evidence=["operations/external_validation/e18_revenue_validation_batch.json"],
    )
    assert plan["canary_executed"] is False
    assert plan["customer_contacted"] is False
    assert plan["live_receipt_created"] is False
    assert plan["owner_approval_required_by_risk"] is False
    assert validate_canary_plan(plan) == []
