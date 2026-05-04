"""Non-production live-test configuration profiles.

These profiles validate live-shaped prerequisites without enabling
production live execution or storing secret values.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping

from gov_mcp.outbound.live_config import CredentialSourceType


class LiveTestProfileKind(str, Enum):
    PRODUCTION_LIVE_CONFIG = "production_live_config"
    LIVE_TEST_CONFIG = "live_test_config"
    SANDBOX_CONFIG = "sandbox_config"
    DRY_RUN_CONFIG = "dry_run_config"


@dataclass(frozen=True)
class LiveTestConfigProfile:
    provider_name: str = "test_only_disabled_live_provider"
    channel: str = "email"
    profile_kind: str = LiveTestProfileKind.LIVE_TEST_CONFIG.value
    live_test_enabled: bool = True
    production_live_enabled: bool = False
    sandbox_enabled: bool = True
    dry_run_enabled: bool = True
    credential_source_type: str = CredentialSourceType.ENVIRONMENT_VARIABLE_NAMES_ONLY.value
    fake_credential_variable_names: List[str] = field(
        default_factory=lambda: ["TEST_ONLY_YSTAR_OUTBOUND_PROVIDER_API_KEY"]
    )
    credential_values_present: bool = False
    provider_endpoint_placeholder: str = "test://disabled-outbound-provider"
    temp_test_store_path: str = "/tmp/ystar_live_test_idempotency.json"
    quota_rate_limit_test_config: Dict[str, Any] = field(
        default_factory=lambda: {"max_live_test_actions_per_window": 1, "window": "live_test_gate"}
    )
    kill_switch_test_config: Dict[str, Any] = field(
        default_factory=lambda: {"global_live_disabled": False, "provider_live_disabled": False}
    )
    suppression_test_config: Dict[str, Any] = field(default_factory=lambda: {"integrated": True, "clear": True})
    compliance_test_config: Dict[str, Any] = field(default_factory=lambda: {"integrated": True, "clear": True})
    persistent_idempotency_test_config: Dict[str, Any] = field(
        default_factory=lambda: {"store_type": "file_backed_json_test_profile", "persistence_status": "live_test_persistent_ready"}
    )
    test_receipt_storage_config: Dict[str, Any] = field(default_factory=lambda: {"configured": True, "receipt_type": "live_test_receipt"})

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.update(
            {
                "artifact_id": "gov_mcp_live_test_config_profile_v1",
                "live_test_config_ready": True,
                "production_live_config_ready": False,
                "secrets_committed": False,
                "real_credentials_required": False,
                "external_effect_allowed": False,
            }
        )
        return data


def build_live_test_config_profile(**overrides: Any) -> Dict[str, Any]:
    return LiveTestConfigProfile(**overrides).to_dict()


def build_live_test_configuration_profiles() -> Dict[str, Any]:
    live_test = build_live_test_config_profile()
    return {
        "artifact_id": "gov_mcp_live_test_configuration_profiles_v1",
        "production_live_config": {
            "profile_kind": LiveTestProfileKind.PRODUCTION_LIVE_CONFIG.value,
            "production_live_enabled": False,
            "production_live_config_ready": False,
            "credential_values_present": False,
            "secrets_committed": False,
            "blocked_reasons": [
                "production_live_enabled_false",
                "production_credentials_absent_by_design",
                "production_persistent_idempotency_not_configured",
            ],
        },
        "live_test_config": live_test,
        "sandbox_config": {"profile_kind": LiveTestProfileKind.SANDBOX_CONFIG.value, "sandbox_enabled": True},
        "dry_run_config": {"profile_kind": LiveTestProfileKind.DRY_RUN_CONFIG.value, "dry_run_enabled": True},
    }


def validate_live_test_config_profile(config: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    if config.get("profile_kind") != LiveTestProfileKind.LIVE_TEST_CONFIG.value:
        errors.append("live_test_profile_kind_required")
    if config.get("live_test_enabled") is not True:
        errors.append("live_test_enabled_required")
    if config.get("production_live_enabled") is not False:
        errors.append("production_live_must_remain_disabled")
    if config.get("credential_values_present") is not False:
        errors.append("credential_values_must_not_be_present")
    if config.get("secrets_committed") is not False:
        errors.append("secrets_committed_must_be_false")
    names = list(config.get("fake_credential_variable_names", []))
    if not names:
        errors.append("fake_credential_variable_names_required")
    for name in names:
        text = str(name)
        if "=" in text or text.strip() != text or not text:
            errors.append("credential_names_only_no_values")
        if not text.startswith("TEST_ONLY_"):
            errors.append("live_test_credential_names_must_be_test_only")
    endpoint = str(config.get("provider_endpoint_placeholder", ""))
    if not endpoint.startswith("test://"):
        errors.append("provider_endpoint_must_be_test_placeholder")
    if not str(config.get("temp_test_store_path", "")).startswith("/tmp/"):
        errors.append("live_test_store_must_be_temp_scoped")
    if config.get("dry_run_enabled") is not True:
        errors.append("dry_run_must_remain_enabled")
    if config.get("sandbox_enabled") is not True:
        errors.append("sandbox_must_remain_enabled")
    return list(dict.fromkeys(errors))
