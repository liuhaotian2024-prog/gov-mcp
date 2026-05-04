from gov_mcp.outbound.live_test_config import (
    build_live_test_config_profile,
    build_live_test_configuration_profiles,
    validate_live_test_config_profile,
)


def test_live_test_config_uses_fake_names_and_keeps_production_disabled():
    profile = build_live_test_config_profile()
    assert validate_live_test_config_profile(profile) == []
    assert profile["live_test_config_ready"] is True
    assert profile["production_live_enabled"] is False
    assert profile["production_live_config_ready"] is False
    assert profile["secrets_committed"] is False
    assert profile["credential_values_present"] is False
    assert profile["fake_credential_variable_names"] == ["TEST_ONLY_YSTAR_OUTBOUND_PROVIDER_API_KEY"]


def test_configuration_profiles_keep_live_test_distinct_from_production_live():
    profiles = build_live_test_configuration_profiles()
    assert profiles["live_test_config"]["profile_kind"] == "live_test_config"
    assert profiles["production_live_config"]["production_live_enabled"] is False
    assert "production_live_enabled_false" in profiles["production_live_config"]["blocked_reasons"]
