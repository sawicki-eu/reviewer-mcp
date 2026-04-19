"""Reviewer profile definitions for GitHub Models-backed MCP servers."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewerProfile:
    """Configuration for one reviewer server profile."""

    key: str
    server_name: str
    default_model: str
    token_parameter: str
    default_max_tokens: int
    description: str


PROFILES: dict[str, ReviewerProfile] = {
    "codex": ReviewerProfile(
        key="codex",
        server_name="codex-reviewer",
        default_model="openai/o3",
        token_parameter="max_completion_tokens",
        default_max_tokens=8000,
        description=(
            "OpenAI reasoning reviewer tuned to challenge plans and diffs before they land."
        ),
    ),
    "mistral": ReviewerProfile(
        key="mistral",
        server_name="mistral-reviewer",
        default_model="mistral-ai/mistral-medium-2505",
        token_parameter="max_tokens",
        default_max_tokens=4000,
        description=(
            "Mistral reviewer that provides an alternate model family for adversarial checks."
        ),
    ),
    "llama": ReviewerProfile(
        key="llama",
        server_name="llama-reviewer",
        default_model="meta/llama-4-scout-17b-16e-instruct",
        token_parameter="max_tokens",
        default_max_tokens=4000,
        description=(
            "Meta Llama reviewer suited for large-context plans and diffs."
        ),
    ),
}


def _normalize_profile_key(value: str | None) -> str:
    key = (value or "codex").strip().lower()
    if not key:
        return "codex"
    return key


def get_profile(profile: str | None = None) -> ReviewerProfile:
    """Return a configured reviewer profile.

    Resolution order:
    1. Explicit function argument
    2. ``REVIEWER_PROFILE`` environment variable
    3. Built-in default of ``codex``
    """

    key = _normalize_profile_key(profile or os.environ.get("REVIEWER_PROFILE"))
    try:
        return PROFILES[key]
    except KeyError as exc:
        available = ", ".join(sorted(PROFILES))
        raise ValueError(f"Unknown reviewer profile '{key}'. Available: {available}") from exc


def get_default_model(profile: ReviewerProfile) -> str:
    """Return the default model for a profile, honoring environment overrides."""

    specific = os.environ.get(f"REVIEWER_{profile.key.upper()}_MODEL")
    generic = os.environ.get("REVIEWER_MODEL")
    return specific or generic or profile.default_model


def get_default_max_tokens(profile: ReviewerProfile) -> int:
    """Return the token budget for a profile, honoring environment overrides."""

    specific = os.environ.get(f"REVIEWER_{profile.key.upper()}_MAX_TOKENS")
    generic = os.environ.get("REVIEWER_MAX_TOKENS")
    raw = specific or generic
    if raw is None:
        return profile.default_max_tokens
    return int(raw)
