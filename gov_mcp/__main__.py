"""Entry point: python -m gov_mcp [command|options].

Commands:
  install    — Detect ecosystems, start server, configure clients
  uninstall  — Stop server, remove configs
  status     — Show server state
  restart    — Restart server

Server mode (original):
  python -m gov_mcp --agents-md ./AGENTS.md [--transport stdio|sse] [--port N]
"""

import sys


def main() -> None:
    # Route to CLI commands if first arg is a known command
    cli_commands = {"install", "uninstall", "status", "restart"}
    if len(sys.argv) > 1 and sys.argv[1] in cli_commands:
        from gov_mcp.cli import cli_main
        sys.exit(cli_main())

    # Otherwise: original server mode
    import argparse
    from pathlib import Path
    from typing import Optional

    parser = argparse.ArgumentParser(description="GOV MCP — Y*gov as a standard MCP server")
    parser.add_argument(
        "--session-config", type=str, default=None,
        help="Path to .ystar_session.json (Y*gov runtime config). "
             "Recommended since gov-mcp 0.2.0. Direct dict load, "
             "confidence ≥0.95.",
    )
    parser.add_argument(
        "--agents-md", type=str, default=None,
        help="[DEPRECATED since 0.2.0] Path to AGENTS.md governance file. "
             "Falls back to regex translation, confidence ≤0.7. "
             "Use --session-config instead.",
    )
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio", help="MCP transport (default: stdio)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="SSE host (only with --transport sse)")
    parser.add_argument("--port", type=int, default=0, help="SSE port (required with --transport sse)")
    parser.add_argument("--exec-whitelist", type=str, default=None, help="Path to exec_whitelist.yaml (default: adjacent to server.py)")
    args = parser.parse_args()

    # ── Contract source resolution (GOV-007 Step 2) ─────────────────
    if not args.session_config and not args.agents_md:
        print(
            "Error: must provide either --session-config (recommended) "
            "or --agents-md (deprecated)",
            file=sys.stderr,
        )
        sys.exit(1)

    session_config_path: Optional[Path] = None
    agents_md_path: Optional[Path] = None
    contract_source_label: str = ""

    if args.session_config:
        session_config_path = Path(args.session_config).resolve()
        if not session_config_path.is_file():
            print(f"Error: {session_config_path} does not exist", file=sys.stderr)
            sys.exit(1)
        contract_source_label = str(session_config_path)
        if args.agents_md:
            print(
                "[GOV MCP] both --session-config and --agents-md provided; "
                "using --session-config and ignoring --agents-md",
                file=sys.stderr,
            )
    else:
        # --agents-md only (deprecated path)
        agents_md_path = Path(args.agents_md).resolve()
        if not agents_md_path.is_file():
            print(f"Error: {agents_md_path} does not exist", file=sys.stderr)
            sys.exit(1)
        contract_source_label = str(agents_md_path)
        print(
            "[GOV MCP] [DEPRECATED] --agents-md mode is deprecated since "
            "0.2.0. Migrate to --session-config <.ystar_session.json> "
            "for higher confidence (≥0.95) and structured rule loading.",
            file=sys.stderr,
        )

    exec_whitelist_path = Path(args.exec_whitelist).resolve() if args.exec_whitelist else None

    from gov_mcp.server import create_server

    sse_kwargs = {}
    if args.transport == "sse":
        if args.port == 0:
            print("Error: --port is required with --transport sse", file=sys.stderr)
            sys.exit(1)
        sse_kwargs = {"host": args.host, "port": args.port}

    server = create_server(
        agents_md_path=agents_md_path,
        session_config_path=session_config_path,
        exec_whitelist_path=exec_whitelist_path,
        **sse_kwargs,
    )

    tools = [t.name for t in server._tool_manager._tools.values()]
    print(f"[GOV MCP] ready — {len(tools)} tools registered, transport={args.transport}", file=sys.stderr)
    if sse_kwargs:
        print(f"[GOV MCP] SSE listening on {args.host}:{args.port}", file=sys.stderr)
    print(f"[GOV MCP] contract loaded from {contract_source_label}", file=sys.stderr)

    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
