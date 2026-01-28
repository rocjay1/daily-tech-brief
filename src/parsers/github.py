"""
GitHub Changelog parser.

This module provides the GitHubChangelogParser class for parsing changelogs
from GitHub repositories.
"""

import re
from typing import List, cast
import logging

import requests
from src.models import Article
from src.parsers.base import FeedParser

logger = logging.getLogger(__name__)


class GitHubChangelogParser(FeedParser):
    """
    Parses GitHub content, specifically designed for Changelog files.
    """

    def _convert_to_raw_url(self, url: str) -> str:
        """Converts a GitHub blob URL to a raw content URL."""
        # Example: https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md
        # -> https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md
        if "github.com" in url and "/blob/" in url:
            return url.replace("github.com", "raw.githubusercontent.com").replace(
                "/blob/", "/"
            )
        return url

    def fetch(self, source: str, url: str) -> List[Article]:
        """Fetches and parses a GitHub changelog."""
        items = []
        try:
            raw_url = self._convert_to_raw_url(url)
            try:
                resp = requests.get(raw_url, timeout=10)
                resp.raise_for_status()
                content = resp.text
            except requests.RequestException as req_err:
                logger.error("Network error fetching %s: %s", source, req_err)
                return []

            # Split by level 2 headers (commonly used for versions in Changelogs)
            # Regex captures the header line and the following content
            # pattern: (^|\n)## (.+?)(\n|$)
            # We'll simple split by "## "

            # Helper to create anchor links (naive implementation for GH style)
            def make_anchor(text: str) -> str:
                return re.sub(r"[^\w\s-]", "", text.lower()).replace(" ", "-")

            lines = content.split("\n")
            current_version = None
            current_body: List[str] = []

            for line in lines:
                if line.strip().startswith("## "):
                    # Save previous
                    if current_version:
                        summary = "\n".join(current_body).strip()
                        anchor = make_anchor(current_version)
                        link = f"{url}#{anchor}"

                        items.append(
                            cast(
                                Article,
                                {
                                    "source": source,
                                    "title": f"Changelog {current_version}",
                                    "link": link,
                                    "summary": (
                                        summary[:250] + "..."
                                        if len(summary) > 250
                                        else summary
                                    ),
                                    "full_text": f"{current_version}\n\n{summary}",
                                    "reason": None,
                                },
                            )
                        )

                    current_version = line.strip().replace("## ", "").strip()
                    current_body = []
                elif current_version:
                    current_body.append(line)

            # Add the last one
            if current_version:
                summary = "\n".join(current_body).strip()
                anchor = make_anchor(current_version)
                link = f"{url}#{anchor}"
                items.append(
                    cast(
                        Article,
                        {
                            "source": source,
                            "title": f"Changelog {current_version}",
                            "link": link,
                            "summary": (
                                summary[:250] + "..." if len(summary) > 250 else summary
                            ),
                            "full_text": f"{current_version}\n\n{summary}",
                            "reason": None,
                        },
                    )
                )

            # Limit to top 5 recent changes to avoid spamming historical versions
            return items[:5]

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Error parsing %s: %s", source, e)
        return items
