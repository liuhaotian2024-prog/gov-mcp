from gov_mcp.outbound.models import OutboundActionIntent, OutboundAuthorizationState, OutboundCapabilityDomain, OutboundExecutionMode, OutboundRiskTier

def valid_intent(**overrides):
    data = dict(action_id="act_sandbox_1", capability_domain=OutboundCapabilityDomain.EXTERNAL_VALIDATION_MESSAGE, risk_tier=OutboundRiskTier.TIER_2_TRANSPARENT_LOW_RISK_EXTERNAL_VALIDATION, execution_mode=OutboundExecutionMode.SEND_GATED_DRY_RUN, authorization_state=OutboundAuthorizationState.OWNER_REVIEW_REQUIRED, target_id="target_1", target_identity_sufficient=True, message_hash="hash_1", idempotency_key="idem_12345678901234567890", ai_transparency_present=True, opt_out_language_present=True, suppression_clear=True, rate_limit_clear=True, hard_gates_absent=True)
    data.update(overrides)
    return OutboundActionIntent(**data)

from gov_mcp.outbound.provider_adapter import ProviderExecutionRequest
from gov_mcp.outbound.sandbox_manifest import build_sandbox_provider_manifest
from gov_mcp.outbound.sandbox_receipts import build_sandbox_receipt
from gov_mcp.outbound.persistent_idempotency import build_persistent_idempotency_status
from gov_mcp.outbound.sandbox_promotion import evaluate_sandbox_to_live_promotion, sandbox_promotion_contract_requirements

def test_sandbox_to_live_promotion_blocks_missing_live_requirements():
    req = ProviderExecutionRequest(action_intent=valid_intent())
    manifest = build_sandbox_provider_manifest(sandbox_ready=True, persistent_idempotency_ready=False)
    receipt = build_sandbox_receipt("act_sandbox_1", "idem_12345678901234567890")
    result = evaluate_sandbox_to_live_promotion(req, manifest, receipt, build_persistent_idempotency_status(persistent_ready=False))
    assert result["promotion_allowed"] is False
    assert "live_provider_scaffolded_but_disabled" in result["reason_codes"]
    assert "live_tests_required" in result["reason_codes"]
    assert "live_provider_config_required" in result["reason_codes"]
    assert "persistent_idempotency_required_for_live_promotion" in result["reason_codes"]
    assert result["live_receipt_created"] is False

def test_promotion_contract_documents_no_external_api_in_e25():
    contract = sandbox_promotion_contract_requirements()
    assert contract["live_promotion_enabled_in_e25"] is False
    assert contract["no_external_api_call_in_e25"] is True
