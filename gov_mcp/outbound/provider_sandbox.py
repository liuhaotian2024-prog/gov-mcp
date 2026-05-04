"""Deterministic provider sandbox scaffold for no-effect outbound execution."""
from __future__ import annotations

from typing import Any, Dict, Mapping

from gov_mcp.outbound.models import OutboundRiskTier, normalize_enum_value
from gov_mcp.outbound.provider_adapter import ProviderExecutionRequest, ProviderExecutionResult, provider_result_id, request_from_mapping
from gov_mcp.outbound.provider_capability import ProviderMode
from gov_mcp.outbound.sandbox_manifest import build_sandbox_provider_manifest
from gov_mcp.outbound.sandbox_receipts import build_sandbox_receipt
from gov_mcp.outbound.persistent_idempotency import FileBackedIdempotencyStore

LOW_RISK_SANDBOX_TIERS = {
    OutboundRiskTier.TIER_1_PUBLIC_READ_ONLY.value,
    OutboundRiskTier.TIER_2_TRANSPARENT_LOW_RISK_EXTERNAL_VALIDATION.value,
}
HIGH_RISK_OWNER_TIERS = {OutboundRiskTier.TIER_4_COMMERCIAL_LEGAL_PRODUCTION_HIGH_RISK.value}


def owner_required_for_sandbox(risk_tier: str) -> bool:
    return risk_tier in HIGH_RISK_OWNER_TIERS


def evaluate_sandbox_guard_stack(request: ProviderExecutionRequest | Mapping[str, Any], manifest: Mapping[str, Any], guard_context: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    req = request if isinstance(request, ProviderExecutionRequest) else request_from_mapping(request)
    intent = req.action_intent
    ctx = dict(guard_context or {})
    risk_tier = normalize_enum_value(intent.risk_tier)
    checks: Dict[str, str] = {}
    reason_codes: list[str] = []
    checks["risk_tier_check"] = "pass" if risk_tier in LOW_RISK_SANDBOX_TIERS or risk_tier in HIGH_RISK_OWNER_TIERS else "fail"
    if checks["risk_tier_check"] == "fail": reason_codes.append("risk_tier_not_sandbox_executable")
    checks["provider_mode_check"] = "pass" if manifest.get("sandbox_provider_mode") == ProviderMode.SANDBOX_READY.value else "fail"
    if checks["provider_mode_check"] == "fail": reason_codes.append(manifest.get("sandbox_execution_blocked_reason", "sandbox_provider_not_ready"))
    checks["sandbox_capability_check"] = "pass" if manifest.get("sandbox_ready") is True else "fail"
    if checks["sandbox_capability_check"] == "fail": reason_codes.append("sandbox_capability_not_ready")
    quota_ok = req.quota_available and int(ctx.get("actions_today", 0)) < int(ctx.get("max_sandbox_actions_per_day", 5))
    checks["quota_rate_limit_check"] = "pass" if quota_ok else "fail"
    if not quota_ok: reason_codes.append("sandbox_quota_or_rate_limit_unavailable")
    checks["idempotency_key_check"] = "pass" if intent.idempotency_key.startswith("idem_") else "fail"
    if checks["idempotency_key_check"] == "fail": reason_codes.append("idempotency_key_missing_or_invalid")
    suppression_ok = req.suppression_clear and intent.suppression_clear and not ctx.get("do_not_contact", False)
    checks["suppression_check"] = "pass" if suppression_ok else "fail"
    if not suppression_ok: reason_codes.append("suppression_or_do_not_contact_active")
    compliance_ok = bool(ctx.get("compliance_clear", True))
    checks["compliance_check"] = "pass" if compliance_ok else "fail"
    if not compliance_ok: reason_codes.append("compliance_blocked")
    evidence_ok = req.evidence_sufficient and intent.target_identity_sufficient and bool(intent.target_id)
    checks["evidence_sufficiency_check"] = "pass" if evidence_ok else "fail"
    if not evidence_ok: reason_codes.append("target_evidence_insufficient")
    message_ok = req.message_safety_passed and bool(intent.message_hash) and intent.ai_transparency_present and intent.opt_out_language_present
    checks["message_safety_check"] = "pass" if message_ok else "fail"
    if not message_ok: reason_codes.append("message_safety_or_transparency_missing")
    kill_ok = not manifest.get("kill_switch_active", False) and not ctx.get("kill_switch_active", False)
    checks["kill_switch_check"] = "pass" if kill_ok else "fail"
    if not kill_ok: reason_codes.append("kill_switch_active")
    owner_required = owner_required_for_sandbox(risk_tier) or bool(ctx.get("explicit_owner_gate", False))
    checks["owner_approval_check"] = "pass" if (not owner_required or req.owner_approval_present) else "fail"
    if owner_required and not req.owner_approval_present: reason_codes.append("owner_approval_required_by_risk_tier")
    checks["live_disabled_check"] = "pass" if manifest.get("live_enabled") is False else "fail"
    if checks["live_disabled_check"] == "fail": reason_codes.append("live_must_remain_disabled_for_sandbox")
    allowed = all(v == "pass" for v in checks.values())
    return {"artifact_id": "gov_mcp_sandbox_guard_stack_result", "action_id": intent.action_id, "allowed_for_sandbox_execution": allowed, "owner_approval_required": owner_required, "owner_approval_required_by_risk_tier": owner_required_for_sandbox(risk_tier), "checks": checks, "reason_codes": list(dict.fromkeys(reason_codes)) or ["sandbox_guard_stack_passed"], "external_provider_called": False, "real_message_sent": False, "live_receipt_created": False}


class DeterministicLocalSandboxProvider:
    provider_mode = ProviderMode.SANDBOX_READY.value

    def __init__(self, manifest: Mapping[str, Any] | None = None, idempotency_store: FileBackedIdempotencyStore | None = None):
        self.manifest = dict(manifest or build_sandbox_provider_manifest(sandbox_ready=True, persistent_idempotency_ready=False))
        self.idempotency_store = idempotency_store
        self._seen: set[str] = set()

    def execute(self, request: ProviderExecutionRequest | Mapping[str, Any], guard_context: Mapping[str, Any] | None = None) -> ProviderExecutionResult:
        req = request if isinstance(request, ProviderExecutionRequest) else request_from_mapping(request)
        guard = evaluate_sandbox_guard_stack(req, self.manifest, guard_context)
        idem_result: Dict[str, Any]
        if req.action_intent.idempotency_key in self._seen:
            idem_result = {"decision": "duplicate_noop", "reason_codes": ["duplicate_idempotency_key"]}
            guard = dict(guard)
            guard["allowed_for_sandbox_execution"] = False
            guard["reason_codes"] = list(dict.fromkeys(list(guard["reason_codes"]) + ["duplicate_idempotency_key"]))
        else:
            self._seen.add(req.action_intent.idempotency_key)
            idem_result = {"decision": "allow", "reason_codes": ["idempotency_key_recorded"]}
        if self.idempotency_store is not None and idem_result["decision"] == "allow":
            idem_result = self.idempotency_store.check_and_record(idempotency_key=req.action_intent.idempotency_key, action_id=req.action_intent.action_id, target_id=req.action_intent.target_id, channel=req.action_intent.channel, provider_mode=self.provider_mode, receipt_id="pending_sandbox_receipt")
        if not guard["allowed_for_sandbox_execution"]:
            return ProviderExecutionResult(provider_result_id(req.action_intent.action_id, "sandbox_blocked"), req.action_intent.action_id, self.provider_mode, "blocked", "blocked_sandbox_receipt", list(guard["reason_codes"]), {"receipt_type": "blocked_sandbox_receipt", "guard_summary": guard, "idempotency_result": idem_result, "external_provider_called": False, "real_message_sent": False, "live_receipt_created": False}, False, False, False)
        receipt = build_sandbox_receipt(req.action_intent.action_id, req.action_intent.idempotency_key, guard_summary=guard, idempotency_result=idem_result, suppression_result={"decision": "allow"}, rate_limit_result={"decision": "allow"}, compliance_result={"decision": "allow"})
        return ProviderExecutionResult(provider_result_id(req.action_intent.action_id, "sandbox_executed"), req.action_intent.action_id, self.provider_mode, "sandbox_executed", "sandbox_receipt", list(guard["reason_codes"]), receipt, False, False, False)


class DisabledNativeSandboxProvider:
    provider_mode = ProviderMode.SANDBOX_DISABLED.value

    def execute(self, request: ProviderExecutionRequest | Mapping[str, Any]) -> ProviderExecutionResult:
        req = request if isinstance(request, ProviderExecutionRequest) else request_from_mapping(request)
        return ProviderExecutionResult(provider_result_id(req.action_intent.action_id, "sandbox_blocked"), req.action_intent.action_id, self.provider_mode, "blocked", "blocked_sandbox_receipt", ["sandbox_provider_scaffolded_but_disabled", "external_provider_not_called", "live_receipt_not_created"], {"receipt_type": "blocked_sandbox_receipt", "action_id": req.action_intent.action_id, "external_provider_called": False, "real_message_sent": False, "live_receipt_created": False}, False, False, False)
