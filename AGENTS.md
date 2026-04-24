# reviewer-mcp — Adversarial review MCP servers

@../AGENTS.md

MCP server package that exposes multiple LLM-backed **adversarial reviewers** of the primary coding agent's plans and diffs. Aims to reduce single-model blind spots by letting the same prompts and tool schema run against different model families across the GitHub Models API and Fireworks AI API.

Runs as a local subprocess via STDIO transport — no ports, no cloud intermediary beyond the provider APIs themselves.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -e .

# Verify API access:
.venv/bin/python -m reviewer_mcp --check --profile codex
.venv/bin/python -m reviewer_mcp --check --profile mistral
.venv/bin/python -m reviewer_mcp --check --profile llama
.venv/bin/python -m reviewer_mcp --check --profile kimi

# Run server manually (Ctrl-C to stop; normally launched by OpenCode):
.venv/bin/python -m reviewer_mcp --profile codex

# Mirror local OpenCode sessions into brain/logs near-real-time:
.venv/bin/python -m reviewer_mcp mirror-opencode --watch --brain-root "$HOME/Projects/brain"

# Install native OpenCode auto-start for the mirror watcher:
.venv/bin/python -m reviewer_mcp install-opencode-mirror-autostart --brain-root "$HOME/Projects/brain"

# Summarize tracked telemetry and transcript bundles:
.venv/bin/python -m reviewer_mcp report --brain-root "$HOME/Projects/brain" --format markdown
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

opencode mcp add --scope user --transport stdio kimi-reviewer \
  -- $HOME/Projects/reviewer-mcp/.venv/bin/python -m reviewer_mcp --profile kimi
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

## Measurement and logs

`reviewer-mcp` now has two local-only measurement layers:

1. **Reviewer raw telemetry**
   - every `review_plan` / `review_diff` call writes one append-only JSON record under `brain/logs/YYYY-MM-DD/reviewer-raw.jsonl`
   - records include the rendered prompt payload, system prompt, request hash, raw provider response, parsed verdict, usage, latency, and error/429 details
   - GitHub auth headers and tokens are never logged

2. **OpenCode transcript mirroring**
    - `mirror-opencode --watch` polls the local OpenCode SQLite DB and mirrors updated root sessions into `brain/logs/YYYY-MM-DD/ses_<root-session-id>/`
    - `install-opencode-mirror-autostart` installs a global OpenCode plugin that triggers `ensure-opencode-mirror` on OpenCode startup for matching workspaces
    - startup prefers a workspace-specific user `systemd` service and falls back to a detached watcher process when `systemd --user` is unavailable
    - raw `opencode export` snapshots are preserved under `snapshots/`
    - append-only `opencode-events.jsonl` stores message metadata and part payloads
    - `reviewer-events.jsonl` stores matched reviewer raw telemetry for that session bundle

Tracked bundle layout:

```text
brain/logs/
  YYYY-MM-DD/
    reviewer-raw.jsonl
    ses_<root-session-id>/
      manifest.json
      index.json
      opencode-events.jsonl
      reviewer-events.jsonl
      snapshots/
```

These logs are intentionally verbatim and may contain secrets from prompts, tool I/O, or model responses. They are meant for a private workspace repo only.

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

GitHub-backed profiles reuse `gh auth token`. The token must carry `models:read` scope (fine-grained PAT) or appropriate classic-PAT scope. Override with `GITHUB_TOKEN` for tests or CI.

`kimi` uses `FIREWORKS_API_KEY`, or reads a one-line API key file from `~/.config/reviewer-mcp/fireworks-api-key` by default (respecting `XDG_CONFIG_HOME`). Override the file path with `FIREWORKS_API_KEY_FILE`.

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

### `kimi`

Server name: `kimi-reviewer`

Default model: `accounts/fireworks/models/kimi-k2p6`

Use when you want a Fireworks-backed reviewer built on Moonshot Kimi K2.6. This profile uses the generic `max_tokens` parameter on Fireworks' OpenAI-compatible chat endpoint.

## Model overrides

Each profile has a built-in default model, but you can override it per call with the `model` parameter.

Environment overrides:

- `REVIEWER_PROFILE` selects the default profile when `--profile` is omitted.
- `REVIEWER_MODEL` overrides the default model for all profiles.
- `REVIEWER_CODEX_MODEL`, `REVIEWER_MISTRAL_MODEL`, `REVIEWER_LLAMA_MODEL`, `REVIEWER_KIMI_MODEL` override only one profile.

## Project layout

```
reviewer-mcp/
├── AGENTS.md
├── README.md
├── opencode/
│   └── plugins/
│       └── reviewer-mcp-autostart.js
├── pyproject.toml
├── .venv/                           (gitignored)
└── reviewer_mcp/
    ├── __init__.py
    ├── __main__.py                  # CLI entry: server, mirror-opencode, report, autostart
    ├── autostart.py                 # OpenCode plugin + systemd/detached watcher orchestration
    ├── fingerprint.py               # Stable hashing for telemetry / mirror correlation
    ├── paths.py                     # brain/logs and local state path resolution
    ├── profiles.py                  # Reviewer profile registry + defaults
    ├── server.py                    # FastMCP factory + tool registrations
    ├── reviewer.py                  # Provider API client + raw reviewer telemetry
    ├── telemetry.py                 # Append-only JSONL helpers
    ├── opencode.py                  # Local OpenCode DB/export integration
    ├── mirror.py                    # Near-real-time transcript mirroring
    ├── report.py                    # Metrics reporting over tracked logs
    ├── auth.py                      # provider-specific token helpers
    └── prompts/
        ├── plan_review.md
        └── diff_review.md
```

## Environment variables

| Var | Default | Purpose |
|-----|---------|---------|
| `GITHUB_TOKEN` | (unset) | Override token instead of calling `gh auth token` |
| `FIREWORKS_API_KEY` | (unset) | Override the Fireworks API key instead of reading the key file |
| `FIREWORKS_API_KEY_FILE` | `~/.config/reviewer-mcp/fireworks-api-key` | File containing the Fireworks API key for the `kimi` profile |
| `REVIEWER_PROFILE` | `codex` | Default reviewer profile when `--profile` is omitted |
| `REVIEWER_MODEL` | per profile | Override model ID for all profiles |
| `REVIEWER_CODEX_MODEL` | `openai/o3` | Override the codex profile model |
| `REVIEWER_MISTRAL_MODEL` | `mistral-ai/mistral-medium-2505` | Override the mistral profile model |
| `REVIEWER_LLAMA_MODEL` | `meta/llama-4-scout-17b-16e-instruct` | Override the llama profile model |
| `REVIEWER_KIMI_MODEL` | `accounts/fireworks/models/kimi-k2p6` | Override the Kimi profile model |
| `REVIEWER_TIMEOUT` | `120` | HTTP timeout in seconds |
| `REVIEWER_MAX_TOKENS` | per profile | Override output budget for all profiles |
| `REVIEWER_CODEX_MAX_TOKENS` | `8000` | Override the codex profile token budget |
| `REVIEWER_MISTRAL_MAX_TOKENS` | `4000` | Override the mistral profile token budget |
| `REVIEWER_LLAMA_MAX_TOKENS` | `4000` | Override the llama profile token budget |
| `REVIEWER_KIMI_MAX_TOKENS` | `4000` | Override the Kimi profile token budget |
| `REVIEWER_BRAIN_ROOT` | auto-detect | Override the workspace `brain/` directory |
| `REVIEWER_STATE_DIR` | `~/.local/state/reviewer-mcp` | Local cursor/dedupe state for mirroring |

## Tradeoffs

- **Latency**: every review adds 10–60s depending on input size. Soft default skips trivial changes.
- **Cost / limits**: provider limits differ. GitHub Models may 429 on heavier use, while Fireworks usage consumes your Fireworks account credits.
- **Provider quirks**: model families and providers do not accept the same token parameter or auth source, so profiles must specify the correct request shape and credential source.
- **Recursion**: reviewer does not itself have access to MCP tools, so no infinite loop risk.
- **No automatic file reading**: callers must pass content inline. Intentional — makes the review deterministic and keeps secrets out of the API call by default.
- **Auto-start scope**: the global plugin is shared across workspaces, but it only starts the watcher for workspaces listed in `~/.config/opencode/reviewer-mcp-autostart.json`.
- **Background process fallback**: on systems without user `systemd`, a detached watcher is started instead, so cleanup and journaling are less uniform than the `systemd` path.
- **Verbatim local logs**: raw transcript and reviewer artifacts are preserved for later analysis, so the tracked `brain/logs/` history will grow over time.
