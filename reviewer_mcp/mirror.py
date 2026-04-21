"""Mirror OpenCode sessions into tracked brain/logs bundles."""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reviewer_mcp import opencode, paths, telemetry
from reviewer_mcp.fingerprint import sha256_json

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class MirrorConfig:
    brain_root: Path
    db_path: Path
    state_dir: Path
    poll_interval: float = 2.0
    idle_seconds: int = 60


def _ensure_state_db(state_path: Path) -> sqlite3.Connection:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(state_path, timeout=30)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS mirror_state ("
        "key TEXT PRIMARY KEY, value TEXT NOT NULL"
        ")"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS emitted_records ("
        "root_session_id TEXT NOT NULL, "
        "record_kind TEXT NOT NULL, "
        "record_id TEXT NOT NULL, "
        "PRIMARY KEY (root_session_id, record_kind, record_id)"
        ")"
    )
    connection.commit()
    return connection


def _get_state_value(connection: sqlite3.Connection, key: str, default: str) -> str:
    row = connection.execute("SELECT value FROM mirror_state WHERE key=?", (key,)).fetchone()
    if row is None:
        return default
    return str(row[0])


def _set_state_value(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT INTO mirror_state(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    connection.commit()


def _already_emitted(
    connection: sqlite3.Connection,
    *,
    root_session_id: str,
    record_kind: str,
    record_id: str,
) -> bool:
    row = connection.execute(
        "SELECT 1 FROM emitted_records WHERE root_session_id=? AND record_kind=? AND record_id=?",
        (root_session_id, record_kind, record_id),
    ).fetchone()
    return row is not None


def _mark_emitted(
    connection: sqlite3.Connection,
    *,
    root_session_id: str,
    record_kind: str,
    record_id: str,
) -> None:
    connection.execute(
        "INSERT OR IGNORE INTO emitted_records(root_session_id, record_kind, record_id) VALUES(?, ?, ?)",
        (root_session_id, record_kind, record_id),
    )


def _record_time(info: dict[str, Any]) -> int | None:
    time_info = info.get("time")
    if not isinstance(time_info, dict):
        return None
    created = time_info.get("created")
    if isinstance(created, int):
        return created
    return None


def _write_manifest(bundle_dir: Path, manifest: dict[str, Any]) -> None:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    target = bundle_dir / "manifest.json"
    target.write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_bundle_record(bundle_dir: Path, file_name: str, record: dict[str, Any]) -> None:
    telemetry.append_jsonl(bundle_dir / file_name, record)


def _write_snapshot(bundle_dir: Path, exported: dict[str, Any], session_id: str, mirrored_at: int) -> None:
    timestamp = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime(mirrored_at / 1000))
    target = bundle_dir / "snapshots" / f"{timestamp}-{session_id}.export.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(exported, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _snapshot_key(session_id: str) -> str:
    return f"snapshot_hash:{session_id}"


def _snapshot_time_key(session_id: str) -> str:
    return f"snapshot_time:{session_id}"


def _maybe_write_snapshot(
    *,
    bundle_dir: Path,
    exported: dict[str, Any],
    session: opencode.SessionRow,
    mirrored_at: int,
    idle_seconds: int,
    state_connection: sqlite3.Connection,
) -> bool:
    export_hash = sha256_json(exported)
    last_hash = _get_state_value(state_connection, _snapshot_key(session.id), "")
    last_snapshot_at = int(_get_state_value(state_connection, _snapshot_time_key(session.id), "0"))
    idle_ms = idle_seconds * 1000
    should_write = False
    if not last_hash:
        should_write = True
    elif export_hash != last_hash and mirrored_at - session.time_updated >= idle_ms:
        should_write = True
    elif export_hash != last_hash and not last_snapshot_at:
        should_write = True
    if not should_write:
        return False
    _write_snapshot(bundle_dir, exported, session.id, mirrored_at)
    _set_state_value(state_connection, _snapshot_key(session.id), export_hash)
    _set_state_value(state_connection, _snapshot_time_key(session.id), str(mirrored_at))
    return True


def _tool_request_hash(part: dict[str, Any]) -> str | None:
    if part.get("type") != "tool":
        return None
    tool_name = part.get("tool")
    state = part.get("state")
    if not isinstance(tool_name, str) or not isinstance(state, dict):
        return None
    state_input = state.get("input")
    if not isinstance(state_input, dict):
        return None
    if tool_name == "review_plan" or tool_name.endswith("review_plan"):
        logical_tool = "review_plan"
    elif tool_name == "review_diff" or tool_name.endswith("review_diff"):
        logical_tool = "review_diff"
    else:
        return None
    return sha256_json({"tool": logical_tool, "input": state_input})


def _profile_from_tool_name(tool_name: str) -> str | None:
    for prefix in ("codex-reviewer", "mistral-reviewer", "llama-reviewer"):
        if tool_name.startswith(prefix):
            return prefix.replace("-reviewer", "")
    return None


def _logical_tool_from_name(tool_name: str | None) -> str | None:
    if not isinstance(tool_name, str):
        return None
    if tool_name == "review_plan" or tool_name.endswith("review_plan"):
        return "review_plan"
    if tool_name == "review_diff" or tool_name.endswith("review_diff"):
        return "review_diff"
    return None


def _mirror_exported_session(
    *,
    bundle_dir: Path,
    root_session_id: str,
    exported: dict[str, Any],
    state_connection: sqlite3.Connection,
    mirrored_at: int,
) -> dict[str, Any]:
    message_count = 0
    part_count = 0
    reviewer_hashes: set[str] = set()
    info = exported.get("info", {})
    for message in exported.get("messages", []):
        message_info = message.get("info", {})
        message_id = message_info.get("id")
        if isinstance(message_id, str) and not _already_emitted(
            state_connection,
            root_session_id=root_session_id,
            record_kind="message",
            record_id=message_id,
        ):
            _append_bundle_record(
                bundle_dir,
                "opencode-events.jsonl",
                {
                    "schema_version": SCHEMA_VERSION,
                    "mirrored_at": mirrored_at,
                    "root_session_id": root_session_id,
                    "session_id": message_info.get("sessionID"),
                    "message_id": message_id,
                    "record_type": "message_info",
                    "role": message_info.get("role"),
                    "agent": message_info.get("agent"),
                    "mode": message_info.get("mode"),
                    "time_created": _record_time(message_info),
                    "payload": message_info,
                },
            )
            _mark_emitted(
                state_connection,
                root_session_id=root_session_id,
                record_kind="message",
                record_id=message_id,
            )
            message_count += 1
        for part in message.get("parts", []):
            part_id = part.get("id")
            if not isinstance(part_id, str):
                continue
            if _already_emitted(
                state_connection,
                root_session_id=root_session_id,
                record_kind="part",
                record_id=part_id,
            ):
                continue
            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            record = {
                "schema_version": SCHEMA_VERSION,
                "mirrored_at": mirrored_at,
                "root_session_id": root_session_id,
                "session_id": part.get("sessionID"),
                "message_id": part.get("messageID"),
                "part_id": part_id,
                "record_type": "part",
                "part_type": part.get("type"),
                "tool": part.get("tool"),
                "status": state.get("status") if isinstance(state, dict) else None,
                "request_hash": _tool_request_hash(part),
                "payload": part,
                "message_info": message_info,
            }
            _append_bundle_record(bundle_dir, "opencode-events.jsonl", record)
            _mark_emitted(
                state_connection,
                root_session_id=root_session_id,
                record_kind="part",
                record_id=part_id,
            )
            part_count += 1
            request_hash = record["request_hash"]
            if isinstance(request_hash, str):
                reviewer_hashes.add(request_hash)
    return {
        "session_info": info,
        "messages_emitted": message_count,
        "parts_emitted": part_count,
        "reviewer_hashes": reviewer_hashes,
    }


def _match_reviewer_raw(
    *,
    brain_root: Path,
    bundle_dir: Path,
    reviewer_hashes: set[str],
    mirrored_at: int,
) -> int:
    if not reviewer_hashes:
        return 0
    target = bundle_dir / "reviewer-events.jsonl"
    existing_ids = {record.get("raw_event_id") for record in telemetry.iter_jsonl(target)}
    matched = 0
    logs_root = brain_root / "logs"
    if not logs_root.exists():
        return 0
    for day_dir in sorted(path for path in logs_root.iterdir() if path.is_dir()):
        source = day_dir / "reviewer-raw.jsonl"
        if not source.exists():
            continue
        for record in telemetry.iter_jsonl(source):
            raw_event_id = record.get("raw_event_id")
            if raw_event_id in existing_ids:
                continue
            if record.get("request_hash") not in reviewer_hashes:
                continue
            payload = dict(record)
            payload["mirrored_at"] = mirrored_at
            telemetry.append_jsonl(target, payload)
            existing_ids.add(raw_event_id)
            matched += 1
    return matched


def _write_index(bundle_dir: Path, summary: dict[str, Any]) -> None:
    target = bundle_dir / "index.json"
    target.write_text(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def mirror_root_bundle(
    config: MirrorConfig,
    *,
    root_session_id: str,
    sessions: dict[str, opencode.SessionRow] | None = None,
) -> dict[str, Any]:
    all_sessions = sessions or opencode.get_all_sessions(config.db_path)
    bundle = opencode.get_bundle_sessions(all_sessions, root_session_id)
    root_session = all_sessions[root_session_id]
    session_day = paths.session_date_from_ms(root_session.time_created)
    bundle_dir = paths.session_bundle_dir(config.brain_root, session_day, root_session_id)
    mirrored_at = telemetry.now_ms()
    state_connection = _ensure_state_db(paths.mirror_state_db_path(config.state_dir))
    try:
        reviewer_hashes: set[str] = set()
        exported_sessions: list[dict[str, Any]] = []
        emitted_messages = 0
        emitted_parts = 0
        for session in bundle:
            exported = opencode.build_session_export(config.db_path, session)
            exported_sessions.append(exported)
            session_result = _mirror_exported_session(
                bundle_dir=bundle_dir,
                root_session_id=root_session_id,
                exported=exported,
                state_connection=state_connection,
                mirrored_at=mirrored_at,
            )
            emitted_messages += session_result["messages_emitted"]
            emitted_parts += session_result["parts_emitted"]
            reviewer_hashes.update(session_result["reviewer_hashes"])
            _maybe_write_snapshot(
                bundle_dir=bundle_dir,
                exported=exported,
                session=session,
                mirrored_at=mirrored_at,
                idle_seconds=config.idle_seconds,
                state_connection=state_connection,
            )

        matched_reviewer = _match_reviewer_raw(
            brain_root=config.brain_root,
            bundle_dir=bundle_dir,
            reviewer_hashes=reviewer_hashes,
            mirrored_at=mirrored_at,
        )

        manifest = {
            "schema_version": SCHEMA_VERSION,
            "root_session_id": root_session_id,
            "title": root_session.title,
            "directory": root_session.directory,
            "session_day": session_day,
            "session_ids": [session.id for session in bundle],
            "child_session_ids": [session.id for session in bundle if session.parent_id],
            "time_created": root_session.time_created,
            "time_updated": max(session.time_updated for session in bundle),
            "last_mirrored_at": mirrored_at,
            "exported_sessions": [exported.get("info", {}).get("id") for exported in exported_sessions],
        }
        _write_manifest(bundle_dir, manifest)
        summary = {
            "schema_version": SCHEMA_VERSION,
            "root_session_id": root_session_id,
            "title": root_session.title,
            "session_day": session_day,
            "last_mirrored_at": mirrored_at,
            "sessions": len(bundle),
            "messages_emitted": emitted_messages,
            "parts_emitted": emitted_parts,
            "matched_reviewer_events": matched_reviewer,
        }
        _write_index(bundle_dir, summary)
        state_connection.commit()
        return summary
    finally:
        state_connection.close()


def mirror_updated_sessions(config: MirrorConfig, *, backfill: bool = False) -> list[dict[str, Any]]:
    state_connection = _ensure_state_db(paths.mirror_state_db_path(config.state_dir))
    try:
        watermark = 0 if backfill else int(_get_state_value(state_connection, "session_watermark", "0"))
        session_ids = opencode.updated_session_ids_since(config.db_path, watermark)
        latest = opencode.latest_session_update(config.db_path)
        sessions = opencode.get_all_sessions(config.db_path)
        roots = sorted({opencode.get_root_session_id(sessions, session_id) for session_id in session_ids})
        results = [mirror_root_bundle(config, root_session_id=root_id, sessions=sessions) for root_id in roots]
        _set_state_value(state_connection, "session_watermark", str(latest))
        return results
    finally:
        state_connection.close()


def watch_updates(config: MirrorConfig) -> None:
    while True:
        mirror_updated_sessions(config)
        time.sleep(config.poll_interval)


def _print_results(results: list[dict[str, Any]]) -> None:
    for result in results:
        print(json.dumps(result, ensure_ascii=True, sort_keys=True), flush=True)


def run_cli(args: Any) -> None:
    brain_root = paths.require_brain_root(explicit=args.brain_root)
    db_path = opencode.resolve_db_path(args.db_path)
    state_dir = paths.local_state_dir(args.state_dir)
    config = MirrorConfig(
        brain_root=brain_root,
        db_path=db_path,
        state_dir=state_dir,
        poll_interval=args.poll_interval,
        idle_seconds=args.idle_seconds,
    )
    if args.once:
        if not args.session:
            raise SystemExit("--once requires --session <session-id>")
        sessions = opencode.get_all_sessions(config.db_path)
        root_id = opencode.get_root_session_id(sessions, args.session)
        result = mirror_root_bundle(config, root_session_id=root_id, sessions=sessions)
        _print_results([result])
        return
    if args.backfill:
        results = mirror_updated_sessions(config, backfill=True)
        _print_results(results)
        return
    if args.watch:
        watch_updates(config)
        return
    results = mirror_updated_sessions(config)
    _print_results(results)
