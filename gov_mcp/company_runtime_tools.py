"""Company runtime governance MCP tools.

These tools classify and preflight company-operation actions. They never execute
external actions and never write CIEU/core DB state.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict

try:  # pragma: no cover - negative path is exercised by monkeypatch tests.
    from ystar.domains.company_runtime import (
        EscalationContract,
        classify_admin_rule,
        classify_company_action,
        mission_action_preflight,
        mission_permission_check,
        value_production_relevance,
    )
    from ystar.domains.company_runtime.delegated_mission_contract import DelegatedMissionContract
    from ystar.domains.company_runtime.permission_tiers import get_permission_tier

    _COMPANY_RUNTIME_AVAILABLE = True
    _COMPANY_RUNTIME_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover
    EscalationContract = None  # type: ignore[assignment]
    DelegatedMissionContract = None  # type: ignore[assignment]
    classify_admin_rule = None  # type: ignore[assignment]
    classify_company_action = None  # type: ignore[assignment]
    mission_action_preflight = None  # type: ignore[assignment]
    mission_permission_check = None  # type: ignore[assignment]
    value_production_relevance = None  # type: ignore[assignment]
    get_permission_tier = None  # type: ignore[assignment]
    _COMPANY_RUNTIME_AVAILABLE = False
    _COMPANY_RUNTIME_IMPORT_ERROR = str(exc)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _unavailable(tool: str) -> Dict[str, Any]:
    return {
        "tool": tool,
        "available": False,
        "error": f"ystar company_runtime unavailable: {_COMPANY_RUNTIME_IMPORT_ERROR or 'unknown import failure'}",
        "external_action_executed": False,
        "persistent_db_write": False,
    }


def _normal_action_dict(action_dict: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(action_dict or {})
    if "action" not in normalized and "action_type" in normalized:
        normalized["action"] = str(normalized["action_type"]).replace("_", " ")
    if "action" not in normalized and "title" in normalized:
        normalized["action"] = normalized["title"]
    return normalized


def gov_company_action_preflight(action_dict: Dict[str, Any], mission_dict: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if not _COMPANY_RUNTIME_AVAILABLE:
        return _unavailable("gov_company_action_preflight")
    action_dict = _normal_action_dict(action_dict)
    mission_dict = mission_dict or {}
    if mission_dict:
        result = mission_permission_check(mission_dict, action_dict)  # type: ignore[misc]
    else:
        result = classify_company_action(action_dict)  # type: ignore[misc]
        result["executes_action"] = False
    result["tool"] = "gov_company_action_preflight"
    result["available"] = True
    result["external_action_executed"] = False
    return result


def gov_company_mission_check(mission_dict: Dict[str, Any]) -> Dict[str, Any]:
    if not _COMPANY_RUNTIME_AVAILABLE:
        return _unavailable("gov_company_mission_check")
    mission = DelegatedMissionContract.from_dict(mission_dict)  # type: ignore[union-attr]
    tier = get_permission_tier(mission.allowed_permission_tier)  # type: ignore[misc]
    missing_budget = tier.requires_budget and not mission.research_budget
    forbidden_actions = list(mission.forbidden_action_classes)
    if missing_budget:
        forbidden_actions.append("read_only_research_without_budget")
    return {
        "tool": "gov_company_mission_check",
        "available": True,
        "mission_id": mission.mission_id,
        "permission_tier": tier.tier_id,
        "tier_name": tier.tier_name,
        "missing_budget": missing_budget,
        "missing_budget_fields": ["research_budget"] if missing_budget else [],
        "forbidden_actions": forbidden_actions,
        "recommended_escalation_points": list(tier.escalation_required_for) + list(mission.required_review_points),
        "status": "needs_budget" if missing_budget else "ok",
        "external_action_executed": False,
    }


def gov_company_escalation_check(escalation_dict: Dict[str, Any]) -> Dict[str, Any]:
    if not _COMPANY_RUNTIME_AVAILABLE:
        return _unavailable("gov_company_escalation_check")
    escalation = EscalationContract.from_dict(escalation_dict)  # type: ignore[union-attr]
    result = escalation.validate()
    if not (escalation_dict.get("recommended_default") or escalation_dict.get("recommendation")):
        result["ok"] = False
        result.setdefault("missing_fields", []).append("recommended_default")
    result.update(
        {
            "tool": "gov_company_escalation_check",
            "available": True,
            "escalation_id": escalation.escalation_id,
            "approval_options": escalation.approval_options,
            "execution_allowed": False,
            "external_action_executed": False,
        }
    )
    return result


def gov_company_record_owner_decision(decision_dict: Dict[str, Any]) -> Dict[str, Any]:
    decision = str(decision_dict.get("decision") or "").strip()
    allowed = {"approve", "reject", "request_revision", "hold"}
    ok = decision in allowed
    return {
        "tool": "gov_company_record_owner_decision",
        "available": _COMPANY_RUNTIME_AVAILABLE,
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


def gov_company_admin_rule_check(rule_dict: Dict[str, Any]) -> Dict[str, Any]:
    if not _COMPANY_RUNTIME_AVAILABLE:
        return _unavailable("gov_company_admin_rule_check")
    result = classify_admin_rule(rule_dict)  # type: ignore[misc]
    result.update(
        {
            "tool": "gov_company_admin_rule_check",
            "available": True,
            "external_action_executed": False,
        }
    )
    return result


def gov_company_value_alignment_check(item_dict: Dict[str, Any]) -> Dict[str, Any]:
    if not _COMPANY_RUNTIME_AVAILABLE:
        return _unavailable("gov_company_value_alignment_check")
    result = value_production_relevance(item_dict)  # type: ignore[misc]
    result.update(
        {
            "tool": "gov_company_value_alignment_check",
            "available": True,
            "external_action_executed": False,
        }
    )
    return result


def gov_company_mission_action_preflight(action_dict: Dict[str, Any], mission_dict: Dict[str, Any]) -> Dict[str, Any]:
    if not _COMPANY_RUNTIME_AVAILABLE:
        return _unavailable("gov_company_mission_action_preflight")
    result = mission_action_preflight(mission_dict, _normal_action_dict(action_dict))  # type: ignore[misc]
    result.update(
        {
            "tool": "gov_company_mission_action_preflight",
            "available": True,
            "external_action_executed": False,
        }
    )
    return result


# Backward-compatible helper names from the first backflow patch.
gov_company_action_preflight_impl = gov_company_action_preflight
gov_company_mission_check_impl = gov_company_mission_check
gov_company_escalation_check_impl = gov_company_escalation_check
gov_company_record_owner_decision_impl = gov_company_record_owner_decision


def register_company_runtime_tools(mcp: Any, state: Any) -> None:
    action_preflight = globals()["gov_company_action_preflight"]
    mission_check = globals()["gov_company_mission_check"]
    escalation_check = globals()["gov_company_escalation_check"]
    record_owner_decision = globals()["gov_company_record_owner_decision"]
    admin_rule_check = globals()["gov_company_admin_rule_check"]
    value_alignment_check = globals()["gov_company_value_alignment_check"]
    mission_action_preflight = globals()["gov_company_mission_action_preflight"]

    @mcp.tool()
    def gov_company_action_preflight(action_dict: dict, mission_dict: dict | None = None) -> str:
        """Classify a company action without executing it."""
        return json.dumps(action_preflight(action_dict, mission_dict), ensure_ascii=False, indent=2)

    @mcp.tool()
    def gov_company_mission_check(mission_dict: dict) -> str:
        """Check a delegated company mission's permission tier and budget envelope."""
        return json.dumps(mission_check(mission_dict), ensure_ascii=False, indent=2)

    @mcp.tool()
    def gov_company_escalation_check(escalation_dict: dict) -> str:
        """Validate a company escalation packet before owner review."""
        return json.dumps(escalation_check(escalation_dict), ensure_ascii=False, indent=2)

    @mcp.tool()
    def gov_company_record_owner_decision(decision_dict: dict) -> str:
        """Normalize an owner decision envelope without executing the approved action."""
        return json.dumps(record_owner_decision(decision_dict), ensure_ascii=False, indent=2)

    @mcp.tool()
    def gov_company_admin_rule_check(rule_dict: dict) -> str:
        """Classify administrative rules without activating old ceremony."""
        return json.dumps(admin_rule_check(rule_dict), ensure_ascii=False, indent=2)

    @mcp.tool()
    def gov_company_value_alignment_check(item_dict: dict) -> str:
        """Check whether a company item advances M-3 value production."""
        return json.dumps(value_alignment_check(item_dict), ensure_ascii=False, indent=2)

    @mcp.tool()
    def gov_company_mission_action_preflight(action_dict: dict, mission_dict: dict) -> str:
        """Combine permission, admin burden, and value alignment preflight."""
        return json.dumps(mission_action_preflight(action_dict, mission_dict), ensure_ascii=False, indent=2)
