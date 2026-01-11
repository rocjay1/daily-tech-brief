"""
Daily Tech Brief Generator
This script fetches RSS feeds, deduplicates articles using Firestore,
curates them using Google Gemini, and sends an email summary.
"""

import concurrent.futures
import datetime
import hashlib
import json
import os
import re
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Any, Optional

import feedparser
from google import genai
from google.cloud import firestore


def load_config(config_filename: str = "config.json") -> Dict[str, Any]:
    """Loads configuration from a JSON file."""
    # Build absolute path relative to this script
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, config_filename)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"⚠️ Config file not found at {config_path}. Using empty config.")
        return {"feeds": {}}


CONFIG = load_config()
FEEDS = CONFIG.get("feeds", {})

TOP_N_ARTICLES = 15

# Env Vars
EMAIL_SENDER = os.environ.get("EMAIL_USER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASS")
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT", EMAIL_SENDER)
GEMINI_API_KEY = os.environ.get("GEMINI_KEY")
GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID")

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587


class StateManager:
    """Handles deduplication using Google Firestore."""

    def __init__(self, project_id: Optional[str]):
        if not project_id:
            print("⚠️ GCP_PROJECT_ID not set. Deduplication disabled.")
            self.db = None
            return

        try:
            self.db = firestore.Client(project=project_id)
            self.collection = self.db.collection("seen_articles")
            print("✅ Connected to Firestore for deduplication.")
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"⚠️ Firestore connection failed: {e}")
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

        print(
            f"🔍 Deduplication: {len(articles)} processed -> {len(new_articles)} new."
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
        print(f"💾 Saved {len(articles)} articles to history.")


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
        feed = feedparser.parse(url, agent="DailyTechBriefBot/1.0")
        for entry in feed.entries:
            title = entry.title if hasattr(entry, "title") else ""
            raw_summary = entry.summary if hasattr(entry, "summary") else ""
            link = entry.link if hasattr(entry, "link") else "#"
            clean_summary = clean_html(raw_summary)
            text_content = f"{title} - {clean_summary[:300]}"

            items.append(
                {
                    "source": source,
                    "title": title,
                    "link": link,
                    "summary": clean_summary[:250] + "...",
                    "full_text": text_content,
                }
            )
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"Error parsing {source}: {e}")
    return items


def get_articles(feeds: Dict[str, str]) -> List[Dict[str, Any]]:
    """Fetches and parses RSS feeds in parallel."""
    raw_items = []
    print(f"--- Starting Scan for {datetime.datetime.now().strftime('%Y-%m-%d')} ---")

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
                print(f"{source} generated an exception: {exc}")

    return raw_items


def analyze_with_gemini(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Uses Google Gemini to select the best articles."""
    print("✨ API Key found. Asking Gemini to curate the list...")
    # Pre-filter top 80 to save tokens
    candidates = articles[:80]

    items_str = json.dumps(
        [
            {"id": i, "source": a["source"], "text": a["full_text"]}
            for i, a in enumerate(candidates)
        ]
    )

    prompt = f"""
    You are an intelligent assistant for a Corporate IT System Engineer focusing on Cloud and AI Engineering.

    User Persona:
    - Role: Internal Corporate IT System Engineer at a tech company.
    - Core Stack: Microsoft Azure, Terraform, Python, GitHub Actions.
    - Primary Work: Cloud-native hosting (Websites, Serverless, Storage, Networking).
    - Recent Focus: AI Engineering (Deploying LLM endpoints, configuring AuthN/AuthZ for developer access).
    - Context: Recently migrated from GitLab to GitHub.

    Task: Review the provided RSS headlines and curate the Top {TOP_N_ARTICLES} most relevant articles.

    Selection Criteria:
    1. **High Priority**: 
       - Practical guides on deploying and securing LLMs/AI endpoints on Azure.
       - Terraform updates (Azure provider, best practices, state management).
       - GitHub Actions workflows (CI/CD optimization, security, custom actions).
       - Azure serverless & networking updates (Container Apps, Functions, Private Link, DNS).
    2. **Educational**: 
       - Deep dives into cloud-native architectures, authentication patterns (OIDC, OAuth) for AI, and Python automation.
    3. **Ignore**: 
       - Generic consumer tech news, pure marketing fluff, extremely basic "Hello World" tutorials, or GitLab-specific content.

    Input Data:
    {items_str}

    Output Format: JSON only. A list of objects with fields: "id" (int) and "analysis" (string - a 1 sentence explanation of why this matters to an Azure/Terraform/AI engineer).
    """

    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
        config={"response_mime_type": "application/json"},
    )
    selections = json.loads(response.text)
    final_list = []
    for sel in selections:
        if sel["id"] < len(candidates):
            original = candidates[sel["id"]]
            original["reason"] = sel["analysis"]
            final_list.append(original)
    return final_list


def send_email(articles: List[Dict[str, Any]]) -> None:
    """Formats and sends the daily brief via email."""
    if not articles:
        print("No articles to send.")
        return

    html_content = f"""
    <html>
    <body style="font-family: 'Segoe UI', sans-serif; color: #333; line-height: 1.6;">
        <div style="max-width: 600px; margin: 0 auto; border: 1px solid #e0e0e0; border-radius: 8px;">
            <div style="background-color: #4b2c92;
                        padding: 20px; text-align: center; color: white;">
                <h2 style="margin:0;">🚀 Daily Brief</h2>
                <p style="margin:5px 0 0; opacity: 0.9;">Top {len(articles)} Stories</p>
            </div>
            <div style="padding: 20px;">
    """
    for item in articles:
        description = (
            f"<b>Why it matters:</b> {item.get('reason', '')}<br><br>{item['summary']}"
        )
        html_content += f"""
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
    html_content += "</div></div></body></html>"

    msg = MIMEMultipart()
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECIPIENT
    msg["Subject"] = f"Daily Brief: {len(articles)} Updates"
    msg.attach(MIMEText(html_content, "html"))

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("✅ Email sent.")
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"❌ Email failed: {e}")


def main():
    """Main execution entry point."""
    if not EMAIL_SENDER:
        print("❌ Error: EMAIL_USER not set.")
        return

    if not GEMINI_API_KEY:
        print("❌ Error: GEMINI_KEY not set. Workflow failed.")
        sys.exit(1)

    state_manager = StateManager(GCP_PROJECT_ID)
    all_articles = get_articles(FEEDS)
    new_articles = state_manager.filter_new(all_articles)

    if not new_articles:
        print("No new articles today!")
    else:
        final_list = analyze_with_gemini(new_articles)
        if final_list:
            send_email(final_list)

            # We mark ALL new_articles found as seen, so we don't re-process
            # the "rejected" ones tomorrow.
            state_manager.save_processed(new_articles)


if __name__ == "__main__":
    main()
