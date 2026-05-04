"""Persistent idempotency foundation for sandbox/live promotion gates."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping

from gov_mcp.outbound.idempotency import validate_idempotency_key


def action_hash(action_id: str, target_id: str, channel: str, provider_mode: str) -> str:
    raw = f"{action_id}:{target_id}:{channel}:{provider_mode}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class IdempotencyRecord:
    idempotency_key: str
    action_id: str
    action_hash: str
    target_id: str
    channel: str
    provider_mode: str
    first_seen: str
    receipt_id: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class FileBackedIdempotencyStore:
    def __init__(self, path: str | Path, *, persistent_ready: bool = False):
        self.path = Path(path)
        self.persistent_ready = persistent_ready
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("{}\n", encoding="utf-8")

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"__missing_store__": True}
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw or "{}")
        except Exception as exc:  # fail closed for corrupted stores
            return {"__corrupted_store__": type(exc).__name__}
        if not isinstance(data, dict):
            return {"__corrupted_store__": "store_root_must_be_object"}
        return data

    def save(self, data: Mapping[str, Any]) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(dict(data), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def check_and_record(
        self,
        *,
        idempotency_key: str,
        action_id: str,
        target_id: str,
        channel: str,
        provider_mode: str,
        receipt_id: str,
        first_seen: str = "deterministic_e25",
    ) -> Dict[str, Any]:
        errors = validate_idempotency_key(idempotency_key)
        if errors:
            return {"decision": "deny", "reason_codes": errors, "persistence_status": self.persistence_status()}
        data = self.load()
        if "__missing_store__" in data:
            return {"decision": "deny", "reason_codes": ["missing_store_blocked"], "persistence_status": "missing_store_blocked"}
        if "__corrupted_store__" in data:
            return {"decision": "deny", "reason_codes": ["corrupted_store_blocked"], "persistence_status": "corrupted_store_blocked"}
        if idempotency_key in data:
            return {
                "decision": "duplicate_noop",
                "reason_codes": ["duplicate_idempotency_key"],
                "record": data[idempotency_key],
                "persistence_status": self.persistence_status(),
            }
        record = IdempotencyRecord(
            idempotency_key,
            action_id,
            action_hash(action_id, target_id, channel, provider_mode),
            target_id,
            channel,
            provider_mode,
            first_seen,
            receipt_id,
        ).to_dict()
        data[idempotency_key] = record
        self.save(data)
        return {
            "decision": "allow",
            "reason_codes": ["idempotency_key_recorded"],
            "record": record,
            "persistence_status": self.persistence_status(),
        }

    def persistence_status(self) -> str:
        return "persistent_ready" if self.persistent_ready else "persistent_disabled"


def build_persistent_idempotency_status(
    *,
    persistent_ready: bool = False,
    configured_path: str = "",
    store_state: str = "available",
) -> Dict[str, Any]:
    status = "persistent_ready" if persistent_ready else "persistent_disabled"
    if store_state == "missing":
        status = "missing_store_blocked"
    elif store_state == "corrupted":
        status = "corrupted_store_blocked"
    return {
        "artifact_id": "gov_mcp_persistent_idempotency_status_v1",
        "persistent_ready": persistent_ready and status == "persistent_ready",
        "persistence_status": status,
        "configured_path": configured_path,
        "memory_only_not_live_safe": status != "persistent_ready",
        "live_promotion_allowed": status == "persistent_ready",
        "live_promotion_blocker": "persistent_idempotency_ready" if status == "persistent_ready" else "persistent_idempotency_not_ready",
    }


def validate_persistent_idempotency_for_live(status: Mapping[str, Any]) -> List[str]:
    if status.get("persistent_ready") is True and status.get("persistence_status") == "persistent_ready":
        return []
    value = str(status.get("persistence_status", "persistent_disabled"))
    if value == "missing_store_blocked":
        return ["missing_store_blocked"]
    if value == "corrupted_store_blocked":
        return ["corrupted_store_blocked"]
    return ["persistent_idempotency_required_for_live_promotion"]
