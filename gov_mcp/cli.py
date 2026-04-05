"""gov-mcp CLI: install, uninstall, status, restart.

Ecosystem-neutral, no hardcoded paths. All detection via pathlib + shutil.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants (configurable, not hardcoded paths)
# ---------------------------------------------------------------------------

DEFAULT_PORT = 7922
PID_FILE_NAME = "gov-mcp.pid"
LOG_FILE_NAME = "gov-mcp.log"


def _state_dir() -> Path:
    """Platform-appropriate state directory for gov-mcp."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    d = base / "gov-mcp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pid_file() -> Path:
    return _state_dir() / PID_FILE_NAME


def _log_file() -> Path:
    return _state_dir() / LOG_FILE_NAME


# ---------------------------------------------------------------------------
# Environment detection
# ---------------------------------------------------------------------------

class _Ecosystem:
    """Detected client ecosystem."""
    name: str
    detected: bool
    config_path: Optional[Path]
    detail: str

    def __init__(self, name: str, detected: bool,
                 config_path: Optional[Path] = None, detail: str = ""):
        self.name = name
        self.detected = detected
        self.config_path = config_path
        self.detail = detail


def detect_ecosystems() -> List[_Ecosystem]:
    """Detect installed MCP client ecosystems."""
    results: List[_Ecosystem] = []

    # Claude Code
    claude_dir = Path.home() / ".claude"
    claude_cmd = shutil.which("claude")
    if claude_dir.is_dir() or claude_cmd:
        detail = f"CLI: {claude_cmd}" if claude_cmd else f"Config: {claude_dir}"
        results.append(_Ecosystem("claude-code", True, claude_dir, detail))
    else:
        results.append(_Ecosystem("claude-code", False))

    # Cursor
    cursor_dir = Path.home() / ".cursor"
    cursor_cmd = shutil.which("cursor")
    if cursor_dir.is_dir() or cursor_cmd:
        detail = f"Dir: {cursor_dir}" if cursor_dir.is_dir() else f"CLI: {cursor_cmd}"
        results.append(_Ecosystem("cursor", True, cursor_dir, detail))
    else:
        results.append(_Ecosystem("cursor", False))

    # Windsurf
    windsurf_dir = Path.home() / ".windsurf"
    windsurf_cmd = shutil.which("windsurf")
    if windsurf_dir.is_dir() or windsurf_cmd:
        results.append(_Ecosystem("windsurf", True, windsurf_dir))
    else:
        results.append(_Ecosystem("windsurf", False))

    # OpenClaw
    openclaw_cmd = shutil.which("openclaw")
    openclaw_dir = Path.home() / ".openclaw"
    if openclaw_cmd or openclaw_dir.is_dir():
        detail = f"CLI: {openclaw_cmd}" if openclaw_cmd else f"Dir: {openclaw_dir}"
        results.append(_Ecosystem("openclaw", True, openclaw_dir, detail))
    else:
        results.append(_Ecosystem("openclaw", False))

    return results


# ---------------------------------------------------------------------------
# Port management
# ---------------------------------------------------------------------------

def _find_available_port(start: int = DEFAULT_PORT, max_tries: int = 20) -> int:
    """Find an available port starting from `start`."""
    for offset in range(max_tries):
        port = start + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No available port found in range {start}-{start + max_tries}")


# ---------------------------------------------------------------------------
# Server management
# ---------------------------------------------------------------------------

def _read_pid() -> Optional[int]:
    pf = _pid_file()
    if pf.is_file():
        try:
            return int(pf.read_text().strip())
        except (ValueError, OSError):
            pass
    return None


def _is_running(pid: Optional[int] = None) -> bool:
    if pid is None:
        pid = _read_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _find_agents_md() -> Optional[Path]:
    """Auto-detect AGENTS.md in common locations."""
    candidates = [
        Path.cwd() / "AGENTS.md",
        Path.home() / "AGENTS.md",
        Path.cwd() / ".." / "AGENTS.md",
    ]
    for p in candidates:
        if p.resolve().is_file():
            return p.resolve()
    return None


def start_server(agents_md: Optional[Path] = None, port: int = 0) -> Tuple[int, int, Path]:
    """Start gov-mcp server in background.

    Returns (pid, port, agents_md_path).
    """
    # Find AGENTS.md
    if agents_md is None:
        agents_md = _find_agents_md()
    if agents_md is None or not agents_md.is_file():
        print("  Error: No AGENTS.md found.", file=sys.stderr)
        print("  Create one or pass --agents-md /path/to/AGENTS.md", file=sys.stderr)
        sys.exit(1)

    # Find port
    if port == 0:
        port = _find_available_port()

    # Build command
    python = sys.executable
    cmd = [
        python, "-m", "gov_mcp",
        "--agents-md", str(agents_md),
        "--transport", "sse",
        "--port", str(port),
    ]

    log = _log_file()
    with open(log, "w") as log_f:
        proc = subprocess.Popen(
            cmd,
            stdout=log_f,
            stderr=log_f,
            start_new_session=True,
        )

    # Write PID + port
    _pid_file().write_text(str(proc.pid))
    (_state_dir() / "port").write_text(str(port))
    (_state_dir() / "agents_md").write_text(str(agents_md))

    # Brief wait to check it didn't crash immediately
    time.sleep(0.5)
    if proc.poll() is not None:
        # Read log for error details
        try:
            log_content = log.read_text()
            if "ModuleNotFoundError" in log_content:
                missing = log_content.split("ModuleNotFoundError: No module named '")[1].split("'")[0]
                print(f"  Error: Missing dependency '{missing}'.", file=sys.stderr)
                print(f"  Run: pip install {missing}", file=sys.stderr)
            else:
                print(f"  Error: Server exited immediately. Check {log}", file=sys.stderr)
        except Exception:
            print(f"  Error: Server exited immediately. Check {log}", file=sys.stderr)
        sys.exit(1)

    return proc.pid, port, agents_md


def stop_server() -> bool:
    """Stop running server. Returns True if stopped."""
    pid = _read_pid()
    if pid is None or not _is_running(pid):
        return False
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            time.sleep(0.1)
            if not _is_running(pid):
                break
        else:
            os.kill(pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    _pid_file().unlink(missing_ok=True)
    return True


def _read_port() -> Optional[int]:
    pf = _state_dir() / "port"
    if pf.is_file():
        try:
            return int(pf.read_text().strip())
        except (ValueError, OSError):
            pass
    return None


# ---------------------------------------------------------------------------
# Client configuration
# ---------------------------------------------------------------------------

def _configure_claude_code(port: int) -> bool:
    """Configure Claude Code via `claude mcp add`."""
    claude_cmd = shutil.which("claude")
    if not claude_cmd:
        return False
    url = f"http://127.0.0.1:{port}/sse"
    try:
        result = subprocess.run(
            [claude_cmd, "mcp", "add", "gov-mcp",
             "--transport", "sse", "--scope", "user", url],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0
    except Exception:
        return False


def _configure_generic(ecosystem_name: str, port: int) -> str:
    """Return generic MCP config snippet for manual setup."""
    url = f"http://127.0.0.1:{port}/sse"
    config = {
        "mcpServers": {
            "gov-mcp": {
                "url": url,
                "transport": "sse",
            }
        }
    }
    return json.dumps(config, indent=2)


def _remove_claude_code() -> bool:
    """Remove gov-mcp from Claude Code."""
    claude_cmd = shutil.which("claude")
    if not claude_cmd:
        return False
    try:
        result = subprocess.run(
            [claude_cmd, "mcp", "remove", "gov-mcp", "--scope", "user"],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def _health_check(port: int, timeout: float = 5.0) -> bool:
    """Check if the server responds on the given port."""
    import urllib.request
    try:
        url = f"http://127.0.0.1:{port}/sse"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        # SSE endpoint may not respond to plain GET — try TCP connect
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=timeout):
                return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def cmd_install(args) -> int:
    """gov-mcp install — detect, start, configure, verify."""
    agents_md = Path(args.agents_md).resolve() if args.agents_md else None
    port = args.port

    print("gov-mcp install")
    print("=" * 50)

    # Step 1: Detect environment
    print("\n[1/5] Detecting environment...")
    ecosystems = detect_ecosystems()
    detected = [e for e in ecosystems if e.detected]
    for eco in ecosystems:
        marker = "+" if eco.detected else "-"
        detail = f" ({eco.detail})" if eco.detail else ""
        print(f"  [{marker}] {eco.name}{detail}")

    if not detected:
        print("  (!) No known MCP client detected. Will output generic config.")

    # Step 2: Start server
    print("\n[2/5] Starting GOV MCP server...")
    # Stop existing if running
    if _is_running():
        print("  Stopping existing server...")
        stop_server()

    pid, actual_port, agents_path = start_server(agents_md, port)
    print(f"  Server started: PID={pid}, port={actual_port}")
    print(f"  Contract: {agents_path}")
    print(f"  Log: {_log_file()}")

    # Step 3: Configure ecosystems
    print("\n[3/5] Configuring clients...")
    configured = 0
    for eco in detected:
        if eco.name == "claude-code":
            ok = _configure_claude_code(actual_port)
            if ok:
                print(f"  [+] {eco.name}: auto-configured via 'claude mcp add'")
                configured += 1
            else:
                print(f"  [!] {eco.name}: auto-config failed. Manual config:")
                print(f"      {_configure_generic(eco.name, actual_port)}")
        else:
            print(f"  [~] {eco.name}: manual config required:")
            snippet = _configure_generic(eco.name, actual_port)
            for line in snippet.split("\n"):
                print(f"      {line}")
            configured += 1  # Count as "shown"

    if not detected:
        print("  Generic MCP config:")
        snippet = _configure_generic("generic", actual_port)
        for line in snippet.split("\n"):
            print(f"      {line}")

    # Step 4: Verify
    print("\n[4/5] Verifying connection...")
    time.sleep(1)  # Give server time to fully start
    healthy = _health_check(actual_port)
    if healthy:
        print(f"  [+] Server responding on 127.0.0.1:{actual_port}")
    else:
        print(f"  [!] Server not responding yet (may still be starting)")
        print(f"      Check log: {_log_file()}")

    # Step 5: Summary
    print(f"\n[5/5] Installation summary")
    print("=" * 50)
    print(f"  Server:     http://127.0.0.1:{actual_port}/sse")
    print(f"  PID:        {pid}")
    print(f"  Contract:   {agents_path}")
    print(f"  Ecosystems: {len(detected)} detected, {configured} configured")
    print(f"  Status:     {'GOV MCP ready' if healthy else 'starting...'}")
    print()
    print("  Next step: Write governance rules in your AGENTS.md")
    print("  Example:   ## Prohibited: rm -rf, sudo, .env files")
    print()

    return 0


def cmd_uninstall(args) -> int:
    """gov-mcp uninstall — stop server, remove configs."""
    print("gov-mcp uninstall")
    print("=" * 50)

    # Stop server
    if _is_running():
        stop_server()
        print("  [+] Server stopped")
    else:
        print("  [-] Server not running")

    # Remove Claude Code config
    if shutil.which("claude"):
        ok = _remove_claude_code()
        if ok:
            print("  [+] Removed from Claude Code")
        else:
            print("  [~] Claude Code: nothing to remove or removal failed")

    # Clean state files
    state = _state_dir()
    for f in [PID_FILE_NAME, LOG_FILE_NAME, "port", "agents_md"]:
        (state / f).unlink(missing_ok=True)
    print(f"  [+] State directory cleaned: {state}")

    print("\n  GOV MCP uninstalled.")
    print("  Other MCP clients may need manual config removal.")
    return 0


def cmd_status(args) -> int:
    """gov-mcp status — show server state."""
    pid = _read_pid()
    port = _read_port()
    running = _is_running(pid)

    print("gov-mcp status")
    print("=" * 50)
    print(f"  Running:    {'yes' if running else 'no'}")
    if running:
        print(f"  PID:        {pid}")
        print(f"  Port:       {port}")
        agents_f = _state_dir() / "agents_md"
        if agents_f.is_file():
            print(f"  Contract:   {agents_f.read_text().strip()}")
        print(f"  Log:        {_log_file()}")
        if port:
            healthy = _health_check(port, timeout=2)
            print(f"  Health:     {'OK' if healthy else 'not responding'}")
    else:
        print("  Run 'gov-mcp install' to start.")

    return 0


def cmd_restart(args) -> int:
    """gov-mcp restart — stop then start."""
    print("gov-mcp restart")
    print("=" * 50)

    # Read existing config
    port = _read_port() or DEFAULT_PORT
    agents_f = _state_dir() / "agents_md"
    agents_md = Path(agents_f.read_text().strip()) if agents_f.is_file() else None

    if args.agents_md:
        agents_md = Path(args.agents_md).resolve()
    if args.port:
        port = args.port

    # Stop
    if _is_running():
        stop_server()
        print("  [+] Stopped existing server")

    # Start
    pid, actual_port, agents_path = start_server(agents_md, port)
    print(f"  [+] Restarted: PID={pid}, port={actual_port}")
    print(f"  Contract: {agents_path}")

    time.sleep(0.5)
    healthy = _health_check(actual_port, timeout=3)
    print(f"  Health: {'OK' if healthy else 'starting...'}")

    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> "argparse.ArgumentParser":
    import argparse

    parser = argparse.ArgumentParser(
        prog="gov-mcp",
        description="GOV MCP — Governed execution for AI agents",
    )
    sub = parser.add_subparsers(dest="command")

    # install
    p_install = sub.add_parser("install", help="Detect, start, configure GOV MCP")
    p_install.add_argument("--agents-md", type=str, default=None,
                           help="Path to AGENTS.md (auto-detected if omitted)")
    p_install.add_argument("--port", type=int, default=0,
                           help=f"Server port (default: {DEFAULT_PORT}, auto if busy)")

    # uninstall
    sub.add_parser("uninstall", help="Stop server and remove configs")

    # status
    sub.add_parser("status", help="Show server status")

    # restart
    p_restart = sub.add_parser("restart", help="Restart server")
    p_restart.add_argument("--agents-md", type=str, default=None)
    p_restart.add_argument("--port", type=int, default=0)

    return parser


def cli_main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "install":
        return cmd_install(args)
    elif args.command == "uninstall":
        return cmd_uninstall(args)
    elif args.command == "status":
        return cmd_status(args)
    elif args.command == "restart":
        return cmd_restart(args)
    else:
        parser.print_help()
        return 1
