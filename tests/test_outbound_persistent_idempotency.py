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


def test_corrupted_and_missing_store_fail_closed(tmp_path):
    path = tmp_path / "idem.json"
    store = FileBackedIdempotencyStore(path, persistent_ready=True)
    path.write_text("{not-json", encoding="utf-8")
    corrupted = store.check_and_record(idempotency_key="idem_12345678901234567890", action_id="act1", target_id="target", channel="email", provider_mode="live", receipt_id="receipt1")
    assert corrupted["decision"] == "deny"
    assert "corrupted_store_blocked" in corrupted["reason_codes"]
    path.unlink()
    missing = store.check_and_record(idempotency_key="idem_22345678901234567890", action_id="act2", target_id="target", channel="email", provider_mode="live", receipt_id="receipt2")
    assert missing["decision"] == "deny"
    assert "missing_store_blocked" in missing["reason_codes"]
