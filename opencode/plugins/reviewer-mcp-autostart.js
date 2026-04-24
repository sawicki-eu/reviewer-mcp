import { readFile } from "node:fs/promises"
import { isAbsolute, relative, resolve } from "node:path"

const CONFIG_PATH = process.env.XDG_CONFIG_HOME
  ? `${process.env.XDG_CONFIG_HOME}/opencode/reviewer-mcp-autostart.json`
  : process.env.HOME
    ? `${process.env.HOME}/.config/opencode/reviewer-mcp-autostart.json`
    : null

function isInsideWorkspace(directory, workspaceRoot) {
  const rel = relative(resolve(workspaceRoot), resolve(directory))
  return rel === "" || (!rel.startsWith("..") && !isAbsolute(rel))
}

async function loadRegistry() {
  if (!CONFIG_PATH) return null
  try {
    const raw = await readFile(CONFIG_PATH, "utf8")
    return JSON.parse(raw)
  } catch {
    return null
  }
}

function selectWorkspaceConfig(registry, directory) {
  const workspaces = Array.isArray(registry?.workspaces) ? registry.workspaces : []
  return workspaces
    .filter((item) => typeof item?.workspace_root === "string" && item.workspace_root.length > 1)
    .sort((left, right) => right.workspace_root.length - left.workspace_root.length)
    .find((item) => isInsideWorkspace(directory, item.workspace_root))
}

export const ReviewerMcpAutostart = async ({ client, directory }) => {
  const registry = await loadRegistry()
  const config = selectWorkspaceConfig(registry, directory)
  const command = Array.isArray(config?.command) ? config.command : null
  if (!config || !command || command.length === 0) {
    return {}
  }

  return {
    "server.connected": async () => {
      try {
        const process = Bun.spawn({
          cmd: command,
          cwd: config.workspace_root,
          stdin: "ignore",
          stdout: "ignore",
          stderr: "pipe",
        })
        void (async () => {
          const exitCode = await process.exited
          if (exitCode === 0) {
            return
          }
          const stderr = process.stderr ? (await new Response(process.stderr).text()).trim() : ""
          await client.app.log({
            body: {
              service: "reviewer-mcp-autostart",
              level: "warn",
              message: "failed to ensure OpenCode mirror watcher",
              extra: {
                workspaceRoot: config.workspace_root,
                error: stderr || `exit status ${exitCode}`,
              },
            },
          })
        })()
      } catch (error) {
        await client.app.log({
          body: {
            service: "reviewer-mcp-autostart",
            level: "warn",
            message: "failed to ensure OpenCode mirror watcher",
            extra: {
              workspaceRoot: config.workspace_root,
              error: String(error),
            },
          },
        })
      }
    },
  }
}
