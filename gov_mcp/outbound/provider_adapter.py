"""Provider adapter boundary for outbound execution.

The disabled-live adapter is a scaffold, not a provider client. It never opens a
network connection, never asks for credentials, and never creates a live send
receipt.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping

from gov_mcp.outbound.dry_run_adapter import dry_run_outbound_action
from gov_mcp.outbound.models import OutboundActionIntent, intent_from_mapping
from gov_mcp.outbound.provider_capability import ProviderMode
from gov_mcp.outbound.provider_manifest import build_provider_capability_manifest


@dataclass(frozen=True)
class ProviderExecutionRequest:
    action_intent: OutboundActionIntent
    provider_mode: ProviderMode | str = ProviderMode.LIVE_DISABLED
    provider_id: str = "disabled_live_outbound_provider"
    promotion_contract_passed: bool = False
    dry_run_receipt: Dict[str, Any] = field(default_factory=dict)
    owner_approval_present: bool = False
    evidence_sufficient: bool = True
    message_safety_passed: bool = True
    quota_available: bool = True
    idempotency_clear: bool = True
    suppression_clear: bool = True

    def mode_value(self) -> str:
        return self.provider_mode.value if isinstance(self.provider_mode, ProviderMode) else str(self.provider_mode)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["action_intent"] = self.action_intent.to_dict()
        data["provider_mode"] = self.mode_value()
        return data


@dataclass(frozen=True)
class ProviderExecutionResult:
    result_id: str
    action_id: str
    provider_mode: str
    execution_status: str
    receipt_type: str
    reason_codes: List[str]
    receipt: Dict[str, Any]
    external_provider_called: bool = False
    real_message_sent: bool = False
    live_receipt_created: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def provider_result_id(action_id: str, status: str) -> str:
    digest = hashlib.sha256(f"{action_id}:{status}".encode("utf-8")).hexdigest()[:16]
    return f"provider_result_{digest}"


def request_from_mapping(data: Mapping[str, Any]) -> ProviderExecutionRequest:
    intent_data = data.get("action_intent", data)
    return ProviderExecutionRequest(
        action_intent=intent_from_mapping(intent_data),
        provider_mode=data.get("provider_mode", ProviderMode.LIVE_DISABLED.value),
        provider_id=str(data.get("provider_id", "disabled_live_outbound_provider")),
        promotion_contract_passed=bool(data.get("promotion_contract_passed", False)),
        dry_run_receipt=dict(data.get("dry_run_receipt", {})),
        owner_approval_present=bool(data.get("owner_approval_present", False)),
        evidence_sufficient=bool(data.get("evidence_sufficient", True)),
        message_safety_passed=bool(data.get("message_safety_passed", True)),
        quota_available=bool(data.get("quota_available", True)),
        idempotency_clear=bool(data.get("idempotency_clear", True)),
        suppression_clear=bool(data.get("suppression_clear", True)),
    )


class DryRunProviderSimulator:
    provider_mode = ProviderMode.DRY_RUN.value

    def execute(self, request: ProviderExecutionRequest | Mapping[str, Any]) -> ProviderExecutionResult:
        req = request if isinstance(request, ProviderExecutionRequest) else request_from_mapping(request)
        receipt = dry_run_outbound_action(req.action_intent)
        return ProviderExecutionResult(
            result_id=provider_result_id(req.action_intent.action_id, "dry_run_completed"),
            action_id=req.action_intent.action_id,
            provider_mode=self.provider_mode,
            execution_status="dry_run_completed" if receipt.get("execution_mode") != "deny" else "dry_run_denied",
            receipt_type="dry_run_receipt",
            reason_codes=list(receipt.get("reason_codes", [])),
            receipt=receipt,
            external_provider_called=False,
            real_message_sent=False,
            live_receipt_created=False,
        )


class DisabledLiveProviderAdapter:
    provider_mode = ProviderMode.LIVE_DISABLED.value

    def capability_manifest(self) -> Dict[str, Any]:
        return build_provider_capability_manifest(provider_mode=ProviderMode.LIVE_DISABLED)

    def execute(self, request: ProviderExecutionRequest | Mapping[str, Any]) -> ProviderExecutionResult:
        req = request if isinstance(request, ProviderExecutionRequest) else request_from_mapping(request)
        return ProviderExecutionResult(
            result_id=provider_result_id(req.action_intent.action_id, "live_blocked"),
            action_id=req.action_intent.action_id,
            provider_mode=self.provider_mode,
            execution_status="blocked",
            receipt_type="blocked_no_live_receipt",
            reason_codes=["live_provider_disabled", "external_provider_not_called", "live_receipt_not_created"],
            receipt={
                "receipt_type": "blocked_no_live_receipt",
                "action_id": req.action_intent.action_id,
                "external_provider_called": False,
                "real_message_sent": False,
                "live_receipt_created": False,
            },
            external_provider_called=False,
            real_message_sent=False,
            live_receipt_created=False,
        )


def validate_provider_execution_result(result: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    if result.get("external_provider_called") is not False:
        errors.append("external_provider_called_must_be_false_for_e21_scaffold")
    if result.get("real_message_sent") is not False:
        errors.append("real_message_sent_must_be_false_for_e21_scaffold")
    if result.get("receipt_type") == "dry_run_receipt" and result.get("live_receipt_created") is True:
        errors.append("dry_run_receipt_cannot_be_live_receipt")
    if result.get("receipt_type") == "live_execution_receipt" and result.get("provider_mode") != ProviderMode.LIVE_READY.value:
        errors.append("live_receipt_requires_live_ready_provider")
    return errors
