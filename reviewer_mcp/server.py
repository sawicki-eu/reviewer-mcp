"""FastMCP server exposing adversarial-review tools."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from reviewer_mcp import reviewer
from reviewer_mcp.profiles import ReviewerProfile, get_profile


def _instructions_for(profile: ReviewerProfile) -> str:
    return (
        "Adversarial reviewer. Call `review_plan` BEFORE executing a non-trivial plan "
        "and `review_diff` AFTER making changes but BEFORE committing. "
        f"This server uses {profile.description} "
        "It returns a structured JSON verdict with fields: verdict, summary, "
        "critical_issues/bugs, risks, missed_alternatives, convention_violations, "
        "questions_for_primary, confidence. Respect `challenge` and `reject` verdicts: "
        "address them before proceeding. Skip review for trivial changes (typos, one-line "
        "obvious fixes) or when the user explicitly says 'skip review'."
    )


def create_mcp(profile: ReviewerProfile | None = None) -> FastMCP:
    """Build an MCP server bound to one reviewer profile."""

    active_profile = profile or get_profile()
    mcp = FastMCP(
        name=active_profile.server_name,
        instructions=_instructions_for(active_profile),
    )


    @mcp.tool()
    def review_plan(
        goal: str,
        plan: str,
        context: str | None = None,
        project_agents_md: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Adversarial review of a proposed plan before execution.

        Args:
            goal: What the user asked for, in their own words.
            plan: The primary agent's proposed plan (markdown ok).
            context: Optional relevant file excerpts, prior decisions, or constraints.
            project_agents_md: Optional contents of the target project's AGENTS.md
                so the reviewer can judge against project conventions.
            model: Optional override for the reviewer model.

        Returns:
            JSON dict with verdict, summary, critical_issues, risks,
            missed_alternatives, convention_violations, questions_for_primary,
            confidence.
        """
        return reviewer.review_plan(
            goal=goal,
            plan=plan,
            context=context,
            project_agents_md=project_agents_md,
            model=model,
            profile=active_profile,
        )


    @mcp.tool()
    def review_diff(
        intent: str,
        diff: str,
        context: str | None = None,
        project_agents_md: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Adversarial review of a diff before commit.

        Args:
            intent: What the change was meant to accomplish.
            diff: Unified diff of the proposed change.
            context: Optional related file excerpts (callers of changed functions,
                tests, etc.) or prior decisions.
            project_agents_md: Optional contents of the target project's AGENTS.md.
            model: Optional override for the reviewer model.

        Returns:
            JSON dict with verdict, summary, bugs, risks, convention_violations,
            missing_tests, missed_alternatives, questions_for_primary, confidence.
        """
        return reviewer.review_diff(
            intent=intent,
            diff=diff,
            context=context,
            project_agents_md=project_agents_md,
            model=model,
            profile=active_profile,
        )

    return mcp


mcp = create_mcp(get_profile("codex"))
