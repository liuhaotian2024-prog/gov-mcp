"""One-action canary prerequisite matrix. Planning only; no execution."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping


def build_canary_prerequisite_matrix(
    *,
    selected_revenue_path: str,
    selected_action_candidate: str,
    kg_support_nodes_edges: List[str],
    target_evidence: List[str],
    message_content_reference: str,
    provider_category: str,
    channel: str,
    risk_tier: str,
    dry_run_history_present: bool,
    sandbox_history_present: bool,
    live_test_gate_result: Mapping[str, Any],
    production_persistent_ready: bool = False,
) -> Dict[str, Any]:
    owner_approval_required_by_risk = risk_tier.startswith("T4") or risk_tier.startswith("T5")
    production_live_ready = bool(live_test_gate_result.get("production_live_ready"))
    return {
        "artifact_id": "gov_mcp_canary_prerequisite_matrix_v1",
        "selected_revenue_path": selected_revenue_path,
        "selected_action_candidate": selected_action_candidate,
        "kg_support_nodes_edges": list(kg_support_nodes_edges),
        "target_evidence": list(target_evidence),
        "message_content_reference": message_content_reference,
        "provider_category": provider_category,
        "channel": channel,
        "risk_tier": risk_tier,
        "autonomous_eligibility": "eligible_after_production_live_readiness_passes",
        "owner_approval_required_by_risk": owner_approval_required_by_risk,
        "dry_run_history_present": dry_run_history_present,
        "sandbox_history_present": sandbox_history_present,
        "live_test_gate_ready": bool(live_test_gate_result.get("live_test_gate_ready")),
        "production_live_config_ready": production_live_ready,
        "production_live_enabled": False,
        "production_persistent_idempotency_ready": production_persistent_ready,
        "kill_switch_result": "production_blocked_default_safe",
        "suppression_compliance_result": "required_clear_before_live",
        "live_receipt_boundary_result": "production_live_receipt_count_zero_until_real_live_effect",
        "abort_criteria": [
            "production_live_enabled_false",
            "production_persistent_idempotency_not_configured",
            "kill_switch_active",
            "suppression_or_compliance_not_clear",
        ],
        "success_criteria": [
            "one production live action accepted by provider",
            "production live receipt written only after external effect",
            "feedback import wait-state opened",
        ],
        "feedback_import_path": "operations/external_validation/e18_batch_feedback_intake_empty.json",
        "ceo_kg_feedback_ingestion_path": "operations/knowledge_graph/e27_ceo_kg_live_test_feedback.json",
        "canary_matrix_created": True,
        "canary_executed": False,
        "production_live_receipt_count": 0,
        "real_customer_contact": False,
        "external_provider_called": False,
        "real_message_sent": False,
        "live_ready_action_count": 1 if production_live_ready else 0,
        "live_blocked_action_count": 0 if production_live_ready else 1,
        "primary_blockers": list(live_test_gate_result.get("production_live_blocked_reasons", [])),
    }


def validate_canary_prerequisite_matrix(matrix: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    if matrix.get("canary_matrix_created") is not True:
        errors.append("canary_matrix_must_be_created")
    if matrix.get("canary_executed") is not False:
        errors.append("canary_must_not_execute_in_e27")
    if matrix.get("production_live_enabled") is not False:
        errors.append("production_live_must_remain_disabled")
    if matrix.get("production_live_receipt_count") != 0:
        errors.append("production_live_receipt_count_must_remain_zero")
    if matrix.get("real_customer_contact") is not False:
        errors.append("real_customer_contact_must_be_false")
    if matrix.get("external_provider_called") is not False:
        errors.append("provider_api_call_must_not_occur")
    if matrix.get("real_message_sent") is not False:
        errors.append("real_message_sent_must_be_false")
    return errors
