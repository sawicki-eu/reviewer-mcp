# reviewer-mcp

MCP server package that exposes multiple adversarial reviewers across the GitHub Models API and Fireworks AI API.

Shared prompts and tool schemas are reused across multiple reviewer profiles:

- `codex-reviewer` on `openai/o3`
- `mistral-reviewer` on `mistral-ai/mistral-medium-2505`
- `llama-reviewer` on `meta/llama-4-scout-17b-16e-instruct`
- `kimi-reviewer` on `accounts/fireworks/models/kimi-k2p6`

Each server exposes the same two tools:

- `review_plan`
- `review_diff`

Pick the reviewer whose model family best complements the primary agent, or register several and use them selectively.

Auth:

- GitHub-backed profiles use `GITHUB_TOKEN` or `gh auth token`
- `kimi-reviewer` uses `FIREWORKS_API_KEY`, or reads `~/.config/reviewer-mcp/fireworks-api-key` by default (respecting `XDG_CONFIG_HOME`)

Example Fireworks key file setup:

```bash
mkdir -p "$HOME/.config/reviewer-mcp"
chmod 700 "$HOME/.config/reviewer-mcp"
printf '%s\n' '<YOUR_FIREWORKS_API_KEY>' > "$HOME/.config/reviewer-mcp/fireworks-api-key"
chmod 600 "$HOME/.config/reviewer-mcp/fireworks-api-key"
```

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

# Install OpenCode auto-start for this workspace
.venv/bin/python -m reviewer_mcp install-opencode-mirror-autostart --brain-root "$HOME/Projects/brain"

# One-shot sync / backfill
.venv/bin/python -m reviewer_mcp mirror-opencode --backfill --brain-root "$HOME/Projects/brain"

# Basic metrics report
.venv/bin/python -m reviewer_mcp report --brain-root "$HOME/Projects/brain" --format markdown
```

`install-opencode-mirror-autostart` installs a global OpenCode plugin symlink plus a workspace registry under `~/.config/opencode/`, writes a user `systemd` service unit under `~/.config/systemd/user/`, and starts the watcher. On platforms where `systemd --user` is unavailable, it falls back to a detached background process with a workspace-specific PID lock and log file under `REVIEWER_STATE_DIR`.

See [AGENTS.md](AGENTS.md) for setup, usage, and design rationale.

## License

Licensed under the GNU Affero General Public License v3.0 or later — see [LICENSE](LICENSE).
