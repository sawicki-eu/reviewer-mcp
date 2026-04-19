#!/usr/bin/env python3
"""Entry point for the reviewer-mcp package.

Usage:
    python -m reviewer_mcp                      # Start MCP server over STDIO
    python -m reviewer_mcp --profile mistral    # Start another reviewer
    python -m reviewer_mcp --check              # Verify API access and exit
"""

from __future__ import annotations

import argparse
import sys

from reviewer_mcp.profiles import get_profile


def main() -> None:
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
    args = parser.parse_args()
    profile = get_profile(args.profile)

    if args.check:
        from reviewer_mcp.reviewer import self_check

        sys.exit(self_check(profile))

    from reviewer_mcp.server import create_mcp

    create_mcp(profile).run(transport="stdio")


if __name__ == "__main__":
    main()
