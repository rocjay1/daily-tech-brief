import unittest
import os
import json
from unittest.mock import MagicMock, patch
from src.daily_brief import clean_html, load_config, StateManager

class TestDailyBrief(unittest.TestCase):

    def test_clean_html(self):
        """Test HTML cleaning function."""
        self.assertEqual(clean_html("<p>Hello</p>"), "Hello")
        self.assertEqual(clean_html("<div><b>Bold</b></div>"), "Bold")
        self.assertEqual(clean_html("No tags"), "No tags")
        self.assertEqual(clean_html(None), "")
        self.assertEqual(clean_html(""), "")
        # Test entity unescaping
        self.assertEqual(clean_html("Tom &amp; Jerry"), "Tom & Jerry")
        self.assertEqual(clean_html("&#62;"), ">")

    @patch("builtins.open", new_callable=unittest.mock.mock_open, read_data='{"feeds": {"test": "url"}}')
    def test_load_config_mock(self, mock_file):
        """Test load_config with mocked file."""
        config = load_config("dummy_config.json")
        self.assertEqual(config["feeds"]["test"], "url")

    def test_state_manager_get_id(self):
        """Test deterministic hashing."""
        with patch("src.daily_brief.firestore.Client"):
            sm = StateManager("test-project")
            url = "http://example.com/article"
            hash1 = sm.get_id(url)
            hash2 = sm.get_id(url)
            self.assertEqual(hash1, hash2)
            self.assertIsInstance(hash1, str)
            self.assertEqual(len(hash1), 32) # MD5 is 32 hex chars

    def test_state_manager_init_no_project_id(self):
        """Test initialization without project_id."""
        sm = StateManager(None)
        self.assertIsNone(sm.db)

if __name__ == '__main__':
    unittest.main()
