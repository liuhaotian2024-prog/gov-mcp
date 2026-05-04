from gov_mcp.outbound.models import OutboundActionIntent, OutboundAuthorizationState, OutboundCapabilityDomain, OutboundExecutionMode, OutboundRiskTier

def valid_intent(**overrides):
    data = dict(action_id="act_sandbox_1", capability_domain=OutboundCapabilityDomain.EXTERNAL_VALIDATION_MESSAGE, risk_tier=OutboundRiskTier.TIER_2_TRANSPARENT_LOW_RISK_EXTERNAL_VALIDATION, execution_mode=OutboundExecutionMode.SEND_GATED_DRY_RUN, authorization_state=OutboundAuthorizationState.OWNER_REVIEW_REQUIRED, target_id="target_1", target_identity_sufficient=True, message_hash="hash_1", idempotency_key="idem_12345678901234567890", ai_transparency_present=True, opt_out_language_present=True, suppression_clear=True, rate_limit_clear=True, hard_gates_absent=True)
    data.update(overrides)
    return OutboundActionIntent(**data)

from gov_mcp.outbound.provider_capability import ProviderMode
from gov_mcp.outbound.sandbox_manifest import build_sandbox_provider_manifest, validate_sandbox_provider_manifest

def test_sandbox_manifest_declares_modes_and_no_external_api():
    manifest = build_sandbox_provider_manifest(sandbox_ready=True)
    assert ProviderMode.SANDBOX_READY.value in manifest["provider_modes"]
    assert ProviderMode.SANDBOX_DISABLED.value in manifest["provider_modes"]
    assert manifest["sandbox_ready"] is True
    assert manifest["sandbox_scaffold_ready"] is True
    assert manifest["external_api_calls_allowed"] is False
    assert manifest["live_enabled"] is False
    assert validate_sandbox_provider_manifest(manifest) == []

def test_sandbox_disabled_manifest_blocks_sandbox():
    manifest = build_sandbox_provider_manifest(sandbox_ready=False)
    assert manifest["sandbox_provider_mode"] == ProviderMode.SANDBOX_DISABLED.value
    assert manifest["sandbox_ready"] is False
    assert "sandbox_provider_scaffolded_but_disabled" == manifest["sandbox_execution_blocked_reason"]
