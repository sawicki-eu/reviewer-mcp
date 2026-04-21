from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from reviewer_mcp import telemetry


class TelemetryTest(unittest.TestCase):
    def test_append_and_iter_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "events.jsonl"
            telemetry.append_jsonl(target, {"a": 1})
            telemetry.append_jsonl(target, {"b": 2})
            self.assertEqual(list(telemetry.iter_jsonl(target)), [{"a": 1}, {"b": 2}])


if __name__ == "__main__":
    unittest.main()
