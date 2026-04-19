"""Reviewer: calls GitHub Models API with the adversarial-review prompt.

We use ``openai/o3`` by default — a reasoning-oriented model that is a different
family than the primary agent (Claude). The reviewer is strictly read-only; it
never touches the filesystem. The MCP tool packages the inputs, we send them
verbatim to the model, and return the structured JSON response.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

from codex_reviewer_mcp.auth import AuthError, get_token

GITHUB_MODELS_URL = "https://models.github.ai/inference/chat/completions"
DEFAULT_MODEL = os.environ.get("CODEX_REVIEWER_MODEL", "openai/o3")
DEFAULT_TIMEOUT = float(os.environ.get("CODEX_REVIEWER_TIMEOUT", "120"))
# o-series models consume output budget as reasoning tokens; need generous limit.
DEFAULT_MAX_COMPLETION_TOKENS = int(
    os.environ.get("CODEX_REVIEWER_MAX_COMPLETION_TOKENS", "8000")
)

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


def _call_model(system_prompt: str, user_message: str, model: str) -> str:
    token = get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "max_completion_tokens": DEFAULT_MAX_COMPLETION_TOKENS,
    }
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
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Unexpected response shape: {data}") from exc


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
) -> dict[str, Any]:
    system_prompt = _load_prompt("plan_review.md")
    user_message = _build_user_message(
        {
            "goal": goal,
            "plan": plan,
            "context": context,
            "project_agents_md": project_agents_md,
        }
    )
    content = _call_model(system_prompt, user_message, model or DEFAULT_MODEL)
    return _parse_verdict(content)


def review_diff(
    intent: str,
    diff: str,
    context: str | None = None,
    project_agents_md: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    system_prompt = _load_prompt("diff_review.md")
    user_message = _build_user_message(
        {
            "intent": intent,
            "diff": diff,
            "context": context,
            "project_agents_md": project_agents_md,
        }
    )
    content = _call_model(system_prompt, user_message, model or DEFAULT_MODEL)
    return _parse_verdict(content)


def self_check() -> int:
    """Verify auth + model reachability. Returns process exit code."""
    try:
        token = get_token()
    except AuthError as exc:
        print(f"[auth] {exc}", flush=True)
        return 2
    print(f"[auth] ok, token length {len(token)}", flush=True)

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {
        "model": DEFAULT_MODEL,
        "messages": [
            {"role": "system", "content": "Reply with exactly: PONG"},
            {"role": "user", "content": "ping"},
        ],
        "max_completion_tokens": 1000,
    }
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
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    usage = data.get("usage", {})
    print(f"[api] ok, model={data.get('model')}, usage={usage}", flush=True)
    print(f"[api] content={content!r}", flush=True)
    return 0
