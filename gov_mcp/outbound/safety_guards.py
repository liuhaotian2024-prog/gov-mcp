"""Deterministic outbound safety guards.

The evaluator is pure and local. It never calls a provider and never mutates
external state.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

from gov_mcp.outbound.models import (
    OutboundActionIntent,
    OutboundAuthorizationState,
    hard_gate_reason_codes,
    normalize_enum_value,
)


GUARD_NAMES = [
    "global_kill_switch",
    "batch_kill_switch",
    "target_suppression",
    "do_not_contact",
    "max_actions_per_day",
    "max_actions_per_target",
    "no_followup_without_positive_signal",
    "no_send_if_missing_target_identity",
    "no_send_if_message_unreviewed",
    "no_send_if_envelope_not_active",
    "no_send_if_hard_gate_detected",
    "no_send_if_owner_activation_missing",
    "no_send_if_idempotency_key_missing",
]


def default_guard_context() -> Dict[str, Any]:
    return {
        "global_kill_switch": False,
        "batch_kill_switch": False,
        "target_suppressed": False,
        "do_not_contact": False,
        "actions_today": 0,
        "max_actions_per_day": 1,
        "actions_for_target": 0,
        "max_actions_per_target": 1,
        "followup": False,
        "positive_signal_present": False,
    }


def evaluate_safety_guards(
    intent: OutboundActionIntent,
    context: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    ctx = {**default_guard_context(), **dict(context or {})}
    authorization_state = normalize_enum_value(intent.authorization_state)
    guard_results: Dict[str, str] = {}

    guard_results["global_kill_switch"] = "fail" if ctx["global_kill_switch"] else "pass"
    guard_results["batch_kill_switch"] = "fail" if ctx["batch_kill_switch"] else "pass"
    guard_results["target_suppression"] = "fail" if (ctx["target_suppressed"] or not intent.suppression_clear) else "pass"
    guard_results["do_not_contact"] = "fail" if ctx["do_not_contact"] else "pass"
    guard_results["max_actions_per_day"] = "fail" if int(ctx["actions_today"]) >= int(ctx["max_actions_per_day"]) else "pass"
    guard_results["max_actions_per_target"] = (
        "fail" if int(ctx["actions_for_target"]) >= int(ctx["max_actions_per_target"]) else "pass"
    )
    guard_results["no_followup_without_positive_signal"] = (
        "fail" if ctx["followup"] and not ctx["positive_signal_present"] else "pass"
    )
    guard_results["no_send_if_missing_target_identity"] = "pass" if intent.target_identity_sufficient and intent.target_id else "fail"
    guard_results["no_send_if_message_unreviewed"] = "pass" if intent.message_hash else "fail"
    guard_results["no_send_if_envelope_not_active"] = (
        "pass" if authorization_state == OutboundAuthorizationState.ACTIVATED.value else "fail"
    )
    guard_results["no_send_if_hard_gate_detected"] = "fail" if hard_gate_reason_codes(intent) else "pass"
    guard_results["no_send_if_owner_activation_missing"] = (
        "pass" if authorization_state == OutboundAuthorizationState.ACTIVATED.value else "fail"
    )
    guard_results["no_send_if_idempotency_key_missing"] = "pass" if intent.idempotency_key else "fail"

    failed = [name for name, status in guard_results.items() if status != "pass"]
    return {
        "guard_results": guard_results,
        "failed_guards": failed,
        "all_guards_passed_for_real_send": not failed,
        "external_action_executed": False,
        "provider_called": False,
        "real_message_sent": False,
    }


def safety_guard_matrix() -> Dict[str, Any]:
    return {
        "guard_names": GUARD_NAMES,
        "failure_effects": {
            "global_kill_switch": "deny_all",
            "batch_kill_switch": "deny_batch",
            "target_suppression": "suppress_target",
            "do_not_contact": "suppress_target_and_stop",
            "max_actions_per_day": "deny_rate_limit",
            "max_actions_per_target": "deny_duplicate_target_send",
            "no_followup_without_positive_signal": "deny_followup",
            "no_send_if_missing_target_identity": "require_more_research",
            "no_send_if_message_unreviewed": "draft_only",
            "no_send_if_envelope_not_active": "send_gated_pending_authorization",
            "no_send_if_hard_gate_detected": "owner_hard_gate",
            "no_send_if_owner_activation_missing": "send_gated_pending_authorization",
            "no_send_if_idempotency_key_missing": "deny_missing_idempotency_key",
        },
        "no_send_invariant": True,
    }
