"""Reporting over tracked brain/logs artifacts."""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

from reviewer_mcp import paths, telemetry


def _iter_session_dirs(brain_root: Path, since: str | None = None) -> list[Path]:
    logs_root = brain_root / "logs"
    if not logs_root.exists():
        return []
    session_dirs: list[Path] = []
    for day_dir in sorted(path for path in logs_root.iterdir() if path.is_dir()):
        if since and day_dir.name < since:
            continue
        for child in sorted(path for path in day_dir.iterdir() if path.is_dir()):
            if child.name.startswith("ses_"):
                session_dirs.append(child)
    return session_dirs


def _iter_reviewer_records(brain_root: Path, since: str | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for session_dir in _iter_session_dirs(brain_root, since=since):
        records.extend(list(telemetry.iter_jsonl(session_dir / "reviewer-events.jsonl")))
    return records


def build_report(brain_root: Path, *, since: str | None = None) -> dict[str, Any]:
    session_dirs = _iter_session_dirs(brain_root, since=since)
    reviewer_records = _iter_reviewer_records(brain_root, since=since)
    matched_raw_ids = {record.get("raw_event_id") for record in reviewer_records}
    durations = [record["duration_ms"] for record in reviewer_records if isinstance(record.get("duration_ms"), int)]
    verdicts: dict[str, int] = {}
    profiles: dict[str, int] = {}
    tools: dict[str, int] = {}
    errors = 0
    rate_limits = 0
    unmatched = 0
    for record in reviewer_records:
        verdict = record.get("verdict")
        if isinstance(verdict, str):
            verdicts[verdict] = verdicts.get(verdict, 0) + 1
        profile = record.get("profile_key")
        if isinstance(profile, str):
            profiles[profile] = profiles.get(profile, 0) + 1
        tool = record.get("logical_tool")
        if isinstance(tool, str):
            tools[tool] = tools.get(tool, 0) + 1
        if record.get("error_class"):
            errors += 1
        if record.get("http_status") == 429:
            rate_limits += 1
    for day_dir in sorted(path for path in (brain_root / "logs").iterdir() if path.is_dir()):
        if since and day_dir.name < since:
            continue
        raw_path = day_dir / "reviewer-raw.jsonl"
        for record in telemetry.iter_jsonl(raw_path):
            if record.get("raw_event_id") not in matched_raw_ids:
                unmatched += 1
    return {
        "session_bundle_count": len(session_dirs),
        "reviewer_call_count": len(reviewer_records),
        "reviewer_calls_by_profile": profiles,
        "reviewer_calls_by_tool": tools,
        "verdict_counts": verdicts,
        "error_count": errors,
        "rate_limit_count": rate_limits,
        "unmatched_reviewer_raw_count": unmatched,
        "duration_ms": {
            "median": statistics.median(durations) if durations else None,
            "p95": statistics.quantiles(durations, n=20)[18] if len(durations) >= 20 else None,
        },
    }


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# reviewer-mcp report",
        "",
        f"- session bundles: {report['session_bundle_count']}",
        f"- reviewer calls: {report['reviewer_call_count']}",
        f"- reviewer errors: {report['error_count']}",
        f"- rate limits: {report['rate_limit_count']}",
        f"- unmatched reviewer raw events: {report['unmatched_reviewer_raw_count']}",
        f"- median latency ms: {report['duration_ms']['median']}",
        f"- p95 latency ms: {report['duration_ms']['p95']}",
        "",
        "## Calls By Profile",
    ]
    for key, value in sorted(report["reviewer_calls_by_profile"].items()):
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Calls By Tool")
    for key, value in sorted(report["reviewer_calls_by_tool"].items()):
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Verdicts")
    for key, value in sorted(report["verdict_counts"].items()):
        lines.append(f"- {key}: {value}")
    return "\n".join(lines) + "\n"


def run_cli(args: Any) -> None:
    brain_root = paths.require_brain_root(explicit=args.brain_root)
    report = build_report(brain_root, since=args.since)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
        return
    if args.format == "tsv":
        for key in (
            "session_bundle_count",
            "reviewer_call_count",
            "error_count",
            "rate_limit_count",
            "unmatched_reviewer_raw_count",
        ):
            print(f"{key}\t{report[key]}")
        return
    print(_render_markdown(report), end="")
