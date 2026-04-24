from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from reviewer_mcp import opencode


class OpenCodePathsTest(unittest.TestCase):
    def test_resolve_db_path_falls_back_when_opencode_missing(self) -> None:
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            with mock.patch.dict(os.environ, {}, clear=True):
                path = opencode.resolve_db_path()
        self.assertEqual(path, (Path.home() / ".local" / "share" / "opencode" / "opencode.db").resolve())


if __name__ == "__main__":
    unittest.main()
