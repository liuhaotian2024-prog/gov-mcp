# gov-mcp Protocol Reference

How to talk to gov-mcp at the wire-protocol level — without using a high-level
MCP client like Claude Code, Cursor, or Windsurf.

Use this if you're integrating gov-mcp into:

- A custom Python / Node / Go application
- A non-MCP-native agent framework (LangChain, AutoGen, AG2, custom)
- A test harness or CI system
- Documentation, training, or reverse-engineering material

For high-level usage with an existing MCP client, see [`README.md`](../README.md).
For copy-pasteable Python examples, see [`QUICKSTART_PYTHON.md`](QUICKSTART_PYTHON.md).
For CrewAI integration, see [`QUICKSTART_CREWAI.md`](QUICKSTART_CREWAI.md).

---

## Background: two layers, one protocol

gov-mcp speaks the standard **Model Context Protocol (MCP)**, specifically
the **MCP SSE transport** (Server-Sent Events). When you talk to gov-mcp
you're operating at two layers:

- **Wire layer**: HTTP + SSE + JSON-RPC 2.0 (defined by the upstream
  [MCP specification](https://spec.modelcontextprotocol.io/))
- **Application layer**: gov-mcp's 38 governance tools (defined in this
  document, sections "Tool catalog" below)

This document covers BOTH layers in enough detail that you can write a
client from scratch with no MCP library. If you have one (e.g.
[`mcp` Python SDK](https://pypi.org/project/mcp/)), the wire layer is
abstracted — jump to "Tool catalog".

---

## Layer 1: SSE handshake

gov-mcp listens on a single SSE endpoint (default `http://127.0.0.1:7922/sse`).
The handshake is a 2-step dance.

### Step 1: GET /sse — open the long-lived stream

```bash
curl -N http://127.0.0.1:7922/sse
```

The first event from the server delivers your message endpoint URL with a
session_id query parameter:

```
event: endpoint
data: /messages/?session_id=abc123def456...

(connection stays open, server will push response events here)
```

Save the `session_id`. **Keep this connection open** — server responses
come through it, not through HTTP responses to your POSTs.

### Step 2: POST /messages/?session_id=&lt;id&gt; — send requests

All client→server requests go to this URL. Each request body is a single
JSON-RPC 2.0 message.

```bash
curl -X POST \
     "http://127.0.0.1:7922/messages/?session_id=abc123def456..." \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

The server returns `202 Accepted` immediately, with no body. The actual
response is pushed through the SSE stream from Step 1.

### The split-channel pattern

This is the trickiest part of MCP SSE for raw HTTP clients:

```
Your client                    gov-mcp server
-----------                    -------------
GET /sse              ─────►   (stays open)
                      ◄─────   event: endpoint
                                data: /messages/?session_id=X

POST /messages/?session_id=X
  body: {jsonrpc, id:1, ...} ─►
                      ◄─────   202 Accepted (no body)
                      ◄─────   (via SSE) {jsonrpc, id:1, result:...}

POST /messages/?session_id=X
  body: {jsonrpc, id:2, ...} ─►
                      ◄─────   202 Accepted (no body)
                      ◄─────   (via SSE) {jsonrpc, id:2, result:...}
```

Most MCP client libraries handle this for you. If you're writing raw
HTTP code:

1. Keep the SSE connection from Step 1 open in one thread/coroutine
2. POST requests in another thread/coroutine
3. Match incoming SSE events to outgoing requests by JSON-RPC `id` field

---

## Layer 2: JSON-RPC 2.0 subset

MCP uses JSON-RPC 2.0 with these methods relevant to gov-mcp clients:

| Method | Purpose | Required? |
|---|---|---|
| `initialize` | Handshake, capabilities exchange | **Yes** (must be first) |
| `notifications/initialized` | Confirm initialization complete | **Yes** (after `initialize`) |
| `tools/list` | List available tools and their schemas | Recommended (discover what's available) |
| `tools/call` | Invoke a specific tool | **Yes** (the actual work) |
| `ping` | Heartbeat | Optional |

### `initialize` request

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": {
      "name": "my-custom-client",
      "version": "0.1.0"
    }
  }
}
```

Response includes server capabilities and protocol version negotiation.

### `tools/list` request

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/list",
  "params": {}
}
```

Response (delivered via SSE):

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "tools": [
      {
        "name": "gov_doctor",
        "description": "Full 14-layer health check on Y*gov governance state.",
        "inputSchema": {
          "type": "object",
          "properties": {},
          "required": []
        }
      }
      // ... 37 more
    ]
  }
}
```

### `tools/call` request — example: gov_doctor

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "gov_doctor",
    "arguments": {}
  }
}
```

Response:

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"health\": \"warning\", \"summary\": \"14/14 checks passed\", ...}"
      }
    ]
  }
}
```

The tool's actual JSON output is returned as a **string** inside
`result.content[0].text`. You'll need to `JSON.parse()` (or equivalent)
that string to get the structured tool output. This double-wrap is
intentional in MCP — the protocol carries arbitrary content types.

### `tools/call` request — example: gov_check (with arguments)

```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "tools/call",
  "params": {
    "name": "gov_check",
    "arguments": {
      "agent_id": "research-agent",
      "tool_name": "Read",
      "params": {
        "file_path": "/etc/passwd"
      }
    }
  }
}
```

Response (DENY example, contract has `/etc` in deny list):

```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"decision\": \"DENY\", \"violations\": [{\"dimension\": \"deny\", \"message\": \"'/etc' is not allowed in file_path\"}], \"governance\": {...}}"
      }
    ]
  }
}
```

---

## Layer 3: Tool catalog (38 tools)

Tools grouped by purpose. Field types in parentheses; `*` marks required.

### Core enforcement (3)

| Tool | Description | Parameters |
|---|---|---|
| `gov_check` | Check a proposed agent action and auto-execute if deterministic. | `agent_id*` (str), `tool_name*` (str), `params*` (dict) |
| `gov_enforce` | Full enforcement pipeline: check + obligation scan + delegation verify. | `agent_id*` (str), `tool_name*` (str), `params*` (dict) |
| `gov_exec` | **[DEPRECATED]** Use `gov_check` instead. Auto-redirects with migration guide. | `command*` (str), `agent_id*` (str), `timeout_secs` (int) |

### Delegation &amp; escalation (3)

| Tool | Description | Parameters |
|---|---|---|
| `gov_delegate` | Register a parent→child delegation and validate monotonicity (child contract must be a strict subset). | `principal*`, `actor*`, `deny`, `only_paths`, `deny_commands`, `only_domains`, `action_scope`, `allow_redelegate` (bool), `delegation_depth` (int) |
| `gov_escalate` | Request permission escalation from the delegating principal. CIEU audit trail. | `agent_id*`, `requested_paths`, `requested_commands`, `requested_domains`, `reason` |
| `gov_chain_reset` | Reset the delegation chain, clearing stale or experimental links. Selective by `agent_id` or full reset. | `agent_id`, `confirm` (bool, must be `true` to actually run) |

### Contract management (4)

| Tool | Description | Parameters |
|---|---|---|
| `gov_contract_load` | Translate AGENTS.md text into a draft IntentContract. Uses regex (no LLM). | `agents_md_text*` (str) |
| `gov_contract_validate` | Validate the currently loaded draft contract — coverage, internal consistency. | (no params) |
| `gov_contract_activate` | Activate the validated draft contract as the enforcement contract. | (no params) |
| `gov_contract_conflicts` | Detect contradictions in the active governance contract. | (no params) |

### Audit &amp; observability (8)

| Tool | Description | Parameters |
|---|---|---|
| `gov_report` | Return CIEU summary: total decisions, deny rate, top violations. | `cieu_db` (str path), `since_hours` (float) |
| `gov_verify` | Verify SHA-256 Merkle chain integrity of CIEU records. | `cieu_db` (str path), `session_id` (str) |
| `gov_obligations` | Query current obligations from the OmissionEngine store. | `actor_id` (str), `status_filter` (str: pending / fulfilled / soft_overdue / hard_overdue) |
| `gov_doctor` | Full 14-layer health check on Y*gov governance state. | (no params) |
| `gov_seal` | Seal a CIEU session with Merkle root for tamper-evident preservation. | `cieu_db*` (str), `session_id*` (str) |
| `gov_audit` | Causal audit report: intent vs actual actions with violation replay. | `cieu_db`, `session_id`, `agent_id`, `decision`, `limit` |
| `gov_trend` | 7-day CIEU event trend analysis (decisions, deny rate direction). | `cieu_db`, `days` (int) |
| `gov_archive` | Move old CIEU data to compressed archive (hot/cold tiering). | `cieu_db*`, `archive_dir`, `hot_days` (int), `dry_run` (bool) |

### Governance analysis (10)

| Tool | Description | Parameters |
|---|---|---|
| `gov_baseline` | Capture current governance state as a baseline snapshot for comparison. | `cieu_db`, `label` (str) |
| `gov_delta` | Compare current governance state against a saved baseline. | `label` (str), `cieu_db` |
| `gov_coverage` | Detect governance blind spots: which declared agents lack coverage. | `declared_agents` (list), `cieu_db` |
| `gov_quality` | Evaluate governance contract quality against CIEU history (8 dimensions). | `cieu_db`, `agents_md` (str) |
| `gov_simulate` | A/B simulation: measure governance intercept effectiveness on synthetic sessions. | `sessions` (int), `seed` (int) |
| `gov_impact` | Predict the impact of contract changes before applying them via CIEU replay. | `contract_changes` (dict), `cieu_db` |
| `gov_check_impact` | Convenience wrapper for `gov_impact` with explicit add/remove parameters. | `add_deny`, `remove_deny`, `add_deny_commands`, `remove_deny_commands`, `add_only_paths`, `cieu_db` |
| `gov_pretrain` | Learn contract improvements from historical CIEU data. Suggests new rules. | `cieu_db`, `days` (int) |
| `gov_counterfactual` | Pearl L3 counterfactual query: "What if we had different rules?" | `hypothetical_deny`, `hypothetical_deny_commands`, `test_actions` (list) |
| `gov_risk_classify` | Classify a governance suggestion as high or low risk. | `suggestion*` (str), `target` (str) |

### User experience (7)

| Tool | Description | Parameters |
|---|---|---|
| `gov_demo` | Zero-config governance demo: 5 checks showing ALLOW and DENY paths. | (no params) |
| `gov_init` | Generate an AGENTS.md governance template for a project type. | `project_type` (str), `custom_rules` (list) |
| `gov_version` | Return gov-mcp and Y*gov version information. | (no params) |
| `gov_policy_builder` | Return the policy builder UI URL and contract data for rendering. | `port` (int) |
| `gov_reset_breaker` | Reset the circuit breaker after manual intervention. | (no params) |
| `gov_session_info` | Show session persistence and auto-trigger state. | (no params) |
| `gov_benchmark` | Run A/B token savings benchmark: traditional tool calls vs `gov_exec`. | `tasks` (list of strings) |

### Domain &amp; data (3)

| Tool | Description | Parameters |
|---|---|---|
| `gov_domain_list` | List all registered governance domain packs (devops, finance, healthcare, research, ...). | (no params) |
| `gov_domain_describe` | Show detailed information about a specific domain pack. | `name*` (str) |
| `gov_domain_init` | Generate a custom domain pack template. | `name*` (str) |

**Total: 3 + 3 + 4 + 8 + 10 + 7 + 3 = 38 tools.** Verified live against
`mcp.client.sse.list_tools()` on a running gov-mcp 0.1.0 instance.

---

## Governance envelope

Every `gov_check` and `gov_enforce` response includes a `governance` field
in the JSON output — a structured audit envelope that rides on top of
the MCP protocol:

```json
{
  "decision": "ALLOW",
  "auto_executed": true,
  "stdout": "...",
  "governance": {
    "cieu_seq": 17753,
    "cieu_level": "ops",
    "event_hash": "924683043aad9a...",
    "writer_verified": true,
    "contract_hash": "sha256:9fdbdaed...",
    "contract_version": "",
    "confidence_score": 0.7,
    "human_approved": false,
    "approval_chain": null,
    "latency_ms": 1.9,
    "host": "generic"
  }
}
```

| Field | Type | Description |
|---|---|---|
| `cieu_seq` | int | Monotonic sequence number — total governance decisions made by this server instance |
| `cieu_level` | str | Evidence grade: `decision` / `ops` / `intent` |
| `event_hash` | str | SHA-256 hash of this event, chained to previous (Merkle chain) |
| `writer_verified` | bool | Whether the CIEU writer token was verified (anti-fabrication check) |
| `contract_hash` | str | SHA-256 of the active governance contract at the time of this decision |
| `contract_version` | str | Contract name/version string |
| `confidence_score` | float | Contract translation confidence (0.5 = pure regex, 0.95+ = structured load) |
| `human_approved` | bool | Whether this contract has been explicitly approved by a human |
| `approval_chain` | list | Chain of approval signatures, if any |
| `latency_ms` | float | Time to compute the governance decision (sub-2ms typical) |
| `host` | str | Detected client ecosystem (`claude_code`, `cursor`, `windsurf`, `openclaw`, `generic`) |

This envelope enables audit trails, compliance reporting, and contract
versioning across multi-agent deployments. Backward-compatible: callers
that don't inspect `governance` are unaffected.

---

## Common errors

| HTTP status | JSON-RPC error code | Cause | Fix |
|---|---|---|---|
| 400 | `-32700` Parse error | Malformed JSON in POST body | Validate request body before sending |
| 400 | `-32600` Invalid Request | JSON-RPC envelope wrong (missing `jsonrpc`, `id`, `method`, ...) | Check envelope structure |
| 400 | `-32601` Method not found | Unknown JSON-RPC method | Use `tools/list`, `tools/call`, `initialize`, `notifications/initialized`, `ping` |
| 400 | `-32602` Invalid params | Tool args don't match the tool's `inputSchema` | Re-fetch via `tools/list`, validate locally |
| 404 | (no body) | `session_id` expired, invalid, or not yet established | Re-do GET /sse handshake |
| 500 | `-32603` Internal error | gov-mcp server-side exception | Check gov-mcp's stderr log; file an issue |

---

## References

- [MCP Specification](https://spec.modelcontextprotocol.io/) — upstream
  protocol authority
- [JSON-RPC 2.0](https://www.jsonrpc.org/specification) — message format
- [Server-Sent Events MDN](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)
- [`mcp` Python SDK](https://pypi.org/project/mcp/) — official client
  library used by [`QUICKSTART_PYTHON.md`](QUICKSTART_PYTHON.md)
- [Y\*gov](https://github.com/liuhaotian2024-prog/Y-star-gov) — the
  governance kernel that gov-mcp exposes
