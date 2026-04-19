from __future__ import annotations

import unittest
from unittest import mock

from reviewer_mcp import reviewer
from reviewer_mcp.profiles import get_profile


class ReviewerRequestTest(unittest.TestCase):
    def test_codex_uses_max_completion_tokens(self) -> None:
        profile = get_profile("codex")
        captured: dict[str, object] = {}

        class FakeResponse:
            status_code = 200
            headers: dict[str, str] = {}

            def json(self) -> dict[str, object]:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": '{"verdict":"approve","summary":"ok","confidence":"high"}'
                            }
                        }
                    ]
                }

        class FakeClient:
            def __init__(self, *, timeout: float) -> None:
                self.timeout = timeout

            def __enter__(self) -> FakeClient:
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]):
                captured["url"] = url
                captured["headers"] = headers
                captured["json"] = json
                return FakeResponse()

        with (
            mock.patch("reviewer_mcp.reviewer.get_token", return_value="token"),
            mock.patch("reviewer_mcp.reviewer.httpx.Client", FakeClient),
        ):
            reviewer.review_plan("goal", "plan", profile=profile)

        body = captured["json"]
        self.assertEqual(body["model"], "openai/o3")
        self.assertIn("max_completion_tokens", body)
        self.assertNotIn("max_tokens", body)

    def test_mistral_uses_max_tokens(self) -> None:
        profile = get_profile("mistral")
        captured: dict[str, object] = {}

        class FakeResponse:
            status_code = 200
            headers: dict[str, str] = {}

            def json(self) -> dict[str, object]:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": '{"verdict":"approve","summary":"ok","confidence":"high"}'
                            }
                        }
                    ]
                }

        class FakeClient:
            def __init__(self, *, timeout: float) -> None:
                self.timeout = timeout

            def __enter__(self) -> FakeClient:
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]):
                captured["json"] = json
                return FakeResponse()

        with (
            mock.patch("reviewer_mcp.reviewer.get_token", return_value="token"),
            mock.patch("reviewer_mcp.reviewer.httpx.Client", FakeClient),
        ):
            reviewer.review_diff("intent", "diff", profile=profile)

        body = captured["json"]
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


if __name__ == "__main__":
    unittest.main()
