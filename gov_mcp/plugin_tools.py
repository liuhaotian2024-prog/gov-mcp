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
        import subprocess
        from pathlib import Path

        try:
            project_path = Path(project_dir).resolve()
            if not project_path.exists():
                return json.dumps({
                    "success": False,
                    "error": f"Project directory does not exist: {project_dir}",
                }, indent=2)

            # Run ystar setup + init via subprocess
            setup_result = subprocess.run(
                ["ystar", "setup"],
                cwd=str(project_path),
                capture_output=True,
                text=True,
                timeout=30,
            )

            if setup_result.returncode != 0:
                return json.dumps({
                    "success": False,
                    "step": "ystar setup",
                    "error": setup_result.stderr or setup_result.stdout,
                }, indent=2)

            init_result = subprocess.run(
                ["ystar", "init"],
                cwd=str(project_path),
                capture_output=True,
                text=True,
                timeout=30,
            )

            if init_result.returncode != 0:
                return json.dumps({
                    "success": False,
                    "step": "ystar init",
                    "error": init_result.stderr or init_result.stdout,
                }, indent=2)

            # Check created files
            created_files = []
            session_json = project_path / ".ystar_session.json"
            agents_md = project_path / "AGENTS.md"

            if session_json.exists():
                created_files.append(str(session_json))
            if agents_md.exists():
                created_files.append(str(agents_md))

            return json.dumps({
                "success": True,
                "project_dir": str(project_path),
                "created_files": created_files,
                "setup_output": setup_result.stdout,
                "init_output": init_result.stdout,
            }, indent=2)

        except subprocess.TimeoutExpired:
            return json.dumps({
                "success": False,
                "error": "Installation timeout (>30s)",
            }, indent=2)
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e),
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
        try:
            if state.omission_engine is None:
                return json.dumps({
                    "success": False,
                    "error": "Omission engine not initialized",
                }, indent=2)

            # Run omission scan via Y*gov OmissionEngine
            # OmissionEngine.scan() returns List[Dict] with detected omissions
            omissions = state.omission_engine.scan(
                lookback_hours=lookback_hours,
                min_confidence=min_confidence,
            )

            # Filter by confidence threshold
            filtered_omissions = [
                o for o in omissions
                if o.get("confidence", 0.0) >= min_confidence
            ]

            return json.dumps({
                "success": True,
                "omissions": filtered_omissions,
                "count": len(filtered_omissions),
                "total_scanned": len(omissions),
                "params": {
                    "lookback_hours": lookback_hours,
                    "min_confidence": min_confidence,
                },
            }, indent=2)

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e),
                "params": {
                    "lookback_hours": lookback_hours,
                    "min_confidence": min_confidence,
                },
            }, indent=2)
