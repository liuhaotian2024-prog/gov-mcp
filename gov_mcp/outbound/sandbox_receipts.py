"""Sandbox receipt models for provider-like no-effect execution."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping


def sandbox_receipt_id(action_id: str, idempotency_key: str) -> str:
    digest = hashlib.sha256(f"sandbox:{action_id}:{idempotency_key}".encode("utf-8")).hexdigest()[:16]
    return f"sandbox_receipt_{digest}"


@dataclass(frozen=True)
class SandboxReceipt:
    receipt_id: str
    action_id: str
    provider_mode: str
    receipt_type: str = "sandbox_receipt"
    execution_status: str = "sandbox_executed"
    guard_summary: Dict[str, Any] = field(default_factory=dict)
    idempotency_result: Dict[str, Any] = field(default_factory=dict)
    suppression_result: Dict[str, Any] = field(default_factory=dict)
    rate_limit_result: Dict[str, Any] = field(default_factory=dict)
    compliance_result: Dict[str, Any] = field(default_factory=dict)
    live_promotion_blocker: str = "live_provider_scaffolded_but_disabled"
    no_customer_contact: bool = True
    no_live_send: bool = True
    no_external_effect: bool = True
    external_provider_called: bool = False
    real_message_sent: bool = False
    live_receipt_created: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_sandbox_receipt(action_id: str, idempotency_key: str, *, guard_summary: Mapping[str, Any] | None = None, idempotency_result: Mapping[str, Any] | None = None, suppression_result: Mapping[str, Any] | None = None, rate_limit_result: Mapping[str, Any] | None = None, compliance_result: Mapping[str, Any] | None = None, live_promotion_blocker: str = "live_provider_scaffolded_but_disabled") -> Dict[str, Any]:
    return SandboxReceipt(
        receipt_id=sandbox_receipt_id(action_id, idempotency_key),
        action_id=action_id,
        provider_mode="sandbox_ready",
        guard_summary=dict(guard_summary or {}),
        idempotency_result=dict(idempotency_result or {}),
        suppression_result=dict(suppression_result or {"decision": "allow"}),
        rate_limit_result=dict(rate_limit_result or {"decision": "allow"}),
        compliance_result=dict(compliance_result or {"decision": "allow"}),
        live_promotion_blocker=live_promotion_blocker,
    ).to_dict()


def validate_sandbox_receipt(receipt: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    if receipt.get("receipt_type") != "sandbox_receipt":
        errors.append("sandbox_receipt_type_required")
    if receipt.get("provider_mode") != "sandbox_ready":
        errors.append("sandbox_receipt_requires_sandbox_ready_mode")
    if receipt.get("live_receipt_created") is not False:
        errors.append("sandbox_receipt_cannot_create_live_receipt")
    if receipt.get("real_message_sent") is not False:
        errors.append("sandbox_receipt_cannot_mark_real_message_sent")
    if receipt.get("external_provider_called") is not False:
        errors.append("sandbox_receipt_cannot_call_external_provider")
    if receipt.get("no_external_effect") is not True:
        errors.append("sandbox_receipt_requires_no_external_effect")
    return errors
