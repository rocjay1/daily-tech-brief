"""Unit tests for daily_brief module."""

import unittest
from unittest.mock import MagicMock, patch
import sys
import os


# Mock external dependencies before importing the module
sys.modules["google"] = MagicMock()
sys.modules["google.genai"] = MagicMock()
sys.modules["google.cloud"] = MagicMock()
sys.modules["google.cloud.firestore"] = MagicMock()
sys.modules["feedparser"] = MagicMock()

# Set env vars
os.environ["EMAIL_USER"] = "test@example.com"
os.environ["EMAIL_PASS"] = "secret"
os.environ["GEMINI_KEY"] = "fake_key"
os.environ["GCP_PROJECT_ID"] = "fake_project"

from src import daily_brief  # pylint: disable=wrong-import-position  # type: ignore
from src.services.email_service import EmailService  # type: ignore


class TestDailyBrief(unittest.TestCase):
    """Test cases for Daily Brief application."""

    def setUp(self):
        # Reset FEEDS before each test
        self.original_feeds = daily_brief.FEEDS
        daily_brief.FEEDS = {
            "platform_updates": {"Platform Feed": "http://p.com/rss"},
            "blogs": {"Blog Feed": "http://b.com/rss"},
        }

    def tearDown(self):
        daily_brief.FEEDS = self.original_feeds

    @patch("src.daily_brief.get_articles")
    @patch("src.daily_brief.LLMService")
    @patch("src.daily_brief.EmailService")
    @patch("src.daily_brief.StateManager")
    def test_main_workflow_split(
        self,
        mock_state_manager,
        mock_email_service,
        mock_llm_service,
        mock_get_articles,
    ):
        """Test that main fetches feeds separately, analyzes them with limits,
        and sends combined email."""

        # Setup mocks
        mock_db_instance = mock_state_manager.return_value
        mock_email_instance = mock_email_service.return_value
        mock_llm_instance = mock_llm_service.return_value

        # Mock get_articles to return different items based on input feeds
        def get_articles_side_effect(feeds):
            if "Platform Feed" in feeds:
                return [
                    {
                        "link": f"p{i}",
                        "source": "Platform Feed",
                        "title": f"P{i}",
                        "full_text": f"Text P{i}",
                        "summary": f"Sum P{i}",
                    }
                    for i in range(20)
                ]
            if "Blog Feed" in feeds:
                return [
                    {
                        "link": f"b{i}",
                        "source": "Blog Feed",
                        "title": f"B{i}",
                        "full_text": f"Text B{i}",
                        "summary": f"Sum B{i}",
                    }
                    for i in range(20)
                ]
            return []

        mock_get_articles.side_effect = get_articles_side_effect

        # Mock filter_new to return all articles as new
        mock_db_instance.filter_new.side_effect = lambda articles: articles

        # Mock analyze_with_gemini to return a subset
        def analyze_side_effect(articles, limit):
            # Return 'limit' items with a 'reason' added
            result = []
            for item in articles[:limit]:
                item_copy = item.copy()
                item_copy["reason"] = "Good article"
                result.append(item_copy)
            return result

        mock_llm_instance.analyze_with_gemini.side_effect = analyze_side_effect

        # Run main
        daily_brief.main()

        # Verifications

        # 1. get_articles called twice (once for platform, once for blogs)
        self.assertEqual(mock_get_articles.call_count, 2)

        # 2. analyze_with_gemini called twice
        self.assertEqual(mock_llm_instance.analyze_with_gemini.call_count, 2)

        # Verify limits passed to analyze
        calls = mock_llm_instance.analyze_with_gemini.call_args_list
        limits = [kwargs["limit"] for args, kwargs in calls]
        self.assertEqual(limits, [15, 15])

        # 3. send_email called once with two lists
        self.assertTrue(mock_email_instance.send_email.called)
        args, _ = mock_email_instance.send_email.call_args
        # Args: recipient, platform_list, blog_list
        recipient = args[0]
        platform_list = args[1]
        blog_list = args[2]
        self.assertEqual(len(platform_list), 15)
        self.assertEqual(len(blog_list), 15)

        # 4. save_processed called with all 40 items (20 platform + 20 blogs)
        self.assertTrue(mock_db_instance.save_processed.called)
        save_args = mock_db_instance.save_processed.call_args[0][0]
        self.assertEqual(len(save_args), 40)

    def test_send_email_formatting(self):
        """Test that email HTML contains section headers."""

        platform_items = [
            {
                "source": "Azure",
                "title": "New VM",
                "link": "http://a.com",
                "summary": "sum",
                "full_text": "text",
                "reason": "imp",
            }
        ]
        blog_items = [
            {
                "source": "DevBlog",
                "title": "Coding",
                "link": "http://b.com",
                "summary": "sum",
                "full_text": "text",
                "reason": "fun",
            }
        ]

        service = EmailService("smtp.server", 587, "user", "pass")

        with patch("smtplib.SMTP") as mock_smtp:
            service.send_email("to@example.com", platform_items, blog_items)

            # Get the sent message content
            instance = mock_smtp.return_value
            self.assertTrue(instance.send_message.called)
            msg = instance.send_message.call_args[0][0]
            html_content_bytes = msg.get_payload(0).get_payload(decode=True)
            html_content = html_content_bytes.decode("utf-8")

            # Check for section headers
            self.assertIn("Platform Updates", html_content)
            self.assertIn("Blog Posts", html_content)

            # Check for content
            self.assertIn("New VM", html_content)
            self.assertIn("Coding", html_content)


if __name__ == "__main__":
    unittest.main()
