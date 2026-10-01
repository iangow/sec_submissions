import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sec_submissions.http import resolve_user_agent, set_user_agent


class UserAgentTests(unittest.TestCase):
    def test_explicit_value_precedes_environment(self):
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Other User other@example.org"}):
            self.assertEqual(
                resolve_user_agent("Example User example@example.org", prompt=False),
                "Example User example@example.org",
            )

    def test_environment_resolution_and_validation(self):
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Example User example@example.org"}):
            self.assertEqual(resolve_user_agent(prompt=False), "Example User example@example.org")
        with patch.dict(os.environ, {"SEC_USER_AGENT": "python"}):
            with self.assertRaisesRegex(ValueError, "does not contain an email"):
                resolve_user_agent(prompt=False)

    def test_general_http_environment_is_a_fallback(self):
        with patch.dict(os.environ, {"HTTP_USER_AGENT": "Example User example@example.org"}, clear=True):
            self.assertEqual(resolve_user_agent(prompt=False), "Example User example@example.org")

    def test_project_persistence_preserves_other_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text("DATA_DIR=/data\nSEC_USER_AGENT=old@example.org\nOTHER=value\n")
            with patch("sec_submissions.http.Path.cwd", return_value=root):
                set_user_agent("New User new@example.org", "project")
                self.assertEqual(
                    (root / ".env").read_text(),
                    "DATA_DIR=/data\nSEC_USER_AGENT=New User new@example.org\nOTHER=value\n",
                )

    def test_interactive_prompt_can_select_project_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("sec_submissions.http.Path.cwd", return_value=root), \
                 patch.dict(os.environ, {}, clear=True), \
                 patch("builtins.input", side_effect=["Example User example@example.org", "project"]):
                resolved = resolve_user_agent(prompt=True)
            self.assertEqual(resolved, "Example User example@example.org")
            self.assertIn("SEC_USER_AGENT=Example User example@example.org", (root / ".env").read_text())


if __name__ == "__main__":
    unittest.main()
