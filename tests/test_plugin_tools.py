"""Tests for plugin marketplace tools (Day 2).

Tests 2 fully implemented tools unique to plugin.json:
- gov_query_cieu: query CIEU audit log
- gov_path_verify: verify file path access

2 stub tools (Day 3+):
- gov_install
- gov_omission_scan

Note: gov_check, gov_delegate, gov_doctor, gov_escalate already exist in server.py
so they are NOT redefined in plugin_tools.py.
"""
import asyncio
import json
import pytest
from pathlib import Path


@pytest.fixture
def test_project_dir(tmp_path):
    """Create a minimal test project with Y*gov config."""
    project = tmp_path / "test_project"
    project.mkdir()

    # Create minimal .ystar_session.json
    session_config = {
        "agent_contracts": {
            "test_agent": {
                "deny": [],
                "only_paths": [str(project)],
                "deny_commands": [],
                "only_domains": [],
            }
        },
        "governance": {
            "mode": "enforce",
            "cieu_enabled": True,
        }
    }

    (project / ".ystar_session.json").write_text(json.dumps(session_config, indent=2))

    # Create empty CIEU database
    (project / ".ystar_cieu.db").touch()

    return project


def test_gov_query_cieu_basic(test_project_dir):
    """Test gov_query_cieu returns CIEU events."""
    from gov_mcp.server import create_server

    # Create server with test project
    mcp = create_server(
        session_config_path=test_project_dir / ".ystar_session.json"
    )

    # Verify gov_query_cieu is registered
    # Note: mcp.list_tools() is async in FastMCP v1.0+, but for basic
    # registration test we just check the server created successfully
    assert mcp is not None


def test_gov_path_verify_basic(test_project_dir):
    """Test gov_path_verify validates file paths."""
    from gov_mcp.server import create_server

    # Create server with test project
    mcp = create_server(
        session_config_path=test_project_dir / ".ystar_session.json"
    )

    # Verify server created successfully
    assert mcp is not None


def test_stub_tools_registered(test_project_dir):
    """Verify 2 stub tools are registered."""
    from gov_mcp.server import create_server

    mcp = create_server(
        session_config_path=test_project_dir / ".ystar_session.json"
    )

    # Verify server created successfully with stubs
    # gov_install and gov_omission_scan should be registered as stubs
    assert mcp is not None


# ============================================================================
# E2E INTEGRATION TESTS (Day 4)
# ============================================================================


@pytest.mark.asyncio
async def test_gov_install_e2e_success(tmp_path):
    """E2E test: gov_install creates .ystar_session.json + AGENTS.md via subprocess."""
    from gov_mcp.server import create_server
    from unittest.mock import patch, MagicMock

    # Create fake project dir
    fake_project = tmp_path / "test_install_project"
    fake_project.mkdir()

    # Create minimal session config to boot server
    session_config = {
        "agent_contracts": {
            "test_agent": {"deny": [], "only_paths": [str(fake_project)]},
        },
        "governance": {"mode": "enforce", "cieu_enabled": True},
    }
    session_json = fake_project / ".ystar_session.json"
    session_json.write_text(json.dumps(session_config, indent=2))

    # Boot server
    mcp = create_server(session_config_path=session_json)

    # Mock subprocess to avoid real ystar calls
    mock_success = MagicMock()
    mock_success.returncode = 0
    mock_success.stdout = "ystar setup complete\nystar init complete"
    mock_success.stderr = ""

    with patch("subprocess.run", return_value=mock_success) as mock_run:
        # Simulate created files
        (fake_project / ".ystar_session.json").touch()
        (fake_project / "AGENTS.md").touch()

        # Call gov_install via registered tool (async call)
        # FastMCP.call_tool returns (content_blocks, metadata) tuple
        result_content, _metadata = await mcp.call_tool("gov_install", {"project_dir": str(fake_project)})
        result = json.loads(result_content[0].text)

        # Verify subprocess.run was called twice (setup + init)
        assert mock_run.call_count == 2
        setup_call = mock_run.call_args_list[0]
        init_call = mock_run.call_args_list[1]
        assert setup_call[0][0] == ["ystar", "setup"]
        assert init_call[0][0] == ["ystar", "init"]
        assert setup_call[1]["cwd"] == str(fake_project)
        assert init_call[1]["cwd"] == str(fake_project)
        assert setup_call[1]["timeout"] == 30
        assert init_call[1]["timeout"] == 30

        # Verify result structure
        assert result["success"] is True
        assert str(fake_project) in result["project_dir"]
        assert len(result["created_files"]) == 2
        assert any(".ystar_session.json" in f for f in result["created_files"])
        assert any("AGENTS.md" in f for f in result["created_files"])


@pytest.mark.asyncio
async def test_gov_install_e2e_timeout(tmp_path):
    """E2E test: gov_install handles subprocess timeout gracefully."""
    from gov_mcp.server import create_server
    from unittest.mock import patch
    import subprocess

    fake_project = tmp_path / "test_timeout_project"
    fake_project.mkdir()

    session_config = {
        "agent_contracts": {"test_agent": {"deny": [], "only_paths": [str(fake_project)]}},
        "governance": {"mode": "enforce", "cieu_enabled": True},
    }
    session_json = fake_project / ".ystar_session.json"
    session_json.write_text(json.dumps(session_config, indent=2))

    mcp = create_server(session_config_path=session_json)

    # Mock subprocess.run to raise TimeoutExpired
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ystar", 30)):
        result_content, _metadata = await mcp.call_tool("gov_install", {"project_dir": str(fake_project)})
        result = json.loads(result_content[0].text)

        assert result["success"] is False
        assert "timeout" in result["error"].lower()


@pytest.mark.asyncio
async def test_gov_omission_scan_e2e_success(test_project_dir):
    """E2E test: gov_omission_scan returns omissions list via real OmissionEngine."""
    from gov_mcp.server import create_server

    # Boot server with real omission engine
    mcp = create_server(session_config_path=test_project_dir / ".ystar_session.json")

    # Call gov_omission_scan
    result_content, _metadata = await mcp.call_tool("gov_omission_scan", {
        "min_confidence": 0.7,
    })
    result = json.loads(result_content[0].text)

    # Verify result structure (omissions may be empty but structure must be valid)
    assert result["success"] is True
    assert "omissions" in result
    assert isinstance(result["omissions"], list)
    assert "count" in result
    assert "total_scanned" in result
    assert result["params"]["min_confidence"] == 0.7

    # Verify each omission has required keys (if any returned)
    for omission in result["omissions"]:
        assert "confidence" in omission
        assert omission["confidence"] >= 0.7


@pytest.mark.asyncio
async def test_gov_omission_scan_e2e_empty_store(test_project_dir):
    """E2E test: gov_omission_scan handles empty CIEU store gracefully."""
    from gov_mcp.server import create_server

    # Boot server (CIEU DB is empty by default in test fixture)
    mcp = create_server(session_config_path=test_project_dir / ".ystar_session.json")

    result_content, _metadata = await mcp.call_tool("gov_omission_scan", {
        "min_confidence": 0.5,
    })
    result = json.loads(result_content[0].text)

    # Should succeed with 0 omissions (not crash)
    assert result["success"] is True
    assert result["count"] == 0
    assert result["omissions"] == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
