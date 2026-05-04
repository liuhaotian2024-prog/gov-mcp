from gov_mcp.outbound.live_kill_switch import build_live_kill_switch, evaluate_live_kill_switch


def test_kill_switch_defaults_safe_and_blocks_live():
    config = build_live_kill_switch()
    result = evaluate_live_kill_switch(config, provider="disabled_live_outbound_provider", channel="email", action_id="act")
    assert result["kill_switch_clear"] is False
    assert "global_live_disabled" in result["reason_codes"]
    assert result["live_receipt_created"] is False


def test_kill_switch_can_be_clear_in_test_fixture_only():
    config = build_live_kill_switch(global_live_disabled=False, provider_live_disabled=False)
    result = evaluate_live_kill_switch(config)
    assert result["kill_switch_clear"] is True
    assert result["reason_codes"] == ["kill_switch_clear"]
