# gov_health — Agent Degradation Detection System

**Status:** P0 deliverable (Board-approved spec)  
**Version:** 1.0  
**Implementation:** 100% deterministic (Iron Rule 1: no LLM)

---

## Overview

The `gov_health` system detects agent degradation by analyzing CIEU event streams across five behavioral signals. Health scores range 0-100, with configurable thresholds triggering reset protocols.

**Core principle:** Degradation patterns emerge gradually in agent behavior before catastrophic failure. Early detection enables intervention before data fabrication or policy drift causes material harm.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      CIEU Event Stream                      │
│  (session_id, agent_id, event_type, decision, violations)  │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   Signal Detection Layer                    │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐              │
│  │ Repetition │ │ Obligation │ │ Inflation  │              │
│  │ (31.25%)   │ │ Decay      │ │ (18.75%)   │              │
│  │            │ │ (31.25%)   │ │            │              │
│  └────────────┘ └────────────┘ └────────────┘              │
│  ┌────────────┐ ┌────────────┐                             │
│  │ Fabrication│ │ Contradic- │ (observation only,          │
│  │ (18.75%)   │ │ tion (0%)  │  not scored)                │
│  └────────────┘ └────────────┘                             │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼ (weighted sum)
┌─────────────────────────────────────────────────────────────┐
│                    Overall Health Score                     │
│                        (0-100)                              │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                     Reset Protocol                          │
│  Health ≥40:  agent may self-reset                         │
│  Health 25-40: supervisor confirmation required             │
│  Health <25:   Board decision required                      │
│  IRON RULE: all resets must notify supervisor via           │
│             gov_dispatch (no notification = violation)      │
└─────────────────────────────────────────────────────────────┘
```

---

## Signal Definitions

### 1. Repetition (31.25% weight)

**Detects:** Agents stuck in loops, repeating identical actions.

**Mechanism:**
- Compute semantic fingerprint for each event (hash of event_type, file_path, command, tool_name)
- Count unique fingerprints in sliding window (default 20 events)
- Repetition rate = 1 - (unique_count / total_count)

**Scoring:**
- Repetition ≤30%: score 100 (normal workflow has some repetition)
- Repetition >30%: linear decay to 0 as repetition approaches 100%

**Example degradation pattern:**
```
Healthy:   Read(file1.txt) → Write(file2.txt) → Read(file3.txt) → ...
Degraded:  Read(same.txt) → Read(same.txt) → Read(same.txt) → ...
```

### 2. Obligation Decay (31.25% weight)

**Detects:** Declining fulfillment of governance obligations over session lifetime.

**Mechanism:**
- Query obligations from OmissionEngine store
- Split session into first half vs second half by obligation creation time
- Compute completion rate for each half: `fulfilled / total`
- Decay = first_half_rate - second_half_rate

**Scoring:**
- Decay ≤0 (improving): score 100
- Decay >0 (degrading): linear penalty, score = 100 * (1 - decay)

**Example degradation pattern:**
```
Session start:  ACKNOWLEDGE → fulfilled, REPORT → fulfilled (100%)
Session middle: REPORT → fulfilled, ACKNOWLEDGE → cancelled (50%)
Session end:    REPORT → pending, ACKNOWLEDGE → pending (0%)
```

### 3. Tool Call Inflation (18.75% weight)

**Detects:** Abnormal increase in tool call count for similar tasks.

**Mechanism:**
- Group consecutive events by task type (simplified: by event_type)
- Compute baseline: median tool call count across historical instances
- Recent instance inflation: `recent_count > baseline * 2.5`

**Scoring:**
- Inflation rate = inflated_task_count / total_task_types
- Score = 100 * (1 - inflation_rate)

**Example degradation pattern:**
```
Baseline:  Read → Write (2 tools per report generation)
Degraded:  Read → Read → Read → Grep → Read → Write → Edit → Write (8 tools)
```

### 4. Fabrication (18.75% weight)

**Detects:** Data fabrication via violation pattern analysis.

**Mechanism:**
- Scan violations for fabrication keywords: "fabricat", "fake", "forged", "synthetic"
- Flag violations in reporting dimensions: "report", "metric", "analytics", "performance"
- Fabrication rate = indicators / total_events

**Scoring:**
- Even 1 fabrication per 100 events is serious → aggressive penalty
- Score = 100 * (1 - fabrication_rate * 50)

**Example violation triggering fabrication signal:**
```json
{
  "dimension": "report_integrity",
  "message": "Fabricated performance metrics detected in quarterly report"
}
```

### 5. Contradiction (0% weight — observation mode)

**Detects:** Contradictory actions within sliding window.

**Board decision:** High false positive rate. Normal workflows like "check file → fix → verify" are flagged incorrectly. In v1, record but don't penalize.

**Patterns detected (but not scored):**
- Write file → Write same file (back-and-forth editing)
- INTENT_DECLARED → INTENT_REJECTED (goal reversal)
- Create entity → Delete entity → Create same entity

**Future:** v2 may add causal context analysis to reduce false positives.

---

## Reset Protocol

Health-based reset authority follows three-tier governance:

| Health Score | Reset Authority | Action Required |
|--------------|-----------------|-----------------|
| ≥40 | Agent (self) | Soft reset: re-read AGENTS.md, recent 5 obligations |
| 25-40 | Supervisor | Supervisor confirms reset via gov_delegate |
| <25 | Board | Manual Board review and decision |

**IRON RULE:** All resets (including self-initiated) MUST notify supervisor via `gov_dispatch`. Failure to notify = governance violation, escalates to Board.

**Reset types:**
- **Soft reset:** Reload governance contract, clear recent working memory, continue session
- **Hard reset:** Seal current session (immutable archive), create handoff obligation for new session

---

## MCP Tools

### `gov_health`

Compute health score for a specific session.

**Parameters:**
- `session_id` (required): Session identifier
- `window_size` (optional, default 20): Number of recent events to analyze
- `threshold` (optional, default 60.0): Health threshold for status determination
- `cieu_db` (optional): Path to CIEU database (uses in-process state if empty)
- `omission_db` (optional): Path to omission database

**Returns:**
```json
{
  "session_id": "GOV-010",
  "agent_id": "cto",
  "overall_health": 86.6,
  "threshold": 60.0,
  "status": "healthy",
  "signals": [
    {
      "name": "repetition",
      "raw_score": 88.2,
      "weight": 0.3125,
      "contribution": 27.6,
      "details": {"repetition_rate": 0.15, "window_size": 20},
      "alerts": []
    },
    ...
  ],
  "recommendation": "Health nominal. Continue normal operations.",
  "reset_policy": {
    "allowed_by": "self",
    "thresholds": {"soft_reset_min": 40.0, "board_decision_max": 25.0},
    "supervisor_notification_required": true
  },
  "governance": {"latency_ms": 8.3}
}
```

**Usage:**
```bash
# Via MCP client
gov_health session_id=GOV-010

# With custom parameters
gov_health session_id=GOV-010 window_size=30 threshold=70.0
```

### `gov_health_retrospective`

Batch health analysis across all sessions (or specific session) with temporal checkpoints.

**Parameters:**
- `cieu_db` (optional): Path to CIEU database
- `omission_db` (optional): Path to omission database
- `session_id` (optional): Analyze specific session (empty = all sessions)
- `checkpoint_interval` (optional, default 10): Compute health every N events

**Returns:**
```json
{
  "total_sessions": 37,
  "sessions": {
    "GOV-010": {
      "agent_id": "cto",
      "total_events": 8,
      "checkpoints": [
        {"event_index": 5, "timestamp": 1234567890, "health": 92.5, "signals": {...}},
        {"event_index": 8, "timestamp": 1234567920, "health": 86.6, "signals": {...}}
      ],
      "trend": "degrading",
      "final_health": 86.6
    },
    ...
  },
  "high_risk_agents": [
    {"agent_id": "cmo", "session_id": "CASE-001", "final_health": 42.1, "decline_rate": -8.2}
  ],
  "degradation_patterns": {},
  "governance": {"latency_ms": 234.5}
}
```

**Use cases:**
1. **Calibration:** Validate thresholds against historical data
2. **Incident analysis:** Detect degradation patterns in known failure cases
3. **Trend detection:** Identify agents with systematic degradation across multiple sessions

**Usage:**
```bash
# Analyze all sessions
gov_health_retrospective

# Analyze specific session with fine-grained checkpoints
gov_health_retrospective session_id=GOV-010 checkpoint_interval=5

# Use external database
gov_health_retrospective cieu_db=/path/to/.ystar_cieu.db
```

---

## Calibration and Validation

### Historical Validation

The system has been validated against Y* Bridge Labs real CIEU data (111 events across 37 sessions). See `scripts/validate_health_historical.py` for full validation report.

**Findings:**
- ✓ All 37 sessions analyzed successfully
- ✓ No runtime errors or edge case failures
- ✓ Degradation detection operational (doctor_test session: 74.7 health, stable trend)
- ⚠ No historical fabrication incidents in current dataset (expected — CASE-001/002 violations not yet in CIEU)

### Threshold Calibration

Board-approved v1 thresholds:
- **Health threshold:** 60.0 (fixed, no per-agent customization in v1)
- **Reset tiers:** 40.0 (self), 25.0 (Board)

**Rationale:** Conservative thresholds reduce false alarms. Labs historical data shows most healthy sessions score 85-100, degraded test sessions score 40-70. 60.0 threshold provides clear separation.

**Future calibration:** v2 may adjust based on 6 months of production data.

---

## Known Limitations (v1)

1. **Contradiction signal disabled (0% weight):** High false positive rate on normal check-fix-verify workflows. v2 will add causal context to distinguish legitimate iteration from actual contradictions.

2. **Task clustering simplified:** Inflation detection groups by `event_type` instead of semantic intent. May miss inflation in semantically similar but syntactically different tasks.

3. **No historical baseline per agent:** All agents judged against same thresholds. v2 may support per-agent baseline calibration after sufficient data collection.

4. **Small session handling:** Sessions <10 events default most signals to 100 (benefit of doubt). May miss degradation in short-lived agents.

---

## Integration with OmissionEngine

When health drops below threshold:

1. **gov_health** computes health score
2. If `overall_health < threshold`, creates ACKNOWLEDGE_DEGRADATION obligation via OmissionEngine
3. If health continues declining across checkpoints, escalates via delegation chain:
   - Agent → Supervisor (via `gov_delegate`)
   - Supervisor → Board (via `gov_escalate`)

**Obligation example:**
```json
{
  "obligation_type": "ACKNOWLEDGE_DEGRADATION",
  "actor_id": "cto",
  "trigger_event_id": "health_check_001",
  "required_event_types": ["DEGRADATION_ACKNOWLEDGED", "RESET_INITIATED"],
  "due_at": 1800.0,  // 30 minutes
  "severity": "high",
  "escalation_policy": {
    "escalate_to": "board",
    "escalation_delay_secs": 3600
  }
}
```

---

## Testing

**Unit tests:** `tests/test_gov_health.py` (26 tests, all passing)
- Signal detection correctness
- Health score calculation
- Reset threshold validation
- Retrospective analysis
- Edge case handling

**Integration tests:** `tests/test_health_mcp_integration.py`
- MCP tool interface
- Database path resolution
- JSON response format
- Error handling

**Historical validation:** `scripts/validate_health_historical.py`
- Validates against Y* Bridge Labs real CIEU data
- Generates full analysis report

**Run tests:**
```bash
cd /path/to/gov-mcp
python3 -m pytest tests/test_gov_health.py -v
python3 scripts/validate_health_historical.py
```

---

## References

- Board decision memo: P0 task specification (2026-04-10)
- CIEU database schema: `ystar/governance/cieu_store.py`
- Omission database schema: `ystar/governance/omission_engine.py`
- Known incidents: CASE-001 (CMO fabrication 2026-03-26), CASE-002 (CFO fabrication 2026-03-27)

---

**Implementation:** `/Users/haotianliu/.openclaw/workspace/gov-mcp/gov_mcp/health.py`  
**MCP tools:** `gov_mcp/server.py` (lines 3212-3340)  
**Last updated:** 2026-04-10
