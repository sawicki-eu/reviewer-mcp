from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from reviewer_mcp import autostart


class AutostartTest(unittest.TestCase):
    def test_install_plugin_config_merges_workspaces(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            user_config_dir = root / "config"
            (root / "workspace-one" / "brain").mkdir(parents=True)
            (root / "workspace-two" / "brain").mkdir(parents=True)

            config_one = autostart.build_config(
                brain_root=str(root / "workspace-one" / "brain"),
                db_path=str(root / "db1.sqlite"),
                state_dir=str(root / "state"),
                python_executable="/usr/bin/python3",
                user_config_dir=str(user_config_dir),
            )
            autostart.install_plugin_config(config_one)

            config_two = autostart.build_config(
                brain_root=str(root / "workspace-two" / "brain"),
                db_path=str(root / "db2.sqlite"),
                state_dir=str(root / "state"),
                python_executable="/usr/bin/python3",
                user_config_dir=str(user_config_dir),
            )
            path = autostart.install_plugin_config(config_two)

            payload = autostart._load_plugin_registry(path)
            self.assertEqual(len(payload["workspaces"]), 2)
            self.assertEqual(
                [item["workspace_root"] for item in payload["workspaces"]],
                [str(config_one.brain_root.parent), str(config_two.brain_root.parent)],
            )

    def test_service_name_varies_by_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "workspace-one" / "brain").mkdir(parents=True)
            (root / "workspace-two" / "brain").mkdir(parents=True)
            config_one = autostart.build_config(
                brain_root=str(root / "workspace-one" / "brain"),
                db_path=str(root / "db1.sqlite"),
                state_dir=str(root / "state"),
                python_executable="/usr/bin/python3",
                user_config_dir=str(root / "config"),
            )
            config_two = autostart.build_config(
                brain_root=str(root / "workspace-two" / "brain"),
                db_path=str(root / "db2.sqlite"),
                state_dir=str(root / "state"),
                python_executable="/usr/bin/python3",
                user_config_dir=str(root / "config"),
            )
            self.assertNotEqual(autostart.service_name(config_one), autostart.service_name(config_two))

    def test_install_plugin_symlink_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            brain_root = root / "workspace" / "brain"
            brain_root.mkdir(parents=True)
            config = autostart.build_config(
                brain_root=str(brain_root),
                db_path=str(root / "db.sqlite"),
                state_dir=str(root / "state"),
                python_executable="/usr/bin/python3",
                user_config_dir=str(root / "config"),
            )
            first = autostart.install_plugin_symlink(config)
            second = autostart.install_plugin_symlink(config)
            self.assertEqual(first, second)
            self.assertTrue(first.is_symlink())

    def test_stale_pid_when_different_process_reuses_pid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "watcher.lock"
            lock_path.write_text("123\n", encoding="utf-8")
            with mock.patch("os.kill"):
                with mock.patch("reviewer_mcp.autostart._running_process_matches", return_value=False):
                    self.assertTrue(
                        autostart.stale_pid(lock_path, expected_tokens=["reviewer_mcp", "mirror-opencode"])
                    )


if __name__ == "__main__":
    unittest.main()
