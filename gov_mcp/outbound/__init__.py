"""Canonical no-send outbound adapter surface for gov-mcp.

E16G intentionally exposes schemas, policy, guards, dry-run receipts, and
idempotency helpers only. It never calls an external provider.
"""

from gov_mcp.outbound.adapter_contract import (
    build_outbound_adapter_contract,
    validate_outbound_adapter_contract,
)
from gov_mcp.outbound.dry_run_adapter import dry_run_outbound_action
from gov_mcp.outbound.models import (
    OutboundActionIntent,
    OutboundAuthorizationState,
    OutboundCapabilityDomain,
    OutboundExecutionMode,
    OutboundRiskTier,
)
from gov_mcp.outbound.policy import evaluate_outbound_policy
from gov_mcp.outbound.safety_guards import evaluate_safety_guards

__all__ = [
    "OutboundActionIntent",
    "OutboundAuthorizationState",
    "OutboundCapabilityDomain",
    "OutboundExecutionMode",
    "OutboundRiskTier",
    "build_outbound_adapter_contract",
    "dry_run_outbound_action",
    "evaluate_outbound_policy",
    "evaluate_safety_guards",
    "validate_outbound_adapter_contract",
]
