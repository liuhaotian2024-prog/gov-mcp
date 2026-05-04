"""Sandbox-to-live promotion contract."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping

from gov_mcp.outbound.persistent_idempotency import validate_persistent_idempotency_for_live
from gov_mcp.outbound.provider_adapter import ProviderExecutionRequest, request_from_mapping
from gov_mcp.outbound.provider_guard_stack import owner_required_by_risk_tier
from gov_mcp.outbound.provider_manifest import manifest_to_capability
from gov_mcp.outbound.sandbox_receipts import validate_sandbox_receipt


def sandbox_receipt_passed(receipt: Mapping[str, Any]) -> bool:
    return bool(receipt and receipt.get("receipt_type") == "sandbox_receipt" and receipt.get("execution_status") == "sandbox_executed" and receipt.get("external_provider_called") is False and receipt.get("real_message_sent") is False and receipt.get("live_receipt_created") is False)


def evaluate_sandbox_to_live_promotion(request: ProviderExecutionRequest | Mapping[str, Any], provider_manifest: Mapping[str, Any], sandbox_receipt: Mapping[str, Any], persistent_idempotency_status: Mapping[str, Any], live_tests_passed: bool = False, live_config_present: bool = False) -> Dict[str, Any]:
    req = request if isinstance(request, ProviderExecutionRequest) else request_from_mapping(request)
    capability = manifest_to_capability(provider_manifest)
    reason_codes: List[str] = []
    if not sandbox_receipt_passed(sandbox_receipt): reason_codes.append("sandbox_pass_required")
    reason_codes.extend(validate_sandbox_receipt(sandbox_receipt))
    if not capability.live_ready(): reason_codes.append(provider_manifest.get("live_execution_blocked_reason", "provider_not_live_ready"))
    if not live_tests_passed: reason_codes.append("live_tests_required")
    if not live_config_present: reason_codes.append("live_provider_config_required")
    reason_codes.extend(validate_persistent_idempotency_for_live(persistent_idempotency_status))
    owner_required = owner_required_by_risk_tier(str(req.action_intent.risk_tier))
    if owner_required and not req.owner_approval_present: reason_codes.append("owner_approval_required_by_risk_tier")
    allowed = not reason_codes
    return {"artifact_id": "gov_mcp_sandbox_to_live_promotion_result", "action_id": req.action_intent.action_id, "promotion_allowed": allowed, "sandbox_passed": sandbox_receipt_passed(sandbox_receipt), "provider_live_ready": capability.live_ready(), "persistent_idempotency_ready": not validate_persistent_idempotency_for_live(persistent_idempotency_status), "owner_approval_required_by_risk_tier": owner_required, "reason_codes": list(dict.fromkeys(reason_codes)) or ["sandbox_to_live_promotion_passed"], "external_provider_called": False, "real_message_sent": False, "live_receipt_created": False}


def sandbox_promotion_contract_requirements() -> Dict[str, Any]:
    return {"contract_id": "gov_mcp_outbound_sandbox_to_live_promotion_v1", "required": ["sandbox pass", "provider capability live_ready", "live provider config present", "live tests pass", "persistent idempotency ready", "suppression clear", "rate limit available", "audit receipt enabled", "owner approval only if required by risk tier"], "live_promotion_enabled_in_e25": False, "no_external_api_call_in_e25": True}
