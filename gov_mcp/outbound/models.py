"""Canonical outbound no-send models.

These models deliberately keep E16G provider-safe: they describe outbound
intent, policy decisions, receipts, and failure receipts without any provider
client or network call.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional


class _StrEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class OutboundCapabilityDomain(_StrEnum):
    EXTERNAL_VALIDATION_MESSAGE = "external_validation_message"
    FEEDBACK_CAPTURE = "feedback_capture"
    AUTHENTICATED_DRAFT_CREATION = "authenticated_draft_creation"
    PUBLICATION_DRAFT = "publication_draft"
    GOVERNED_PUBLICATION = "governed_publication"
    LOW_RISK_FORM_SUBMISSION = "low_risk_form_submission"
    PAYMENT_OR_CONTRACT_GATE = "payment_or_contract_gate"
    CORE_WRITEBACK_GATE = "core_writeback_gate"


class OutboundRiskTier(_StrEnum):
    TIER_0_INTERNAL = "TIER_0_INTERNAL"
    TIER_1_PUBLIC_READ_ONLY = "TIER_1_PUBLIC_READ_ONLY"
    TIER_2_TRANSPARENT_LOW_RISK_EXTERNAL_VALIDATION = "TIER_2_TRANSPARENT_LOW_RISK_EXTERNAL_VALIDATION"
    TIER_3_PUBLIC_BROADCAST_OR_LANDING = "TIER_3_PUBLIC_BROADCAST_OR_LANDING"
    TIER_4_COMMERCIAL_LEGAL_PRODUCTION_HIGH_RISK = "TIER_4_COMMERCIAL_LEGAL_PRODUCTION_HIGH_RISK"


class OutboundExecutionMode(_StrEnum):
    DENY = "deny"
    PREPARE_ONLY = "prepare_only"
    DRAFT_ONLY = "draft_only"
    OWNER_HANDOFF = "owner_handoff"
    DRY_RUN_LOCAL = "dry_run_local"
    SEND_GATED_PENDING_AUTHORIZATION = "send_gated_pending_authorization"
    SEND_GATED_DRY_RUN = "send_gated_dry_run"
    GOV_MCP_EXECUTE_AFTER_ACTIVATION = "gov_mcp_execute_after_activation"


class OutboundAuthorizationState(_StrEnum):
    OWNER_REVIEW_REQUIRED = "owner_review_required"
    ACTIVATION_PREFLIGHT_PASSED = "activation_preflight_passed"
    ACTIVATION_READY_BUT_NOT_APPROVED = "activation_ready_but_not_approved"
    ACTIVATED = "activated"
    REVOKED = "revoked"
    EXPIRED = "expired"
    BLOCKED_BY_SCOPE_MISMATCH = "blocked_by_scope_mismatch"
    BLOCKED_BY_HARD_GATE = "blocked_by_hard_gate"


HARD_GATE_ACTIONS = {
    "payment",
    "contract",
    "legal_obligation",
    "financial_commitment",
    "customer_system_access",
    "regulated_form_submission",
    "government_form_submission",
    "tax_form_submission",
    "immigration_form_submission",
    "identity_form_submission",
    "credential_disclosure",
    "core_brain_cieu_memory_writeback",
    "publication",
    "account_creation",
    "login",
    "form_submission",
}


@dataclass(frozen=True)
class OutboundActionIntent:
    action_id: str
    capability_domain: OutboundCapabilityDomain | str
    risk_tier: OutboundRiskTier | str
    execution_mode: OutboundExecutionMode | str
    authorization_state: OutboundAuthorizationState | str
    target_id: str
    target_identity_sufficient: bool
    message_hash: str
    idempotency_key: str
    ai_transparency_present: bool
    opt_out_language_present: bool
    suppression_clear: bool
    rate_limit_clear: bool
    hard_gates_absent: bool
    requested_action: str = "external_validation_message"
    channel: str = "owner_approved_validation_message"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        for key in ["capability_domain", "risk_tier", "execution_mode", "authorization_state"]:
            value = data[key]
            if isinstance(value, Enum):
                data[key] = value.value
        return data


@dataclass(frozen=True)
class OutboundPreflightResult:
    action_id: str
    decision: str
    execution_mode: str
    authorization_state: str
    allowed_for_real_send: bool
    allowed_for_dry_run: bool
    reason_codes: List[str]
    guard_results: Dict[str, str]
    external_action_executed: bool = False
    provider_called: bool = False
    real_message_sent: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OutboundExecutionReceipt:
    receipt_id: str
    action_id: str
    execution_mode: str
    preflight_result: Dict[str, Any]
    guard_results: Dict[str, str]
    execution_status: str
    external_action_executed: bool
    provider_called: bool
    real_message_sent: bool
    ledger_transition: str
    feedback_wait_state: str
    reason_codes: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OutboundFailureReceipt:
    receipt_id: str
    action_id: str
    failure_code: str
    execution_mode: str
    reason_codes: List[str]
    external_action_executed: bool = False
    provider_called: bool = False
    real_message_sent: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def normalize_enum_value(value: Any) -> str:
    return value.value if isinstance(value, Enum) else str(value)


def intent_from_mapping(data: Mapping[str, Any]) -> OutboundActionIntent:
    return OutboundActionIntent(
        action_id=str(data.get("action_id", "")),
        capability_domain=data.get("capability_domain", OutboundCapabilityDomain.EXTERNAL_VALIDATION_MESSAGE),
        risk_tier=data.get("risk_tier", OutboundRiskTier.TIER_2_TRANSPARENT_LOW_RISK_EXTERNAL_VALIDATION),
        execution_mode=data.get("execution_mode", OutboundExecutionMode.SEND_GATED_DRY_RUN),
        authorization_state=data.get("authorization_state", OutboundAuthorizationState.OWNER_REVIEW_REQUIRED),
        target_id=str(data.get("target_id", "")),
        target_identity_sufficient=bool(data.get("target_identity_sufficient", False)),
        message_hash=str(data.get("message_hash", "")),
        idempotency_key=str(data.get("idempotency_key", "")),
        ai_transparency_present=bool(data.get("ai_transparency_present", False)),
        opt_out_language_present=bool(data.get("opt_out_language_present", False)),
        suppression_clear=bool(data.get("suppression_clear", False)),
        rate_limit_clear=bool(data.get("rate_limit_clear", False)),
        hard_gates_absent=bool(data.get("hard_gates_absent", False)),
        requested_action=str(data.get("requested_action", "external_validation_message")),
        channel=str(data.get("channel", "owner_approved_validation_message")),
        metadata=dict(data.get("metadata", {})),
    )


def hard_gate_reason_codes(intent: OutboundActionIntent) -> List[str]:
    reasons: List[str] = []
    if intent.requested_action in HARD_GATE_ACTIONS:
        reasons.append(f"hard_gate_requested_action_{intent.requested_action}")
    if not intent.hard_gates_absent:
        reasons.append("hard_gate_detected")
    if normalize_enum_value(intent.capability_domain) in {
        OutboundCapabilityDomain.PAYMENT_OR_CONTRACT_GATE.value,
        OutboundCapabilityDomain.CORE_WRITEBACK_GATE.value,
        OutboundCapabilityDomain.GOVERNED_PUBLICATION.value,
        OutboundCapabilityDomain.LOW_RISK_FORM_SUBMISSION.value,
    }:
        reasons.append(f"hard_gate_capability_domain_{normalize_enum_value(intent.capability_domain)}")
    return reasons


def execution_mode_aliases() -> Dict[str, str]:
    return {"mcp_execute_after_activation": OutboundExecutionMode.GOV_MCP_EXECUTE_AFTER_ACTIVATION.value}


def canonical_execution_mode(value: str) -> str:
    return execution_mode_aliases().get(value, value)
