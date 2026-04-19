# codex-reviewer-mcp — Adversarial review MCP server

@../AGENTS.md

MCP server that exposes a second LLM as an **adversarial reviewer** of the primary coding agent's plans and diffs. Aims to reduce single-model blind spots by having a different model family (OpenAI `o3` via GitHub Models API) critique the primary agent's output.

Runs as a local subprocess via STDIO transport — no ports, no cloud intermediary beyond the Models API itself.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -e .

# Verify API access (uses `gh auth token`):
.venv/bin/python -m codex_reviewer_mcp --check

# Run server manually (Ctrl-C to stop; normally launched by OpenCode):
.venv/bin/python -m codex_reviewer_mcp
```

## MCP registration

Register once at user scope so it is available in every project:

```bash
opencode mcp add --scope user --transport stdio codex-reviewer \
  -- $HOME/Projects/codex-reviewer-mcp/.venv/bin/python -m codex_reviewer_mcp
```

(Exact command depends on your MCP client — see Integration below.)

## Tools

### `review_plan(goal, plan, context?, project_agents_md?, model?)`

Call **before** executing a non-trivial plan. Returns JSON:

```
{ "verdict": "approve" | "approve-with-concerns" | "challenge" | "reject",
  "summary": "...",
  "critical_issues": [...],
  "risks": [...],
  "missed_alternatives": [...],
  "convention_violations": [...],
  "questions_for_primary": [...],
  "confidence": "low" | "medium" | "high" }
```

### `review_diff(intent, diff, context?, project_agents_md?, model?)`

Call **after** making changes but **before** committing. Returns JSON with `bugs` (line-level) and `missing_tests` in addition to the same fields as `review_plan`.

## When to invoke

Soft default workflow:

1. User asks for a non-trivial change.
2. Primary agent plans. → Call `review_plan`.
3. Address `challenge`/`reject` feedback. Iterate if needed.
4. Primary agent implements.
5. → Call `review_diff` with the unified diff (`git diff`).
6. Address findings. Commit.

Skip review for:
- Typos, obvious one-line fixes
- When the user explicitly says "skip review"

Force review on demand: user says "review this" at any point.

## Auth

Uses `gh auth token` to reuse the GitHub CLI's stored PAT. The token must carry `models:read` scope (fine-grained PAT) or appropriate classic-PAT scope. Override with the `GITHUB_TOKEN` env var (useful for tests / CI).

## Model choice

Default: `openai/o3`. Rationale: different family than the primary agent (Claude), and reasoning-tuned so it catches logic flaws.

Override per-call with the `model` parameter, or globally via `CODEX_REVIEWER_MODEL` env var. Other good candidates available on the GitHub Models catalog: `openai/o4-mini`, `openai/gpt-5`.

## Project layout

```
codex-reviewer-mcp/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── .venv/                           (gitignored)
└── codex_reviewer_mcp/
    ├── __init__.py
    ├── __main__.py                  # CLI entry: --check or run server
    ├── server.py                    # FastMCP app + tool registrations
    ├── reviewer.py                  # HTTP client for GitHub Models API
    ├── auth.py                      # gh CLI token provider
    └── prompts/
        ├── plan_review.md
        └── diff_review.md
```

## Environment variables

| Var | Default | Purpose |
|-----|---------|---------|
| `GITHUB_TOKEN` | (unset) | Override token instead of calling `gh auth token` |
| `CODEX_REVIEWER_MODEL` | `openai/o3` | Reviewer model ID |
| `CODEX_REVIEWER_TIMEOUT` | `120` | HTTP timeout in seconds |
| `CODEX_REVIEWER_MAX_COMPLETION_TOKENS` | `8000` | Output budget (o-series burns most of this as reasoning tokens) |

## Tradeoffs

- **Latency**: every review adds 10–60s depending on input size. Soft default skips trivial changes.
- **Cost**: GitHub Models has rate limits for Copilot subscribers; watch for 429s on heavy use.
- **Recursion**: reviewer does not itself have access to MCP tools, so no infinite loop risk.
- **No automatic file reading**: callers must pass content inline. Intentional — makes the review deterministic and keeps secrets out of the API call by default.
