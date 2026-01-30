"""
Daily Tech Brief Generator
This script fetches RSS feeds and GitHub changelogs, deduplicates articles using Firestore,
curates them using Google Gemini, and sends an email summary.
"""

import concurrent.futures
import datetime
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, cast, Optional

# Services
from src.services.db import StateManager
from src.services.email_service import EmailService
from src.services.llm import LLMService

# Parsers
from src.parsers.base import FeedParser
from src.parsers.rss import RSSParser
from src.parsers.github import GitHubChangelogParser
from src.models import Article

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_config(config_filename: str = "../config/config.json") -> Dict[str, Any]:
    """Loads configuration from a JSON file."""
    base_dir = Path(__file__).resolve().parent
    config_path = base_dir / config_filename

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("Config file not found at %s. Using empty config.", config_path)
        return {"feeds": {}}


# Global config to maintain backward compatibility for tests that might rely on it
CONFIG: Dict[str, Any] = load_config()
FEEDS: Dict[str, Any] = CONFIG.get("feeds", {})


class DailyBriefApp:
    """
    Main application class for generating the Daily Tech Brief.
    """
    # pylint: disable=too-many-instance-attributes

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        # Allow overriding feeds from global if config doesn't have them (for tests)
        self.feeds = config.get("feeds", {}) or FEEDS

        self.email_sender = os.environ.get("EMAIL_USER", "")
        self.email_password = os.environ.get("EMAIL_PASS", "")
        self.email_recipient = os.environ.get("EMAIL_RECIPIENT", self.email_sender or "")
        self.gemini_api_key = os.environ.get("GEMINI_KEY", "")
        self.gcp_project_id = os.environ.get("GCP_PROJECT_ID", "")

        self.state_manager: Optional[StateManager] = None
        self.email_service: Optional[EmailService] = None
        self.llm_service: Optional[LLMService] = None

    def _init_services(self) -> bool:
        """Initialize external services."""
        if not self.email_sender or not self.email_password:
            logger.error("Error: EMAIL_USER or EMAIL_PASS not set.")
            return False

        if not self.gemini_api_key:
            logger.error("Error: GEMINI_KEY not set. Workflow failed.")
            return False

        self.state_manager = StateManager(self.gcp_project_id)
        self.email_service = EmailService(
            smtp_server=str(self.config.get("smtp_server", "smtp.gmail.com")),
            smtp_port=int(self.config.get("smtp_port", 587)),
            sender_email=self.email_sender,
            sender_password=self.email_password,
        )
        self.llm_service = LLMService(api_key=self.gemini_api_key)
        return True

    def _get_parser(self, url: str) -> FeedParser:
        """Factory to return the appropriate parser."""
        if "github.com" in url and ("blob" in url or "raw" in url):
            return GitHubChangelogParser()
        return RSSParser()

    def _fetch_feed_safe(self, source: str, url: str) -> List[Article]:
        """Wrapper to fetch feed with appropriate parser."""
        parser = self._get_parser(url)
        return parser.fetch(source, url)

    def _process_feeds(self, feeds: Dict[str, str]) -> List[Article]:
        """Fetches and parses feeds in parallel."""
        raw_items: List[Article] = []
        logger.info(
            "--- Starting Scan for %s ---", datetime.datetime.now().strftime("%Y-%m-%d")
        )

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_to_source = {
                executor.submit(self._fetch_feed_safe, source, url): source
                for source, url in feeds.items()
            }
            for future in concurrent.futures.as_completed(future_to_source):
                try:
                    items = future.result()
                    raw_items.extend(items)
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    source = future_to_source[future]
                    logger.error("%s generated an exception: %s", source, exc)

        return raw_items

    def _deduplicate(self, articles: List[Article]) -> List[Article]:
        """Deduplicates articles using StateManager."""
        if not self.state_manager:
            return articles

        return cast(
            List[Article],
            self.state_manager.filter_new(cast(List[Dict[str, Any]], articles)),
        )

    def _curate(self, articles: List[Article], limit: int = 15) -> List[Article]:
        """Curates articles using LLM."""
        if not self.llm_service or not articles:
            return []
        return self.llm_service.analyze_with_gemini(articles, limit=limit)

    def run(self):
        """Main execution flow."""
        if not self._init_services():
            sys.exit(1)

        # Load feeds
        platform_feeds = self.feeds.get("platform_updates", {})
        blog_feeds = self.feeds.get("blogs", {})

        # Fetch articles
        raw_platform = self._process_feeds(cast(Dict[str, str], platform_feeds))
        raw_blogs = self._process_feeds(cast(Dict[str, str], blog_feeds))

        # Deduplicate
        new_platform = self._deduplicate(raw_platform)
        new_blogs = self._deduplicate(raw_blogs)

        if not new_platform and not new_blogs:
            logger.info("No new articles today!")
            return

        # Analyze / Curate
        final_platform = self._curate(new_platform, limit=15)
        final_blogs = self._curate(new_blogs, limit=15)

        if final_platform or final_blogs:
            if self.email_service:
                self.email_service.send_email(
                    self.email_recipient, final_platform, final_blogs
                )

            # Save processed state
            if self.state_manager:
                self.state_manager.save_processed(
                    cast(List[Dict[str, Any]], new_platform + new_blogs)
                )


def main():
    """Main execution entry point."""
    app = DailyBriefApp(CONFIG)
    app.run()


if __name__ == "__main__":
    main()
