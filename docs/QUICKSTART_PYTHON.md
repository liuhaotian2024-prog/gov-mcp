# gov-mcp Quick Start: Python (no MCP client framework)

Get from `pip install gov-mcp` to a working governance check in Python in
under 5 minutes — without depending on Claude Code, Cursor, Windsurf, or
any other MCP client framework.

You'll use the official [`mcp`](https://pypi.org/project/mcp/) Python
client library directly. This is the lowest-level Python integration
that works for any application: web servers, CLI tools, Jupyter
notebooks, test harnesses, custom agent loops.

For the wire protocol details, see [`PROTOCOL.md`](PROTOCOL.md).
For CrewAI integration, see [`QUICKSTART_CREWAI.md`](QUICKSTART_CREWAI.md).

---

## Prerequisites

- **Python 3.10+**
- **`gov-mcp` installed**: `pip install gov-mcp`
- **An `AGENTS.md` file** with your governance contract (or use a
  minimal example below)

---

## Step 1: Create a minimal AGENTS.md

Save as `./AGENTS.md`:

```markdown
# My Project Governance Contract

## Deny
- /etc
- /production
- /root
- ~/.ssh

## Deny Commands
- rm -rf
- sudo
- DROP TABLE

## Permitted
- File reads in ./data/
- File writes in ./output/
- git status, git diff, git log
```

That's it. The regex parser will extract the rules. (For richer
contracts, see Y\*gov's documentation on the AGENTS.md DSL.)

---

## Step 2: Start the gov-mcp server

In one terminal:

```bash
python -m gov_mcp \
    --agents-md ./AGENTS.md \
    --transport sse \
    --host 127.0.0.1 \
    --port 7922
```

You should see:

```
[GOV MCP] ready — 38 tools registered, transport=sse
[GOV MCP] SSE listening on 127.0.0.1:7922
[GOV MCP] contract loaded from ./AGENTS.md
INFO:     Started server process [12345]
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:7922
```

**Leave this running.** The rest of the quickstart assumes the server is
up.

---

## Step 3: Install the MCP client library

In a second terminal (or your application virtualenv):

```bash
pip install mcp
```

This is the official Anthropic MCP Python SDK. (gov-mcp itself uses it
under the hood, so if you have gov-mcp installed it's already there as
a transitive dependency.)

---

## Step 4: Connect and call your first tool

Save this as `quickstart.py`:

```python
"""
gov-mcp Python quickstart — minimal client that calls gov_doctor and gov_check.
"""
import asyncio
import json

from mcp import ClientSession
from mcp.client.sse import sse_client


GOV_MCP_URL = "http://127.0.0.1:7922/sse"


async def main() -> None:
    # Open SSE connection to gov-mcp
    async with sse_client(GOV_MCP_URL) as (read, write):
        async with ClientSession(read, write) as session:

            # Required handshake: must call before anything else
            await session.initialize()

            # ── Discover what's available ───────────────────────────────
            tools = await session.list_tools()
            print(f"gov-mcp exposes {len(tools.tools)} tools:")
            for t in tools.tools[:5]:
                first_line = (t.description or "").split("\n")[0]
                print(f"  - {t.name}: {first_line[:60]}")
            print(f"  ... ({len(tools.tools) - 5} more)")
            print()

            # ── Health check ────────────────────────────────────────────
            doctor_response = await session.call_tool("gov_doctor", {})
            doctor_text = doctor_response.content[0].text
            doctor = json.loads(doctor_text)

            print("=== gov_doctor result ===")
            print(f"  health:  {doctor.get('health')}")
            print(f"  summary: {doctor.get('summary')}")
            for w in doctor.get("warnings", []):
                print(f"  warn:    {w}")
            print()

            # ── Governance check: should be ALLOWED ─────────────────────
            allow_response = await session.call_tool("gov_check", {
                "agent_id": "quickstart-agent",
                "tool_name": "Read",
                "params": {
                    "file_path": "./data/example.txt",
                },
            })
            allow_decision = json.loads(allow_response.content[0].text)
            print("=== gov_check for ./data/example.txt ===")
            print(f"  decision: {allow_decision.get('decision')}")
            print(f"  envelope: cieu_seq={allow_decision.get('governance', {}).get('cieu_seq')}, "
                  f"latency={allow_decision.get('governance', {}).get('latency_ms', 0):.2f}ms")
            print()

            # ── Governance check: should be DENIED ──────────────────────
            deny_response = await session.call_tool("gov_check", {
                "agent_id": "quickstart-agent",
                "tool_name": "Read",
                "params": {
                    "file_path": "/etc/passwd",
                },
            })
            deny_decision = json.loads(deny_response.content[0].text)
            print("=== gov_check for /etc/passwd ===")
            print(f"  decision: {deny_decision.get('decision')}")
            for v in deny_decision.get("violations", []):
                print(f"  violation: {v.get('message')}")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Step 5: Run it

```bash
python quickstart.py
```

Expected output (numbers may vary):

```
gov-mcp exposes 38 tools:
  - gov_check: Check a proposed agent action and auto-execute if det...
  - gov_enforce: Full enforcement pipeline: check + obligation scan + ...
  - gov_delegate: Register a parent→child delegation and validate mono...
  - gov_escalate: Request permission escalation from the delegating pr...
  - gov_chain_reset: Reset the delegation chain, clearing stale or expe...
  ... (33 more)

=== gov_doctor result ===
  health:  warning
  summary: 14/14 checks passed
  warn:    L1.02: CIEU using in-memory store (not persisted)

=== gov_check for ./data/example.txt ===
  decision: ALLOW
  envelope: cieu_seq=2, latency=1.87ms

=== gov_check for /etc/passwd ===
  decision: DENY
  violation: '/etc' is not allowed in file_path
```

You just used gov-mcp to govern an action without writing a single line
of MCP wire-protocol code. The `mcp` library handled SSE handshake,
JSON-RPC 2.0 framing, and message routing. **Sub-2ms governance check
latency**, deterministic ALLOW/DENY decision, full audit envelope.

---

## What just happened

1. **SSE handshake** (GET /sse) — opened a long-lived stream to gov-mcp
2. **`initialize` JSON-RPC method** — handshake complete, server
   capabilities advertised
3. **`tools/list`** — server returned all 38 tool definitions with
   schemas
4. **`tools/call` for `gov_doctor`** — invoked the tool, got back a
   JSON string in `result.content[0].text`
5. **`tools/call` for `gov_check`** (allow case) — proposed reading
   `./data/example.txt`, got back ALLOW with a governance envelope
6. **`tools/call` for `gov_check`** (deny case) — proposed reading
   `/etc/passwd`, got back DENY because the contract has `/etc` in its
   `deny` list

The wire-level details (POST /messages/?session_id=..., JSON-RPC ids,
SSE event matching) are all handled inside `mcp.client.sse.sse_client`
and `mcp.ClientSession`. You only see the application layer.

---

## Patterns for real applications

### Pattern 1: One client, many checks (long-lived agent loop)

Reuse the same `ClientSession` across many `call_tool` invocations.
Don't re-do the SSE handshake on every check.

```python
async with sse_client(GOV_MCP_URL) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()

        while running:
            action = get_next_agent_action()
            decision = await session.call_tool("gov_check", {
                "agent_id": action.agent_id,
                "tool_name": action.tool,
                "params": action.params,
            })
            d = json.loads(decision.content[0].text)
            if d["decision"] == "ALLOW":
                execute(action)
            else:
                report_blocked(action, d["violations"])
```

### Pattern 2: Sync wrapper for non-async codebases

If your application is sync (Flask, Django, plain scripts), wrap the
async client in a thread-local event loop:

```python
import asyncio
import json
from mcp import ClientSession
from mcp.client.sse import sse_client


class GovMcpSync:
    """Thread-safe sync wrapper around gov-mcp's MCP client."""

    def __init__(self, url: str = "http://127.0.0.1:7922/sse"):
        self.url = url
        self._loop = asyncio.new_event_loop()

    def check(self, agent_id: str, tool_name: str, params: dict) -> dict:
        return self._loop.run_until_complete(
            self._async_check(agent_id, tool_name, params)
        )

    async def _async_check(self, agent_id, tool_name, params):
        async with sse_client(self.url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("gov_check", {
                    "agent_id": agent_id,
                    "tool_name": tool_name,
                    "params": params,
                })
                return json.loads(result.content[0].text)


# Usage in sync code:
gov = GovMcpSync()
decision = gov.check("my-agent", "Read", {"file_path": "/etc/passwd"})
if decision["decision"] == "DENY":
    raise PermissionError(decision["violations"])
```

For high-throughput applications, use Pattern 1 (long-lived session) to
avoid the SSE handshake cost on every call. Pattern 2 is fine for
infrequent governance checks.

### Pattern 3: gov_exec (auto-execute deterministic Bash commands)

For deterministic shell commands (`ls`, `git status`, `cat`, etc.),
`gov_check` auto-executes the command inline and returns stdout in the
same response — no second tool call needed. This saves roughly 22%
tokens vs the explicit check-then-execute pattern.

```python
result = await session.call_tool("gov_check", {
    "agent_id": "my-agent",
    "tool_name": "Bash",
    "params": {"command": "git status"},
})
d = json.loads(result.content[0].text)
print(d["decision"])      # ALLOW
print(d["auto_executed"]) # True (deterministic command)
print(d["stdout"])        # "On branch main\n..."
```

For non-deterministic commands or non-Bash tools, the response is just
ALLOW or DENY — your application handles execution.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ConnectionRefusedError: 7922` | gov-mcp server not running | Start it (Step 2) |
| `Unknown tool: gov_xxxx` | Tool not registered (your gov-mcp version is older) | Upgrade `pip install -U gov-mcp` |
| `(empty tools list)` | Server started but failed to load contract | Check stderr — `--agents-md` path wrong, or AGENTS.md is malformed |
| `Error: -32602 Invalid params` | Tool args don't match `inputSchema` | Re-fetch with `list_tools()`, check field names and types |
| `cieu: not_configured` in gov_doctor | No CIEU database configured | Pass `cieu_db` parameter to tools that need persistence (gov_report, gov_verify, gov_seal) |
| Async context manager errors | Mixing async and sync code carelessly | Use Pattern 2 (sync wrapper) |

---

## Next steps

- **Replace `gov_check` with your real agent's tool calls.** Every action
  your agent proposes can run through gov-mcp first.
- **Use `gov_exec` for deterministic Bash batches** (single round-trip,
  see Pattern 3).
- **Read [`PROTOCOL.md`](PROTOCOL.md)** for the full 38-tool catalog and
  the wire-level reference if you want to write a custom client without
  the `mcp` library.
- **Read [`QUICKSTART_CREWAI.md`](QUICKSTART_CREWAI.md)** if you're using
  CrewAI for your agent framework — that guide shows how to wrap CrewAI
  tools with gov-mcp checks.
- **Use `gov_obligations` to track unfulfilled commitments**, `gov_report`
  for audit summaries, `gov_verify` for tamper-evident chain integrity.
