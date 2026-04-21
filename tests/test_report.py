from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from reviewer_mcp import report, telemetry


class ReportTest(unittest.TestCase):
    def test_build_report_from_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            brain_root = Path(temp_dir) / "brain"
            bundle_dir = brain_root / "logs" / "2026-04-21" / "ses_root"
            bundle_dir.mkdir(parents=True)
            telemetry.append_jsonl(
                bundle_dir / "reviewer-events.jsonl",
                {
                    "raw_event_id": "rev_1",
                    "profile_key": "codex",
                    "logical_tool": "review_plan",
                    "verdict": "approve",
                    "duration_ms": 123,
                    "http_status": 200,
                    "error_class": None,
                },
            )
            telemetry.append_jsonl(
                brain_root / "logs" / "2026-04-21" / "reviewer-raw.jsonl",
                {
                    "raw_event_id": "rev_2",
                    "profile_key": "mistral",
                    "logical_tool": "review_diff",
                },
            )
            result = report.build_report(brain_root)
            self.assertEqual(result["session_bundle_count"], 1)
            self.assertEqual(result["reviewer_call_count"], 1)
            self.assertEqual(result["reviewer_calls_by_profile"]["codex"], 1)
            self.assertEqual(result["unmatched_reviewer_raw_count"], 1)


if __name__ == "__main__":
    unittest.main()
