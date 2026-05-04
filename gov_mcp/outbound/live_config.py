"""Live provider configuration contract with no secret values."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping


class CredentialSourceType(str, Enum):
    NONE = "none"
    ENVIRONMENT_VARIABLE_NAMES_ONLY = "environment_variable_names_only"
    LOCAL_ENV_FILE_PATH = "local_env_file_path"
    EXTERNAL_SECRET_MANAGER_PLACEHOLDER = "external_secret_manager_placeholder"


@dataclass(frozen=True)
class LiveProviderConfig:
    provider_name: str = "disabled_live_outbound_provider"
    channel: str = "email"
    live_enabled: bool = False
    sandbox_enabled: bool = True
    dry_run_enabled: bool = True
    credential_source_type: str = CredentialSourceType.NONE.value
    required_credential_variable_names: List[str] = field(default_factory=list)
    credential_values_present: bool = False
    quota_rate_limit_config: Dict[str, Any] = field(default_factory=lambda: {"max_live_actions_per_window": 0, "window": "disabled"})
    kill_switch_config: Dict[str, Any] = field(default_factory=lambda: {"global_live_disabled": True})
    suppression_registry_config: Dict[str, Any] = field(default_factory=lambda: {"required": True, "configured": False})
    compliance_registry_config: Dict[str, Any] = field(default_factory=lambda: {"required": True, "configured": False})
    persistent_idempotency_config: Dict[str, Any] = field(default_factory=lambda: {"required": True, "persistence_status": "persistent_disabled"})
    audit_receipt_storage_config: Dict[str, Any] = field(default_factory=lambda: {"required": True, "configured": False})
    live_receipt_boundary_config: Dict[str, Any] = field(default_factory=lambda: {"required": True, "configured": True})

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["artifact_id"] = "gov_mcp_live_provider_config_contract_v1"
        data["secrets_committed"] = False
        data["live_config_schema_ready"] = True
        return data


def build_live_provider_config(**overrides: Any) -> Dict[str, Any]:
    return LiveProviderConfig(**overrides).to_dict()


def validate_live_provider_config(config: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    if config.get("credential_values_present") is True:
        errors.append("credential_values_must_not_be_present")
    if config.get("secrets_committed") is not False:
        errors.append("secrets_committed_must_be_false")
    names = config.get("required_credential_variable_names", [])
    if any("=" in str(name) or str(name).strip() != str(name) or not str(name) for name in names):
        errors.append("credential_names_only_no_values")
    if config.get("live_enabled") is True and not names and config.get("credential_source_type") != CredentialSourceType.NONE.value:
        errors.append("live_enabled_requires_credential_names")
    if config.get("dry_run_enabled") is not True:
        errors.append("dry_run_must_remain_enabled")
    if config.get("sandbox_enabled") is not True:
        errors.append("sandbox_must_remain_enabled_for_canary_readiness")
    return list(dict.fromkeys(errors))
