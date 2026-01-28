"""
RSS feed parser implementation.

This module provides the RSSParser class for fetching and parsing RSS feeds.
"""

import re
from typing import List, cast
import logging

import requests
import feedparser  # type: ignore
from src.models import Article
from src.parsers.base import FeedParser

logger = logging.getLogger(__name__)


class RSSParser(FeedParser):
    """Parses standard RSS feeds."""

    def _clean_html(self, raw_html: str) -> str:
        """Removes HTML tags from a string."""
        if not raw_html:
            return ""
        cleaner = re.compile("<.*?>")
        text = re.sub(cleaner, "", raw_html)
        return " ".join(text.split())

    def fetch(self, source: str, url: str) -> List[Article]:
        """Fetches and parses a single RSS feed."""
        items = []
        try:
            # Add a user-agent to prevent 403s from some strict blogs
            # Use requests with timeout for robustness
            try:
                resp = requests.get(
                    url, timeout=10, headers={"User-Agent": "DailyTechBriefBot/1.0"}
                )
                resp.raise_for_status()
                feed_content = resp.content
            except requests.RequestException as req_err:
                logger.error("Network error fetching %s: %s", source, req_err)
                return []

            feed = feedparser.parse(feed_content)
            for entry in feed.entries:
                title = entry.title if hasattr(entry, "title") else ""
                raw_summary = entry.summary if hasattr(entry, "summary") else ""
                link = entry.link if hasattr(entry, "link") else "#"
                clean_content = self._clean_html(raw_summary)
                text_content = f"{title} - {clean_content[:300]}"

                items.append(
                    cast(
                        Article,
                        {
                            "source": source,
                            "title": title,
                            "link": link,
                            "summary": clean_content[:250] + "...",
                            "full_text": text_content,
                            "reason": None,
                        },
                    )
                )
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Error parsing %s: %s", source, e)
        return items
