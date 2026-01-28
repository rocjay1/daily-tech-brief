"""
Base classes and interfaces for feed parsers.

This module defines the contract that all feed parsers must follow.
"""

from typing import Protocol, List
from src.models import Article


class FeedParser(Protocol):
    """
    Protocol for feed parsers.

    Classes implementing this protocol should be able to fetch and parse
    content from a given URL into a list of Article objects.
    """

    def fetch(self, source: str, url: str) -> List[Article]:
        """Fetches and parses a feed."""
