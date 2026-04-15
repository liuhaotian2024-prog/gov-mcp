#!/usr/bin/env python3
"""
gov_health — Agent Degradation Detection System (Board P0)

100% deterministic (no LLM). Analyzes CIEU event streams to detect
five degradation signals. v1 configuration per Board decision:

Active signals (weighted):
  - Repetition (31.25%): hash fingerprint matching in sliding window
  - Obligation Decay (31.25%): completion rate decline over session
  - Inflation (18.75%): tool call count anomaly for same task type
  - Fabrication (18.75%): violation pattern matching

Observation-only signal (0% weight, recorded but not scored):
  - Contradiction: reverse actions within window (high false positive rate)

Health score: 0-100 scale, threshold=60 (v1 fixed, no per-agent customization).

Reset protocol:
  - 40+: agent may soft-reset
  - 25-40: requires supervisor confirmation
  - <25: requires Board decision
  - All resets must notify supervisor via gov_dispatch (violation if skipped)

Design: Pure function + SQLite query. Zero state. Can run on historical data.
"""

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ============================================================================
# Configuration (Board-approved v1)
# ============================================================================

SIGNAL_WEIGHTS = {
    "repetition": 0.3125,
    "obligation_decay": 0.3125,
    "inflation": 0.1875,
    "fabrication": 0.1875,
    "contradiction": 0.0,  # Observation mode only
}

HEALTH_THRESHOLD_DEFAULT = 60.0
RESET_THRESHOLDS = {
    "soft_reset_min": 40.0,
    "supervisor_confirm_max": 40.0,
    "board_decision_max": 25.0,
}

# Signal-specific parameters
REPETITION_WINDOW = 20
REPETITION_THRESHOLD = 0.3  # % of window that are duplicates
INFLATION_BASELINE_MULTIPLIER = 2.5  # Alert if tool calls > baseline * multiplier
CONTRADICTION_WINDOW = 10


# ============================================================================
# Data structures
# ============================================================================

@dataclass
class HealthSignal:
    """Individual degradation signal result."""
    name: str
    raw_score: float  # 0-100 (100 = perfect health)
    weight: float
    weighted_contribution: float
    details: Dict[str, Any] = field(default_factory=dict)
    alerts: List[str] = field(default_factory=list)


@dataclass
class HealthReport:
    """Complete health assessment for a session/window."""
    session_id: str
    agent_id: str
    window_start: float
    window_end: float
    event_count: int

    overall_health: float  # 0-100
    signals: List[HealthSignal]
    trend: str  # "stable", "degrading", "improving", "insufficient_data"
    recommendation: str
    alerts: List[str]

    reset_allowed: str  # "self", "supervisor", "board", "none"

    # Metadata
    computed_at: float = field(default_factory=time.time)


# ============================================================================
# Fingerprinting for repetition detection
# ============================================================================

def event_fingerprint(event: Dict[str, Any]) -> str:
    """
    Generate stable hash fingerprint for an event.

    Matches on: event_type, tool_name (from task_description), file_path, command.
    Ignores: timestamps, event_id, decision outcomes.

    This is the "semantic action signature" — two events with same fingerprint
    represent the agent doing the same thing again.
    """
    parts = []

    # Event type (e.g., "Read", "Write", "INTENT_DECLARED")
    if event.get("event_type"):
        parts.append(f"type:{event['event_type']}")

    # File path (if present)
    if event.get("file_path"):
        parts.append(f"file:{event['file_path']}")

    # Command (if present, normalized)
    if event.get("command"):
        # Normalize whitespace but keep core structure
        cmd = " ".join(event["command"].split())
        parts.append(f"cmd:{cmd}")

    # Tool name extraction from task_description (if present)
    if event.get("task_description"):
        # Common pattern: tool calls are logged as "tool_name(params)"
        desc = event["task_description"]
        if "(" in desc:
            tool = desc.split("(")[0].strip()
            parts.append(f"tool:{tool}")

    signature = "|".join(sorted(parts))
    return hashlib.sha256(signature.encode()).hexdigest()[:16]


# ============================================================================
# Signal 1: Repetition Detection
# ============================================================================

def detect_repetition(events: List[Dict[str, Any]], window_size: int = REPETITION_WINDOW) -> HealthSignal:
    """
    Detect repeated actions within a sliding window.

    Logic:
      - Compute fingerprint for each event
      - Count unique vs total in window
      - High repetition = low health score

    Returns:
      HealthSignal with raw_score 0-100 (100 = no repetition)
    """
    if len(events) < 5:
        return HealthSignal(
            name="repetition",
            raw_score=100.0,
            weight=SIGNAL_WEIGHTS["repetition"],
            weighted_contribution=100.0 * SIGNAL_WEIGHTS["repetition"],
            details={"status": "insufficient_data"},
        )

    # Use last window_size events
    window = events[-window_size:] if len(events) > window_size else events

    fingerprints = [event_fingerprint(e) for e in window]
    unique_count = len(set(fingerprints))
    total_count = len(fingerprints)

    repetition_rate = 1.0 - (unique_count / total_count)

    # Score: 100 when no repetition, 0 when 100% repetition
    # Apply threshold: above REPETITION_THRESHOLD, scale linearly down
    if repetition_rate <= REPETITION_THRESHOLD:
        raw_score = 100.0
    else:
        # Linear decay from 100 to 0 as repetition goes from threshold to 1.0
        excess = repetition_rate - REPETITION_THRESHOLD
        max_excess = 1.0 - REPETITION_THRESHOLD
        raw_score = max(0.0, 100.0 * (1.0 - excess / max_excess))

    alerts = []
    if repetition_rate > REPETITION_THRESHOLD:
        alerts.append(f"High repetition detected: {repetition_rate:.1%} duplicate actions in recent window")

    return HealthSignal(
        name="repetition",
        raw_score=raw_score,
        weight=SIGNAL_WEIGHTS["repetition"],
        weighted_contribution=raw_score * SIGNAL_WEIGHTS["repetition"],
        details={
            "window_size": len(window),
            "unique_actions": unique_count,
            "total_actions": total_count,
            "repetition_rate": repetition_rate,
        },
        alerts=alerts,
    )


# ============================================================================
# Signal 2: Obligation Decay
# ============================================================================

def detect_obligation_decay(
    omission_db_path: Optional[Path],
    session_id: str,
    agent_id: str,
) -> HealthSignal:
    """
    Measure obligation fulfillment rate decay over session.

    Compares first half vs second half of session:
      - First half completion rate: baseline
      - Second half completion rate: current
      - Decay = baseline - current

    Returns:
      HealthSignal with raw_score 0-100 (100 = no decay, improving completion rate)
    """
    if omission_db_path is None or not omission_db_path.exists():
        return HealthSignal(
            name="obligation_decay",
            raw_score=100.0,
            weight=SIGNAL_WEIGHTS["obligation_decay"],
            weighted_contribution=100.0 * SIGNAL_WEIGHTS["obligation_decay"],
            details={"status": "no_omission_db"},
        )

    conn = sqlite3.connect(str(omission_db_path))
    conn.row_factory = sqlite3.Row

    try:
        # Get all obligations for this session/agent
        cursor = conn.execute(
            """
            SELECT obligation_id, status, created_at, updated_at
            FROM obligations
            WHERE session_id = ? AND actor_id = ?
            ORDER BY created_at ASC
            """,
            (session_id, agent_id),
        )
        obls = [dict(row) for row in cursor.fetchall()]

        if len(obls) < 4:
            # Too few obligations to measure decay
            return HealthSignal(
                name="obligation_decay",
                raw_score=100.0,
                weight=SIGNAL_WEIGHTS["obligation_decay"],
                weighted_contribution=100.0 * SIGNAL_WEIGHTS["obligation_decay"],
                details={"status": "insufficient_obligations", "total": len(obls)},
            )

        # Split into first half and second half by creation time
        mid_idx = len(obls) // 2
        first_half = obls[:mid_idx]
        second_half = obls[mid_idx:]

        def completion_rate(obligations):
            if not obligations:
                return 1.0
            completed = sum(1 for o in obligations if o["status"] in ("fulfilled", "cancelled"))
            return completed / len(obligations)

        first_rate = completion_rate(first_half)
        second_rate = completion_rate(second_half)

        # Decay metric: negative if improving, positive if degrading
        decay = first_rate - second_rate

        # Score: 100 when no decay or improving, 0 when complete collapse
        # decay = 0 → score 100
        # decay = 1.0 (from 100% to 0%) → score 0
        raw_score = max(0.0, 100.0 * (1.0 - decay))

        alerts = []
        if decay > 0.2:
            alerts.append(
                f"Obligation completion declining: {first_rate:.1%} → {second_rate:.1%}"
            )

        return HealthSignal(
            name="obligation_decay",
            raw_score=raw_score,
            weight=SIGNAL_WEIGHTS["obligation_decay"],
            weighted_contribution=raw_score * SIGNAL_WEIGHTS["obligation_decay"],
            details={
                "first_half_rate": first_rate,
                "second_half_rate": second_rate,
                "decay": decay,
                "total_obligations": len(obls),
            },
            alerts=alerts,
        )

    finally:
        conn.close()


# ============================================================================
# Signal 3: Tool Call Inflation
# ============================================================================

def detect_inflation(events: List[Dict[str, Any]]) -> HealthSignal:
    """
    Detect abnormal increase in tool call count for similar tasks.

    Logic:
      - Group events by task type (intent category or event_type)
      - For each task type, compute median tool call count (baseline)
      - Recent instances with tool_count > baseline * multiplier → inflation

    Returns:
      HealthSignal with raw_score 0-100 (100 = efficient, no inflation)
    """
    if len(events) < 10:
        return HealthSignal(
            name="inflation",
            raw_score=100.0,
            weight=SIGNAL_WEIGHTS["inflation"],
            weighted_contribution=100.0 * SIGNAL_WEIGHTS["inflation"],
            details={"status": "insufficient_data"},
        )

    # Group events by task signature (simplified: by event_type)
    # In a real system, would cluster by semantic intent
    task_groups: Dict[str, List[int]] = {}

    # Count consecutive events of same type as one "task instance"
    task_instances = []
    current_task = None
    current_count = 0

    for e in events:
        etype = e.get("event_type", "unknown")
        if etype == current_task:
            current_count += 1
        else:
            if current_task is not None:
                task_instances.append((current_task, current_count))
            current_task = etype
            current_count = 1

    if current_task is not None:
        task_instances.append((current_task, current_count))

    # Group by task type
    for task_type, count in task_instances:
        if task_type not in task_groups:
            task_groups[task_type] = []
        task_groups[task_type].append(count)

    # Check for inflation: recent instances > baseline
    inflation_cases = []
    total_checks = 0

    for task_type, counts in task_groups.items():
        if len(counts) < 3:
            continue

        # Baseline: median of all instances except last
        baseline = sorted(counts[:-1])[len(counts[:-1]) // 2]
        recent = counts[-1]

        total_checks += 1
        if recent > baseline * INFLATION_BASELINE_MULTIPLIER:
            inflation_cases.append({
                "task_type": task_type,
                "baseline": baseline,
                "recent": recent,
                "ratio": recent / max(baseline, 1),
            })

    if total_checks == 0:
        inflation_rate = 0.0
    else:
        inflation_rate = len(inflation_cases) / total_checks

    # Score: 100 when no inflation, 0 when all tasks inflated
    raw_score = max(0.0, 100.0 * (1.0 - inflation_rate))

    alerts = []
    for case in inflation_cases:
        alerts.append(
            f"Tool inflation in {case['task_type']}: "
            f"{case['recent']} calls (baseline {case['baseline']}, {case['ratio']:.1f}x)"
        )

    return HealthSignal(
        name="inflation",
        raw_score=raw_score,
        weight=SIGNAL_WEIGHTS["inflation"],
        weighted_contribution=raw_score * SIGNAL_WEIGHTS["inflation"],
        details={
            "total_task_types": len(task_groups),
            "inflated_count": len(inflation_cases),
            "inflation_rate": inflation_rate,
            "cases": inflation_cases[:3],  # Top 3 for brevity
        },
        alerts=alerts,
    )


# ============================================================================
# Signal 4: Fabrication Detection
# ============================================================================

def detect_fabrication(events: List[Dict[str, Any]]) -> HealthSignal:
    """
    Detect data fabrication via violation pattern analysis.

    Fabrication violations have specific signatures:
      - Multiple violations with "fabrication" or "fake" in message
      - Violations in reporting/metrics dimensions
      - Pattern of deny → allow → deny (attempting to bypass)

    Returns:
      HealthSignal with raw_score 0-100 (100 = no fabrication detected)
    """
    if len(events) < 5:
        return HealthSignal(
            name="fabrication",
            raw_score=100.0,
            weight=SIGNAL_WEIGHTS["fabrication"],
            weighted_contribution=100.0 * SIGNAL_WEIGHTS["fabrication"],
            details={"status": "insufficient_data"},
        )

    fabrication_indicators = 0
    total_violations = 0
    details_list = []

    for e in events:
        if e.get("passed") == 0:  # Violation
            total_violations += 1
            violations_json = e.get("violations", "[]")

            try:
                violations = json.loads(violations_json) if isinstance(violations_json, str) else violations_json
            except:
                violations = []

            for v in violations:
                msg = v.get("message", "").lower()
                dimension = v.get("dimension", "").lower()

                # Fabrication keywords
                if any(kw in msg for kw in ["fabricat", "fake", "forged", "synthetic", "made up"]):
                    fabrication_indicators += 1
                    details_list.append({
                        "event_type": e.get("event_type"),
                        "dimension": dimension,
                        "message": v.get("message", ""),
                    })

                # Reporting dimension violations (common fabrication vector)
                if any(kw in dimension for kw in ["report", "metric", "analytics", "performance"]):
                    fabrication_indicators += 1
                    details_list.append({
                        "event_type": e.get("event_type"),
                        "dimension": dimension,
                        "message": v.get("message", ""),
                    })

    # Score: penalize based on fabrication indicator rate
    if total_violations == 0:
        raw_score = 100.0
    else:
        fabrication_rate = fabrication_indicators / len(events)
        # Even 1 fabrication per 100 events is serious
        raw_score = max(0.0, 100.0 * (1.0 - fabrication_rate * 50))

    alerts = []
    if fabrication_indicators > 0:
        alerts.append(f"Fabrication indicators detected: {fabrication_indicators} instances")

    return HealthSignal(
        name="fabrication",
        raw_score=raw_score,
        weight=SIGNAL_WEIGHTS["fabrication"],
        weighted_contribution=raw_score * SIGNAL_WEIGHTS["fabrication"],
        details={
            "total_violations": total_violations,
            "fabrication_indicators": fabrication_indicators,
            "samples": details_list[:3],
        },
        alerts=alerts,
    )


# ============================================================================
# Signal 5: Contradiction (observation mode, weight=0)
# ============================================================================

def detect_contradiction(events: List[Dict[str, Any]], window_size: int = CONTRADICTION_WINDOW) -> HealthSignal:
    """
    Detect contradictory actions within a window (observation mode only).

    Contradiction patterns:
      - Write file → Read file → Write same file (different content)
      - Create → Delete → Create same entity
      - Declare intent → Reject intent → Declare same intent

    HIGH FALSE POSITIVE RATE: Normal workflow includes "check → fix → verify".
    Board decision: record but don't penalize (weight=0).

    Returns:
      HealthSignal with weight=0 (observation only)
    """
    if len(events) < 3:
        return HealthSignal(
            name="contradiction",
            raw_score=100.0,
            weight=0.0,
            weighted_contribution=0.0,
            details={"status": "insufficient_data", "mode": "observation"},
        )

    window = events[-window_size:] if len(events) > window_size else events

    contradictions = []

    # Pattern: action → reverse_action on same target
    for i in range(len(window) - 1):
        e1 = window[i]
        e2 = window[i + 1]

        # Write → Write same file (if content differs, indicates back-and-forth)
        if (e1.get("event_type") == "Write" and e2.get("event_type") == "Write" and
            e1.get("file_path") == e2.get("file_path")):
            contradictions.append({
                "pattern": "write_rewrite",
                "target": e1.get("file_path"),
            })

        # INTENT_DECLARED → INTENT_REJECTED for same intent
        if (e1.get("event_type") == "INTENT_DECLARED" and e2.get("event_type") == "INTENT_REJECTED" and
            e1.get("task_description") == e2.get("task_description")):
            contradictions.append({
                "pattern": "intent_reversal",
                "target": e1.get("task_description"),
            })

    contradiction_rate = len(contradictions) / len(window)

    # Purely observational — always score 100 (no penalty)
    raw_score = 100.0

    alerts = []
    if len(contradictions) > 0:
        alerts.append(
            f"[OBSERVATION] {len(contradictions)} contradictory patterns detected "
            f"(not penalized in v1)"
        )

    return HealthSignal(
        name="contradiction",
        raw_score=raw_score,
        weight=0.0,  # Board decision: observation only
        weighted_contribution=0.0,
        details={
            "mode": "observation",
            "window_size": len(window),
            "contradictions_detected": len(contradictions),
            "contradiction_rate": contradiction_rate,
            "samples": contradictions[:3],
        },
        alerts=alerts,
    )


# ============================================================================
# Health computation and trend analysis
# ============================================================================

def compute_health_score(
    cieu_db_path: Path,
    omission_db_path: Optional[Path],
    session_id: str,
    window_size: int = 20,
    threshold: float = HEALTH_THRESHOLD_DEFAULT,
) -> HealthReport:
    """
    Compute comprehensive health score for a session.

    Args:
        cieu_db_path: Path to CIEU database
        omission_db_path: Optional path to omission database
        session_id: Session identifier
        window_size: Number of recent events to analyze
        threshold: Health threshold (default 60.0)

    Returns:
        HealthReport with overall score and detailed signal breakdown
    """
    conn = sqlite3.connect(str(cieu_db_path))
    conn.row_factory = sqlite3.Row

    try:
        # Fetch events for this session
        cursor = conn.execute(
            """
            SELECT *
            FROM cieu_events
            WHERE session_id = ?
            ORDER BY created_at ASC
            """,
            (session_id,),
        )
        events = [dict(row) for row in cursor.fetchall()]

        if not events:
            raise ValueError(f"No events found for session {session_id}")

        agent_id = events[0].get("agent_id", "unknown")
        window_start = events[-window_size]["created_at"] if len(events) > window_size else events[0]["created_at"]
        window_end = events[-1]["created_at"]

        # Compute all signals
        signals = [
            detect_repetition(events, window_size),
            detect_obligation_decay(omission_db_path, session_id, agent_id),
            detect_inflation(events),
            detect_fabrication(events),
            detect_contradiction(events),  # Observation only
        ]

        # Overall health: weighted sum
        overall_health = sum(s.weighted_contribution for s in signals)

        # Aggregate alerts
        all_alerts = []
        for s in signals:
            all_alerts.extend(s.alerts)

        # Determine trend (requires historical data — simplified for v1)
        trend = "stable"  # TODO: implement historical comparison in gov_health_retrospective

        # Recommendation
        if overall_health >= threshold:
            recommendation = "Health nominal. Continue normal operations."
        elif overall_health >= RESET_THRESHOLDS["supervisor_confirm_max"]:
            recommendation = "Health below threshold. Consider soft reset (re-read governance contract)."
        elif overall_health >= RESET_THRESHOLDS["board_decision_max"]:
            recommendation = "Health degraded. Supervisor confirmation required for reset."
        else:
            recommendation = "Critical degradation. Board decision required."

        # Reset permission level
        if overall_health >= RESET_THRESHOLDS["soft_reset_min"]:
            reset_allowed = "self"
        elif overall_health >= RESET_THRESHOLDS["board_decision_max"]:
            reset_allowed = "supervisor"
        else:
            reset_allowed = "board"

        return HealthReport(
            session_id=session_id,
            agent_id=agent_id,
            window_start=window_start,
            window_end=window_end,
            event_count=len(events),
            overall_health=overall_health,
            signals=signals,
            trend=trend,
            recommendation=recommendation,
            alerts=all_alerts,
            reset_allowed=reset_allowed,
        )

    finally:
        conn.close()


def health_report_to_dict(report: HealthReport) -> Dict[str, Any]:
    """Convert HealthReport to JSON-serializable dict."""
    return {
        "session_id": report.session_id,
        "agent_id": report.agent_id,
        "window": {
            "start": report.window_start,
            "end": report.window_end,
            "event_count": report.event_count,
        },
        "overall_health": round(report.overall_health, 2),
        "threshold": HEALTH_THRESHOLD_DEFAULT,
        "status": "healthy" if report.overall_health >= HEALTH_THRESHOLD_DEFAULT else "degraded",
        "signals": [
            {
                "name": s.name,
                "raw_score": round(s.raw_score, 2),
                "weight": s.weight,
                "contribution": round(s.weighted_contribution, 2),
                "details": s.details,
                "alerts": s.alerts,
            }
            for s in report.signals
        ],
        "trend": report.trend,
        "recommendation": report.recommendation,
        "alerts": report.alerts,
        "reset_policy": {
            "allowed_by": report.reset_allowed,
            "thresholds": RESET_THRESHOLDS,
            "supervisor_notification_required": True,  # Iron rule
        },
        "computed_at": report.computed_at,
    }


# ============================================================================
# Retrospective analysis (historical batch processing)
# ============================================================================

def retrospective_analysis(
    cieu_db_path: Path,
    omission_db_path: Optional[Path],
    session_id: Optional[str] = None,
    checkpoint_interval: int = 10,
) -> Dict[str, Any]:
    """
    Run health analysis on historical CIEU data.

    For each session (or specified session), compute health score at multiple
    checkpoints throughout the session lifetime to detect degradation patterns.

    Args:
        cieu_db_path: Path to CIEU database
        omission_db_path: Optional path to omission database
        session_id: Analyze specific session (None = all sessions)
        checkpoint_interval: Compute health every N events

    Returns:
        Dict with session timelines and degradation patterns
    """
    conn = sqlite3.connect(str(cieu_db_path))
    conn.row_factory = sqlite3.Row

    try:
        # Get all sessions or specific session
        if session_id:
            sessions = [session_id]
        else:
            cursor = conn.execute("SELECT DISTINCT session_id FROM cieu_events")
            sessions = [row["session_id"] for row in cursor.fetchall()]

        results = {
            "total_sessions": len(sessions),
            "sessions": {},
            "high_risk_agents": [],
            "degradation_patterns": {},
        }

        for sid in sessions:
            cursor = conn.execute(
                """
                SELECT *
                FROM cieu_events
                WHERE session_id = ?
                ORDER BY created_at ASC
                """,
                (sid,),
            )
            events = [dict(row) for row in cursor.fetchall()]

            if len(events) < checkpoint_interval:
                continue

            agent_id = events[0].get("agent_id", "unknown")

            # Compute health at multiple checkpoints
            checkpoints = []
            for i in range(checkpoint_interval, len(events) + 1, checkpoint_interval):
                window_events = events[:i]

                # Compute signals at this checkpoint
                signals = [
                    detect_repetition(window_events, min(20, i)),
                    detect_obligation_decay(omission_db_path, sid, agent_id),
                    detect_inflation(window_events),
                    detect_fabrication(window_events),
                    detect_contradiction(window_events),
                ]

                health = sum(s.weighted_contribution for s in signals)

                checkpoints.append({
                    "event_index": i,
                    "timestamp": window_events[-1]["created_at"],
                    "health": round(health, 2),
                    "signals": {s.name: round(s.raw_score, 2) for s in signals},
                })

            # Detect degradation trend
            if len(checkpoints) >= 3:
                health_values = [c["health"] for c in checkpoints]
                avg_delta = (health_values[-1] - health_values[0]) / len(health_values)

                if avg_delta < -5:
                    trend = "degrading"
                    if health_values[-1] < HEALTH_THRESHOLD_DEFAULT:
                        results["high_risk_agents"].append({
                            "agent_id": agent_id,
                            "session_id": sid,
                            "final_health": health_values[-1],
                            "decline_rate": round(avg_delta, 2),
                        })
                elif avg_delta > 5:
                    trend = "improving"
                else:
                    trend = "stable"
            else:
                trend = "insufficient_data"

            results["sessions"][sid] = {
                "agent_id": agent_id,
                "total_events": len(events),
                "checkpoints": checkpoints,
                "trend": trend,
                "final_health": checkpoints[-1]["health"] if checkpoints else None,
            }

        return results

    finally:
        conn.close()
