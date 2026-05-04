from gov_mcp.outbound.adapter_contract import (
    build_outbound_adapter_contract,
    validate_outbound_adapter_contract,
)


def test_adapter_contract_is_owned_by_gov_mcp_and_no_send():
    contract = build_outbound_adapter_contract()
    assert validate_outbound_adapter_contract(contract) == []
    assert contract["owner_repo"] == "gov-mcp"
    assert contract["provider_adapter_mode"] == "local_no_send"
    assert contract["external_provider_called"] is False
    assert contract["real_message_sent"] is False
    assert contract["future_execution_request_schema"]["disabled_in_e16g"] is True


def test_adapter_contract_declares_canonical_execution_modes():
    contract = build_outbound_adapter_contract()
    assert "send_gated_dry_run" in contract["execution_modes"]
    assert "gov_mcp_execute_after_activation" in contract["execution_modes"]
    assert "mcp_execute_after_activation" not in contract["execution_modes"]
