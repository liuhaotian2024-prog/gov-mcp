# gov-mcp Quick Start: CrewAI Integration

Add gov-mcp governance to a [CrewAI](https://github.com/crewAIInc/crewAI)
multi-agent crew. Every tool call your CrewAI agents make will be
checked by gov-mcp's `gov_check` first, and denied actions will be
blocked before they execute.

This is a complete, runnable example. ~15 minutes to set up, immediate
visible governance enforcement.

For lower-level Python integration without CrewAI, see
[`QUICKSTART_PYTHON.md`](QUICKSTART_PYTHON.md). For wire-protocol
details, see [`PROTOCOL.md`](PROTOCOL.md).

---

## Why governance for CrewAI?

CrewAI is great for orchestrating multi-agent workflows. But out of the
box, agents can:

- Read any file your Python process can read
- Run any shell command via `BashTool` or `CodeInterpreterTool`
- Make any HTTP request via `WebsiteSearchTool` or `ScrapeWebsiteTool`
- Modify any file via `FileWriteTool`

In production, you usually want a stricter contract: **"this agent can
read `./data/`, can run `git status`, but can't access `/etc` or run
`rm -rf`"**. gov-mcp enforces that contract at runtime, deterministically
(no LLM in the check path), with sub-2ms latency.

This is **defense-in-depth**: even if a prompt injection convinces your
agent to try to read `/etc/passwd`, gov-mcp blocks the actual file read
before it touches disk.

---

## Architecture

```
CrewAI Agent (LLM-based, untrusted intent)
   │
   │ proposes tool call
   ▼
CrewAI Tool Wrapper (your code, ~10 lines per tool)
   │
   │ asks gov-mcp first
   ▼
gov-mcp gov_check  ←  AGENTS.md contract
   │
   │ ALLOW or DENY (deterministic, no LLM)
   ▼
If ALLOW: actual tool runs, result returned to agent
If DENY:  tool wrapper returns the violation, agent sees the error
                                            and can decide what to do
```

The key property: **the LLM-based agent never has authority over its own
governance**. It can ask, but the answer comes from a deterministic
contract checker, not from another LLM.

---

## Prerequisites

- **Python 3.10+**
- **`pip install crewai crewai-tools mcp gov-mcp`**
- **gov-mcp server running** on `:7922` (see
  [`QUICKSTART_PYTHON.md`](QUICKSTART_PYTHON.md) Step 2 for the startup
  command)
- **An `AGENTS.md`** loaded by gov-mcp at startup
- **An LLM API key** for CrewAI (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
  etc.)

---

## Step 1: Set up `AGENTS.md` with the contract

Save as `./AGENTS.md` (the same one you pass to gov-mcp at startup):

```markdown
# Research Agent Governance Contract

## Deny
- /etc
- /production
- /root
- ~/.ssh
- ~/.aws

## Deny Commands
- rm -rf
- sudo
- DROP TABLE

## Permitted
- File reads in ./data/
- File reads in ./reports/
- git status, git diff, git log
```

---

## Step 2: Set up `./data/` with example data

```bash
mkdir -p ./data
echo "AI agent governance is the practice of constraining what an autonomous agent can do, by enforcing a contract at runtime rather than at training time." > ./data/example.txt
```

---

## Step 3: Start gov-mcp (separate terminal)

```bash
python -m gov_mcp \
    --agents-md ./AGENTS.md \
    --transport sse \
    --host 127.0.0.1 \
    --port 7922
```

Verify it's up:

```bash
curl -s http://127.0.0.1:7922/sse | head -3
# Should show: event: endpoint
#              data: /messages/?session_id=...
```

Leave this running.

---

## Step 4: The full crew example

Save as `crewai_governed.py`:

```python
"""
CrewAI agents governed by gov-mcp.

A research agent reads files and summarizes them. gov-mcp blocks any
read attempt outside the permitted directories.

The wrapper pattern works with any CrewAI version and any Y*gov contract.
"""
import asyncio
import json
from typing import Any, Dict

from crewai import Agent, Task, Crew
from crewai.tools import BaseTool

from mcp import ClientSession
from mcp.client.sse import sse_client


GOV_MCP_URL = "http://127.0.0.1:7922/sse"


# ============================================================================
# gov-mcp client — sync wrapper around the async mcp library
# ============================================================================

class GovMcpClient:
    """Thread-local sync wrapper for CrewAI tool callbacks."""

    def __init__(self, url: str = GOV_MCP_URL):
        self.url = url
        self._loop = asyncio.new_event_loop()

    def check(self, agent_id: str, tool_name: str, params: Dict[str, Any]) -> Dict:
        """Synchronously call gov_check, return parsed result dict."""
        return self._loop.run_until_complete(
            self._async_call("gov_check", {
                "agent_id": agent_id,
                "tool_name": tool_name,
                "params": params,
            })
        )

    async def _async_call(self, tool_name: str, args: Dict) -> Dict:
        async with sse_client(self.url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, args)
                return json.loads(result.content[0].text)


# Module-level singleton — share across CrewAI tool instances
GOV_MCP = GovMcpClient()


# ============================================================================
# Governed file-read tool — wraps the actual read with gov_check
# ============================================================================

class GovernedReadTool(BaseTool):
    """Read a file with gov-mcp governance enforcement."""

    name: str = "governed_read"
    description: str = (
        "Read the contents of a file. All reads are governed by gov-mcp. "
        "Some paths may be blocked by the active governance contract — "
        "if so, the response explains which rule blocked it."
    )

    # Set this when constructing — the agent_id used in CIEU audit records.
    agent_id: str = "research-agent"

    def _run(self, file_path: str) -> str:
        # ── Step 1: ask gov-mcp if this read is allowed ───────────────
        decision = GOV_MCP.check(
            agent_id=self.agent_id,
            tool_name="Read",
            params={"file_path": file_path},
        )

        if decision.get("decision") == "DENY":
            violations = decision.get("violations", [])
            reasons = "; ".join(v.get("message", "") for v in violations)
            return (
                f"BLOCKED by gov-mcp governance: {reasons}. "
                f"This action violated the active contract. "
                f"Try a different file path within ./data/ or ./reports/."
            )

        # ── Step 2: ALLOW — actually read the file ────────────────────
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Truncate for demo brevity
            if len(content) > 2000:
                content = content[:2000] + "\n... (truncated)"
            return content
        except FileNotFoundError:
            return f"File not found: {file_path}"
        except Exception as e:
            return f"Read error: {type(e).__name__}: {e}"


# ============================================================================
# CrewAI agent + tasks + crew
# ============================================================================

researcher = Agent(
    role="File Researcher",
    goal="Read files in the permitted directories and summarize their contents",
    backstory=(
        "You are a careful file researcher. You can only read files in "
        "./data/ and ./reports/. If you try to read elsewhere, gov-mcp "
        "will block you with a clear violation message. When that happens, "
        "respect the block and report it — do not try to bypass governance."
    ),
    tools=[GovernedReadTool()],
    verbose=True,
)

# ── Task 1: should be ALLOWED (file is in ./data/) ─────────────────────
task_allowed = Task(
    description=(
        "Read the file at './data/example.txt' and write a 1-sentence "
        "summary of its contents."
    ),
    agent=researcher,
    expected_output="A single sentence summarizing the file's contents.",
)

# ── Task 2: should be DENIED by gov-mcp (file is in /etc/) ─────────────
task_denied = Task(
    description=(
        "Read the file at '/etc/passwd' and summarize its contents. "
        "If gov-mcp blocks the read, report that fact verbatim and stop. "
        "Do not attempt to bypass governance."
    ),
    agent=researcher,
    expected_output=(
        "Either a summary, or a clear 'BLOCKED' report quoting the "
        "gov-mcp violation message."
    ),
)


crew = Crew(
    agents=[researcher],
    tasks=[task_allowed, task_denied],
    verbose=True,
)


# ============================================================================
# Run
# ============================================================================

if __name__ == "__main__":
    print("Starting governed crew...")
    print("(Make sure gov-mcp is running on port 7922 in another terminal)")
    print()

    result = crew.kickoff()

    print()
    print("=== final crew result ===")
    print(result)
```

---

## Step 5: Run the crew

```bash
export OPENAI_API_KEY=sk-...   # or whatever LLM CrewAI uses
python crewai_governed.py
```

---

## Expected behavior

CrewAI executes Task 1 (read `./data/example.txt`) successfully. Then it
executes Task 2 (read `/etc/passwd`) and gov-mcp blocks it. The agent
sees the violation message in its tool result and reports the block in
its task output.

**Task 1 (ALLOWED) — excerpt of agent's reasoning:**

```
Thought: I need to read the file ./data/example.txt
Action: governed_read
Action Input: {"file_path": "./data/example.txt"}
Observation: AI agent governance is the practice of constraining what
an autonomous agent can do, by enforcing a contract at runtime rather
than at training time.

Thought: I have the content. Now I'll summarize it in one sentence.
Final Answer: The file explains that AI agent governance constrains
agent behavior at runtime via contract enforcement, not at training
time.
```

**Task 2 (DENIED) — excerpt of agent's reasoning:**

```
Thought: I need to read /etc/passwd as instructed.
Action: governed_read
Action Input: {"file_path": "/etc/passwd"}
Observation: BLOCKED by gov-mcp governance: '/etc' is not allowed in
file_path. This action violated the active contract. Try a different
file path within ./data/ or ./reports/.

Thought: gov-mcp blocked the read. The task instructions say to respect
the block and report it.
Final Answer: BLOCKED. gov-mcp violation: '/etc' is not allowed in
file_path. The active contract prohibits reads under /etc.
```

The LLM-based agent never gained access to `/etc/passwd`. The decision
was made deterministically by gov-mcp's regex contract check, not by
the LLM. **Even a prompt injection that overrode the agent's task
instructions would not change the outcome** — the governance check
happens in `_run()` before the file is touched.

---

## What you got

| Property | How it's achieved |
|---|---|
| **Deterministic enforcement** | Every CrewAI tool call goes through gov-mcp's `gov_check` first. No LLM in the decision path. No prompt injection can change ALLOW→DENY. |
| **Sub-2ms latency** | gov-mcp's regex check is ~1.9ms typical. Acceptable for hot-loop agent workflows. |
| **Audit trail** | gov-mcp records every decision in its CIEU log. Use `gov_report` and `gov_verify` MCP tools to extract reports for compliance. |
| **Contract source of truth** | Your governance rules live in `AGENTS.md`, separate from your CrewAI code. Update one without touching the other. |
| **Defense in depth** | Even if your CrewAI agent's prompt is injected, gov-mcp's contract check happens AFTER the agent has decided on an action and BEFORE the action executes. |

---

## Adapting to your real crew

Replace `GovernedReadTool` with wrapped versions of your actual tools.
The pattern is always the same:

```python
class GovernedYourTool(BaseTool):
    name: str = "your_tool"
    description: str = "..."
    agent_id: str = "your-agent"

    def _run(self, **kwargs) -> str:
        decision = GOV_MCP.check(
            agent_id=self.agent_id,
            tool_name="YourToolName",  # the name your contract recognizes
            params=kwargs,
        )
        if decision.get("decision") == "DENY":
            violations = decision.get("violations", [])
            return f"BLOCKED: {[v['message'] for v in violations]}"
        # ALLOW — actual tool logic:
        return self._do_actual_work(**kwargs)

    def _do_actual_work(self, **kwargs) -> str:
        # ... your real implementation
        ...
```

For **deterministic Bash commands**, you can use `gov_exec` (or
`gov_check` with `tool_name="Bash"`), which does check + execute in
**one** MCP round-trip — saves ~22% tokens vs the explicit
check-then-execute pattern. Useful for tools like `git status`,
`ls`, `cat`.

```python
class GovernedBashTool(BaseTool):
    name: str = "governed_bash"
    description: str = "Run a shell command, governed by gov-mcp."
    agent_id: str = "ops-agent"

    def _run(self, command: str) -> str:
        result = GOV_MCP.check(
            agent_id=self.agent_id,
            tool_name="Bash",
            params={"command": command},
        )
        # If deterministic, gov_check auto-executed and returned stdout
        if result.get("auto_executed"):
            return result.get("stdout", "")
        # If non-deterministic ALLOW, your code runs the command
        if result.get("decision") == "ALLOW":
            import subprocess
            return subprocess.check_output(command, shell=True, text=True)
        # DENY
        return f"BLOCKED: {[v['message'] for v in result.get('violations', [])]}"
```

---

## Optional: use CrewAI's `MCPServerAdapter` (recent CrewAI versions)

Recent versions of `crewai-tools` ship an `MCPServerAdapter` that
auto-loads all of an MCP server's tools as CrewAI tools. This is faster
to set up but gives you less control:

```python
from crewai_tools import MCPServerAdapter

# Auto-load ALL 38 gov-mcp tools as CrewAI tools
adapter = MCPServerAdapter({
    "url": "http://127.0.0.1:7922/sse",
    "transport": "sse",
})
gov_tools = adapter.tools()  # list of 38 BaseTool instances

researcher = Agent(
    role="File Researcher",
    tools=gov_tools,  # agent now has direct access to gov_check, gov_report, etc.
    ...
)
```

**Trade-off**: this gives the agent direct access to *all* gov-mcp
tools, including meta-tools like `gov_chain_reset`, `gov_pretrain`, etc.
For most production crews you want the wrapper pattern (above), where
you wrap *only* the actual work tools (read, write, bash) and *only*
those go through `gov_check`. Use `MCPServerAdapter` if your agent
genuinely needs to manage the governance contract itself.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ConnectionRefusedError: 7922` | gov-mcp server not running | Start it (Step 3) |
| `BLOCKED by gov-mcp governance: '/etc' is not allowed` | The contract worked! | Expected for Task 2 |
| `Read error: [Errno 13] Permission denied` | File system permission, not gov-mcp | Check OS-level permissions on the path |
| Agent loops indefinitely on a DENY result | Agent doesn't understand the block, keeps retrying | Improve the agent's `backstory` to explain "gov-mcp blocks are final" |
| `TypeError: ... missing required arg 'agent_id'` | gov_check params shape wrong | Check the call shape — `agent_id`, `tool_name`, `params` are all required |
| Auto-executed Bash returns stale output | gov-mcp's exec_whitelist doesn't include your command | Check `gov-mcp/gov_mcp/exec_whitelist.yaml` |

---

## Next steps

- **Read [`PROTOCOL.md`](PROTOCOL.md)** for the full 38-tool catalog
  beyond `gov_check`. Useful tools for crews:
  - `gov_obligations` — query unfulfilled commitments per agent
  - `gov_report` — extract audit summaries (decisions, deny rate)
  - `gov_audit` — causal audit with violation replay
  - `gov_delegate` — register parent→child sub-agent delegations
- **Read [`QUICKSTART_PYTHON.md`](QUICKSTART_PYTHON.md)** for the lower-
  level mcp client patterns and the long-lived session pattern.
- **Use `gov_obligations`** to track which CrewAI agents have
  unfulfilled obligations after each task. Useful for SLA enforcement.
- **Use `gov_report --format json`** in your CI to fail builds when the
  deny rate spikes (indicates contract drift or new attack patterns).
