#!/usr/bin/env python3
"""Entry point for the reviewer-mcp package.

Usage:
    python -m reviewer_mcp                      # Start MCP server over STDIO
    python -m reviewer_mcp --profile mistral    # Start another reviewer
    python -m reviewer_mcp --check              # Verify API access and exit
    python -m reviewer_mcp mirror-opencode --watch
    python -m reviewer_mcp report --format markdown
"""

from __future__ import annotations

import argparse
import sys

from reviewer_mcp.profiles import get_profile


def _legacy_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="reviewer-mcp — adversarial review MCP server",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify GitHub Models API access and exit",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="Reviewer profile to run: codex, mistral, llama",
    )
    return parser


def _mirror_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mirror local OpenCode sessions into brain/logs",
    )
    parser.add_argument("--brain-root", default=None, help="Path to the workspace brain directory")
    parser.add_argument("--db-path", default=None, help="Override OpenCode SQLite DB path")
    parser.add_argument("--state-dir", default=None, help="Override local reviewer state dir")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--idle-seconds", type=int, default=60)
    parser.add_argument("--watch", action="store_true", help="Keep mirroring updated sessions")
    parser.add_argument("--backfill", action="store_true", help="Mirror all known sessions once")
    parser.add_argument("--once", action="store_true", help="Mirror a single bundle once")
    parser.add_argument("--session", default=None, help="Session ID for --once mode")
    return parser


def _report_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report reviewer telemetry and mirrored transcript metrics",
    )
    parser.add_argument("--brain-root", default=None, help="Path to the workspace brain directory")
    parser.add_argument(
        "--format",
        default="markdown",
        choices=("json", "markdown", "tsv"),
        help="Output format",
    )
    parser.add_argument("--since", default=None, help="Filter logs from YYYY-MM-DD onward")
    return parser


def _autostart_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--brain-root", default=None, help="Path to the workspace brain directory")
    parser.add_argument("--db-path", default=None, help="Override OpenCode SQLite DB path")
    parser.add_argument("--state-dir", default=None, help="Override local reviewer state dir")
    parser.add_argument("--python", dest="python_executable", default=None, help="Python executable")
    parser.add_argument("--user-config-dir", default=None, help="Override XDG config directory")
    parser.add_argument("--json", action="store_true", help="Print machine-readable output")
    return parser


def main(argv: list[str] | None = None) -> None:
    args_list = list(sys.argv[1:] if argv is None else argv)

    if args_list and args_list[0] == "mirror-opencode":
        from reviewer_mcp.mirror import run_cli as run_mirror_cli

        parser = _mirror_parser()
        args = parser.parse_args(args_list[1:])
        run_mirror_cli(args)
        return

    if args_list and args_list[0] == "report":
        from reviewer_mcp.report import run_cli as run_report_cli

        parser = _report_parser()
        args = parser.parse_args(args_list[1:])
        run_report_cli(args)
        return

    if args_list and args_list[0] == "install-opencode-mirror-autostart":
        from reviewer_mcp.autostart import run_install_cli

        parser = _autostart_parser("Install OpenCode mirror auto-start artifacts")
        parser.add_argument(
            "--no-start",
            action="store_true",
            help="Install/update artifacts without starting the watcher",
        )
        args = parser.parse_args(args_list[1:])
        run_install_cli(args)
        return

    if args_list and args_list[0] == "ensure-opencode-mirror":
        from reviewer_mcp.autostart import run_ensure_cli

        parser = _autostart_parser("Ensure the OpenCode mirror watcher is running")
        args = parser.parse_args(args_list[1:])
        run_ensure_cli(args)
        return

    parser = _legacy_parser()
    args = parser.parse_args(args_list)
    profile = get_profile(args.profile)

    if args.check:
        from reviewer_mcp.reviewer import self_check

        sys.exit(self_check(profile))

    from reviewer_mcp.server import create_mcp

    create_mcp(profile).run(transport="stdio")


if __name__ == "__main__":
    main()
