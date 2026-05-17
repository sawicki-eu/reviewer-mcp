# reviewer-mcp

MCP server package that exposes multiple adversarial reviewers across the GitHub Models API and Fireworks AI API.

Shared prompts and tool schemas are reused across multiple reviewer profiles:

- `codex-reviewer` on `openai/o3`
- `mistral-reviewer` on `mistral-ai/mistral-medium-2505`
- `llama-reviewer` on `meta/llama-4-scout-17b-16e-instruct`
- `kimi-reviewer` on `accounts/fireworks/models/kimi-k2p6`
- `deepseek-reviewer` on `accounts/fireworks/models/deepseek-v4-pro`

Each server exposes the same two tools:

- `review_plan`
- `review_diff`

Pick the reviewer whose model family best complements the primary agent, or register several and use them selectively.

## Install

Register one or more reviewer profiles as MCP servers at user scope so they are available in every project.

### OpenCode

Add entries to `~/.config/opencode/opencode.json` (or `opencode.jsonc`):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "codex-reviewer": {
      "type": "local",
      "command": [
        "/home/pawel/Projects/reviewer-mcp/.venv/bin/python",
        "-m", "reviewer_mcp", "--profile", "codex"
      ],
      "enabled": true
    },
    "mistral-reviewer": {
      "type": "local",
      "command": [
        "/home/pawel/Projects/reviewer-mcp/.venv/bin/python",
        "-m", "reviewer_mcp", "--profile", "mistral"
      ],
      "enabled": true
    },
    "llama-reviewer": {
      "type": "local",
      "command": [
        "/home/pawel/Projects/reviewer-mcp/.venv/bin/python",
        "-m", "reviewer_mcp", "--profile", "llama"
      ],
      "enabled": true
    },
    "kimi-reviewer": {
      "type": "local",
      "command": [
        "/home/pawel/Projects/reviewer-mcp/.venv/bin/python",
        "-m", "reviewer_mcp", "--profile", "kimi"
      ],
      "enabled": true
    },
    "deepseek-reviewer": {
      "type": "local",
      "command": [
        "/home/pawel/Projects/reviewer-mcp/.venv/bin/python",
        "-m", "reviewer_mcp", "--profile", "deepseek"
      ],
      "enabled": true
    }
  }
}
```

Alternatively, run `opencode mcp add` and use the interactive wizard (select **Global** scope, then provide the command and arguments above).

### Claude Code

Add entries to `~/.claude/settings.json` (create the file if it does not exist):

```json
{
  "mcpServers": {
    "codex-reviewer": {
      "command": "/home/pawel/Projects/reviewer-mcp/.venv/bin/python",
      "args": ["-m", "reviewer_mcp", "--profile", "codex"]
    },
    "mistral-reviewer": {
      "command": "/home/pawel/Projects/reviewer-mcp/.venv/bin/python",
      "args": ["-m", "reviewer_mcp", "--profile", "mistral"]
    },
    "llama-reviewer": {
      "command": "/home/pawel/Projects/reviewer-mcp/.venv/bin/python",
      "args": ["-m", "reviewer_mcp", "--profile", "llama"]
    },
    "kimi-reviewer": {
      "command": "/home/pawel/Projects/reviewer-mcp/.venv/bin/python",
      "args": ["-m", "reviewer_mcp", "--profile", "kimi"]
    },
    "deepseek-reviewer": {
      "command": "/home/pawel/Projects/reviewer-mcp/.venv/bin/python",
      "args": ["-m", "reviewer_mcp", "--profile", "deepseek"]
    }
  }
}
```

Adjust the Python path if you installed the virtual environment elsewhere.

Auth:

- GitHub-backed profiles use `GITHUB_TOKEN` or `gh auth token`
- `kimi-reviewer` and `deepseek-reviewer` use `FIREWORKS_API_KEY`, or reads `~/.config/reviewer-mcp/fireworks-api-key` by default (respecting `XDG_CONFIG_HOME`)

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

# Auto-commit brain/ artifacts (safety net)
.venv/bin/python -m reviewer_mcp brain-sync --watch --brain-root "$HOME/Projects/brain"

# Install brain-sync as systemd user service
.venv/bin/python -m reviewer_mcp install-brain-sync-autostart --brain-root "$HOME/Projects/brain"
```

`install-opencode-mirror-autostart` installs a global OpenCode plugin symlink plus a workspace registry under `~/.config/opencode/`, writes a user `systemd` service unit under `~/.config/systemd/user/`, and starts the watcher. On platforms where `systemd --user` is unavailable, it falls back to a detached background process with a workspace-specific PID lock and log file under `REVIEWER_STATE_DIR`.

### Brain-sync safety net

The `brain-sync` daemon auto-commits `brain/` artifacts (logs, sessions, scripts, decisions) to git every time they remain stable for 60 seconds. It complements the OpenCode plugin-based auto-commit by catching crashes, abrupt client closures, and other edge cases where the plugin cannot run.

- Polls `git status` every 30 seconds
- Commits with message `brain: safety-net sync <ISO-timestamp>`
- Flushes pending commits on SIGTERM
- Uses PID lock files to prevent duplicate instances
- **Never pushes** — push remains the OpenCode plugin's responsibility or explicit user action

See [AGENTS.md](AGENTS.md) for setup, usage, and design rationale.

## License

Licensed under the GNU Affero General Public License v3.0 or later — see [LICENSE](LICENSE).
