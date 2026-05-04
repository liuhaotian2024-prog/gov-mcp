from gov_mcp.outbound.models import (
    OutboundActionIntent,
    OutboundAuthorizationState,
    OutboundCapabilityDomain,
    OutboundExecutionMode,
    OutboundRiskTier,
)


def valid_intent(**overrides):
    data = dict(
        action_id="act_provider_1",
        capability_domain=OutboundCapabilityDomain.EXTERNAL_VALIDATION_MESSAGE,
        risk_tier=OutboundRiskTier.TIER_2_TRANSPARENT_LOW_RISK_EXTERNAL_VALIDATION,
        execution_mode=OutboundExecutionMode.SEND_GATED_DRY_RUN,
        authorization_state=OutboundAuthorizationState.OWNER_REVIEW_REQUIRED,
        target_id="target_1",
        target_identity_sufficient=True,
        message_hash="hash_1",
        idempotency_key="idem_12345678901234567890",
        ai_transparency_present=True,
        opt_out_language_present=True,
        suppression_clear=True,
        rate_limit_clear=True,
        hard_gates_absent=True,
    )
    data.update(overrides)
    return OutboundActionIntent(**data)

from gov_mcp.outbound.provider_capability import ProviderMode
from gov_mcp.outbound.provider_manifest import build_provider_capability_manifest, manifest_to_capability


def test_provider_manifest_distinguishes_disabled_live_from_ready_live():
    disabled = build_provider_capability_manifest()
    ready = build_provider_capability_manifest(provider_mode=ProviderMode.LIVE_READY, supports_live=True)
    assert disabled["live_execution_blocked_reason"] == "live_provider_scaffolded_but_disabled"
    assert disabled["live_provider_enabled"] is False
    assert ready["live_execution_blocked_reason"] == "live_ready"
    assert manifest_to_capability(ready).live_ready() is True


def test_manifest_never_claims_external_effects():
    manifest = build_provider_capability_manifest()
    assert manifest["external_provider_called"] is False
    assert manifest["real_message_sent"] is False
    assert manifest["no_external_api_call_in_e21"] is True
