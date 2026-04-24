"""Reviewer: calls provider APIs with the adversarial-review prompts.

The reviewer is logically read-only from the caller's point of view: it never
edits repo files, but it can emit append-only local telemetry under ``brain/``
so review effectiveness can be measured later.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from reviewer_mcp import telemetry
from reviewer_mcp.auth import AuthError, get_token
from reviewer_mcp.fingerprint import canonical_json, sha256_json
from reviewer_mcp.profiles import (
    ReviewerProfile,
    get_default_max_tokens,
    get_default_model,
    get_profile,
)

DEFAULT_TIMEOUT = float(os.environ.get("REVIEWER_TIMEOUT", "120"))

PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True)
class ModelCallResult:
    request_body: dict[str, Any]
    http_status: int
    retry_after: str | None
    response_text: str
    response_json: dict[str, Any] | None
    assistant_content: str
    usage: dict[str, Any] | None


class ModelCallError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        request_body: dict[str, Any],
        http_status: int | None = None,
        retry_after: str | None = None,
        response_text: str | None = None,
        response_json: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.request_body = request_body
        self.http_status = http_status
        self.retry_after = retry_after
        self.response_text = response_text
        self.response_json = response_json


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _build_user_message(payload: dict[str, Any]) -> str:
    """Render the reviewer inputs as a single user message.

    Sections are delimited by explicit headers so the model can't conflate them.
    Values that are None or empty are omitted.
    """

    parts: list[str] = []
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        parts.append(f"===== {key.upper()} =====\n{value}".rstrip())
    return "\n\n".join(parts)


def _build_request_body(
    *,
    system_prompt: str,
    user_message: str,
    model: str,
    profile: ReviewerProfile,
    token_budget: int | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        profile.token_parameter: token_budget or get_default_max_tokens(profile),
    }
    return body


def _extract_message_content(data: dict[str, Any]) -> str:
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Unexpected response shape: {data}") from exc

    content = message.get("content") or ""
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        content = "\n".join(parts)

    if isinstance(content, str) and content.strip():
        return content

    reasoning = message.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip():
        raise RuntimeError(
            "Model returned empty assistant content and only reasoning_content. "
            "Choose a different reviewer profile or increase the token budget."
        )

    raise RuntimeError(f"Model returned empty assistant content: {data}")


def _call_model(request_body: dict[str, Any], profile: ReviewerProfile) -> ModelCallResult:
    token = get_token(profile)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            response = client.post(profile.api_url, headers=headers, json=request_body)
    except httpx.HTTPError as exc:
        raise ModelCallError(
            f"{profile.provider_name} transport error: {exc}",
            request_body=request_body,
        ) from exc

    response_text = response.text
    try:
        response_json = response.json()
    except ValueError:
        response_json = None

    if response.status_code == 429:
        retry_after = response.headers.get("retry-after")
        raise ModelCallError(
            f"{profile.provider_name} rate-limited (HTTP 429). Retry-After: {retry_after or 'unknown'}s. "
            "Consider spacing out calls, skipping trivial reviews, or upgrading tier.",
            request_body=request_body,
            http_status=response.status_code,
            retry_after=retry_after,
            response_text=response_text,
            response_json=response_json,
        )

    if response.status_code != 200:
        raise ModelCallError(
            f"{profile.provider_name} returned {response.status_code}: {response_text[:500]}",
            request_body=request_body,
            http_status=response.status_code,
            retry_after=response.headers.get("retry-after"),
            response_text=response_text,
            response_json=response_json,
        )

    if response_json is None:
        raise ModelCallError(
            f"{profile.provider_name} returned HTTP 200 but not valid JSON.",
            request_body=request_body,
            http_status=response.status_code,
            retry_after=response.headers.get("retry-after"),
            response_text=response_text,
        )

    try:
        assistant_content = _extract_message_content(response_json)
    except RuntimeError as exc:
        raise ModelCallError(
            str(exc),
            request_body=request_body,
            http_status=response.status_code,
            retry_after=response.headers.get("retry-after"),
            response_text=response_text,
            response_json=response_json,
        ) from exc

    usage = response_json.get("usage")
    return ModelCallResult(
        request_body=request_body,
        http_status=response.status_code,
        retry_after=response.headers.get("retry-after"),
        response_text=response_text,
        response_json=response_json,
        assistant_content=assistant_content,
        usage=usage if isinstance(usage, dict) else None,
    )


def _parse_verdict_result(content: str) -> tuple[dict[str, Any], bool]:
    """Parse the model's JSON verdict; tolerate stray markdown fences."""

    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        return json.loads(stripped), True
    except json.JSONDecodeError:
        return (
            {
                "verdict": "challenge",
                "summary": "Reviewer returned non-JSON output.",
                "raw_output": content,
                "confidence": "low",
            },
            False,
        )


def _parse_verdict(content: str) -> dict[str, Any]:
    verdict, _parse_success = _parse_verdict_result(content)
    return verdict


def _finding_counts(parsed_verdict: dict[str, Any] | None) -> dict[str, int]:
    if not parsed_verdict:
        return {}
    counts: dict[str, int] = {}
    for key in (
        "bugs",
        "critical_issues",
        "risks",
        "missing_tests",
        "missed_alternatives",
        "convention_violations",
        "questions_for_primary",
    ):
        value = parsed_verdict.get(key)
        if isinstance(value, list):
            counts[key] = len(value)
    return counts


def _emit_review_telemetry(
    *,
    logical_tool: str,
    profile: ReviewerProfile,
    model: str,
    input_payload: dict[str, Any],
    system_prompt: str,
    user_message: str,
    request_body: dict[str, Any],
    started_at: int,
    finished_at: int,
    result: ModelCallResult | None,
    parsed_verdict: dict[str, Any] | None,
    parse_success: bool | None,
    error: Exception | None,
) -> None:
    request_hash = sha256_json({"tool": logical_tool, "input": input_payload})
    error_status = getattr(error, "http_status", None)
    error_retry_after = getattr(error, "retry_after", None)
    error_response_text = getattr(error, "response_text", None)
    error_response_json = getattr(error, "response_json", None)
    record = {
        "schema_version": telemetry.SCHEMA_VERSION,
        "raw_event_id": telemetry.new_event_id(),
        "recorded_at": finished_at,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": finished_at - started_at,
        "profile_key": profile.key,
        "profile_server_name": profile.server_name,
        "logical_tool": logical_tool,
        "model": model,
        "request_hash": request_hash,
        "input_payload": input_payload,
        "input_bytes": len(canonical_json(input_payload).encode("utf-8")),
        "rendered_user_message": user_message,
        "user_message_bytes": len(user_message.encode("utf-8")),
        "system_prompt_text": system_prompt,
        "request_body": request_body,
        "request_body_bytes": len(canonical_json(request_body).encode("utf-8")),
        "http_status": result.http_status if result else error_status,
        "retry_after": result.retry_after if result else error_retry_after,
        "raw_response_body": result.response_text if result else error_response_text,
        "raw_response_json": result.response_json if result else error_response_json,
        "assistant_content": result.assistant_content if result else None,
        "parsed_verdict": parsed_verdict,
        "parse_success": parse_success,
        "verdict": parsed_verdict.get("verdict") if parsed_verdict else None,
        "confidence": parsed_verdict.get("confidence") if parsed_verdict else None,
        "finding_counts": _finding_counts(parsed_verdict),
        "usage": result.usage if result else None,
        "error_class": type(error).__name__ if error else None,
        "error_message": str(error) if error else None,
    }
    telemetry.safe_append_reviewer_raw(record)


def _run_review(
    *,
    logical_tool: str,
    prompt_name: str,
    payload: dict[str, Any],
    model: str | None,
    profile: ReviewerProfile | None,
) -> dict[str, Any]:
    active_profile = profile or get_profile()
    selected_model = model or get_default_model(active_profile)
    system_prompt = _load_prompt(prompt_name)
    user_message = _build_user_message(payload)
    request_body = _build_request_body(
        system_prompt=system_prompt,
        user_message=user_message,
        model=selected_model,
        profile=active_profile,
    )
    started_at = telemetry.now_ms()
    result: ModelCallResult | None = None
    parsed_verdict: dict[str, Any] | None = None
    parse_success: bool | None = None
    error: Exception | None = None
    try:
        result = _call_model(request_body, active_profile)
        parsed_verdict, parse_success = _parse_verdict_result(result.assistant_content)
        return parsed_verdict
    except Exception as exc:
        error = exc
        raise
    finally:
        _emit_review_telemetry(
            logical_tool=logical_tool,
            profile=active_profile,
            model=selected_model,
            input_payload=payload,
            system_prompt=system_prompt,
            user_message=user_message,
            request_body=request_body,
            started_at=started_at,
            finished_at=telemetry.now_ms(),
            result=result,
            parsed_verdict=parsed_verdict,
            parse_success=parse_success,
            error=error,
        )


def review_plan(
    goal: str,
    plan: str,
    context: str | None = None,
    project_agents_md: str | None = None,
    model: str | None = None,
    profile: ReviewerProfile | None = None,
) -> dict[str, Any]:
    return _run_review(
        logical_tool="review_plan",
        prompt_name="plan_review.md",
        payload={
            "goal": goal,
            "plan": plan,
            "context": context,
            "project_agents_md": project_agents_md,
        },
        model=model,
        profile=profile,
    )


def review_diff(
    intent: str,
    diff: str,
    context: str | None = None,
    project_agents_md: str | None = None,
    model: str | None = None,
    profile: ReviewerProfile | None = None,
) -> dict[str, Any]:
    return _run_review(
        logical_tool="review_diff",
        prompt_name="diff_review.md",
        payload={
            "intent": intent,
            "diff": diff,
            "context": context,
            "project_agents_md": project_agents_md,
        },
        model=model,
        profile=profile,
    )


def self_check(profile: ReviewerProfile | None = None) -> int:
    """Verify auth + model reachability. Returns process exit code."""

    active_profile = profile or get_profile()
    try:
        token = get_token(active_profile)
    except AuthError as exc:
        print(f"[auth] {exc}", flush=True)
        return 2
    print(f"[auth] ok, token length {len(token)}", flush=True)

    body = _build_request_body(
        system_prompt="Reply with exactly: PONG",
        user_message="ping",
        model=get_default_model(active_profile),
        profile=active_profile,
        token_budget=128,
    )
    try:
        result = _call_model(body, active_profile)
    except ModelCallError as exc:
        if exc.http_status is None:
            print(f"[api] transport error: {exc}", flush=True)
            return 3
        print(f"[api] HTTP {exc.http_status}: {(exc.response_text or '')[:300]}", flush=True)
        return 4
    print(f"[api] ok, usage={result.usage or {}}", flush=True)
    print(f"[api] content={result.assistant_content!r}", flush=True)
    return 0
