"""Helpers for reading local OpenCode session metadata and transcript rows."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SessionRow:
    id: str
    parent_id: str | None
    title: str
    directory: str
    time_created: int
    time_updated: int


def default_data_dir() -> Path:
    raw = os.environ.get("XDG_DATA_HOME")
    if raw:
        return Path(raw).expanduser() / "opencode"
    return Path.home() / ".local" / "share" / "opencode"


def default_db_path() -> Path:
    return default_data_dir() / "opencode.db"


def resolve_db_path(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    try:
        result = subprocess.run(
            ["opencode", "db", "path"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        candidate = result.stdout.strip()
        if candidate:
            return Path(candidate).expanduser().resolve()
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass
    return default_db_path().expanduser().resolve()


def _connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def _loads_json(raw: str) -> dict[str, Any]:
    return json.loads(raw)


def get_all_sessions(db_path: Path) -> dict[str, SessionRow]:
    with _connect(db_path) as connection:
        rows = connection.execute(
            "SELECT id, parent_id, title, directory, time_created, time_updated FROM session"
        ).fetchall()
    return {
        row["id"]: SessionRow(
            id=row["id"],
            parent_id=row["parent_id"],
            title=row["title"],
            directory=row["directory"],
            time_created=row["time_created"],
            time_updated=row["time_updated"],
        )
        for row in rows
    }


def updated_session_ids_since(db_path: Path, watermark_ms: int) -> list[str]:
    with _connect(db_path) as connection:
        rows = connection.execute(
            "SELECT id FROM session WHERE time_updated > ? ORDER BY time_updated",
            (watermark_ms,),
        ).fetchall()
    return [row["id"] for row in rows]


def latest_session_update(db_path: Path) -> int:
    with _connect(db_path) as connection:
        row = connection.execute("SELECT COALESCE(MAX(time_updated), 0) AS max_updated FROM session").fetchone()
    return int(row["max_updated"])


def get_root_session_id(sessions: dict[str, SessionRow], session_id: str) -> str:
    current = sessions[session_id]
    while current.parent_id:
        current = sessions[current.parent_id]
    return current.id


def get_bundle_sessions(sessions: dict[str, SessionRow], root_session_id: str) -> list[SessionRow]:
    bundle: list[SessionRow] = []
    for session in sessions.values():
        if get_root_session_id(sessions, session.id) == root_session_id:
            bundle.append(session)
    bundle.sort(key=lambda item: (item.time_created, item.id))
    return bundle


def get_session_messages(db_path: Path, session_id: str) -> list[dict[str, Any]]:
    with _connect(db_path) as connection:
        rows = connection.execute(
            "SELECT id, data FROM message WHERE session_id=? ORDER BY time_created",
            (session_id,),
        ).fetchall()
    messages: list[dict[str, Any]] = []
    for row in rows:
        payload = _loads_json(row["data"])
        payload.setdefault("id", row["id"])
        payload.setdefault("sessionID", session_id)
        messages.append(payload)
    return messages


def get_session_parts(db_path: Path, session_id: str) -> dict[str, list[dict[str, Any]]]:
    with _connect(db_path) as connection:
        rows = connection.execute(
            "SELECT id, message_id, data FROM part WHERE session_id=? ORDER BY time_created",
            (session_id,),
        ).fetchall()
    parts_by_message: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        payload = _loads_json(row["data"])
        payload.setdefault("id", row["id"])
        payload.setdefault("sessionID", session_id)
        payload.setdefault("messageID", row["message_id"])
        parts_by_message.setdefault(row["message_id"], []).append(payload)
    return parts_by_message


def build_session_export(db_path: Path, session: SessionRow) -> dict[str, Any]:
    messages = get_session_messages(db_path, session.id)
    parts_by_message = get_session_parts(db_path, session.id)
    exported_messages = []
    for message_info in messages:
        message_id = message_info.get("id")
        exported_messages.append(
            {
                "info": message_info,
                "parts": parts_by_message.get(message_id, []),
            }
        )
    return {
        "info": {
            "id": session.id,
            "directory": session.directory,
            "title": session.title,
            "time": {
                "created": session.time_created,
                "updated": session.time_updated,
            },
        },
        "messages": exported_messages,
    }
