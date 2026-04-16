# Gov-MCP Anthropic Desktop Extension Package

## Day 1 Status (2026-04-16)

**Deliverable:** Plugin manifest skeleton initialized.

## Files

- `plugin.json` — Anthropic Desktop Extension manifest (schema v2)
- `README_PLUGIN.md` — This file (build instructions)

## Build Commands (Day 2+)

```bash
# Bundle into .mcpb package
mcpb build

# Verify bundle
mcpb validate gov-mcp.mcpb

# Test locally
mcpb install gov-mcp.mcpb
```

## Tool Subset (8 tools declared)

1. `gov_check` — pre-execution governance check
2. `gov_delegate` — governed sub-agent dispatch
3. `gov_query_cieu` — CIEU audit log query
4. `gov_install` — install contracts
5. `gov_doctor` — health check
6. `gov_omission_scan` — find missing checks
7. `gov_path_verify` — path scope verification
8. `gov_escalate` — human approval escalation

## Runtime Configuration

**Command:** `python3 -m gov_mcp.server`

**Environment:**
- `YSTAR_CONTRACTS_DIR=${PLUGIN_DIR}/.ystar_contracts`
- `YSTAR_CIEU_DB=${PLUGIN_DIR}/.ystar_cieu.db`

## Next Steps (Day 2)

- Implement 8 tool handlers in `gov_mcp/server.py`
- Add FastMCP integration
- Test with Anthropic Desktop client
- Create sample `.ystar_contracts/` directory
