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
from typing import Any, Dict, List, cast

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


def load_config(config_filename: str = "config/config.json") -> Dict[str, Any]:
    """Loads configuration from a JSON file."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, config_filename)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("Config file not found at %s. Using empty config.", config_path)
        return {"feeds": {}}


CONFIG: Dict[str, Any] = load_config()
FEEDS: Dict[str, Any] = CONFIG.get("feeds", {})

# Env Vars
EMAIL_SENDER: str = os.environ.get("EMAIL_USER", "")
EMAIL_PASSWORD: str = os.environ.get("EMAIL_PASS", "")
EMAIL_RECIPIENT: str = os.environ.get("EMAIL_RECIPIENT", EMAIL_SENDER or "")
GEMINI_API_KEY: str = os.environ.get("GEMINI_KEY", "")
GCP_PROJECT_ID: str = os.environ.get("GCP_PROJECT_ID", "")


def get_parser(url: str) -> FeedParser:
    """Factory to return the appropriate parser."""
    if "github.com" in url and ("blob" in url or "raw" in url):
        return GitHubChangelogParser()
    return RSSParser()


def fetch_feed_safe(source: str, url: str) -> List[Article]:
    """Wrapper to fetch feed with appropriate parser."""
    parser = get_parser(url)
    return parser.fetch(source, url)


def get_articles(feeds: Dict[str, str]) -> List[Article]:
    """Fetches and parses feeds in parallel."""
    raw_items: List[Article] = []
    logger.info(
        "--- Starting Scan for %s ---", datetime.datetime.now().strftime("%Y-%m-%d")
    )

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future_to_source = {
            executor.submit(fetch_feed_safe, source, url): source
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


def main():
    """Main execution entry point."""
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        logger.error("Error: EMAIL_USER or EMAIL_PASS not set.")
        return

    if not GEMINI_API_KEY:
        logger.error("Error: GEMINI_KEY not set. Workflow failed.")
        sys.exit(1)

    # Initialize Services
    state_manager = StateManager(GCP_PROJECT_ID)
    email_service = EmailService(
        smtp_server=str(CONFIG.get("smtp_server", "smtp.gmail.com")),
        smtp_port=int(CONFIG.get("smtp_port", 587)),
        sender_email=EMAIL_SENDER,
        sender_password=EMAIL_PASSWORD,
    )
    llm_service = LLMService(api_key=GEMINI_API_KEY)

    # Load feeds
    platform_feeds = FEEDS.get("platform_updates", {})
    blog_feeds = FEEDS.get("blogs", {})

    # Fetch articles
    raw_platform = get_articles(cast(Dict[str, str], platform_feeds))
    raw_blogs = get_articles(cast(Dict[str, str], blog_feeds))

    # Deduplicate
    # Mypy might complain about type mismatch if StateManager isn't fully typed with Article
    # We'll cast for now or update StateManager signature
    new_platform = cast(
        List[Article],
        state_manager.filter_new(cast(List[Dict[str, Any]], raw_platform)),
    )
    new_blogs = cast(
        List[Article], state_manager.filter_new(cast(List[Dict[str, Any]], raw_blogs))
    )

    if not new_platform and not new_blogs:
        logger.info("No new articles today!")
        return

    # Analyze / Curate
    final_platform = []
    if new_platform:
        final_platform = llm_service.analyze_with_gemini(new_platform, limit=15)

    final_blogs = []
    if new_blogs:
        final_blogs = llm_service.analyze_with_gemini(new_blogs, limit=15)

    if final_platform or final_blogs:
        email_service.send_email(EMAIL_RECIPIENT, final_platform, final_blogs)

        # Save processed state
        state_manager.save_processed(
            cast(List[Dict[str, Any]], new_platform + new_blogs)
        )


if __name__ == "__main__":
    main()
