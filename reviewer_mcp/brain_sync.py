"""Safety-net daemon that auto-commits brain/ artifacts to git.

Complements the OpenCode plugin-based auto-commit by catching crashes,
abrupt client closures, and other situations where the plugin cannot run.
Never pushes — push remains the responsibility of the OpenCode plugin or
explicit user action.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reviewer_mcp import paths

DEFAULT_POLL_INTERVAL = 30.0
DEFAULT_STABILITY_SECONDS = 60

GIT_COMMIT_MESSAGE = "brain: safety-net sync {iso}"


class BrainSyncError(RuntimeError):
    """Raised when the brain-sync daemon cannot operate."""


@dataclass(frozen=True)
class SyncConfig:
    brain_root: Path
    repo_root: Path
    poll_interval: float
    stability_seconds: int
    pid_file: Path | None


def _run_git(repo_root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _git_dir(repo_root: Path) -> Path | None:
    """Return the git directory if repo_root is inside a git repo, else None."""
    result = _run_git(repo_root, "rev-parse", "--git-dir", check=False)
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def _has_uncommitted_changes(repo_root: Path) -> bool:
    """Return True if brain/ has uncommitted or unstaged changes."""
    # Check staged changes
    staged = _run_git(repo_root, "diff", "--cached", "--quiet", "brain/", check=False)
    if staged.returncode != 0:
        return True
    # Check unstaged changes
    unstaged = _run_git(repo_root, "diff", "--quiet", "brain/", check=False)
    if unstaged.returncode != 0:
        return True
    # Check untracked files
    untracked = _run_git(repo_root, "ls-files", "--others", "--exclude-standard", "brain/", check=False)
    if untracked.stdout.strip():
        return True
    return False


def _commit_changes(repo_root: Path) -> bool:
    """Stage and commit brain/ changes. Return True if a commit was made."""
    # First verify there are actual changes (not just previously staged)
    diff_cached = _run_git(repo_root, "diff", "--cached", "--quiet", "brain/", check=False)
    diff_unstaged = _run_git(repo_root, "diff", "--quiet", "brain/", check=False)
    untracked = _run_git(repo_root, "ls-files", "--others", "--exclude-standard", "brain/", check=False)

    has_changes = (
        diff_cached.returncode != 0
        or diff_unstaged.returncode != 0
        or bool(untracked.stdout.strip())
    )

    if not has_changes:
        return False

    # Stage all brain/ changes
    _run_git(repo_root, "add", "brain/")

    # Verify staging produced something to commit
    diff_after_stage = _run_git(repo_root, "diff", "--cached", "--quiet", "brain/", check=False)
    if diff_after_stage.returncode == 0:
        # Nothing staged after add (e.g., all changes were already staged)
        return False

    iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    message = GIT_COMMIT_MESSAGE.format(iso=iso)
    _run_git(repo_root, "commit", "-m", message, check=False)
    return True


def _write_pid(pid_file: Path | None) -> None:
    if pid_file is None:
        return
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(f"{os.getpid()}\n", encoding="utf-8")


def _remove_pid(pid_file: Path | None) -> None:
    if pid_file is None:
        return
    try:
        pid_file.unlink()
    except FileNotFoundError:
        pass


def _stale_pid(pid_file: Path) -> bool:
    try:
        pid_text = pid_file.read_text(encoding="utf-8").strip()
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
    return False


def _check_pid_lock(pid_file: Path | None) -> None:
    if pid_file is None:
        return
    if not pid_file.exists():
        return
    if _stale_pid(pid_file):
        pid_file.unlink()
        return
    raise BrainSyncError(
        f"Another brain-sync instance appears to be running (PID file: {pid_file}). "
        "Stop it first or remove the PID file."
    )


class BrainSyncDaemon:
    def __init__(self, config: SyncConfig) -> None:
        self.config = config
        self._shutdown_requested = False
        self._stability_timer: float | None = None

    def _handle_signal(self, _signum: int, _frame: Any) -> None:
        self._shutdown_requested = True

    def _install_signal_handlers(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _flush(self) -> bool:
        """Attempt a final commit. Return True if a commit was made."""
        if not _has_uncommitted_changes(self.config.repo_root):
            return False
        return _commit_changes(self.config.repo_root)

    def run(self) -> int:
        self._install_signal_handlers()
        _write_pid(self.config.pid_file)
        try:
            print(
                f"[brain-sync] watching {self.config.brain_root} "
                f"(poll={self.config.poll_interval}s, stability={self.config.stability_seconds}s)",
                flush=True,
            )
            while not self._shutdown_requested:
                has_changes = _has_uncommitted_changes(self.config.repo_root)

                if has_changes and self._stability_timer is None:
                    # New changes detected — start stability timer
                    self._stability_timer = time.monotonic()
                    print(
                        f"[brain-sync] changes detected, starting {self.config.stability_seconds}s stability timer",
                        flush=True,
                    )
                elif has_changes and self._stability_timer is not None:
                    # Changes still present — check if stability period elapsed
                    elapsed = time.monotonic() - self._stability_timer
                    if elapsed >= self.config.stability_seconds:
                        committed = _commit_changes(self.config.repo_root)
                        if committed:
                            print("[brain-sync] committed brain/ changes", flush=True)
                        self._stability_timer = None
                elif not has_changes and self._stability_timer is not None:
                    # Changes disappeared before stability timer fired (e.g., committed by plugin)
                    print("[brain-sync] changes resolved externally, clearing timer", flush=True)
                    self._stability_timer = None

                # Sleep in short increments so we respond quickly to shutdown
                slept = 0.0
                while slept < self.config.poll_interval and not self._shutdown_requested:
                    time.sleep(1.0)
                    slept += 1.0

            # Shutdown requested — final flush
            print("[brain-sync] shutdown requested, flushing pending changes", flush=True)
            committed = self._flush()
            if committed:
                print("[brain-sync] committed brain/ changes on shutdown", flush=True)
            return 0
        finally:
            _remove_pid(self.config.pid_file)


def build_config(args: argparse.Namespace) -> SyncConfig:
    brain_root = paths.require_brain_root(explicit=args.brain_root)
    repo_root = brain_root.parent

    git_dir = _git_dir(repo_root)
    if git_dir is None:
        raise BrainSyncError(
            f"The workspace root {repo_root} does not appear to be a git repository. "
            "brain-sync requires the workspace to be tracked by git."
        )

    pid_file: Path | None = None
    if args.pid_file:
        pid_file = Path(args.pid_file).expanduser().resolve()
    elif os.environ.get("REVIEWER_STATE_DIR"):
        pid_file = (
            Path(os.environ["REVIEWER_STATE_DIR"]).expanduser().resolve()
            / "brain-sync.pid"
        )
    else:
        pid_file = Path.home() / ".local" / "state" / "reviewer-mcp" / "brain-sync.pid"

    _check_pid_lock(pid_file)

    return SyncConfig(
        brain_root=brain_root,
        repo_root=repo_root,
        poll_interval=args.poll_interval,
        stability_seconds=args.stability_seconds,
        pid_file=pid_file,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Brain-sync safety-net daemon")
    parser.add_argument("--brain-root", default=None, help="Path to the workspace brain directory")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=DEFAULT_POLL_INTERVAL,
        help=f"Polling interval in seconds (default: {DEFAULT_POLL_INTERVAL})",
    )
    parser.add_argument(
        "--stability-seconds",
        type=int,
        default=DEFAULT_STABILITY_SECONDS,
        help=f"Stability period before committing in seconds (default: {DEFAULT_STABILITY_SECONDS})",
    )
    parser.add_argument("--pid-file", default=None, help="Path to PID lock file")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Run the daemon continuously (default when no other action is specified)",
    )
    return parser


def run_cli(args: Any) -> None:
    config = build_config(args)
    if args.watch or True:  # Default to watch mode
        daemon = BrainSyncDaemon(config)
        sys.exit(daemon.run())
