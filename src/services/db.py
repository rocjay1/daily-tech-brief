"""
Database service for state management and deduplication.

This module provides the StateManager class which interfaces with Google Firestore
to track seen articles and prevent duplicates in the daily brief.
"""

import hashlib
import datetime
import logging
from typing import List, Dict, Optional
from google.cloud import firestore  # type: ignore

logger = logging.getLogger(__name__)


class StateManager:
    """Handles deduplication using Google Firestore."""

    def __init__(self, project_id: Optional[str]):
        if not project_id:
            logger.warning("GCP_PROJECT_ID not set. Deduplication disabled.")
            self.db = None
            return

        try:
            self.db = firestore.Client(project=project_id)
            self.collection = self.db.collection("seen_articles")
            logger.info("Connected to Firestore for deduplication.")
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Firestore connection failed: %s", e)
            self.db = None

    def get_id(self, url: str) -> str:
        """Creates a deterministic hash of the URL."""
        return hashlib.md5(url.encode("utf-8")).hexdigest()

    def filter_new(self, articles: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Returns only articles that haven't been seen before."""
        if not self.db or not articles:
            return articles

        # Firestore allows up to 10 'in' queries, but batch_get is better for many keys.
        # We will check all article IDs.
        new_articles = []

        # Create references for all candidates
        doc_refs = [self.collection.document(self.get_id(a["link"])) for a in articles]

        # Fetch all in parallel (Streaming)
        # We process in chunks of 30 just to be safe with API limits
        chunk_size = 30
        seen_ids = set()

        for i in range(0, len(doc_refs), chunk_size):
            chunk = doc_refs[i : i + chunk_size]
            snapshots = self.db.get_all(chunk)
            for snap in snapshots:
                if snap.exists:
                    seen_ids.add(snap.id)

        # Filter
        for article in articles:
            aid = self.get_id(article["link"])
            if aid not in seen_ids:
                new_articles.append(article)

        logger.info(
            "Deduplication: %d processed -> %d new.", len(articles), len(new_articles)
        )
        return new_articles

    def save_processed(self, articles: List[Dict[str, str]]) -> None:
        """Marks articles as seen."""
        if not self.db or not articles:
            return

        batch = self.db.batch()
        count = 0

        for article in articles:
            ref = self.collection.document(self.get_id(article["link"]))
            batch.set(
                ref,
                {
                    "title": article["title"],
                    "url": article["link"],
                    "processed_at": datetime.datetime.now(),
                },
            )
            count += 1

            # Firestore batches limited to 500 writes
            if count >= 400:
                batch.commit()
                batch = self.db.batch()
                count = 0

        if count > 0:
            batch.commit()
        logger.info("Saved %d articles to history.", len(articles))
