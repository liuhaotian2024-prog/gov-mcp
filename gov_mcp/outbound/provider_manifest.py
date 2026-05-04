"""Provider capability manifest for outbound execution.

The default E21 manifest intentionally exposes no-send and dry-run capability,
plus a disabled live scaffold. It does not claim live provider readiness.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from gov_mcp.outbound.provider_capability import ProviderCapability, ProviderMode, capability_from_mapping


def build_provider_capability_manifest(
    *,
    provider_id: str = "disabled_live_outbound_provider",
    provider_mode: ProviderMode | str = ProviderMode.LIVE_DISABLED,
    provider_tests_passed: bool = True,
    supports_live: bool | None = None,
) -> Dict[str, Any]:
    mode = provider_mode.value if isinstance(provider_mode, ProviderMode) else str(provider_mode)
    live_enabled = mode == ProviderMode.LIVE_READY.value
    if supports_live is None:
        supports_live = live_enabled
    capability = ProviderCapability(
        provider_id=provider_id,
        provider_mode=mode,
        supports_no_send=True,
        supports_dry_run=True,
        supports_live=bool(supports_live),
        provider_tests_passed=provider_tests_passed,
        rate_limit_guard_present=True,
        idempotency_guard_present=True,
        suppression_guard_present=True,
        audit_receipt_enabled=True,
        rollback_reversal_path_present=False,
        credential_required_for_live=True,
        external_network_required_for_live=True,
        external_provider_called=False,
        real_message_sent=False,
    )
    data = capability.to_dict()
    data.update(
        {
            "artifact_id": "gov_mcp_outbound_provider_capability_manifest_v1",
            "canonical_owner_repo": "gov-mcp",
            "provider_modes": [item.value for item in ProviderMode],
            "no_send_available": data["supports_no_send"],
            "dry_run_available": data["supports_dry_run"],
            "live_scaffold_available": True,
            "live_provider_enabled": capability.live_ready(),
            "live_execution_blocked_reason": "live_provider_scaffolded_but_disabled" if not capability.live_ready() else "live_ready",
            "dry_run_receipt_type": "dry_run_receipt",
            "live_receipt_type": "live_execution_receipt",
            "dry_run_and_live_receipts_distinct": True,
            "no_external_api_call_in_e21": True,
        }
    )
    return data


def manifest_to_capability(manifest: Mapping[str, Any]) -> ProviderCapability:
    return capability_from_mapping(manifest)


def validate_provider_capability_manifest(manifest: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    if manifest.get("canonical_owner_repo") != "gov-mcp":
        errors.append("canonical_owner_repo_must_be_gov_mcp")
    if manifest.get("no_send_available") is not True:
        errors.append("no_send_must_remain_available")
    if manifest.get("dry_run_available") is not True:
        errors.append("dry_run_must_remain_available")
    if manifest.get("dry_run_and_live_receipts_distinct") is not True:
        errors.append("dry_run_live_receipts_must_be_distinct")
    if manifest.get("external_provider_called") is not False:
        errors.append("provider_call_must_not_occur_in_manifest")
    if manifest.get("real_message_sent") is not False:
        errors.append("real_message_sent_must_be_false")
    if manifest.get("provider_mode") == ProviderMode.LIVE_READY.value and manifest.get("live_provider_enabled") is not True:
        errors.append("live_ready_mode_requires_live_provider_enabled")
    if manifest.get("provider_mode") != ProviderMode.LIVE_READY.value and manifest.get("live_provider_enabled") is True:
        errors.append("non_live_ready_mode_cannot_enable_live_provider")
    return list(dict.fromkeys(errors))
