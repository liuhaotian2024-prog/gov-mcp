import sys
from pathlib import Path

Y_STAR_GOV = Path(__file__).resolve().parents[2] / "Y-star-gov"
if Y_STAR_GOV.exists():
    sys.path.insert(0, str(Y_STAR_GOV))

from gov_mcp.company_runtime_tools import (
    gov_company_action_preflight_impl,
    gov_company_escalation_check_impl,
    gov_company_mission_check_impl,
    gov_company_record_owner_decision_impl,
)


def test_action_preflight_allows_internal_work():
    result = gov_company_action_preflight_impl({"action": "internal analysis and strategy brief"})
    assert result["decision"] == "ALLOW_INTERNAL"
    assert result["external_action_executed"] is False


def test_action_preflight_requires_owner_approval_for_email():
    result = gov_company_action_preflight_impl({"action": "send email to customer"})
    assert result["decision"] == "NEEDS_OWNER_APPROVAL"
    assert result["external_action_executed"] is False


def test_action_preflight_blocks_payment():
    result = gov_company_action_preflight_impl({"action": "process payment"})
    assert result["decision"] == "BLOCKED"


def test_mission_check_reports_tier_and_budget():
    result = gov_company_mission_check_impl({"mission_id": "m1", "allowed_permission_tier": 1})
    assert result["permission_tier"] == 1
    assert result["missing_budget"] is True
    assert result["external_action_executed"] is False


def test_mission_aware_preflight_builds_escalation():
    result = gov_company_action_preflight_impl(
        {"action": "contact customer"},
        {"mission_id": "m2", "allowed_permission_tier": 2},
    )
    assert result["decision"] == "NEEDS_OWNER_APPROVAL"
    assert result["escalation"]["executes_action"] is False


def test_escalation_check_validates_packet():
    result = gov_company_escalation_check_impl(
        {
            "escalation_id": "e1",
            "requested_action": "manual customer discovery message",
            "action_class": "external_contact",
            "reason": "business validation",
            "risk_summary": "could contact a customer",
            "recommended_default": "hold until owner approves exact content",
        }
    )
    assert result["ok"] is True
    assert "approve" in result["approval_options"]


def test_record_owner_decision_is_local_envelope_only():
    result = gov_company_record_owner_decision_impl({"decision": "approve", "action_id": "a1"})
    assert result["ok"] is True
    assert result["persistent_db_write"] is False
    assert result["external_action_executed"] is False


def test_admin_report_not_mission_bound_returns_simplify_or_archive():
    result = gov_company_action_preflight_impl({"rule_type": "reporting_obligation", "rule": "daily report every night"})
    assert result["decision"] == "SIMPLIFY_OR_ARCHIVE"
    assert result["external_action_executed"] is False


def test_mission_check_flags_admin_burden():
    result = gov_company_mission_check_impl(
        {
            "mission_id": "m_admin",
            "allowed_permission_tier": 0,
            "admin_rules": [{"rule": "weekly report cadence"}],
        }
    )
    assert result["admin_burden_detected"] is True


def test_escalation_without_recommendation_fails_validation():
    result = gov_company_escalation_check_impl(
        {
            "escalation_id": "e_missing_recommendation",
            "requested_action": "manual customer discovery message",
            "action_class": "external_contact",
            "reason": "business validation",
            "risk_summary": "could contact a customer",
        }
    )
    assert result["ok"] is False
    assert "recommended_default" in result["missing_fields"]


def test_owner_decision_supports_request_more_evidence():
    result = gov_company_record_owner_decision_impl({"decision": "request_more_evidence", "action_id": "a2"})
    assert result["ok"] is True
    assert result["external_action_executed"] is False
