"""One-action live canary plan contract. Planning only; no execution."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping


def build_one_action_live_canary_plan(
    *,
    selected_revenue_path: str,
    action_id: str,
    channel: str,
    provider_category: str,
    risk_tier: str,
    kg_support: List[str],
    message_reference: str,
    target_evidence: List[str],
) -> Dict[str, Any]:
    return {
        "artifact_id": "gov_mcp_one_action_live_canary_plan_v1",
        "selected_revenue_path": selected_revenue_path,
        "selected_action_candidate": action_id,
        "kg_support_nodes_edges": kg_support,
        "target_evidence": target_evidence,
        "message_content_reference": message_reference,
        "channel": channel,
        "provider_category": provider_category,
        "risk_tier": risk_tier,
        "autonomous_eligibility": "eligible_in_principle_after_live_readiness_passes",
        "owner_approval_required_by_risk": risk_tier.startswith("T4") or risk_tier.startswith("T5"),
        "required_live_config": "gov_mcp_live_provider_config_contract_v1",
        "required_credential_source_names_only": ["YSTAR_OUTBOUND_PROVIDER_API_KEY"],
        "persistent_idempotency_requirement": "persistent_ready",
        "rate_limit": {"max_live_actions": 1, "window": "canary"},
        "suppression_check": "required_clear",
        "compliance_check": "required_clear",
        "kill_switch": "required_clear",
        "live_receipt_path": "live_receipt_writer_ready_required_before_execution",
        "rollback_reversal_policy": "record suppression/stop future followup; provider-level reversal only if provider supports it",
        "abort_criteria": ["kill_switch_active", "suppression_not_clear", "compliance_not_clear", "provider_live_not_ready", "persistent_idempotency_not_ready"],
        "success_criteria": ["provider accepted one live action", "live receipt written", "feedback import wait-state opened"],
        "failure_criteria": ["provider error", "rate limit exceeded", "bounce/suppression signal"],
        "post_canary_feedback_import_path": "operations/external_validation/e18_batch_feedback_intake_empty.json",
        "ceo_kg_feedback_ingestion_path": "operations/knowledge_graph/e26_ceo_kg_live_readiness_feedback.json",
        "canary_executed": False,
        "live_disabled_unless_validator_passes": True,
        "customer_contacted": False,
        "live_receipt_created": False,
    }


def validate_canary_plan(plan: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    if plan.get("canary_executed") is not False:
        errors.append("canary_must_not_execute_in_plan")
    if plan.get("customer_contacted") is not False:
        errors.append("canary_plan_cannot_contact_customer")
    if plan.get("live_receipt_created") is not False:
        errors.append("canary_plan_cannot_create_live_receipt")
    if not plan.get("required_credential_source_names_only"):
        errors.append("credential_source_names_required_without_values")
    return errors
