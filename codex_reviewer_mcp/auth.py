"""Auth: obtain a GitHub PAT via the `gh` CLI for the Models API.

We reuse the token already managed by `gh auth login`. This avoids a second
secret to manage; the trade-off is that token rotation is handled by gh, and
the token must have `models:read` scope (or equivalent classic-PAT scope).
"""

from __future__ import annotations

import os
import subprocess


class AuthError(RuntimeError):
    """Raised when a GitHub token cannot be obtained."""


def get_token() -> str:
    """Return a GitHub token.

    Priority:
    1. ``GITHUB_TOKEN`` env var (useful for tests / CI)
    2. ``gh auth token`` from the GitHub CLI
    """
    env_token = os.environ.get("GITHUB_TOKEN")
    if env_token:
        return env_token.strip()

    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError as exc:
        raise AuthError("`gh` CLI not found; install it or set GITHUB_TOKEN") from exc
    except subprocess.CalledProcessError as exc:
        raise AuthError(f"`gh auth token` failed: {exc.stderr.strip()}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AuthError("`gh auth token` timed out") from exc

    token = result.stdout.strip()
    if not token:
        raise AuthError("`gh auth token` returned an empty string; run `gh auth login`")
    return token
