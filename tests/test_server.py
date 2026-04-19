from __future__ import annotations

import unittest

from reviewer_mcp.profiles import get_profile
from reviewer_mcp.server import create_mcp


class ServerFactoryTest(unittest.TestCase):
    def test_codex_server_metadata(self) -> None:
        mcp = create_mcp(get_profile("codex"))
        self.assertEqual(mcp.name, "codex-reviewer")
        self.assertIn("OpenAI", mcp.instructions)

    def test_llama_server_metadata(self) -> None:
        mcp = create_mcp(get_profile("llama"))
        self.assertEqual(mcp.name, "llama-reviewer")
        self.assertIn("Meta Llama", mcp.instructions)


if __name__ == "__main__":
    unittest.main()
