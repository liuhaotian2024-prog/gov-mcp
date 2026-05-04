"""Provider capability models for governed outbound execution.

E21 introduces live-provider vocabulary without enabling any live provider. The
models are pure data contracts so provider readiness can be checked before any
external effect is possible.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, Mapping


class _StrEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class ProviderMode(_StrEnum):
    NO_SEND = "no_send"
    DRY_RUN = "dry_run"
    LIVE_DISABLED = "live_disabled"
    LIVE_READY = "live_ready"
    LIVE_BLOCKED = "live_blocked"


@dataclass(frozen=True)
class ProviderCapability:
    provider_id: str
    provider_mode: ProviderMode | str
    supports_no_send: bool
    supports_dry_run: bool
    supports_live: bool
    provider_tests_passed: bool
    rate_limit_guard_present: bool
    idempotency_guard_present: bool
    suppression_guard_present: bool
    audit_receipt_enabled: bool
    rollback_reversal_path_present: bool
    credential_required_for_live: bool = True
    external_network_required_for_live: bool = True
    external_provider_called: bool = False
    real_message_sent: bool = False

    def mode_value(self) -> str:
        return self.provider_mode.value if isinstance(self.provider_mode, Enum) else str(self.provider_mode)

    def live_ready(self) -> bool:
        return bool(
            self.mode_value() == ProviderMode.LIVE_READY.value
            and self.supports_live
            and self.provider_tests_passed
            and self.rate_limit_guard_present
            and self.idempotency_guard_present
            and self.suppression_guard_present
            and self.audit_receipt_enabled
        )

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["provider_mode"] = self.mode_value()
        data["live_ready"] = self.live_ready()
        return data


def capability_from_mapping(data: Mapping[str, Any]) -> ProviderCapability:
    return ProviderCapability(
        provider_id=str(data.get("provider_id", "disabled_live_outbound_provider")),
        provider_mode=data.get("provider_mode", ProviderMode.LIVE_DISABLED.value),
        supports_no_send=bool(data.get("supports_no_send", True)),
        supports_dry_run=bool(data.get("supports_dry_run", True)),
        supports_live=bool(data.get("supports_live", False)),
        provider_tests_passed=bool(data.get("provider_tests_passed", False)),
        rate_limit_guard_present=bool(data.get("rate_limit_guard_present", False)),
        idempotency_guard_present=bool(data.get("idempotency_guard_present", False)),
        suppression_guard_present=bool(data.get("suppression_guard_present", False)),
        audit_receipt_enabled=bool(data.get("audit_receipt_enabled", False)),
        rollback_reversal_path_present=bool(data.get("rollback_reversal_path_present", False)),
        credential_required_for_live=bool(data.get("credential_required_for_live", True)),
        external_network_required_for_live=bool(data.get("external_network_required_for_live", True)),
        external_provider_called=bool(data.get("external_provider_called", False)),
        real_message_sent=bool(data.get("real_message_sent", False)),
    )
