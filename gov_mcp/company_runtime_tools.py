"""Company runtime governance MCP tools.

These tools classify and preflight company-operation actions. They never execute
external actions and never write CIEU/core DB state.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict

from ystar.domains.company_runtime import (
    EscalationContract,
    build_escalation_decision,
    classify_company_action,
    mission_permission_check,
)
from ystar.domains.company_runtime.delegated_mission_contract import DelegatedMissionContract
from ystar.domains.company_runtime.permission_tiers import TIER_REGISTRY, get_permission_tier


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def gov_company_action_preflight_impl(action_dict: Dict[str, Any], mission_dict: Dict[str, Any] | None = None) -> Dict[str, Any]:
    mission_dict = mission_dict or {}
    if mission_dict:
        result = mission_permission_check(mission_dict, action_dict)
    else:
        result = classify_company_action(action_dict)
        result["executes_action"] = False
    result["tool"] = "gov_company_action_preflight"
    result["external_action_executed"] = False
    return result


def gov_company_mission_check_impl(mission_dict: Dict[str, Any]) -> Dict[str, Any]:
    mission = DelegatedMissionContract.from_dict(mission_dict)
    tier = get_permission_tier(mission.allowed_permission_tier)
    missing_budget = tier.requires_budget and not mission.research_budget
    return {
        "tool": "gov_company_mission_check",
        "mission_id": mission.mission_id,
        "permission_tier": tier.tier_id,
        "tier_name": tier.tier_name,
        "missing_budget": missing_budget,
        "forbidden_actions": mission.forbidden_action_classes,
        "recommended_escalation_points": list(tier.escalation_required_for) + list(mission.required_review_points),
        "external_action_executed": False,
    }


def gov_company_escalation_check_impl(escalation_dict: Dict[str, Any]) -> Dict[str, Any]:
    escalation = EscalationContract.from_dict(escalation_dict)
    result = escalation.validate()
    result.update(
        {
            "tool": "gov_company_escalation_check",
            "escalation_id": escalation.escalation_id,
            "approval_options": escalation.approval_options,
            "external_action_executed": False,
        }
    )
    return result


def gov_company_record_owner_decision_impl(decision_dict: Dict[str, Any]) -> Dict[str, Any]:
    decision = str(decision_dict.get("decision") or "").strip()
    allowed = {"approve", "reject", "request_revision", "hold"}
    ok = decision in allowed
    return {
        "tool": "gov_company_record_owner_decision",
        "ok": ok,
        "decision_id": decision_dict.get("decision_id") or f"owner_decision_{_now()}",
        "decision": decision,
        "allowed_decisions": sorted(allowed),
        "normalized_decision": {
            "action_id": decision_dict.get("action_id"),
            "mission_id": decision_dict.get("mission_id"),
            "decided_by": decision_dict.get("decided_by") or "owner",
            "decision_note": decision_dict.get("decision_note") or "",
            "created_at": _now(),
        },
        "persistent_db_write": False,
        "external_action_executed": False,
    }


def register_company_runtime_tools(mcp: Any, state: Any) -> None:
    @mcp.tool()
    def gov_company_action_preflight(action_dict: dict, mission_dict: dict | None = None) -> str:
        """Classify a company action without executing it."""
        return json.dumps(gov_company_action_preflight_impl(action_dict, mission_dict), ensure_ascii=False, indent=2)

    @mcp.tool()
    def gov_company_mission_check(mission_dict: dict) -> str:
        """Check a delegated company mission's permission tier and budget envelope."""
        return json.dumps(gov_company_mission_check_impl(mission_dict), ensure_ascii=False, indent=2)

    @mcp.tool()
    def gov_company_escalation_check(escalation_dict: dict) -> str:
        """Validate a company escalation packet before owner review."""
        return json.dumps(gov_company_escalation_check_impl(escalation_dict), ensure_ascii=False, indent=2)

    @mcp.tool()
    def gov_company_record_owner_decision(decision_dict: dict) -> str:
        """Normalize an owner decision envelope without executing the approved action."""
        return json.dumps(gov_company_record_owner_decision_impl(decision_dict), ensure_ascii=False, indent=2)
