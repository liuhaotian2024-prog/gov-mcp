"""Non-production live-test gate and live readiness validator v2."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping

from gov_mcp.outbound.live_test_config import validate_live_test_config_profile
from gov_mcp.outbound.live_test_receipts import validate_live_test_receipt


DEFAULT_PRODUCTION_BLOCKERS = [
    "production_live_enabled_false",
    "production_credentials_absent_by_design",
    "production_persistent_idempotency_not_configured",
    "production_kill_switch_default_block",
    "production_live_tests_not_configured",
]


def _unique(items: List[str]) -> List[str]:
    return list(dict.fromkeys(items))


def evaluate_live_test_gate(
    *,
    live_test_config: Mapping[str, Any],
    persistent_idempotency_test_result: Mapping[str, Any],
    kill_switch_test_result: Mapping[str, Any],
    live_test_receipt: Mapping[str, Any],
    dry_run_receipt_history_present: bool,
    sandbox_receipt_history_present: bool,
    ceo_kg_route_supported: bool,
    suppression_clear: bool = True,
    compliance_clear: bool = True,
    rate_limit_available: bool = True,
    production_live_enabled: bool = False,
    production_persistent_ready: bool = False,
    production_live_tests_configured: bool = False,
) -> Dict[str, Any]:
    live_test_blockers: List[str] = []
    live_test_blockers.extend(validate_live_test_config_profile(live_test_config))
    live_test_blockers.extend(validate_live_test_receipt(live_test_receipt))
    if persistent_idempotency_test_result.get("live_test_persistent_ready") is not True:
        live_test_blockers.append("live_test_persistent_idempotency_not_ready")
    if persistent_idempotency_test_result.get("duplicate_protection_passed") is not True:
        live_test_blockers.append("live_test_duplicate_protection_not_proven")
    if kill_switch_test_result.get("allow_profile_passed") is not True:
        live_test_blockers.append("kill_switch_allow_profile_not_proven")
    if kill_switch_test_result.get("block_profile_passed") is not True:
        live_test_blockers.append("kill_switch_block_profile_not_proven")
    if not dry_run_receipt_history_present:
        live_test_blockers.append("dry_run_receipt_history_required")
    if not sandbox_receipt_history_present:
        live_test_blockers.append("sandbox_receipt_history_required")
    if not ceo_kg_route_supported:
        live_test_blockers.append("ceo_kg_route_support_required")
    if not suppression_clear:
        live_test_blockers.append("suppression_not_clear")
    if not compliance_clear:
        live_test_blockers.append("compliance_not_clear")
    if not rate_limit_available:
        live_test_blockers.append("rate_limit_not_available")

    production_blockers: List[str] = []
    if production_live_enabled is not True:
        production_blockers.append("production_live_enabled_false")
    if live_test_config.get("credential_values_present") is not False:
        production_blockers.append("credential_values_must_not_be_present")
    production_blockers.append("production_credentials_absent_by_design")
    if production_persistent_ready is not True:
        production_blockers.append("production_persistent_idempotency_not_configured")
    production_blockers.append("production_kill_switch_default_block")
    if production_live_tests_configured is not True:
        production_blockers.append("production_live_tests_not_configured")

    live_test_blockers = _unique(live_test_blockers)
    production_blockers = _unique(production_blockers)
    return {
        "artifact_id": "gov_mcp_live_readiness_validator_v2_result",
        "dry_run_ready": True,
        "sandbox_ready": True,
        "live_test_gate_ready": not live_test_blockers,
        "live_test_gate_blocked_reasons": live_test_blockers,
        "production_live_ready": False,
        "production_live_blocked": True,
        "production_live_blocked_reasons": production_blockers,
        "production_live_receipt_count": 0,
        "external_provider_called": False,
        "real_message_sent": False,
        "customer_contacted": False,
        "production_live_enabled": False,
        "owner_manual_send_default": False,
    }


def evaluate_live_readiness_v2(**kwargs: Any) -> Dict[str, Any]:
    return evaluate_live_test_gate(**kwargs)
