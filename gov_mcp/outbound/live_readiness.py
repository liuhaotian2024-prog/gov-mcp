"""Live readiness validator integrating existing provider wheels."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping

from gov_mcp.outbound.live_config import validate_live_provider_config
from gov_mcp.outbound.persistent_idempotency import validate_persistent_idempotency_for_live
from gov_mcp.outbound.provider_manifest import manifest_to_capability


def evaluate_live_readiness(
    *,
    live_config: Mapping[str, Any],
    provider_manifest: Mapping[str, Any],
    persistent_idempotency_status: Mapping[str, Any],
    kill_switch_result: Mapping[str, Any],
    live_receipt_boundary: Mapping[str, Any],
    promotion_result: Mapping[str, Any],
    dry_run_receipt_history_present: bool,
    sandbox_receipt_history_present: bool,
    ceo_kg_route_supported: bool,
) -> Dict[str, Any]:
    blockers: List[str] = []
    blockers.extend(validate_live_provider_config(live_config))
    capability = manifest_to_capability(provider_manifest)
    if live_config.get("live_enabled") is not True:
        blockers.append("live_enabled_false")
    if not capability.live_ready():
        blockers.append(provider_manifest.get("live_execution_blocked_reason", "provider_not_live_ready"))
    blockers.extend(validate_persistent_idempotency_for_live(persistent_idempotency_status))
    if kill_switch_result.get("kill_switch_clear") is not True:
        blockers.extend(kill_switch_result.get("reason_codes", ["kill_switch_not_clear"]))
    if live_receipt_boundary.get("live_receipt_allowed") is not True:
        blockers.extend(live_receipt_boundary.get("reason_codes", ["live_receipt_boundary_not_ready"]))
    if promotion_result.get("promotion_allowed") is not True:
        blockers.extend(promotion_result.get("reason_codes", ["promotion_gate_not_passed"]))
    if not dry_run_receipt_history_present:
        blockers.append("dry_run_receipt_history_required")
    if not sandbox_receipt_history_present:
        blockers.append("sandbox_receipt_history_required")
    if not ceo_kg_route_supported:
        blockers.append("ceo_kg_route_support_required")
    blockers = list(dict.fromkeys(blockers))
    return {
        "artifact_id": "gov_mcp_live_readiness_validator_result_v1",
        "live_ready": not blockers,
        "live_ready_action_count": 1 if not blockers else 0,
        "live_blocked_action_count": 0 if not blockers else 1,
        "reason_codes": blockers or ["live_readiness_passed"],
        "external_provider_called": False,
        "real_message_sent": False,
        "live_receipt_created": False,
    }
