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

See [AGENTS.md](AGENTS.md) for setup, usage, and design rationale.

## License

Licensed under the GNU Affero General Public License v3.0 or later — see [LICENSE](LICENSE).
