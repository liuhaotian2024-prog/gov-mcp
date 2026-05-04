"""Provider sandbox capability manifest."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping

from gov_mcp.outbound.provider_capability import ProviderMode
from gov_mcp.outbound.provider_manifest import build_provider_capability_manifest, validate_provider_capability_manifest
from gov_mcp.outbound.persistent_idempotency import build_persistent_idempotency_status


def build_sandbox_provider_manifest(*, sandbox_ready: bool = True, persistent_idempotency_ready: bool = False, kill_switch_active: bool = False) -> Dict[str, Any]:
    mode = ProviderMode.SANDBOX_READY if sandbox_ready else ProviderMode.SANDBOX_DISABLED
    manifest = build_provider_capability_manifest(provider_mode=mode, sandbox_tests_passed=sandbox_ready, supports_sandbox=True, supports_live=False)
    manifest.update({
        "artifact_id": "gov_mcp_outbound_sandbox_provider_manifest_v1",
        "sandbox_provider_mode": mode.value,
        "sandbox_scaffold_ready": sandbox_ready,
        "sandbox_native_provider_disabled": True,
        "deterministic_local_sandbox_harness": True,
        "external_api_calls_allowed": False,
        "kill_switch_active": kill_switch_active,
        "persistent_idempotency": build_persistent_idempotency_status(persistent_ready=persistent_idempotency_ready),
        "live_enabled": False,
        "live_blocked_reason": "live_provider_scaffolded_but_disabled",
    })
    return manifest


def validate_sandbox_provider_manifest(manifest: Mapping[str, Any]) -> List[str]:
    errors = validate_provider_capability_manifest(manifest)
    if manifest.get("sandbox_mode_available") is not True:
        errors.append("sandbox_mode_missing")
    if manifest.get("sandbox_provider_mode") not in {ProviderMode.SANDBOX_READY.value, ProviderMode.SANDBOX_DISABLED.value}:
        errors.append("invalid_sandbox_provider_mode")
    if manifest.get("external_api_calls_allowed") is not False:
        errors.append("sandbox_must_not_allow_external_api_calls")
    if manifest.get("live_enabled") is not False:
        errors.append("sandbox_manifest_cannot_enable_live")
    return list(dict.fromkeys(errors))
