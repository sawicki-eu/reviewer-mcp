"""Path resolution for reviewer telemetry, mirror state, and brain logs."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


def find_brain_root(
    *,
    explicit: str | os.PathLike[str] | None = None,
    start: Path | None = None,
) -> Path | None:
    """Find the workspace ``brain`` directory.

    Resolution order:
    1. Explicit argument
    2. ``REVIEWER_BRAIN_ROOT``
    3. Walk upward from ``start`` (or ``Path.cwd()``) looking for ``brain/``
    """

    raw = explicit or os.environ.get("REVIEWER_BRAIN_ROOT")
    if raw:
        candidate = Path(raw).expanduser().resolve()
        return candidate if candidate.is_dir() else None

    origin = (start or Path.cwd()).resolve()
    for parent in (origin, *origin.parents):
        candidate = parent / "brain"
        if candidate.is_dir():
            return candidate
    return None


def require_brain_root(
    *,
    explicit: str | os.PathLike[str] | None = None,
    start: Path | None = None,
) -> Path:
    brain_root = find_brain_root(explicit=explicit, start=start)
    if brain_root is None:
        raise RuntimeError(
            "Could not locate workspace brain/ directory. Set REVIEWER_BRAIN_ROOT or pass "
            "--brain-root explicitly."
        )
    return brain_root


def local_state_dir(explicit: str | os.PathLike[str] | None = None) -> Path:
    raw = explicit or os.environ.get("REVIEWER_STATE_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.home() / ".local" / "state" / "reviewer-mcp"


def session_date_from_ms(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000).date().isoformat()


def logs_day_dir(brain_root: Path, day: str) -> Path:
    return brain_root / "logs" / day


def reviewer_raw_path(brain_root: Path, day: str) -> Path:
    return logs_day_dir(brain_root, day) / "reviewer-raw.jsonl"


def session_bundle_dir(brain_root: Path, day: str, root_session_id: str) -> Path:
    return logs_day_dir(brain_root, day) / root_session_id


def mirror_state_db_path(state_dir: Path) -> Path:
    return state_dir / "opencode-mirror.db"
