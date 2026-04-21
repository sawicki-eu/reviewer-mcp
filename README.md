# reviewer-mcp

MCP server package that exposes multiple adversarial reviewers over the GitHub Models API.

Shared prompts and tool schemas are reused across multiple reviewer profiles:

- `codex-reviewer` on `openai/o3`
- `mistral-reviewer` on `mistral-ai/mistral-medium-2505`
- `llama-reviewer` on `meta/llama-4-scout-17b-16e-instruct`

Each server exposes the same two tools:

- `review_plan`
- `review_diff`

Pick the reviewer whose model family best complements the primary agent, or register several and use them selectively.

## Logging And Measurement

The package now also includes local measurement tooling for the adversarial-review workflow:

- raw reviewer call telemetry is appended under `brain/logs/YYYY-MM-DD/reviewer-raw.jsonl`
- OpenCode sessions can be mirrored near-real-time into `brain/logs/YYYY-MM-DD/ses_<root-session-id>/`
- bundle-local `reviewer-events.jsonl` files are matched back to reviewer raw telemetry by hashed tool input
- `report` can summarize tracked logs without querying OpenCode directly

Example commands:

```bash
# Near-real-time mirroring loop
.venv/bin/python -m reviewer_mcp mirror-opencode --watch --brain-root "$HOME/Projects/brain"

# One-shot sync / backfill
.venv/bin/python -m reviewer_mcp mirror-opencode --backfill --brain-root "$HOME/Projects/brain"

# Basic metrics report
.venv/bin/python -m reviewer_mcp report --brain-root "$HOME/Projects/brain" --format markdown
```

See [AGENTS.md](AGENTS.md) for setup, usage, and design rationale.

## License

Licensed under the GNU Affero General Public License v3.0 or later — see [LICENSE](LICENSE).
