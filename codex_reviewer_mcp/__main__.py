#!/usr/bin/env python3
"""Entry point for the codex-reviewer MCP server.

Usage:
    python -m codex_reviewer_mcp           # Start MCP server over STDIO
    python -m codex_reviewer_mcp --check   # Verify API access and exit
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="codex-reviewer-mcp — adversarial review MCP server",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify GitHub Models API access and exit",
    )
    args = parser.parse_args()

    if args.check:
        from codex_reviewer_mcp.reviewer import self_check

        sys.exit(self_check())

    from codex_reviewer_mcp.server import mcp

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
