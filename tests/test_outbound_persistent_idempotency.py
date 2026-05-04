from gov_mcp.outbound.models import OutboundActionIntent, OutboundAuthorizationState, OutboundCapabilityDomain, OutboundExecutionMode, OutboundRiskTier

def valid_intent(**overrides):
    data = dict(action_id="act_sandbox_1", capability_domain=OutboundCapabilityDomain.EXTERNAL_VALIDATION_MESSAGE, risk_tier=OutboundRiskTier.TIER_2_TRANSPARENT_LOW_RISK_EXTERNAL_VALIDATION, execution_mode=OutboundExecutionMode.SEND_GATED_DRY_RUN, authorization_state=OutboundAuthorizationState.OWNER_REVIEW_REQUIRED, target_id="target_1", target_identity_sufficient=True, message_hash="hash_1", idempotency_key="idem_12345678901234567890", ai_transparency_present=True, opt_out_language_present=True, suppression_clear=True, rate_limit_clear=True, hard_gates_absent=True)
    data.update(overrides)
    return OutboundActionIntent(**data)

from gov_mcp.outbound.persistent_idempotency import FileBackedIdempotencyStore, build_persistent_idempotency_status, validate_persistent_idempotency_for_live

def test_file_backed_idempotency_detects_duplicate(tmp_path):
    store = FileBackedIdempotencyStore(tmp_path / "idem.json", persistent_ready=True)
    first = store.check_and_record(idempotency_key="idem_12345678901234567890", action_id="act1", target_id="target", channel="email", provider_mode="sandbox_ready", receipt_id="receipt1")
    second = store.check_and_record(idempotency_key="idem_12345678901234567890", action_id="act1", target_id="target", channel="email", provider_mode="sandbox_ready", receipt_id="receipt2")
    assert first["decision"] == "allow"
    assert second["decision"] == "duplicate_noop"
    assert second["persistence_status"] == "persistent_ready"

def test_memory_only_not_live_safe_blocks_promotion():
    status = build_persistent_idempotency_status(persistent_ready=False)
    assert status["memory_only_not_live_safe"] is True
    assert "persistent_idempotency_required_for_live_promotion" in validate_persistent_idempotency_for_live(status)
    ready = build_persistent_idempotency_status(persistent_ready=True)
    assert validate_persistent_idempotency_for_live(ready) == []
