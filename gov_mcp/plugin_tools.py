"""Plugin tools for gov-mcp MCP marketplace integration.

This module defines tools declared in plugin.json that are NOT already in server.py.
Day 2: Implement 2 tools fully (gov_query_cieu, gov_path_verify), 2 stubs.

Tools in plugin.json already implemented in server.py (skip here):
- gov_check (line 873)
- gov_delegate (line 1034)
- gov_doctor (line 2057)
- gov_escalate (line 1107)

New tools to implement (plugin.json unique):
- gov_query_cieu (query CIEU audit log)
- gov_install (setup governance for project)
- gov_omission_scan (detect missing checks)
- gov_path_verify (validate file path access)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, List

from mcp.server.fastmcp import FastMCP


def register_plugin_tools(mcp: FastMCP, state: Any) -> None:
    """Register 4 unique plugin tools with FastMCP server.

    Args:
        mcp: FastMCP server instance
        state: _State object from server.py (has _cieu_store, omission_engine, contract)
    """

    # ========================================================================
    # FULLY IMPLEMENTED (Day 2)
    # ========================================================================

    @mcp.tool()
    def gov_query_cieu(
        event_type: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 100,
    ) -> str:
        """Query CIEU audit log (Contextual, Intervention, Execution, Update records).

        Args:
            event_type: Filter by event type (C/I/E/U), default shows all
            agent_id: Filter by agent ID, default shows all agents
            limit: Max number of events to return (default 100)

        Returns:
            JSON array of CIEU events matching filters
        """
        try:
            if state._cieu_store is None:
                return json.dumps({
                    "error": "CIEU store not initialized",
                    "events": [],
                    "count": 0,
                })

            # Query CIEU store
            all_events = state._cieu_store.query(limit=limit)

            # Apply filters
            filtered_events = []
            for evt in all_events:
                # Filter by event_type if specified
                if event_type is not None:
                    evt_type = evt.get("event_type", "")
                    if not evt_type.startswith(event_type.upper()):
                        continue

                # Filter by agent_id if specified
                if agent_id is not None:
                    if evt.get("agent") != agent_id:
                        continue

                filtered_events.append(evt)

            return json.dumps({
                "events": filtered_events,
                "count": len(filtered_events),
                "filters": {
                    "event_type": event_type,
                    "agent_id": agent_id,
                    "limit": limit,
                },
            }, indent=2)

        except Exception as e:
            return json.dumps({
                "error": str(e),
                "events": [],
                "count": 0,
            })

    @mcp.tool()
    def gov_path_verify(
        file_path: str,
        agent_id: Optional[str] = None,
    ) -> str:
        """Verify file path access is within allowed scopes.

        Args:
            file_path: Path to verify
            agent_id: Agent requesting access (defaults to current agent)

        Returns:
            JSON with verification result (allowed/denied + scope info)
        """
        try:
            from ystar import check, CheckResult

            # Get current agent from state if not provided
            if agent_id is None:
                agent_id = getattr(state, 'current_agent_id', 'unknown')

            # Run path check through Y*gov kernel
            result: CheckResult = check(
                agent_id=agent_id,
                file_path=file_path,
            )

            # Find which scope matched (if any)
            matched_scope = None
            if result.allowed and state.contract:
                for allowed_path in state.contract.only_paths:
                    if Path(file_path).is_relative_to(Path(allowed_path)):
                        matched_scope = allowed_path
                        break

            return json.dumps({
                "allowed": result.allowed,
                "file_path": file_path,
                "agent_id": agent_id,
                "matched_scope": matched_scope,
                "reason": result.reason or "",
                "violations": [str(v) for v in result.violations] if hasattr(result, 'violations') else [],
            }, indent=2)

        except Exception as e:
            return json.dumps({
                "allowed": False,
                "file_path": file_path,
                "agent_id": agent_id,
                "error": str(e),
            }, indent=2)

    # ========================================================================
    # STUBS (Day 3+)
    # ========================================================================

    @mcp.tool()
    def gov_install(project_dir: str) -> str:
        """Install governance contracts for a project directory.

        Args:
            project_dir: Path to project root (will create .ystar_session.json + AGENTS.md)

        Returns:
            JSON with installation status + created files list
        """
        return json.dumps({
            "status": "not_implemented",
            "tool": "gov_install",
            "message": "Day 3+ implementation pending (will wrap 'ystar setup' + 'ystar init')",
            "params": {"project_dir": project_dir},
        }, indent=2)

    @mcp.tool()
    def gov_omission_scan(
        lookback_hours: int = 24,
        min_confidence: float = 0.7,
    ) -> str:
        """Scan for missing governance checks in recent actions.

        Args:
            lookback_hours: How far back to scan (default 24h)
            min_confidence: Minimum confidence threshold for flagging omissions (0.0-1.0)

        Returns:
            JSON with list of detected omissions + confidence scores
        """
        return json.dumps({
            "status": "not_implemented",
            "tool": "gov_omission_scan",
            "message": "Day 3+ implementation pending (will use state.omission_engine.scan)",
            "params": {
                "lookback_hours": lookback_hours,
                "min_confidence": min_confidence,
            },
        }, indent=2)
