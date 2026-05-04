from gov_mcp.outbound.live_config import build_live_provider_config, validate_live_provider_config


def test_live_config_defaults_disabled_and_never_contains_secret_values():
    config = build_live_provider_config(required_credential_variable_names=["YSTAR_OUTBOUND_PROVIDER_API_KEY"])
    assert config["live_config_schema_ready"] is True
    assert config["live_enabled"] is False
    assert config["secrets_committed"] is False
    assert validate_live_provider_config(config) == []


def test_live_config_rejects_credential_values():
    config = build_live_provider_config(
        credential_source_type="environment_variable_names_only",
        required_credential_variable_names=["KEY=value"],
        credential_values_present=True,
    )
    errors = validate_live_provider_config(config)
    assert "credential_values_must_not_be_present" in errors
    assert "credential_names_only_no_values" in errors
