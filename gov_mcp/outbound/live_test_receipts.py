"""Live-test receipt fixtures distinct from production live receipts."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping


def live_test_receipt_id(action_id: str, idempotency_key: str) -> str:
    digest = hashlib.sha256(f"live-test:{action_id}:{idempotency_key}".encode("utf-8")).hexdigest()[:16]
    return f"live_test_receipt_{digest}"


@dataclass(frozen=True)
class LiveTestReceipt:
    receipt_id: str
    action_id: str
    idempotency_key: str
    provider_mode: str = "live_test"
    receipt_type: str = "live_test_receipt"
    execution_status: str = "live_test_fixture_validated"
    external_effect: bool = False
    production_live_receipt: bool = False
    production_live_receipt_created: bool = False
    live_receipt_created: bool = False
    real_message_sent: bool = False
    external_provider_called: bool = False
    no_customer_contact: bool = True
    guard_summary: Dict[str, Any] = field(default_factory=dict)
    idempotency_result: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["artifact_id"] = "gov_mcp_live_test_receipt_fixture_v1"
        return data


def build_live_test_receipt(
    *,
    action_id: str,
    idempotency_key: str,
    guard_summary: Mapping[str, Any] | None = None,
    idempotency_result: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    return LiveTestReceipt(
        receipt_id=live_test_receipt_id(action_id, idempotency_key),
        action_id=action_id,
        idempotency_key=idempotency_key,
        guard_summary=dict(guard_summary or {"live_test_gate": "passed"}),
        idempotency_result=dict(idempotency_result or {"decision": "allow"}),
    ).to_dict()


def validate_live_test_receipt(receipt: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    if receipt.get("receipt_type") != "live_test_receipt":
        errors.append("live_test_receipt_type_required")
    if receipt.get("provider_mode") != "live_test":
        errors.append("live_test_provider_mode_required")
    if receipt.get("external_effect") is not False:
        errors.append("live_test_receipt_must_have_no_external_effect")
    if receipt.get("production_live_receipt") is not False:
        errors.append("live_test_receipt_cannot_be_production_live_receipt")
    if receipt.get("production_live_receipt_created") is not False:
        errors.append("production_live_receipt_count_must_remain_zero")
    if receipt.get("live_receipt_created") is not False:
        errors.append("live_test_receipt_cannot_create_live_receipt")
    if receipt.get("real_message_sent") is not False:
        errors.append("live_test_receipt_cannot_mark_real_message_sent")
    if receipt.get("external_provider_called") is not False:
        errors.append("live_test_receipt_cannot_call_external_provider")
    return list(dict.fromkeys(errors))


def accept_as_production_live_receipt(receipt: Mapping[str, Any]) -> bool:
    return bool(
        receipt.get("receipt_type") == "live_receipt"
        and receipt.get("provider_mode") == "live"
        and receipt.get("external_effect") is True
        and receipt.get("production_live_receipt_created") is True
    )
