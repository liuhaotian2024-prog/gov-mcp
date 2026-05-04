"""Live receipt boundary: no live receipts without a real allowed live effect."""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Mapping


def live_receipt_id(action_id: str, idempotency_key: str) -> str:
    digest = hashlib.sha256(f"live:{action_id}:{idempotency_key}".encode("utf-8")).hexdigest()[:16]
    return f"live_receipt_{digest}"


REQUIRED_LIVE_FLAGS = [
    "live_mode_enabled",
    "provider_live_ready",
    "persistent_idempotency_ready",
    "kill_switch_clear",
    "suppression_clear",
    "compliance_clear",
    "rate_limit_available",
    "live_tests_passed",
    "promotion_allowed",
    "external_effect_confirmed",
]


def evaluate_live_receipt_boundary(context: Mapping[str, Any]) -> Dict[str, Any]:
    blockers = [f"{flag}_required" for flag in REQUIRED_LIVE_FLAGS if context.get(flag) is not True]
    return {
        "artifact_id": "gov_mcp_live_receipt_boundary_result_v1",
        "live_receipt_allowed": not blockers,
        "receipt_type": "live_receipt" if not blockers else "blocked_receipt",
        "reason_codes": blockers or ["live_receipt_boundary_passed"],
        "live_receipt_created": False,
        "external_provider_called": False,
        "real_message_sent": False,
    }


def build_live_receipt(*, action_id: str, idempotency_key: str, context: Mapping[str, Any]) -> Dict[str, Any]:
    boundary = evaluate_live_receipt_boundary(context)
    if not boundary["live_receipt_allowed"]:
        return {
            "receipt_type": "blocked_receipt",
            "action_id": action_id,
            "reason_codes": boundary["reason_codes"],
            "live_receipt_created": False,
            "external_effect": False,
        }
    return {
        "receipt_id": live_receipt_id(action_id, idempotency_key),
        "receipt_type": "live_receipt",
        "action_id": action_id,
        "mode": "live",
        "external_effect": True,
        "live_receipt_created": True,
    }


def validate_receipt_boundary(receipt: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    if receipt.get("receipt_type") in {"dry_run_receipt", "sandbox_receipt", "blocked_receipt", "replay_noop_receipt"} and receipt.get("live_receipt_created") is True:
        errors.append("non_live_receipt_cannot_create_live_receipt")
    if receipt.get("receipt_type") == "live_receipt":
        if receipt.get("mode") != "live":
            errors.append("live_receipt_requires_live_mode")
        if receipt.get("external_effect") is not True:
            errors.append("live_receipt_requires_external_effect_true")
    return errors
