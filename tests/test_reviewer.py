from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from reviewer_mcp import reviewer, telemetry
from reviewer_mcp.profiles import get_profile


class ReviewerRequestTest(unittest.TestCase):
    def test_codex_uses_max_completion_tokens(self) -> None:
        profile = get_profile("codex")
        body = reviewer._build_request_body(
            system_prompt="sys",
            user_message="user",
            model="openai/o3",
            profile=profile,
        )
        self.assertEqual(body["model"], "openai/o3")
        self.assertIn("max_completion_tokens", body)
        self.assertNotIn("max_tokens", body)

    def test_mistral_uses_max_tokens(self) -> None:
        profile = get_profile("mistral")
        body = reviewer._build_request_body(
            system_prompt="sys",
            user_message="user",
            model="mistral-ai/mistral-medium-2505",
            profile=profile,
        )
        self.assertEqual(body["model"], "mistral-ai/mistral-medium-2505")
        self.assertIn("max_tokens", body)
        self.assertNotIn("max_completion_tokens", body)


class ReviewerParsingTest(unittest.TestCase):
    def test_parse_json_with_fences(self) -> None:
        content = "```json\n{\"verdict\":\"approve\",\"summary\":\"ok\",\"confidence\":\"high\"}\n```"
        parsed = reviewer._parse_verdict(content)
        self.assertEqual(parsed["verdict"], "approve")

    def test_non_json_output_returns_challenge(self) -> None:
        parsed = reviewer._parse_verdict("not json")
        self.assertEqual(parsed["verdict"], "challenge")
        self.assertEqual(parsed["confidence"], "low")

    def test_empty_content_returns_challenge(self) -> None:
        parsed = reviewer._parse_verdict("")
        self.assertEqual(parsed["verdict"], "challenge")
        self.assertIn("non-JSON", parsed["summary"])


class ReviewerTelemetryTest(unittest.TestCase):
    def test_review_plan_writes_raw_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            brain_root = Path(temp_dir) / "brain"
            brain_root.mkdir()
            response = reviewer.ModelCallResult(
                request_body={"model": "openai/o3"},
                http_status=200,
                retry_after=None,
                response_text='{"choices":[{"message":{"content":"{\\"verdict\\":\\"approve\\",\\"summary\\":\\"ok\\",\\"confidence\\":\\"high\\"}"}}]}',
                response_json={
                    "choices": [
                        {
                            "message": {
                                "content": '{"verdict":"approve","summary":"ok","confidence":"high"}'
                            }
                        }
                    ],
                    "usage": {"total_tokens": 42},
                },
                assistant_content='{"verdict":"approve","summary":"ok","confidence":"high"}',
                usage={"total_tokens": 42},
            )
            with (
                mock.patch("reviewer_mcp.reviewer._call_model", return_value=response),
                mock.patch("reviewer_mcp.paths.find_brain_root", return_value=brain_root),
            ):
                parsed = reviewer.review_plan("goal", "plan")

            self.assertEqual(parsed["verdict"], "approve")
            raw_path = brain_root / telemetry.now_ms().__class__.__name__
            del raw_path
            day_dir = next((brain_root / "logs").iterdir())
            records = list(telemetry.iter_jsonl(day_dir / "reviewer-raw.jsonl"))
            self.assertEqual(len(records), 1)
            record = records[0]
            self.assertEqual(record["logical_tool"], "review_plan")
            self.assertEqual(record["verdict"], "approve")
            self.assertEqual(record["usage"], {"total_tokens": 42})
            self.assertNotIn("Authorization", str(record["request_body"]))

    def test_review_diff_logs_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            brain_root = Path(temp_dir) / "brain"
            brain_root.mkdir()
            error = reviewer.ModelCallError(
                "boom",
                request_body={"model": "openai/o3"},
                http_status=429,
                retry_after="10",
                response_text="rate limited",
                response_json={"error": "rate-limited"},
            )
            with (
                mock.patch("reviewer_mcp.reviewer._call_model", side_effect=error),
                mock.patch("reviewer_mcp.paths.find_brain_root", return_value=brain_root),
            ):
                with self.assertRaises(reviewer.ModelCallError):
                    reviewer.review_diff("intent", "diff")

            day_dir = next((brain_root / "logs").iterdir())
            records = list(telemetry.iter_jsonl(day_dir / "reviewer-raw.jsonl"))
            self.assertEqual(len(records), 1)
            record = records[0]
            self.assertEqual(record["logical_tool"], "review_diff")
            self.assertEqual(record["http_status"], 429)
            self.assertEqual(record["retry_after"], "10")
            self.assertEqual(record["error_class"], "ModelCallError")


if __name__ == "__main__":
    unittest.main()
