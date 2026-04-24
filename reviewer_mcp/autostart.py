"""Auto-start helpers for the OpenCode transcript mirror."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from reviewer_mcp import opencode, paths

PLUGIN_FILE_NAME = "reviewer-mcp-autostart.js"
PLUGIN_CONFIG_FILE_NAME = "reviewer-mcp-autostart.json"


@dataclass(frozen=True)
class EnsureConfig:
    brain_root: Path
    db_path: Path
    state_dir: Path
    python_executable: Path
    project_root: Path
    user_config_dir: Path
    systemd_user_dir: Path


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_python_executable() -> Path:
    return Path(sys.executable).resolve()


def default_user_config_dir() -> Path:
    raw = os.environ.get("XDG_CONFIG_HOME")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".config").resolve()


def default_opencode_plugin_dir(user_config_dir: Path) -> Path:
    return user_config_dir / "opencode" / "plugins"


def default_opencode_config_dir(user_config_dir: Path) -> Path:
    return user_config_dir / "opencode"


def default_systemd_user_dir(user_config_dir: Path) -> Path:
    return user_config_dir / "systemd" / "user"


def workspace_key(config: EnsureConfig) -> str:
    return hashlib.sha256(str(config.brain_root).encode("utf-8")).hexdigest()[:12]


def default_lock_path(config: EnsureConfig) -> Path:
    return config.state_dir / f"opencode-mirror-{workspace_key(config)}.lock"


def lock_expected_tokens(config: EnsureConfig) -> list[str]:
    return [
        "reviewer_mcp",
        "mirror-opencode",
        "--brain-root",
        str(config.brain_root),
        "--db-path",
        str(config.db_path),
        "--state-dir",
        str(config.state_dir),
    ]


def build_config(
    *,
    brain_root: str | None = None,
    db_path: str | None = None,
    state_dir: str | None = None,
    python_executable: str | None = None,
    user_config_dir: str | None = None,
) -> EnsureConfig:
    resolved_user_config_dir = (
        Path(user_config_dir).expanduser().resolve() if user_config_dir else default_user_config_dir()
    )
    resolved_state_dir = paths.local_state_dir(state_dir)
    return EnsureConfig(
        brain_root=paths.require_brain_root(explicit=brain_root),
        db_path=opencode.resolve_db_path(db_path),
        state_dir=resolved_state_dir,
        python_executable=(
            Path(python_executable).expanduser().resolve()
            if python_executable
            else default_python_executable()
        ),
        project_root=project_root(),
        user_config_dir=resolved_user_config_dir,
        systemd_user_dir=default_systemd_user_dir(resolved_user_config_dir),
    )


def service_environment(config: EnsureConfig) -> dict[str, str]:
    return {
        "REVIEWER_BRAIN_ROOT": str(config.brain_root),
        "REVIEWER_STATE_DIR": str(config.state_dir),
    }


def service_name(config: EnsureConfig) -> str:
    return f"reviewer-mcp-opencode-mirror-{workspace_key(config)}.service"


def service_exec_args(config: EnsureConfig) -> list[str]:
    return [
        str(config.python_executable),
        "-m",
        "reviewer_mcp",
        "mirror-opencode",
        "--watch",
        "--brain-root",
        str(config.brain_root),
        "--db-path",
        str(config.db_path),
        "--state-dir",
        str(config.state_dir),
    ]


def render_systemd_service(config: EnsureConfig) -> str:
    exec_start = " ".join(json.dumps(arg) for arg in service_exec_args(config))
    environment = service_environment(config)
    environment_lines = [f"Environment={json.dumps(f'{key}={value}')}" for key, value in environment.items()]
    lines = [
        "[Unit]",
        "Description=Mirror OpenCode sessions into reviewer-mcp brain logs",
        "After=default.target",
        "",
        "[Service]",
        "Type=simple",
        f"WorkingDirectory={json.dumps(str(config.project_root))}",
        *environment_lines,
        f"ExecStart={exec_start}",
        "Restart=always",
        "RestartSec=5",
        "",
        "[Install]",
        "WantedBy=default.target",
        "",
    ]
    return "\n".join(lines)


def plugin_source_path(config: EnsureConfig) -> Path:
    return config.project_root / "opencode" / "plugins" / PLUGIN_FILE_NAME


def plugin_target_path(config: EnsureConfig) -> Path:
    return default_opencode_plugin_dir(config.user_config_dir) / PLUGIN_FILE_NAME


def service_target_path(config: EnsureConfig) -> Path:
    return config.systemd_user_dir / service_name(config)


def plugin_config_path(config: EnsureConfig) -> Path:
    return default_opencode_config_dir(config.user_config_dir) / PLUGIN_CONFIG_FILE_NAME


def _load_plugin_registry(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"schema_version": 1, "workspaces": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"schema_version": 1, "workspaces": []}
    workspaces = payload.get("workspaces")
    if not isinstance(payload, dict) or not isinstance(workspaces, list):
        return {"schema_version": 1, "workspaces": []}
    return {
        "schema_version": payload.get("schema_version", 1),
        "workspaces": [entry for entry in workspaces if isinstance(entry, dict)],
    }


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def install_plugin_symlink(config: EnsureConfig) -> Path:
    source = plugin_source_path(config)
    target = plugin_target_path(config)
    ensure_directory(target.parent)
    if target.is_symlink() or target.exists():
        if target.resolve() == source.resolve():
            return target
        raise RuntimeError(f"Refusing to overwrite existing plugin target: {target}")
    target.symlink_to(source)
    return target


def install_service_file(config: EnsureConfig) -> Path:
    target = service_target_path(config)
    ensure_directory(target.parent)
    rendered = render_systemd_service(config)
    if not target.exists() or target.read_text(encoding="utf-8") != rendered:
        target.write_text(rendered, encoding="utf-8")
    return target


def plugin_command(config: EnsureConfig) -> list[str]:
    return [
        str(config.python_executable),
        "-m",
        "reviewer_mcp",
        "ensure-opencode-mirror",
        "--brain-root",
        str(config.brain_root),
        "--db-path",
        str(config.db_path),
        "--state-dir",
        str(config.state_dir),
        "--python",
        str(config.python_executable),
        "--user-config-dir",
        str(config.user_config_dir),
        "--json",
    ]


def install_plugin_config(config: EnsureConfig) -> Path:
    target = plugin_config_path(config)
    ensure_directory(target.parent)
    registry = _load_plugin_registry(target)
    entry = {
        "brain_root": str(config.brain_root),
        "command": plugin_command(config),
        "workspace_root": str(config.brain_root.parent),
    }
    workspaces = [
        item
        for item in registry["workspaces"]
        if item.get("workspace_root") != entry["workspace_root"]
    ]
    workspaces.append(entry)
    payload = {
        "schema_version": 1,
        "workspaces": sorted(workspaces, key=lambda item: str(item.get("workspace_root", ""))),
    }
    target.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return target


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=check)


def systemd_is_usable() -> bool:
    try:
        probe = _run(["systemctl", "--user", "show-environment"], check=False)
    except FileNotFoundError:
        return False
    return probe.returncode == 0


def ensure_systemd_running(config: EnsureConfig) -> dict[str, object]:
    unit_path = install_service_file(config)
    _run(["systemctl", "--user", "daemon-reload"])
    name = service_name(config)
    start = _run(["systemctl", "--user", "start", name], check=False)
    is_active = _run(["systemctl", "--user", "is-active", name], check=False)
    return {
        "mode": "systemd",
        "service": name,
        "service_path": str(unit_path),
        "started": start.returncode == 0,
        "active": is_active.returncode == 0,
        "stderr": (start.stderr or is_active.stderr).strip() or None,
    }


def _running_process_matches(pid: int, expected_tokens: list[str]) -> bool:
    proc_cmdline = Path("/proc") / str(pid) / "cmdline"
    try:
        raw = proc_cmdline.read_bytes()
    except FileNotFoundError:
        raw = b""
    except PermissionError:
        return True
    if raw:
        tokens = [item.decode("utf-8", errors="replace") for item in raw.split(b"\x00") if item]
        return all(token in tokens for token in expected_tokens)
    try:
        result = _run(["ps", "-p", str(pid), "-o", "args="], check=False)
    except FileNotFoundError:
        return True
    command_line = result.stdout.strip()
    if not command_line:
        return False
    return all(token in command_line for token in expected_tokens)


def stale_pid(lock_path: Path, *, expected_tokens: list[str] | None = None) -> bool:
    try:
        pid_text = lock_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return True
    if not pid_text:
        return True
    try:
        pid = int(pid_text)
    except ValueError:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    if expected_tokens is not None and not _running_process_matches(pid, expected_tokens):
        return True
    return False


def ensure_detached_running(config: EnsureConfig) -> dict[str, object]:
    lock_path = default_lock_path(config)
    ensure_directory(lock_path.parent)
    if lock_path.exists() and not stale_pid(lock_path, expected_tokens=lock_expected_tokens(config)):
        return {
            "mode": "detached",
            "lock_path": str(lock_path),
            "started": False,
            "active": True,
        }
    log_path = config.state_dir / f"opencode-mirror-{workspace_key(config)}.log"
    with log_path.open("a", encoding="utf-8") as log_file:
        process = subprocess.Popen(  # noqa: S603
            service_exec_args(config),
            cwd=config.project_root,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env={**os.environ, **service_environment(config)},
        )
    lock_path.write_text(f"{process.pid}\n", encoding="utf-8")
    return {
        "mode": "detached",
        "lock_path": str(lock_path),
        "started": True,
        "active": True,
        "pid": process.pid,
        "log_path": str(log_path),
    }


def ensure_mirror_running(config: EnsureConfig) -> dict[str, object]:
    if systemd_is_usable():
        try:
            result = ensure_systemd_running(config)
        except (OSError, subprocess.CalledProcessError):
            result = None
        if result and result.get("active"):
            return result
    return ensure_detached_running(config)


def install_autostart(config: EnsureConfig) -> dict[str, object]:
    plugin_path = install_plugin_symlink(config)
    plugin_config = install_plugin_config(config)
    service_path = install_service_file(config)
    return {
        "plugin_path": str(plugin_path),
        "plugin_source": str(plugin_source_path(config)),
        "plugin_config_path": str(plugin_config),
        "service_path": str(service_path),
    }


def _ensure_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ensure the OpenCode mirror auto-start is installed")
    parser.add_argument("--brain-root", default=None)
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--state-dir", default=None)
    parser.add_argument("--python", dest="python_executable", default=None)
    parser.add_argument("--user-config-dir", default=None)
    parser.add_argument("--json", action="store_true", help="Print machine-readable output")
    parser.add_argument(
        "--no-start",
        action="store_true",
        help="Install/update artifacts without starting the watcher",
    )
    return parser


def run_install_cli(args: argparse.Namespace) -> None:
    config = build_config(
        brain_root=args.brain_root,
        db_path=args.db_path,
        state_dir=args.state_dir,
        python_executable=args.python_executable,
        user_config_dir=args.user_config_dir,
    )
    payload = {"installed": install_autostart(config)}
    if not args.no_start:
        payload["ensure"] = ensure_mirror_running(config)
    if args.json:
        print(json.dumps(payload, ensure_ascii=True, sort_keys=True))
        return
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))


def run_ensure_cli(args: argparse.Namespace) -> None:
    config = build_config(
        brain_root=args.brain_root,
        db_path=args.db_path,
        state_dir=args.state_dir,
        python_executable=args.python_executable,
        user_config_dir=args.user_config_dir,
    )
    payload = ensure_mirror_running(config)
    if args.json:
        print(json.dumps(payload, ensure_ascii=True, sort_keys=True))
        return
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
