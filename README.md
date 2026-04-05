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
pip install ystar-gov  # governance kernel
pip install mcp        # MCP protocol
```

### 2. Write your governance contract

Create `AGENTS.md`:

```markdown
## Agent: my-agent
## Prohibited: rm -rf, sudo, .env files, /etc access
## Permitted: file read/write, shell commands
```

### 3. Run

```bash
python -m gov_mcp --agents-md ./AGENTS.md
```

### 4. Connect from your agent framework

#### Claude Code (claude_desktop_config.json)

```json
{
  "mcpServers": {
    "gov-mcp": {
      "command": "python",
      "args": ["-m", "gov_mcp", "--agents-md", "/path/to/AGENTS.md"]
    }
  }
}
```

#### Cursor (.cursor/mcp.json)

```json
{
  "mcpServers": {
    "gov-mcp": {
      "command": "python",
      "args": ["-m", "gov_mcp", "--agents-md", "/path/to/AGENTS.md"]
    }
  }
}
```

#### Windsurf / Generic MCP Client

```json
{
  "mcpServers": {
    "gov-mcp": {
      "command": "python",
      "args": ["-m", "gov_mcp", "--agents-md", "/path/to/AGENTS.md"],
      "transport": "stdio"
    }
  }
}
```

## Tools (14)

### Core Enforcement
| Tool | Description |
|---|---|
| `gov_check` | Check action against contract. Auto-routes deterministic commands. |
| `gov_enforce` | Full pipeline: check + obligation scan + delegation verify. |
| `gov_exec` | Execute command after governance + whitelist check. |

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
    +-- Is it a deterministic Bash command?
    |   Yes --> Auto-route: execute + return result inline
    |   No  --> Return ALLOW/DENY decision
    |
    v
ALLOW or DENY (with violation details)
```

## Auto-Routing

Deterministic commands (`ls`, `git status`, `cat`, `pwd`, etc.) are classified by the structural router and executed inline within `gov_check` — no separate `gov_exec` call needed. This eliminates one LLM round-trip per safe command.

## License

MIT
