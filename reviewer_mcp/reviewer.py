"""Reviewer: calls GitHub Models API with the adversarial-review prompts.

The reviewer is strictly read-only; it never touches the filesystem. The MCP
tool packages the inputs, we send them verbatim to the selected GitHub Models
profile, and return the structured JSON response.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

from reviewer_mcp.auth import AuthError, get_token
from reviewer_mcp.profiles import (
    ReviewerProfile,
    get_default_max_tokens,
    get_default_model,
    get_profile,
)

GITHUB_MODELS_URL = "https://models.github.ai/inference/chat/completions"
DEFAULT_TIMEOUT = float(os.environ.get("REVIEWER_TIMEOUT", "120"))

PROMPTS_DIR = Path(__file__).parent / "prompts"


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


def _call_model(
    system_prompt: str,
    user_message: str,
    *,
    model: str,
    profile: ReviewerProfile,
) -> str:
    token = get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = _build_request_body(
        system_prompt=system_prompt,
        user_message=user_message,
        model=model,
        profile=profile,
    )
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        response = client.post(GITHUB_MODELS_URL, headers=headers, json=body)
    if response.status_code == 429:
        retry_after = response.headers.get("retry-after", "unknown")
        raise RuntimeError(
            f"GitHub Models API rate-limited (HTTP 429). Retry-After: {retry_after}s. "
            "Consider spacing out calls, skipping trivial reviews, or upgrading tier."
        )
    if response.status_code != 200:
        raise RuntimeError(
            f"GitHub Models API returned {response.status_code}: {response.text[:500]}"
        )
    data = response.json()
    return _extract_message_content(data)


def _parse_verdict(content: str) -> dict[str, Any]:
    """Parse the model's JSON verdict; tolerate stray markdown fences."""
    stripped = content.strip()
    if stripped.startswith("```"):
        # Remove first and last fence lines.
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return {
            "verdict": "challenge",
            "summary": "Reviewer returned non-JSON output.",
            "raw_output": content,
            "confidence": "low",
        }


def review_plan(
    goal: str,
    plan: str,
    context: str | None = None,
    project_agents_md: str | None = None,
    model: str | None = None,
    profile: ReviewerProfile | None = None,
) -> dict[str, Any]:
    active_profile = profile or get_profile()
    system_prompt = _load_prompt("plan_review.md")
    user_message = _build_user_message(
        {
            "goal": goal,
            "plan": plan,
            "context": context,
            "project_agents_md": project_agents_md,
        }
    )
    content = _call_model(
        system_prompt,
        user_message,
        model=model or get_default_model(active_profile),
        profile=active_profile,
    )
    return _parse_verdict(content)


def review_diff(
    intent: str,
    diff: str,
    context: str | None = None,
    project_agents_md: str | None = None,
    model: str | None = None,
    profile: ReviewerProfile | None = None,
) -> dict[str, Any]:
    active_profile = profile or get_profile()
    system_prompt = _load_prompt("diff_review.md")
    user_message = _build_user_message(
        {
            "intent": intent,
            "diff": diff,
            "context": context,
            "project_agents_md": project_agents_md,
        }
    )
    content = _call_model(
        system_prompt,
        user_message,
        model=model or get_default_model(active_profile),
        profile=active_profile,
    )
    return _parse_verdict(content)


def self_check(profile: ReviewerProfile | None = None) -> int:
    """Verify auth + model reachability. Returns process exit code."""
    active_profile = profile or get_profile()
    try:
        token = get_token()
    except AuthError as exc:
        print(f"[auth] {exc}", flush=True)
        return 2
    print(f"[auth] ok, token length {len(token)}", flush=True)

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = _build_request_body(
        system_prompt="Reply with exactly: PONG",
        user_message="ping",
        model=get_default_model(active_profile),
        profile=active_profile,
        token_budget=128,
    )
    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(GITHUB_MODELS_URL, headers=headers, json=body)
    except httpx.HTTPError as exc:
        print(f"[api] transport error: {exc}", flush=True)
        return 3
    if response.status_code != 200:
        print(f"[api] HTTP {response.status_code}: {response.text[:300]}", flush=True)
        return 4
    data = response.json()
    try:
        content = _extract_message_content(data)
    except RuntimeError as exc:
        print(f"[api] invalid content: {exc}", flush=True)
        return 5
    usage = data.get("usage", {})
    print(f"[api] ok, model={data.get('model')}, usage={usage}", flush=True)
    print(f"[api] content={content!r}", flush=True)
    return 0
