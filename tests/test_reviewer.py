from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from reviewer_mcp import reviewer, telemetry
from reviewer_mcp.auth import AuthError, get_token
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

    def test_kimi_uses_fireworks_url_and_max_tokens(self) -> None:
        profile = get_profile("kimi")
        body = reviewer._build_request_body(
            system_prompt="sys",
            user_message="user",
            model="accounts/fireworks/models/kimi-k2p6",
            profile=profile,
        )
        self.assertEqual(body["model"], "accounts/fireworks/models/kimi-k2p6")
        self.assertIn("max_tokens", body)
        self.assertNotIn("max_completion_tokens", body)
        self.assertEqual(profile.api_url, "https://api.fireworks.ai/inference/v1/chat/completions")


class ReviewerAuthTest(unittest.TestCase):
    def test_github_profile_falls_back_to_gh_cli(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["gh", "auth", "token"],
            returncode=0,
            stdout="gh-cli-token\n",
            stderr="",
        )
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("subprocess.run", return_value=completed) as run,
        ):
            token = get_token(get_profile("mistral"))
        self.assertEqual(token, "gh-cli-token")
        run.assert_called_once()

    def test_github_profile_surfaces_missing_gh(self) -> None:
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("subprocess.run", side_effect=FileNotFoundError),
        ):
            with self.assertRaisesRegex(AuthError, "gh` CLI not found"):
                get_token(get_profile("llama"))

    def test_github_profile_uses_env_token_first(self) -> None:
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "gh-token"}, clear=True):
            token = get_token(get_profile("codex"))
        self.assertEqual(token, "gh-token")

    def test_fireworks_profile_uses_fireworks_api_key(self) -> None:
        with mock.patch.dict(os.environ, {"FIREWORKS_API_KEY": "fw-token"}, clear=True):
            token = get_token(get_profile("kimi"))
        self.assertEqual(token, "fw-token")

    def test_fireworks_profile_requires_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_key_path = Path(temp_dir) / "missing-fireworks-key"
            with mock.patch.dict(
                os.environ,
                {"FIREWORKS_API_KEY_FILE": str(missing_key_path)},
                clear=True,
            ):
                with self.assertRaisesRegex(AuthError, "FIREWORKS_API_KEY"):
                    get_token(get_profile("kimi"))

    def test_fireworks_profile_reads_default_xdg_key_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir) / "config"
            key_path = config_dir / "reviewer-mcp" / "fireworks-api-key"
            key_path.parent.mkdir(parents=True)
            key_path.write_text("fw-file-token\n", encoding="utf-8")

            with mock.patch.dict(
                os.environ,
                {"XDG_CONFIG_HOME": str(config_dir)},
                clear=True,
            ):
                token = get_token(get_profile("kimi"))

        self.assertEqual(token, "fw-file-token")

    def test_fireworks_profile_honors_explicit_key_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            key_path = Path(temp_dir) / "kimi-token.txt"
            key_path.write_text("fw-explicit-token\n", encoding="utf-8")

            with mock.patch.dict(
                os.environ,
                {"FIREWORKS_API_KEY_FILE": str(key_path)},
                clear=True,
            ):
                token = get_token(get_profile("kimi"))

        self.assertEqual(token, "fw-explicit-token")

    def test_fireworks_profile_rejects_empty_key_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            key_path = Path(temp_dir) / "empty-token.txt"
            key_path.write_text("\n", encoding="utf-8")

            with mock.patch.dict(
                os.environ,
                {"FIREWORKS_API_KEY_FILE": str(key_path)},
                clear=True,
            ):
                with self.assertRaisesRegex(AuthError, "file is empty"):
                    get_token(get_profile("kimi"))


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

    def test_transport_errors_include_provider_name(self) -> None:
        profile = get_profile("kimi")
        with (
            mock.patch("reviewer_mcp.reviewer.get_token", return_value="fw-token"),
            mock.patch("httpx.Client") as client_cls,
        ):
            client = client_cls.return_value.__enter__.return_value
            client.post.side_effect = reviewer.httpx.ConnectError("boom")
            with self.assertRaisesRegex(reviewer.ModelCallError, "Fireworks AI API transport error"):
                reviewer._call_model({"model": profile.default_model}, profile)


if __name__ == "__main__":
    unittest.main()
