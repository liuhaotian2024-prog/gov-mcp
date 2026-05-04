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

from gov_mcp.outbound.provider_capability import ProviderMode, capability_from_mapping
from gov_mcp.outbound.provider_manifest import build_provider_capability_manifest, validate_provider_capability_manifest


def test_default_manifest_has_dry_run_but_no_live_enabled():
    manifest = build_provider_capability_manifest()
    assert manifest["no_send_available"] is True
    assert manifest["dry_run_available"] is True
    assert manifest["live_scaffold_available"] is True
    assert manifest["live_provider_enabled"] is False
    assert manifest["provider_mode"] == ProviderMode.LIVE_DISABLED.value
    assert manifest["real_message_sent"] is False
    assert validate_provider_capability_manifest(manifest) == []


def test_live_ready_requires_explicit_live_mode_and_support():
    manifest = build_provider_capability_manifest(provider_mode=ProviderMode.LIVE_READY, supports_live=True)
    capability = capability_from_mapping(manifest)
    assert capability.live_ready() is True
    assert manifest["live_provider_enabled"] is True
