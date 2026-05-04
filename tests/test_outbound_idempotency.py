from gov_mcp.outbound.idempotency import (
    IdempotencyRegistry,
    build_idempotency_key,
    validate_idempotency_key,
)


def test_idempotency_key_is_deterministic_and_valid():
    key_1 = build_idempotency_key("action_1", "message_hash", "scope")
    key_2 = build_idempotency_key("action_1", "message_hash", "scope")
    assert key_1 == key_2
    assert validate_idempotency_key(key_1) == []


def test_registry_blocks_duplicate_and_cancelled_keys():
    registry = IdempotencyRegistry()
    key = build_idempotency_key("action_1", "message_hash", "scope")
    assert registry.check_new(key, "action_1")["decision"] == "allow"
    assert registry.check_new(key, "action_1")["decision"] == "deny"
    cancelled = registry.cancel(key)
    assert cancelled["rollback_marker"].startswith("rollback_")


def test_registry_emergency_stop_blocks_new_keys():
    registry = IdempotencyRegistry()
    registry.emergency_stop()
    key = build_idempotency_key("action_2", "message_hash", "scope")
    result = registry.check_new(key, "action_2")
    assert result["decision"] == "deny"
    assert "emergency_stop_active" in result["reason_codes"]
