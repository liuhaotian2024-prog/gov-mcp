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
        return json.loads(self.path.read_text(encoding="utf-8") or "{}")

    def save(self, data: Mapping[str, Any]) -> None:
        self.path.write_text(json.dumps(dict(data), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def check_and_record(self, *, idempotency_key: str, action_id: str, target_id: str, channel: str, provider_mode: str, receipt_id: str, first_seen: str = "deterministic_e25") -> Dict[str, Any]:
        errors = validate_idempotency_key(idempotency_key)
        if errors:
            return {"decision": "deny", "reason_codes": errors, "persistence_status": self.persistence_status()}
        data = self.load()
        if idempotency_key in data:
            return {"decision": "duplicate_noop", "reason_codes": ["duplicate_idempotency_key"], "record": data[idempotency_key], "persistence_status": self.persistence_status()}
        record = IdempotencyRecord(idempotency_key, action_id, action_hash(action_id, target_id, channel, provider_mode), target_id, channel, provider_mode, first_seen, receipt_id).to_dict()
        data[idempotency_key] = record
        self.save(data)
        return {"decision": "allow", "reason_codes": ["idempotency_key_recorded"], "record": record, "persistence_status": self.persistence_status()}

    def persistence_status(self) -> str:
        return "persistent_ready" if self.persistent_ready else "persistent_disabled"


def build_persistent_idempotency_status(*, persistent_ready: bool = False, configured_path: str = "") -> Dict[str, Any]:
    return {
        "artifact_id": "gov_mcp_persistent_idempotency_status_v1",
        "persistent_ready": persistent_ready,
        "persistence_status": "persistent_ready" if persistent_ready else "persistent_disabled",
        "configured_path": configured_path,
        "memory_only_not_live_safe": not persistent_ready,
        "live_promotion_allowed": persistent_ready,
        "live_promotion_blocker": "persistent_idempotency_not_ready" if not persistent_ready else "persistent_idempotency_ready",
    }


def validate_persistent_idempotency_for_live(status: Mapping[str, Any]) -> List[str]:
    if status.get("persistent_ready") is True and status.get("persistence_status") == "persistent_ready":
        return []
    return ["persistent_idempotency_required_for_live_promotion"]
