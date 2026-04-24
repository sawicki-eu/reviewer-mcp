from __future__ import annotations

import os
import unittest
from unittest import mock

from reviewer_mcp.profiles import get_default_max_tokens, get_default_model, get_profile


class ProfilesTest(unittest.TestCase):
    def test_default_profile_is_codex(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            profile = get_profile()
        self.assertEqual(profile.key, "codex")
        self.assertEqual(profile.server_name, "codex-reviewer")

    def test_environment_selects_profile(self) -> None:
        with mock.patch.dict(os.environ, {"REVIEWER_PROFILE": "llama"}, clear=True):
            profile = get_profile()
        self.assertEqual(profile.key, "llama")
        self.assertEqual(profile.default_model, "meta/llama-4-scout-17b-16e-instruct")

    def test_kimi_profile_uses_fireworks_provider(self) -> None:
        profile = get_profile("kimi")
        self.assertEqual(profile.server_name, "kimi-reviewer")
        self.assertEqual(profile.provider_name, "Fireworks AI API")
        self.assertEqual(profile.api_url, "https://api.fireworks.ai/inference/v1/chat/completions")
        self.assertEqual(profile.auth_mode, "fireworks")
        self.assertEqual(profile.default_model, "accounts/fireworks/models/kimi-k2p6")

    def test_unknown_profile_raises_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown reviewer profile"):
            get_profile("nope")

    def test_specific_model_override_beats_generic(self) -> None:
        profile = get_profile("mistral")
        with mock.patch.dict(
            os.environ,
            {
                "REVIEWER_MODEL": "generic/model",
                "REVIEWER_MISTRAL_MODEL": "mistral/custom",
            },
            clear=True,
        ):
            model = get_default_model(profile)
        self.assertEqual(model, "mistral/custom")

    def test_specific_max_tokens_override_beats_generic(self) -> None:
        profile = get_profile("llama")
        with mock.patch.dict(
            os.environ,
            {
                "REVIEWER_MAX_TOKENS": "1234",
                "REVIEWER_LLAMA_MAX_TOKENS": "4321",
            },
            clear=True,
        ):
            tokens = get_default_max_tokens(profile)
        self.assertEqual(tokens, 4321)

    def test_kimi_specific_model_override_beats_generic(self) -> None:
        profile = get_profile("kimi")
        with mock.patch.dict(
            os.environ,
            {
                "REVIEWER_MODEL": "generic/model",
                "REVIEWER_KIMI_MODEL": "accounts/fireworks/models/custom-kimi",
            },
            clear=True,
        ):
            model = get_default_model(profile)
        self.assertEqual(model, "accounts/fireworks/models/custom-kimi")


if __name__ == "__main__":
    unittest.main()
