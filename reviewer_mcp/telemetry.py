"""Append-only reviewer telemetry logging."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Iterator

from reviewer_mcp import paths

SCHEMA_VERSION = 1


def now_ms() -> int:
    from time import time

    return int(time() * 1000)


def new_event_id() -> str:
    return f"rev_{uuid.uuid4().hex}"


def append_jsonl(file_path: Path, record: dict[str, Any]) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=True, sort_keys=True))
        handle.write("\n")


def iter_jsonl(file_path: Path) -> Iterator[dict[str, Any]]:
    if not file_path.exists():
        return
    with file_path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            yield json.loads(stripped)


def append_reviewer_raw(
    record: dict[str, Any],
    *,
    brain_root: Path | None = None,
) -> Path:
    active_brain_root = brain_root or paths.require_brain_root()
    record_day = paths.session_date_from_ms(record["recorded_at"])
    target = paths.reviewer_raw_path(active_brain_root, record_day)
    append_jsonl(target, record)
    return target


def safe_append_reviewer_raw(
    record: dict[str, Any],
    *,
    brain_root: Path | None = None,
) -> Path | None:
    try:
        return append_reviewer_raw(record, brain_root=brain_root)
    except Exception:
        return None
