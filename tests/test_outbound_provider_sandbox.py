from gov_mcp.outbound.models import OutboundActionIntent, OutboundAuthorizationState, OutboundCapabilityDomain, OutboundExecutionMode, OutboundRiskTier

def valid_intent(**overrides):
    data = dict(action_id="act_sandbox_1", capability_domain=OutboundCapabilityDomain.EXTERNAL_VALIDATION_MESSAGE, risk_tier=OutboundRiskTier.TIER_2_TRANSPARENT_LOW_RISK_EXTERNAL_VALIDATION, execution_mode=OutboundExecutionMode.SEND_GATED_DRY_RUN, authorization_state=OutboundAuthorizationState.OWNER_REVIEW_REQUIRED, target_id="target_1", target_identity_sufficient=True, message_hash="hash_1", idempotency_key="idem_12345678901234567890", ai_transparency_present=True, opt_out_language_present=True, suppression_clear=True, rate_limit_clear=True, hard_gates_absent=True)
    data.update(overrides)
    return OutboundActionIntent(**data)

from gov_mcp.outbound.provider_adapter import ProviderExecutionRequest
from gov_mcp.outbound.provider_capability import ProviderMode
from gov_mcp.outbound.provider_sandbox import DeterministicLocalSandboxProvider, DisabledNativeSandboxProvider, evaluate_sandbox_guard_stack
from gov_mcp.outbound.sandbox_manifest import build_sandbox_provider_manifest

def test_sandbox_mode_distinct_and_executes_without_external_effect():
    manifest = build_sandbox_provider_manifest(sandbox_ready=True)
    result = DeterministicLocalSandboxProvider(manifest).execute(ProviderExecutionRequest(action_intent=valid_intent()))
    payload = result.to_dict()
    assert payload["provider_mode"] == ProviderMode.SANDBOX_READY.value
    assert payload["receipt_type"] == "sandbox_receipt"
    assert payload["receipt"]["receipt_type"] == "sandbox_receipt"
    assert payload["external_provider_called"] is False
    assert payload["real_message_sent"] is False
    assert payload["live_receipt_created"] is False

def test_disabled_native_sandbox_blocks_without_send():
    result = DisabledNativeSandboxProvider().execute(ProviderExecutionRequest(action_intent=valid_intent()))
    payload = result.to_dict()
    assert payload["execution_status"] == "blocked"
    assert payload["provider_mode"] == ProviderMode.SANDBOX_DISABLED.value
    assert "sandbox_provider_scaffolded_but_disabled" in payload["reason_codes"]
    assert payload["external_provider_called"] is False

def test_suppression_rate_limit_and_owner_risk_checks():
    manifest = build_sandbox_provider_manifest(sandbox_ready=True)
    suppressed = evaluate_sandbox_guard_stack(ProviderExecutionRequest(action_intent=valid_intent()), manifest, {"do_not_contact": True})
    assert suppressed["allowed_for_sandbox_execution"] is False
    assert "suppression_or_do_not_contact_active" in suppressed["reason_codes"]
    limited = evaluate_sandbox_guard_stack(ProviderExecutionRequest(action_intent=valid_intent()), manifest, {"actions_today": 5, "max_sandbox_actions_per_day": 5})
    assert "sandbox_quota_or_rate_limit_unavailable" in limited["reason_codes"]
    high = evaluate_sandbox_guard_stack(ProviderExecutionRequest(action_intent=valid_intent(risk_tier=OutboundRiskTier.TIER_4_COMMERCIAL_LEGAL_PRODUCTION_HIGH_RISK)), manifest)
    assert high["owner_approval_required_by_risk_tier"] is True
    assert "owner_approval_required_by_risk_tier" in high["reason_codes"]
    low = evaluate_sandbox_guard_stack(ProviderExecutionRequest(action_intent=valid_intent()), manifest)
    assert low["owner_approval_required_by_risk_tier"] is False
