"""Unit tests for parsers."""

import unittest
from unittest.mock import MagicMock, patch
import sys
import os


from src.parsers.github import GitHubChangelogParser
from src.parsers.rss import RSSParser


class TestGitHubParser(unittest.TestCase):
    def test_convert_to_raw(self):
        parser = GitHubChangelogParser()
        blob_url = "https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md"
        expected = (
            "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md"
        )
        self.assertEqual(parser._convert_to_raw_url(blob_url), expected)

        # Should leave other URLs alone
        raw_url = "https://raw.githubusercontent.com/foo/bar/main/baz.md"
        self.assertEqual(parser._convert_to_raw_url(raw_url), raw_url)

    @patch("requests.get")
    def test_fetch_changelog(self, mock_get):
        parser = GitHubChangelogParser()

        # Mock response
        mock_resp = MagicMock()
        mock_resp.text = """
## 2.1.22
- Fixed stuff

## 2.1.21
- Added stuff
"""
        mock_get.return_value = mock_resp

        items = parser.fetch(
            "Test Source", "https://github.com/org/repo/blob/main/CHANGELOG.md"
        )

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "Changelog 2.1.22")
        self.assertIn("Fixed stuff", items[0]["summary"])
        self.assertEqual(items[1]["title"], "Changelog 2.1.21")


class TestRSSParser(unittest.TestCase):
    def test_clean_html(self):
        parser = RSSParser()
        html = "<p>Hello <b>World</b></p>"
        clean = parser._clean_html(html)
        self.assertEqual(clean, "Hello World")


if __name__ == "__main__":
    unittest.main()
