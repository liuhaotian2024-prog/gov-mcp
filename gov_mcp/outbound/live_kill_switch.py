"""Fail-safe live kill switch evaluation."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping


@dataclass(frozen=True)
class LiveKillSwitch:
    global_live_disabled: bool = True
    provider_live_disabled: bool = True
    disabled_channels: List[str] = field(default_factory=list)
    disabled_campaigns: List[str] = field(default_factory=list)
    disabled_targets: List[str] = field(default_factory=list)
    disabled_actions: List[str] = field(default_factory=list)
    emergency_stop_reason: str = "live_execution_disabled_by_default"
    audit_czl_note: str = "Kill switch defaults safe for live execution."

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["artifact_id"] = "gov_mcp_live_kill_switch_v1"
        return data


def build_live_kill_switch(**overrides: Any) -> Dict[str, Any]:
    return LiveKillSwitch(**overrides).to_dict()


def evaluate_live_kill_switch(config: Mapping[str, Any], *, provider: str = "", channel: str = "", campaign: str = "", target_id: str = "", action_id: str = "") -> Dict[str, Any]:
    reasons: List[str] = []
    if config.get("global_live_disabled", True):
        reasons.append("global_live_disabled")
    if config.get("provider_live_disabled", True):
        reasons.append("provider_live_disabled")
    if channel and channel in config.get("disabled_channels", []):
        reasons.append("channel_live_disabled")
    if campaign and campaign in config.get("disabled_campaigns", []):
        reasons.append("campaign_live_disabled")
    if target_id and target_id in config.get("disabled_targets", []):
        reasons.append("target_live_disabled")
    if action_id and action_id in config.get("disabled_actions", []):
        reasons.append("action_live_disabled")
    return {
        "artifact_id": "gov_mcp_live_kill_switch_result_v1",
        "live_execution_allowed": not reasons,
        "kill_switch_clear": not reasons,
        "reason_codes": reasons or ["kill_switch_clear"],
        "audit_czl_note": config.get("audit_czl_note", "Kill switch evaluated."),
        "external_provider_called": False,
        "real_message_sent": False,
        "live_receipt_created": False,
    }
