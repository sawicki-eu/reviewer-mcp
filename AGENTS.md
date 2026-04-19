# reviewer-mcp — Adversarial review MCP servers

@../AGENTS.md

MCP server package that exposes multiple LLM-backed **adversarial reviewers** of the primary coding agent's plans and diffs. Aims to reduce single-model blind spots by letting the same prompts and tool schema run against different model families available on the GitHub Models API.

Runs as a local subprocess via STDIO transport — no ports, no cloud intermediary beyond the Models API itself.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -e .

# Verify API access (uses `gh auth token`):
.venv/bin/python -m reviewer_mcp --check --profile codex
.venv/bin/python -m reviewer_mcp --check --profile mistral
.venv/bin/python -m reviewer_mcp --check --profile llama

# Run server manually (Ctrl-C to stop; normally launched by OpenCode):
.venv/bin/python -m reviewer_mcp --profile codex
```

## MCP registration

Register one or more reviewer profiles at user scope so they are available in every project:

```bash
opencode mcp add --scope user --transport stdio codex-reviewer \
  -- $HOME/Projects/reviewer-mcp/.venv/bin/python -m reviewer_mcp --profile codex

opencode mcp add --scope user --transport stdio mistral-reviewer \
  -- $HOME/Projects/reviewer-mcp/.venv/bin/python -m reviewer_mcp --profile mistral

opencode mcp add --scope user --transport stdio llama-reviewer \
  -- $HOME/Projects/reviewer-mcp/.venv/bin/python -m reviewer_mcp --profile llama
```

(Exact command depends on your MCP client — see Integration below.)

## Tools

Every profile exports the same tools and JSON response contract.

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

## Profiles

### `codex`

Server name: `codex-reviewer`

Default model: `openai/o3`

Use when you want the strongest reasoning-oriented reviewer and can tolerate custom-tier GitHub rate limits. This profile uses the OpenAI-specific `max_completion_tokens` parameter because GitHub Models requires that for `o3`.

### `mistral`

Server name: `mistral-reviewer`

Default model: `mistral-ai/mistral-medium-2505`

Recommended alternate reviewer for routine adversarial review. This profile uses the generic `max_tokens` parameter required by Mistral on GitHub Models.

### `llama`

Server name: `llama-reviewer`

Default model: `meta/llama-4-scout-17b-16e-instruct`

Best fit for very large diffs or plans where the huge context window matters. This profile also uses `max_tokens`.

## Model overrides

Each profile has a built-in default model, but you can override it per call with the `model` parameter.

Environment overrides:

- `REVIEWER_PROFILE` selects the default profile when `--profile` is omitted.
- `REVIEWER_MODEL` overrides the default model for all profiles.
- `REVIEWER_CODEX_MODEL`, `REVIEWER_MISTRAL_MODEL`, `REVIEWER_LLAMA_MODEL` override only one profile.

## Project layout

```
reviewer-mcp/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── .venv/                           (gitignored)
└── reviewer_mcp/
    ├── __init__.py
    ├── __main__.py                  # CLI entry: --check or run server
    ├── profiles.py                  # Reviewer profile registry + defaults
    ├── server.py                    # FastMCP factory + tool registrations
    ├── reviewer.py                  # Shared GitHub Models client logic
    ├── auth.py                      # gh CLI token provider
    └── prompts/
        ├── plan_review.md
        └── diff_review.md
```

## Environment variables

| Var | Default | Purpose |
|-----|---------|---------|
| `GITHUB_TOKEN` | (unset) | Override token instead of calling `gh auth token` |
| `REVIEWER_PROFILE` | `codex` | Default reviewer profile when `--profile` is omitted |
| `REVIEWER_MODEL` | per profile | Override model ID for all profiles |
| `REVIEWER_CODEX_MODEL` | `openai/o3` | Override the codex profile model |
| `REVIEWER_MISTRAL_MODEL` | `mistral-ai/mistral-medium-2505` | Override the mistral profile model |
| `REVIEWER_LLAMA_MODEL` | `meta/llama-4-scout-17b-16e-instruct` | Override the llama profile model |
| `REVIEWER_TIMEOUT` | `120` | HTTP timeout in seconds |
| `REVIEWER_MAX_TOKENS` | per profile | Override output budget for all profiles |
| `REVIEWER_CODEX_MAX_TOKENS` | `8000` | Override the codex profile token budget |
| `REVIEWER_MISTRAL_MAX_TOKENS` | `4000` | Override the mistral profile token budget |
| `REVIEWER_LLAMA_MAX_TOKENS` | `4000` | Override the llama profile token budget |

## Tradeoffs

- **Latency**: every review adds 10–60s depending on input size. Soft default skips trivial changes.
- **Cost / limits**: GitHub Models has rate limits for Copilot subscribers; watch for 429s on heavy use, especially with the `codex` profile on `openai/o3`.
- **Provider quirks**: GitHub Models does not accept the same token parameter for every model family, so new profiles must specify the correct request shape.
- **Recursion**: reviewer does not itself have access to MCP tools, so no infinite loop risk.
- **No automatic file reading**: callers must pass content inline. Intentional — makes the review deterministic and keeps secrets out of the API call by default.
