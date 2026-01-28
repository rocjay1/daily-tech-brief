# System Architecture

## Logic Flow

1. **Fetch:** Python script pulls content from configured sources:
   - **RSS Feeds:** Parsed using `feedparser` (e.g., Azure Updates, Blogs).
   - **GitHub Changelogs:** Custom parser retrieves and processes Markdown changelogs (e.g., Claude Code).
2. **Deduplicate:** Checks article URLs against a Firestore database. If it's been seen before, it's skipped.
3. **Analyze:** Sends candidates to Gemini 2.0 Flash to pick the top 15 "High Signal" articles and explain *why* they matter. If the AI processing fails, the workflow stops.
4. **Send:** Formats the chosen articles into an HTML email and sends it via SMTP.
5. **Save:** Writes the new article IDs to Firestore so they aren't sent again tomorrow.

## Code Structure

The codebase follows a modular architecture:

- **`src.models`**: Type definitions (e.g., `Article`).
- **`src.services`**:
  - `db.py`: Firestore interactions for deduplication.
  - `email_service.py`: Email formatting and sending logic.
  - `llm.py`: Interaction with Google Gemini API.
- **`src.parsers`**:
  - `base.py`: Protocol definition for feed parsers.
  - `rss.py`: Logic for standard RSS feeds.
  - `github.py`: Logic for parsing GitHub Markdown files.
- **`src.daily_brief.py`**: Main orchestrator that ties everything together.
