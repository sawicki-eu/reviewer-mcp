from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from reviewer_mcp import mirror, telemetry


class MirrorHelpersTest(unittest.TestCase):
    def test_profile_from_tool_name(self) -> None:
        self.assertEqual(mirror._profile_from_tool_name("codex-reviewer_review_plan"), "codex")
        self.assertEqual(mirror._profile_from_tool_name("mistral-reviewer_review_diff"), "mistral")
        self.assertIsNone(mirror._profile_from_tool_name("bash"))

    def test_tool_request_hash_only_for_reviewer_tools(self) -> None:
        part = {
            "type": "tool",
            "tool": "codex-reviewer_review_plan",
            "state": {"input": {"goal": "x", "plan": "y"}},
        }
        self.assertIsInstance(mirror._tool_request_hash(part), str)
        self.assertIsNone(mirror._tool_request_hash({"type": "text"}))

    def test_match_reviewer_raw(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            brain_root = Path(temp_dir) / "brain"
            bundle_dir = brain_root / "logs" / "2026-04-21" / "ses_root"
            bundle_dir.mkdir(parents=True)
            raw_path = brain_root / "logs" / "2026-04-21" / "reviewer-raw.jsonl"
            telemetry.append_jsonl(
                raw_path,
                {
                    "raw_event_id": "rev_1",
                    "request_hash": "abc",
                    "logical_tool": "review_plan",
                    "recorded_at": 1,
                },
            )
            matched = mirror._match_reviewer_raw(
                brain_root=brain_root,
                bundle_dir=bundle_dir,
                reviewer_hashes={"abc"},
                mirrored_at=2,
            )
            self.assertEqual(matched, 1)
            records = list(telemetry.iter_jsonl(bundle_dir / "reviewer-events.jsonl"))
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["raw_event_id"], "rev_1")


if __name__ == "__main__":
    unittest.main()
