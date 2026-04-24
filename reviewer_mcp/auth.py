"""Provider auth helpers for reviewer profiles."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from reviewer_mcp.profiles import ReviewerProfile, get_profile

FIREWORKS_API_KEY_FILE_NAME = "fireworks-api-key"


class AuthError(RuntimeError):
    """Raised when an API token cannot be obtained."""


def _get_github_token() -> str:
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


def _default_user_config_dir() -> Path:
    raw = os.environ.get("XDG_CONFIG_HOME")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".config").resolve()


def _default_fireworks_api_key_path() -> Path:
    return _default_user_config_dir() / "reviewer-mcp" / FIREWORKS_API_KEY_FILE_NAME


def _fireworks_api_key_path() -> Path:
    raw = os.environ.get("FIREWORKS_API_KEY_FILE")
    if raw:
        return Path(raw).expanduser().resolve()
    return _default_fireworks_api_key_path()


def _read_text_secret(path: Path, label: str) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise AuthError(f"Could not read {label} from {path}: {exc}") from exc
    if not value:
        raise AuthError(f"{label} file is empty: {path}")
    return value


def _get_fireworks_token() -> str:
    """Return a Fireworks API key from the environment or config file."""

    env_token = os.environ.get("FIREWORKS_API_KEY", "").strip()
    if env_token:
        return env_token

    path = _fireworks_api_key_path()
    if path.exists():
        if not path.is_file():
            raise AuthError(f"Fireworks API key path is not a file: {path}")
        return _read_text_secret(path, "Fireworks API key")

    raise AuthError(
        "FIREWORKS_API_KEY is not set and no Fireworks API key file was found at "
        f"{path}; create the file or export FIREWORKS_API_KEY"
    )


def get_token(profile: ReviewerProfile | None = None) -> str:
    """Return the API token for the active reviewer profile."""

    active_profile = profile or get_profile()
    if active_profile.auth_mode == "github":
        return _get_github_token()
    if active_profile.auth_mode == "fireworks":
        return _get_fireworks_token()
    raise AuthError(
        f"Unsupported auth mode '{active_profile.auth_mode}' for profile '{active_profile.key}'"
    )
