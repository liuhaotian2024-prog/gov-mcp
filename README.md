# gov-mcp

**Governed execution for any AI agent framework.**

An MCP server that enforces runtime governance on AI agent actions — file access, command execution, delegation chains, and permission escalation. Built on the [Y*gov](https://github.com/liuhaotian2024-prog/Y-star-gov) governance kernel.

## Why

AI agents can read files, run commands, and call APIs. Without governance, a single prompt injection or misaligned sub-agent can `rm -rf /`, leak `.env` secrets, or escalate privileges.

gov-mcp sits between the agent and the system. Every action is checked against a governance contract before execution. Deterministic commands are auto-routed for zero-overhead execution.

## Performance (EXP-008)

| Metric | Without gov-mcp | With gov-mcp | Improvement |
|---|---|---|---|
| Output tokens | 6,107 | 3,352 | **-45.1%** |
| Wall time | 171.1s | 65.8s | **-61.5%** |
| False positives | 0 | 0 | -- |

## Quick Start

### 1. Install

```bash
pip install gov-mcp
```

### 2. Write your governance contract

Create `AGENTS.md`:

```markdown
## Agent: my-agent
## Prohibited: rm -rf, sudo, .env files, /etc access
## Permitted: file read/write, shell commands
```

### 3. One-command install

```bash
gov-mcp install
```

This will:
1. Detect your environment (Claude Code, Cursor, Windsurf, OpenClaw)
2. Start the GOV MCP server (background, auto port selection)
3. Auto-configure detected clients
4. Verify the connection
5. Print a summary with next steps

### 4. Management commands

```bash
gov-mcp status     # Check if server is running
gov-mcp restart    # Restart with fresh config
gov-mcp uninstall  # Stop server, remove all configs
```

### 5. Manual setup (alternative)

If you prefer manual configuration:

```bash
# Start server directly
python -m gov_mcp --agents-md ./AGENTS.md --transport sse --port 7922
```

Connect from any MCP client:

```json
{
  "mcpServers": {
    "gov-mcp": {
      "url": "http://127.0.0.1:7922/sse",
      "transport": "sse"
    }
  }
}
```

## Tools (13)

### Core Enforcement
| Tool | Description |
|---|---|
| `gov_check` | Check action + auto-execute deterministic commands. Single entry point. |
| `gov_enforce` | Full pipeline: check + obligation scan + delegation verify. |
| `gov_exec` | **[DEPRECATED]** Use `gov_check` instead. Redirects with migration guide. |

### Delegation & Escalation
| Tool | Description |
|---|---|
| `gov_delegate` | Register parent-child delegation with monotonicity validation. |
| `gov_escalate` | Request permission expansion from principal. CIEU audit trail. |
| `gov_chain_reset` | Clear stale delegation links (selective or full reset). |

### Contract Management
| Tool | Description |
|---|---|
| `gov_contract_load` | Translate AGENTS.md into draft contract. |
| `gov_contract_validate` | Validate draft contract coverage and health. |
| `gov_contract_activate` | Activate validated contract for enforcement. |

### Audit & Observability
| Tool | Description |
|---|---|
| `gov_report` | CIEU summary: decisions, deny rate, top violations. |
| `gov_verify` | SHA-256 Merkle chain integrity verification. |
| `gov_obligations` | Query obligation status from OmissionEngine. |
| `gov_doctor` | Health check: contract, delegation, omission engine. |
| `gov_benchmark` | Token savings benchmark: Mode A vs Mode B vs Mode C. |

## How It Works

```
Agent proposes action
    |
    v
gov_check(agent_id, tool_name, params)
    |
    +-- Is agent delegated? --> Use delegated contract
    |   (otherwise)         --> Use global contract
    |
    +-- Contract check: ALLOW or DENY
    |
    +-- If ALLOW + deterministic Bash command:
    |   Execute inline, return stdout in response
    |   { "decision": "ALLOW", "auto_executed": true, "stdout": "..." }
    |
    +-- If ALLOW + non-deterministic:
    |   Return ALLOW only (agent handles execution)
    |
    +-- If DENY:
        Return DENY with violation details
```

## Auto-Execution

Deterministic commands (`ls`, `git status`, `cat`, `pwd`, etc.) are classified
by the structural router and **executed inline** within `gov_check`. The agent
receives stdout/stderr in the same response — no second tool call needed.

This saves **22% tokens** and eliminates one LLM round-trip per safe command.
66.7% of typical Bash commands are auto-executed (based on stress testing).

## License

MIT
