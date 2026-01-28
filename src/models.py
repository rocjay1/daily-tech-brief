"""
Data models for the Daily Tech Brief application.
"""

from typing import TypedDict, Optional


class Article(TypedDict):
    """Type definition for an article."""

    source: str
    title: str
    link: str
    summary: str
    full_text: str
    reason: Optional[str]  # Added by Gemini analysis
