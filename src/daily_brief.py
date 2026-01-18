"""
Daily Tech Brief Generator
This script fetches RSS feeds, deduplicates articles using Firestore,
curates them using Google Gemini, and sends an email summary.
"""

import concurrent.futures
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import hashlib
import json
import logging
import os
import re
import smtplib
import sys
from typing import Dict, List, Any, Optional, TypedDict, cast

import requests
import feedparser  # type: ignore
from google import genai
from google.cloud import firestore  # type: ignore


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_config(config_filename: str = "config.json") -> Dict[str, Any]:
    """Loads configuration from a JSON file."""
    # Build absolute path relative to this script
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
SMTP_SERVER: str = cast(str, CONFIG.get("smtp_server", "smtp.gmail.com"))
SMTP_PORT: int = cast(int, CONFIG.get("smtp_port", 587))

# Env Vars
EMAIL_SENDER: Optional[str] = os.environ.get("EMAIL_USER")
EMAIL_PASSWORD: Optional[str] = os.environ.get("EMAIL_PASS")
EMAIL_RECIPIENT: str = os.environ.get("EMAIL_RECIPIENT", EMAIL_SENDER or "")
GEMINI_API_KEY: Optional[str] = os.environ.get("GEMINI_KEY")
GCP_PROJECT_ID: Optional[str] = os.environ.get("GCP_PROJECT_ID")


class Article(TypedDict):
    """Type definition for an article."""

    source: str
    title: str
    link: str
    summary: str
    full_text: str
    reason: Optional[str]  # Added by Gemini analysis


def parse_json_response(text: str) -> Any:
    """Safely parses JSON from LLM output, handling markdown blocks."""
    cleaned = text.strip()
    # Strip Markdown code blocks usually returned by Gemini
    if cleaned.startswith("```"):
        # Remove opening ```json or ```
        cleaned = cleaned.split("\n", 1)[1]
        # Remove closing ```
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("\n", 1)[0]

    return json.loads(cleaned)


def get_gemini_prompt(items_str: str, limit: int) -> str:
    """Returns the prompt for Gemini analysis."""
    return f"""
    You are a Principal Cloud Architect and AI Engineer acting as an intelligent assistant for a Corporate IT System Engineer.

    User Persona:
    - Role: Internal Corporate IT System Engineer at a tech company.
    - Core Stack: Microsoft Azure, Terraform, Python, GitHub Actions.
    - Primary Work: Cloud-native hosting (Websites, Serverless, Storage, Networking).
    - Recent Focus: AI Engineering (Deploying LLM endpoints, configuring AuthN/AuthZ for developer access).
    - Context: Recently migrated from GitLab to GitHub.

    Task: Review the provided RSS headlines and curate the Top {limit} most relevant articles.

    Selection Criteria:
    1. **High Priority (Must Have)**:
       - Architectural patterns for deploying and securing LLMs/AI endpoints on Azure.
       - Advanced Terraform patterns (Azure provider, state management, modules).
       - GitHub Actions security hardening and reusable workflows.
       - Azure networking deep dives (Private Link, DNS, Hub-and-Spoke topology).
    2. **Educational (Good to Have)**:
       - Cloud-native identity patterns (OIDC, OAuth, Workload Identity).
       - Python automation best practices for extensive cloud environments.
    3. **Ignore**:
       - Generic consumer tech news, product marketing fluff, basic "Hello World" tutorials, or GitLab-specific content.

    Input Data:
    {items_str}

    Output Format:
    - Return a raw JSON list of objects.
    - DO NOT use Markdown formatting (no ```json blocks).
    - Object schema: {{"id": int, "analysis": "1 sentence architectural justification"}}
    """


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

    def filter_new(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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

    def save_processed(self, articles: List[Dict[str, Any]]) -> None:
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


def clean_html(raw_html: Optional[str]) -> str:
    """Removes HTML tags from a string."""
    if not raw_html:
        return ""
    cleaner = re.compile("<.*?>")
    text = re.sub(cleaner, "", raw_html)
    return " ".join(text.split())


def fetch_feed(source: str, url: str) -> List[Dict[str, Any]]:
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
            clean_summary = clean_html(raw_summary)
            text_content = f"{title} - {clean_summary[:300]}"

            items.append(
                cast(
                    Dict[str, Any],
                    Article(
                        source=source,
                        title=title,
                        link=link,
                        summary=clean_summary[:250] + "...",
                        full_text=text_content,
                        reason=None,
                    ),
                )
            )
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error parsing %s: %s", source, e)
    return items


def get_articles(feeds: Dict[str, str]) -> List[Dict[str, Any]]:
    """Fetches and parses RSS feeds in parallel."""
    raw_items = []
    logger.info(
        "--- Starting Scan for %s ---", datetime.datetime.now().strftime("%Y-%m-%d")
    )

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future_to_source = {
            executor.submit(fetch_feed, source, url): source
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


def analyze_with_gemini(
    articles: List[Dict[str, Any]], limit: int
) -> List[Dict[str, Any]]:
    """Uses Google Gemini to select the best articles."""
    logger.info("API Key found. Asking Gemini to curate (limit %d)...", limit)
    # Pre-filter: Increased to 500 to leverage Gemini 2.0 Flash context window
    candidates = articles[:500]

    items_str = json.dumps(
        [
            {"id": i, "source": a["source"], "text": a["full_text"]}
            for i, a in enumerate(candidates)
        ]
    )

    prompt = get_gemini_prompt(items_str, limit)

    client = genai.Client(api_key=cast(str, GEMINI_API_KEY))
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        # Use robust parser
        response_text = response.text if response.text else ""
        selections = parse_json_response(response_text)

        final_list = []
        for sel in selections:
            if isinstance(sel, dict) and "id" in sel and sel["id"] < len(candidates):
                original = candidates[sel["id"]]
                original["reason"] = sel.get("analysis", "No analysis provided.")
                final_list.append(original)
        return final_list

    except (json.JSONDecodeError, ValueError) as e:
        logger.error("Failed to parse Gemini response: %s", e)
        return []
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Gemini API error: %s", e)
        return []


def send_email(
    platform_articles: List[Dict[str, Any]], blog_articles: List[Dict[str, Any]]
) -> None:
    """Formats and sends the daily brief via email."""
    total_articles = len(platform_articles) + len(blog_articles)
    if total_articles == 0:
        logger.info("No articles to send.")
        return

    html_content = f"""
    <html>
    <body style="font-family: 'Segoe UI', sans-serif; color: #333; line-height: 1.6;">
        <div style="max-width: 600px; margin: 0 auto; border: 1px solid #e0e0e0; border-radius: 8px;">
            <div style="background-color: #4b2c92;
                        padding: 20px; text-align: center; color: white;">
                <h2 style="margin:0;">🚀 Daily Brief</h2>
                <p style="margin:5px 0 0; opacity: 0.9;">Top {total_articles} Stories</p>
            </div>
            <div style="padding: 20px;">
    """

    def render_section(title: str, items: List[Dict[str, Any]]) -> str:
        if not items:
            return ""
        section_style = (
            "border-bottom: 2px solid #4b2c92; padding-bottom: 5px; margin-top: 30px;"
        )
        section_html = f"<h3 style='{section_style}'>{title}</h3>"
        for item in items:
            description = (
                f"<b>Why it matters:</b> {item.get('reason', '')}"
                f"<br><br>{item['summary']}"
            )
            section_html += f"""
            <div style="margin-bottom: 25px; border-bottom: 1px solid #eee; padding-bottom: 15px;">
                <span style="font-size: 11px; font-weight: bold; color: #666;
                             text-transform: uppercase;">{item['source']}</span>
                <h3 style="margin: 5px 0; font-size: 18px;">
                    <a href="{item['link']}"
                       style="text-decoration: none; color: #0078D4;">{item['title']}</a>
                </h3>
                <p style="font-size: 14px; color: #444; margin-top: 5px;">{description}</p>
            </div>
            """
        return section_html

    html_content += render_section("Platform Updates", platform_articles)
    html_content += render_section("Blog Posts", blog_articles)

    html_content += "</div></div></body></html>"

    msg = MIMEMultipart()
    msg["From"] = cast(str, EMAIL_SENDER)
    msg["To"] = EMAIL_RECIPIENT
    msg["Subject"] = f"Daily Brief: {total_articles} Updates"
    msg.attach(MIMEText(html_content, "html"))

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(cast(str, EMAIL_SENDER), cast(str, EMAIL_PASSWORD))
        server.send_message(msg)
        server.quit()
        logger.info("Email sent.")
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Email failed: %s", e)


def main():
    """Main execution entry point."""
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        logger.error("Error: EMAIL_USER or EMAIL_PASS not set.")
        return

    if not GEMINI_API_KEY:
        logger.error("Error: GEMINI_KEY not set. Workflow failed.")
        sys.exit(1)

    state_manager = StateManager(GCP_PROJECT_ID)

    # Load separate feed groups
    platform_feeds = FEEDS.get("platform_updates", {})
    blog_feeds = FEEDS.get("blogs", {})

    # Fetch articles
    raw_platform = get_articles(cast(Dict[str, str], platform_feeds))
    raw_blogs = get_articles(cast(Dict[str, str], blog_feeds))

    # Deduplicate
    new_platform = state_manager.filter_new(raw_platform)
    new_blogs = state_manager.filter_new(raw_blogs)

    if not new_platform and not new_blogs:
        logger.info("No new articles today!")
        return

    # Analyze / Curate
    final_platform = []
    if new_platform:
        final_platform = analyze_with_gemini(new_platform, limit=15)

    final_blogs = []
    if new_blogs:
        final_blogs = analyze_with_gemini(new_blogs, limit=15)

    if final_platform or final_blogs:
        send_email(final_platform, final_blogs)

        # Save processed state
        # (We save all deduplicated items, even if not selected, to avoid re-processing)
        state_manager.save_processed(new_platform + new_blogs)


if __name__ == "__main__":
    main()
