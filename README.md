# gov-mcp

gov-mcp is the provider/tool execution boundary for the Y* agent-company
runtime. It exposes MCP tools, governance checks, company runtime tools,
outbound policy, provider guard stacks, dry-run adapters, and receipts.

It is not the CEO behavior center and it is not the canonical governance
kernel. bridge-labs produces CEO/company actions. Y-star-gov validates those
actions. gov-mcp carries approved or scoped actions to the provider/tool
boundary, with dry-run/no-send behavior by default.

## Current role in the system

| Repository | Canonical role |
| --- | --- |
| `gov-mcp` | Provider/tool execution boundary, MCP tools, outbound policy, dry-run adapter, provider guard stack, receipts. |
| `Y-star-gov` | Governance reflex center, deterministic runtime validation, CIEUStore formal records. |
| `ystar-bridge-labs` | CEO/company behavior center, mission command, owner decisions, pre-action packets, post-action residuals. |
| `K9Audit` | Separate stronger evidence-chain ledger. It is not a default gov-mcp write path. |

## What is implemented

### MCP server and tool registration

Core entry points include:

- `gov_mcp/server.py`
- `gov_mcp/company_runtime_tools.py`
- `gov_mcp/__main__.py`

The server exposes governance and company-runtime tools for MCP-compatible
clients.

### Governance check and enforce boundary

gov-mcp provides governance-facing tools such as `gov_check`, `gov_enforce`,
`gov_report`, `gov_verify`, `gov_doctor`, and related runtime helpers. These
tools are intended to sit at the action boundary, not to replace the
Y-star-gov kernel.

### Outbound dry-run and no-send safety

The outbound path is intentionally no-send by default.

Key modules:

- `gov_mcp/outbound/policy.py`
- `gov_mcp/outbound/dry_run_adapter.py`
- `gov_mcp/outbound/provider_guard_stack.py`
- `gov_mcp/outbound/receipts.py`
- `gov_mcp/outbound/models.py`

The dry-run adapter returns receipts with:

- `provider_action_executed: false`
- `external_side_effect: false`
- `external_provider_called: false`
- `no_send_invariant: true`
- `send_blocked_until_owner_activation: true`

This allows bridge-labs and Y-star-gov to prove the provider/tool boundary
without sending messages, publishing content, calling live provider APIs, or
using credentials.

## Runtime chain with the other repositories

The current integrated internal chain is:

```text
bridge-labs CEO major action
-> Y-star-gov runtime governance decision
-> if ALLOW and provider/tool-bound: gov-mcp dry-run envelope only
-> gov-mcp no-send receipt
-> bridge-labs post-action residual
-> Y-star-gov CIEUStore record
```

gov-mcp does not decide the CEO action on its own. It consumes the governance
decision and preserves the execution boundary.

## What this repository does not claim

gov-mcp does not currently claim:

- live provider execution by default;
- customer outreach;
- publication;
- payment or revenue execution;
- customer validation;
- paid signal;
- pricing validation;
- legal or compliance proof;
- production deployment;
- completion of the full L5 revenue/customer/payment loop.

## Quick start

Install:

```bash
pip install gov-mcp
```

Start or inspect the local server:

```bash
python -m gov_mcp --help
python -m gov_mcp status
```

Use dry-run outbound behavior for safe local proof:

```python
from gov_mcp.outbound.dry_run_adapter import dry_run_outbound_action

receipt = dry_run_outbound_action({
    "action_id": "demo_dry_run",
    "capability_domain": "external_validation_message",
    "risk_tier": "TIER_2_TRANSPARENT_LOW_RISK_EXTERNAL_VALIDATION",
    "execution_mode": "send_gated_dry_run",
    "authorization_state": "owner_review_required",
    "target_id": "dry_run_target",
    "target_identity_sufficient": True,
    "message_hash": "sha256:demo",
    "idempotency_key": "demo_dry_run:1",
    "ai_transparency_present": True,
    "opt_out_language_present": True,
    "suppression_clear": True,
    "rate_limit_clear": True,
    "hard_gates_absent": True,
})

assert receipt["external_provider_called"] is False
assert receipt["no_send_invariant"] is True
```

## Targeted validation commands

Useful checks:

```bash
python3 -m py_compile gov_mcp/outbound/dry_run_adapter.py
pytest -q tests/test_outbound_dry_run_adapter.py
pytest -q tests/test_company_runtime_tools.py
```

Use the narrowest relevant test for the module being changed. Do not enable live
provider execution in routine tests.

## Next engineering direction

The next gov-mcp-facing work should add owner-activated live-ready preflight
while keeping provider calls disabled by default. A future live-ready path must
prove owner activation, idempotency, suppression checks, rate limiting,
AI-transparency checks, opt-out language checks, receipt integrity, and no-send
behavior before any real provider execution is considered.
