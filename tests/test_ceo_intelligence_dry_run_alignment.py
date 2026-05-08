from __future__ import annotations

from gov_mcp.outbound.dry_run_adapter import dry_run_outbound_action


def test_dry_run_receipt_accepts_ceo_intelligence_metadata_without_send():
    receipt = dry_run_outbound_action(
        {
            "action_id": "e89_selected_provider_candidate",
            "capability_domain": "external_validation_message",
            "risk_tier": "TIER_2_TRANSPARENT_LOW_RISK_EXTERNAL_VALIDATION",
            "execution_mode": "send_gated_dry_run",
            "authorization_state": "owner_review_required",
            "target_id": "dry_run_target_e89",
            "target_identity_sufficient": True,
            "message_hash": "sha256:e89-selected-message",
            "idempotency_key": "e89-selected-provider-candidate:dry-run",
            "ai_transparency_present": True,
            "opt_out_language_present": True,
            "suppression_clear": True,
            "rate_limit_clear": True,
            "hard_gates_absent": True,
            "requested_action": "external_validation_message",
            "channel": "owner_approved_validation_message",
            "metadata": {
                "intelligence_loop_id": "e89_intelligence_loop",
                "selected_candidate_id": "candidate_provider_dry_run",
                "YstarGov_intelligence_decision": "ALLOW",
                "commercial_sharpness_summary": {"shortest_cash_path_fit": 7},
                "owner_approval_state": "not_required",
            },
        }
    )

    assert receipt["receipt_type"] == "dry_run_receipt"
    assert receipt["intelligence_loop_id"] == "e89_intelligence_loop"
    assert receipt["selected_candidate_id"] == "candidate_provider_dry_run"
    assert receipt["YstarGov_intelligence_decision"] == "ALLOW"
    assert receipt["intelligence_loop_metadata"]["no_send_invariant"] is True
    assert receipt["provider_called"] is False
    assert receipt["external_provider_called"] is False
    assert receipt["provider_action_executed"] is False
    assert receipt["external_action_executed"] is False
    assert receipt["real_message_sent"] is False
    assert receipt["no_send_invariant"] is True
