"""Canonical gov-mcp outbound adapter contract.

The contract is intentionally no-send for E16G. It defines the adapter
boundary that real providers must later implement behind explicit activation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from gov_mcp.outbound.models import (
    OutboundAuthorizationState,
    OutboundCapabilityDomain,
    OutboundExecutionMode,
    OutboundRiskTier,
)
from gov_mcp.outbound.policy import outbound_policy_summary
from gov_mcp.outbound.safety_guards import safety_guard_matrix


def build_outbound_adapter_contract() -> Dict[str, Any]:
    return {
        "contract_id": "gov_mcp_outbound_no_send_adapter_contract_v1",
        "owner_repo": "gov-mcp",
        "provider_adapter_mode": "local_no_send",
        "no_send_invariant": True,
        "external_provider_called": False,
        "real_message_sent": False,
        "network_required": False,
        "login_required": False,
        "credential_required": False,
        "capability_domains": [item.value for item in OutboundCapabilityDomain],
        "risk_tiers": [item.value for item in OutboundRiskTier],
        "execution_modes": [item.value for item in OutboundExecutionMode],
        "authorization_states": [item.value for item in OutboundAuthorizationState],
        "input_schema": {
            "action_intent": "OutboundActionIntent",
            "ygov_decision_envelope": "required_for_future_live_send",
            "authorization_state": "required",
            "idempotency_key": "required",
            "message_hash": "required",
        },
        "preflight_schema": {
            "policy_result": "OutboundPreflightResult",
            "safety_guards": safety_guard_matrix(),
        },
        "dry_run_request_schema": {
            "execution_mode": "draft_only|send_gated_dry_run|dry_run_local",
            "provider_adapter_mode": "local_no_send",
        },
        "future_execution_request_schema": {
            "execution_mode": "gov_mcp_execute_after_activation",
            "requires_activated_authorization": True,
            "requires_provider_adapter": True,
            "disabled_in_e16g": True,
        },
        "execution_receipt_schema": {
            "receipt_id": "required",
            "action_id": "required",
            "execution_mode": "required",
            "preflight_result": "required",
            "guard_results": "required",
            "external_action_executed": False,
            "provider_called": False,
            "real_message_sent": False,
            "ledger_transition": "required",
            "feedback_wait_state": "required",
            "reason_codes": "required",
        },
        "failure_receipt_schema": {
            "receipt_id": "required",
            "action_id": "required",
            "failure_code": "deny|guard_failed|authorization_missing|rate_limit|suppressed|kill_switch|adapter_unavailable",
            "reason_codes": "required",
        },
        "idempotency_key_requirement": "sha256(action_id + message_hash + authorization_scope)",
        "audit_ledger_hook": "receipt must be written before feedback wait-state can be counted",
        "feedback_wait_state_hook": "waiting_feedback only after valid real-send receipt in future activated mode",
        "policy": outbound_policy_summary(),
    }


def validate_outbound_adapter_contract(contract: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    if contract.get("owner_repo") != "gov-mcp":
        errors.append("owner_repo_must_be_gov_mcp")
    if contract.get("provider_adapter_mode") != "local_no_send":
        errors.append("provider_adapter_mode_must_be_local_no_send")
    for flag in ["no_send_invariant", "external_provider_called", "real_message_sent", "network_required", "login_required", "credential_required"]:
        value = contract.get(flag)
        if flag == "no_send_invariant":
            if value is not True:
                errors.append("no_send_invariant_must_be_true")
        elif value is not False:
            errors.append(f"{flag}_must_be_false")
    for mode in ["deny", "draft_only", "send_gated_dry_run", "gov_mcp_execute_after_activation"]:
        if mode not in contract.get("execution_modes", []):
            errors.append(f"missing_execution_mode_{mode}")
    if contract.get("future_execution_request_schema", {}).get("disabled_in_e16g") is not True:
        errors.append("future_live_execution_must_be_disabled_in_e16g")
    return list(dict.fromkeys(errors))
