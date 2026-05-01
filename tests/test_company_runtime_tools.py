import sys
from pathlib import Path

Y_STAR_GOV = Path(__file__).resolve().parents[2] / "Y-star-gov"
if Y_STAR_GOV.exists():
    sys.path.insert(0, str(Y_STAR_GOV))

from gov_mcp.company_runtime_tools import (
    gov_company_action_preflight,
    gov_company_action_preflight_impl,
    gov_company_admin_rule_check,
    gov_company_escalation_check,
    gov_company_escalation_check_impl,
    gov_company_mission_check,
    gov_company_mission_check_impl,
    gov_company_record_owner_decision,
    gov_company_record_owner_decision_impl,
    gov_company_value_alignment_check,
    register_company_runtime_tools,
)


def test_action_preflight_allows_internal_work():
    result = gov_company_action_preflight_impl({"action": "internal analysis and strategy brief"})
    assert result["decision"] == "ALLOW_INTERNAL"
    assert result["external_action_executed"] is False


def test_public_action_preflight_import_works():
    result = gov_company_action_preflight({"action_type": "send_email"}, {})
    assert result["decision"] == "NEEDS_OWNER_APPROVAL"
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
            "recommended_default": "hold until owner selects exact recipient",
        }
    )
    assert result["ok"] is True
    assert "approve" in result["approval_options"]


def test_escalation_requires_recommendation_or_reason():
    result = gov_company_escalation_check(
        {
            "escalation_id": "e2",
            "requested_action": "manual customer discovery message",
            "action_class": "external_contact",
            "reason": "business validation",
            "risk_summary": "could contact a customer",
        }
    )
    assert result["ok"] is False
    assert "recommended_default" in result["missing_fields"]


def test_record_owner_decision_is_local_envelope_only():
    result = gov_company_record_owner_decision_impl({"decision": "approve", "action_id": "a1"})
    assert result["ok"] is True
    assert result["persistent_db_write"] is False
    assert result["external_action_executed"] is False


def test_admin_rule_check_returns_archive_for_old_daily_report():
    result = gov_company_admin_rule_check({"title": "daily report", "rule_text": "nightly report required"})
    assert result["decision"] == "ARCHIVE_LEGACY"
    assert result["external_action_executed"] is False


def test_value_alignment_check_prioritizes_m3_revenue_task():
    result = gov_company_value_alignment_check({"title": "first paid customer interview"})
    assert result["relevance"] == "HIGH"


def test_register_company_runtime_tools_registers_expected_names():
    class FakeMCP:
        def __init__(self):
            self.names = []

        def tool(self):
            def decorator(fn):
                self.names.append(fn.__name__)
                return fn

            return decorator

    fake = FakeMCP()
    register_company_runtime_tools(fake, state=None)
    assert {
        "gov_company_action_preflight",
        "gov_company_mission_check",
        "gov_company_escalation_check",
        "gov_company_record_owner_decision",
        "gov_company_admin_rule_check",
        "gov_company_value_alignment_check",
        "gov_company_mission_action_preflight",
    }.issubset(set(fake.names))


def test_public_wrappers_match_helper_behavior():
    assert gov_company_mission_check({"mission_id": "m1", "allowed_permission_tier": 1})["missing_budget"] is True
    assert gov_company_record_owner_decision({"decision": "hold"})["external_action_executed"] is False


def test_unavailable_ystar_domain_does_not_crash(monkeypatch):
    import gov_mcp.company_runtime_tools as tools

    monkeypatch.setattr(tools, "_COMPANY_RUNTIME_AVAILABLE", False)
    monkeypatch.setattr(tools, "_COMPANY_RUNTIME_IMPORT_ERROR", "test unavailable")
    result = tools.gov_company_action_preflight({"action": "send email"}, {})
    assert result["available"] is False
    assert result["external_action_executed"] is False
