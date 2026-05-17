from __future__ import annotations

import os
import signal
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from reviewer_mcp import brain_sync


class BrainSyncGitHelpersTest(unittest.TestCase):
    def test_has_uncommitted_changes_detects_staged(self) -> None:
        with mock.patch(
            "reviewer_mcp.brain_sync._run_git",
            side_effect=lambda repo, *args, check=True: self._fake_run(repo, args),
        ):
            # staged diff returns non-zero (has changes)
            self._git_responses = {
                ("diff", "--cached", "--quiet", "brain/"): 1,
                ("diff", "--quiet", "brain/"): 0,
                ("ls-files", "--others", "--exclude-standard", "brain/"): "",
            }
            self.assertTrue(brain_sync._has_uncommitted_changes(Path("/repo")))

    def test_has_uncommitted_changes_detects_unstaged(self) -> None:
        with mock.patch(
            "reviewer_mcp.brain_sync._run_git",
            side_effect=lambda repo, *args, check=True: self._fake_run(repo, args),
        ):
            self._git_responses = {
                ("diff", "--cached", "--quiet", "brain/"): 0,
                ("diff", "--quiet", "brain/"): 1,
                ("ls-files", "--others", "--exclude-standard", "brain/"): "",
            }
            self.assertTrue(brain_sync._has_uncommitted_changes(Path("/repo")))

    def test_has_uncommitted_changes_detects_untracked(self) -> None:
        with mock.patch(
            "reviewer_mcp.brain_sync._run_git",
            side_effect=lambda repo, *args, check=True: self._fake_run(repo, args),
        ):
            self._git_responses = {
                ("diff", "--cached", "--quiet", "brain/"): 0,
                ("diff", "--quiet", "brain/"): 0,
                ("ls-files", "--others", "--exclude-standard", "brain/"): "brain/logs/foo.jsonl",
            }
            self.assertTrue(brain_sync._has_uncommitted_changes(Path("/repo")))

    def test_has_uncommitted_changes_clean_repo(self) -> None:
        with mock.patch(
            "reviewer_mcp.brain_sync._run_git",
            side_effect=lambda repo, *args, check=True: self._fake_run(repo, args),
        ):
            self._git_responses = {
                ("diff", "--cached", "--quiet", "brain/"): 0,
                ("diff", "--quiet", "brain/"): 0,
                ("ls-files", "--others", "--exclude-standard", "brain/"): "",
            }
            self.assertFalse(brain_sync._has_uncommitted_changes(Path("/repo")))

    def _fake_run(
        self, repo: Path, args: tuple[str, ...]
    ) -> mock.MagicMock:
        key = tuple(args)
        rc = self._git_responses.get(key, 0)
        stdout = self._git_responses.get(key, "")
        if isinstance(stdout, int):
            stdout = ""
        result = mock.MagicMock()
        result.returncode = rc if isinstance(rc, int) else 0
        result.stdout = stdout if isinstance(stdout, str) else ""
        return result

    def test_commit_changes_skips_when_nothing_to_commit(self) -> None:
        with mock.patch(
            "reviewer_mcp.brain_sync._run_git",
            side_effect=lambda repo, *args, check=True: self._fake_run_commit(repo, args),
        ):
            self._commit_responses = {
                ("diff", "--cached", "--quiet", "brain/"): 0,
                ("diff", "--quiet", "brain/"): 0,
                ("ls-files", "--others", "--exclude-standard", "brain/"): "",
            }
            self.assertFalse(brain_sync._commit_changes(Path("/repo")))

    def test_commit_changes_adds_and_commits(self) -> None:
        calls: list[tuple[str, ...]] = []
        added = False

        def capture(repo: Path, *args: str, check: bool = True) -> mock.MagicMock:
            nonlocal added
            calls.append(tuple(args))
            result = mock.MagicMock()
            if args == ("diff", "--cached", "--quiet", "brain/"):
                result.returncode = 1 if added else 0  # staged after add
            elif args == ("diff", "--quiet", "brain/"):
                result.returncode = 1  # unstaged changes exist
            elif args == ("ls-files", "--others", "--exclude-standard", "brain/"):
                result.stdout = ""
            elif args == ("add", "brain/"):
                added = True
                result.returncode = 0
            elif args[0] == "commit":
                result.returncode = 0
            else:
                result.returncode = 0
            return result

        with mock.patch("reviewer_mcp.brain_sync._run_git", side_effect=capture):
            self.assertTrue(brain_sync._commit_changes(Path("/repo")))

        # Verify git add and git commit were called
        self.assertIn(("add", "brain/"), calls)
        commit_calls = [c for c in calls if c[0] == "commit"]
        self.assertEqual(len(commit_calls), 1)
        # commit args: ("commit", "-m", "brain: safety-net sync ...")
        self.assertTrue(
            any(arg.startswith("brain: safety-net sync") for arg in commit_calls[0]),
            f"Expected commit message starting with 'brain: safety-net sync', got {commit_calls[0]}",
        )

    def _fake_run_commit(self, repo: Path, args: tuple[str, ...]) -> mock.MagicMock:
        key = tuple(args)
        rc = self._commit_responses.get(key, 0)
        stdout = self._commit_responses.get(key, "")
        if isinstance(stdout, int):
            stdout = ""
        result = mock.MagicMock()
        result.returncode = rc if isinstance(rc, int) else 0
        result.stdout = stdout if isinstance(stdout, str) else ""
        return result


class BrainSyncPathTest(unittest.TestCase):
    def test_git_dir_returns_none_for_non_git(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertIsNone(brain_sync._git_dir(Path(temp_dir)))

    def test_git_dir_returns_path_for_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            subprocess.run(["git", "init"], cwd=temp_dir, check=True, capture_output=True)
            result = brain_sync._git_dir(Path(temp_dir))
            self.assertIsNotNone(result)

    def test_build_config_raises_for_non_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            brain_root = Path(temp_dir) / "brain"
            brain_root.mkdir()
            args = mock.MagicMock()
            args.brain_root = str(brain_root)
            args.poll_interval = 30.0
            args.stability_seconds = 60
            args.pid_file = None
            with mock.patch("reviewer_mcp.brain_sync.paths.require_brain_root", return_value=brain_root):
                with self.assertRaises(brain_sync.BrainSyncError) as ctx:
                    brain_sync.build_config(args)
            self.assertIn("does not appear to be a git repository", str(ctx.exception))

    def test_build_config_succeeds_for_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            subprocess.run(["git", "init"], cwd=temp_dir, check=True, capture_output=True)
            brain_root = Path(temp_dir) / "brain"
            brain_root.mkdir()
            args = mock.MagicMock()
            args.brain_root = str(brain_root)
            args.poll_interval = 30.0
            args.stability_seconds = 60
            args.pid_file = None
            with mock.patch("reviewer_mcp.brain_sync.paths.require_brain_root", return_value=brain_root):
                config = brain_sync.build_config(args)
            self.assertEqual(config.brain_root, brain_root)
            self.assertEqual(config.repo_root, Path(temp_dir))


class BrainSyncDaemonTest(unittest.TestCase):
    def test_sigterm_handler_sets_flag(self) -> None:
        config = mock.MagicMock()
        config.repo_root = Path("/repo")
        config.poll_interval = 0.1
        config.stability_seconds = 0.2
        config.pid_file = None

        daemon = brain_sync.BrainSyncDaemon(config)
        self.assertFalse(daemon._shutdown_requested)
        daemon._handle_signal(signal.SIGTERM, None)
        self.assertTrue(daemon._shutdown_requested)

    def test_flush_commits_pending_changes(self) -> None:
        config = mock.MagicMock()
        config.repo_root = Path("/repo")

        with mock.patch(
            "reviewer_mcp.brain_sync._has_uncommitted_changes",
            return_value=True,
        ), mock.patch(
            "reviewer_mcp.brain_sync._commit_changes",
            return_value=True,
        ) as mock_commit:
            daemon = brain_sync.BrainSyncDaemon(config)
            result = daemon._flush()
            self.assertTrue(result)
            mock_commit.assert_called_once_with(Path("/repo"))

    def test_flush_skips_when_no_changes(self) -> None:
        config = mock.MagicMock()
        config.repo_root = Path("/repo")

        with mock.patch(
            "reviewer_mcp.brain_sync._has_uncommitted_changes",
            return_value=False,
        ), mock.patch(
            "reviewer_mcp.brain_sync._commit_changes",
        ) as mock_commit:
            daemon = brain_sync.BrainSyncDaemon(config)
            result = daemon._flush()
            self.assertFalse(result)
            mock_commit.assert_not_called()

    def test_pid_lock_prevents_duplicate_instances(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pid_file = Path(temp_dir) / "brain-sync.pid"
            pid_file.write_text(f"{os.getpid()}\n", encoding="utf-8")
            with self.assertRaises(brain_sync.BrainSyncError) as ctx:
                brain_sync._check_pid_lock(pid_file)
            self.assertIn("Another brain-sync instance", str(ctx.exception))

    def test_stale_pid_file_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pid_file = Path(temp_dir) / "brain-sync.pid"
            pid_file.write_text("99999\n", encoding="utf-8")
            # PID 99999 should not exist
            brain_sync._check_pid_lock(pid_file)
            self.assertFalse(pid_file.exists())


class BrainSyncNoPushTest(unittest.TestCase):
    def test_commit_changes_never_calls_push(self) -> None:
        """Critical safety invariant: brain-sync must never push."""
        calls: list[tuple[str, ...]] = []

        def capture(repo: Path, *args: str, check: bool = True) -> mock.MagicMock:
            calls.append(tuple(args))
            result = mock.MagicMock()
            if args == ("diff", "--cached", "--quiet", "brain/"):
                result.returncode = 0
            elif args == ("diff", "--quiet", "brain/"):
                result.returncode = 1
            elif args == ("ls-files", "--others", "--exclude-standard", "brain/"):
                result.stdout = ""
            elif args == ("add", "brain/"):
                result.returncode = 0
            elif args == ("commit", "-m"):
                result.returncode = 0
            else:
                result.returncode = 0
            return result

        with mock.patch("reviewer_mcp.brain_sync._run_git", side_effect=capture):
            brain_sync._commit_changes(Path("/repo"))

        push_calls = [c for c in calls if "push" in c]
        self.assertEqual(len(push_calls), 0, "brain_sync._commit_changes must never invoke git push")


import subprocess


if __name__ == "__main__":
    unittest.main()
