"""Pure idempotency helpers for outbound dry-run/pilot receipts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, List


def build_idempotency_key(action_id: str, message_hash: str, authorization_scope: str) -> str:
    raw = f"{action_id}:{message_hash}:{authorization_scope}".encode("utf-8")
    return "idem_" + hashlib.sha256(raw).hexdigest()[:32]


def validate_idempotency_key(key: str) -> List[str]:
    if not key:
        return ["idempotency_key_missing"]
    if not key.startswith("idem_"):
        return ["idempotency_key_prefix_invalid"]
    if len(key) < 20:
        return ["idempotency_key_too_short"]
    return []


@dataclass
class IdempotencyRegistry:
    seen: Dict[str, str] = field(default_factory=dict)
    cancelled: set[str] = field(default_factory=set)
    emergency_stopped: bool = False

    def check_new(self, key: str, action_id: str) -> Dict[str, object]:
        errors = validate_idempotency_key(key)
        if self.emergency_stopped:
            errors.append("emergency_stop_active")
        if key in self.cancelled:
            errors.append("idempotency_key_cancelled")
        if key in self.seen:
            errors.append("duplicate_idempotency_key")
        if errors:
            return {"decision": "deny", "reason_codes": errors}
        self.seen[key] = action_id
        return {"decision": "allow", "reason_codes": ["idempotency_key_recorded"]}

    def cancel(self, key: str) -> Dict[str, object]:
        self.cancelled.add(key)
        return {"status": "cancelled", "idempotency_key": key, "rollback_marker": f"rollback_{key}"}

    def emergency_stop(self) -> Dict[str, object]:
        self.emergency_stopped = True
        return {"status": "emergency_stop_active"}
