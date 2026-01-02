import feedparser
import smtplib
import os
import json
import re
import hashlib
from google import genai
from google.cloud import firestore
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# --- CONFIGURATION ---

# Expanded List of High-Signal Feeds
FEEDS = {
    # Cloud & Infrastructure (Azure/Terraform)
    "Azure Blog": "https://azure.microsoft.com/en-us/blog/feed/",
    "Azure Tools (Terraform)": "https://techcommunity.microsoft.com/gscwv57232/rss/board?board.id=AzureToolsBlog",
    "Spacelift (IaC Deep Dives)": "https://spacelift.io/blog/feed",
    "Firefly (Cloud Governance)": "https://www.firefly.ai/blog/rss.xml",  # Verify if they have a direct RSS, often generic blogs need specific scraping or standard /feed
    # AI Engineering & LLMs
    "Latent Space (AI Engineering)": "https://www.latent.space/feed",
    "The Batch (DeepLearning.AI)": "https://www.deeplearning.ai/the-batch/feed/",
    "TLDR AI": "https://tldr.tech/ai/rss",
    # Linux & Systems
    "LWN (Linux Kernel)": "https://lwn.net/headlines/rss",
    "Phoronix (Linux Hardware)": "https://www.phoronix.com/rss.php",
    "Julia Evans (Wizard Zines)": "https://jvns.ca/atom.xml",
    # DevOps & GitHub
    "GitHub Engineering": "https://github.blog/category/engineering/feed/",
    "Microsoft DevOps": "https://devblogs.microsoft.com/devops/feed/",
}

# Fallback Weights (used if API Key is missing/fails)
WEIGHTS = {
    "Terraform": 5,
    "OpenTofu": 5,
    "Azure": 4,
    "LLM": 4,
    "Security": 4,
    "GitHub Actions": 3,
    "CI/CD": 3,
    "Identity": 3,
    "Linux": 3,
    "Kernel": 3,
    "Bicep": 1,
    "Copilot": 1,
    "eBPF": 1,
    "Kubernetes": 1,
    "Python": 1,
}

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

    def __init__(self, project_id):
        if not project_id:
            print("⚠️ GCP_PROJECT_ID not set. Deduplication disabled.")
            self.db = None
            return

        try:
            self.db = firestore.Client(project=project_id)
            self.collection = self.db.collection("seen_articles")
            print("✅ Connected to Firestore for deduplication.")
        except Exception as e:
            print(f"⚠️ Firestore connection failed: {e}")
            self.db = None

    def get_id(self, url):
        """Creates a deterministic hash of the URL."""
        return hashlib.md5(url.encode("utf-8")).hexdigest()

    def filter_new(self, articles):
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

    def save_processed(self, articles):
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
                    "processed_at": datetime.now(),
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


def clean_html(raw_html):
    if not raw_html:
        return ""
    cleaner = re.compile("<.*?>")
    text = re.sub(cleaner, "", raw_html)
    return " ".join(text.split())


def get_articles(feeds):
    raw_items = []
    print(f"--- Starting Scan for {datetime.now().strftime('%Y-%m-%d')} ---")

    for source, url in feeds.items():
        try:
            # Add a user-agent to prevent 403s from some strict blogs
            feed = feedparser.parse(url, agent="DailyTechBriefBot/1.0")
            for entry in feed.entries:
                title = entry.title if hasattr(entry, "title") else ""
                raw_summary = entry.summary if hasattr(entry, "summary") else ""
                link = entry.link if hasattr(entry, "link") else "#"
                clean_summary = clean_html(raw_summary)
                text_content = f"{title} - {clean_summary[:300]}"

                raw_items.append(
                    {
                        "source": source,
                        "title": title,
                        "link": link,
                        "summary": clean_summary[:250] + "...",
                        "full_text": text_content,
                    }
                )
        except Exception as e:
            print(f"Error parsing {source}: {e}")
            continue
    return raw_items


def score_mechanically(articles):
    print("🤖 No API Key found. Using Mechanical Scoring.")
    scored = []
    for item in articles:
        score = 0
        matched = []
        text_lower = (item["title"] + " " + item["summary"]).lower()
        for word, weight in WEIGHTS.items():
            if word.lower() in text_lower:
                score += weight
                matched.append(word)
        if score > 0:
            item["score"] = score
            item["tags"] = list(set(matched))
            item["reason"] = "Keyword Match"
            scored.append(item)
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:TOP_N_ARTICLES]


def analyze_with_gemini(articles):
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
    You are an intelligent assistant for a Cloud System Engineer working at a tech company. 
    Role: Focus on Azure, Terraform, Python, Linux Kernel, CI/CD, and AI Engineering (LLMs).
    
    Task: Review these RSS headlines and pick the Top {TOP_N_ARTICLES} most relevant items.
    
    Criteria:
    - High Priority: Deep technical dives (Phoronix/LWN), Terraform/OpenTofu updates, Practical AI Engineering.
    - Educational: Good educational content explaining complex topics (like Kernel internals, AI architecture, or Network protocols) is highly valued.
    - Ignore: Fluff, pure marketing, or extremely basic "Hello World" tutorials.
    
    Input Data:
    {items_str}
    
    Output Format: JSON only. A list of objects with fields: "id" (int) and "analysis" (string - a 1 sentence explanation of why this matters).
    """

    try:
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
    except Exception as e:
        print(f"⚠️ Gemini Error: {e}")
        return score_mechanically(articles)


def send_email(articles, method="Mechanical"):
    if not articles:
        print("No articles to send.")
        return

    html_content = f"""
    <html>
    <body style="font-family: 'Segoe UI', sans-serif; color: #333; line-height: 1.6;">
        <div style="max-width: 600px; margin: 0 auto; border: 1px solid #e0e0e0; border-radius: 8px;">
            <div style="background-color: {'#4b2c92' if method == 'AI' else '#0078D4'}; padding: 20px; text-align: center; color: white;">
                <h2 style="margin:0;">🚀 Daily Brief ({method})</h2>
                <p style="margin:5px 0 0; opacity: 0.9;">Top {len(articles)} Stories</p>
            </div>
            <div style="padding: 20px;">
    """
    for item in articles:
        description = (
            f"<b>Why it matters:</b> {item.get('reason', '')}<br><br>{item['summary']}"
            if method == "AI"
            else item["summary"]
        )
        html_content += f"""
        <div style="margin-bottom: 25px; border-bottom: 1px solid #eee; padding-bottom: 15px;">
            <span style="font-size: 11px; font-weight: bold; color: #666; text-transform: uppercase;">{item['source']}</span>
            <h3 style="margin: 5px 0; font-size: 18px;">
                <a href="{item['link']}" style="text-decoration: none; color: #0078D4;">{item['title']}</a>
            </h3>
            <p style="font-size: 14px; color: #444; margin-top: 5px;">{description}</p>
        </div>
        """
    html_content += "</div></div></body></html>"

    msg = MIMEMultipart()
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECIPIENT
    msg["Subject"] = f"Daily Brief: {len(articles)} Updates ({method})"
    msg.attach(MIMEText(html_content, "html"))

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"✅ Email sent.")
    except Exception as e:
        print(f"❌ Email failed: {e}")


if __name__ == "__main__":
    if not EMAIL_SENDER:
        print("❌ Error: EMAIL_USER not set.")
    else:
        # 1. Init DB
        state_manager = StateManager(GCP_PROJECT_ID)

        # 2. Fetch
        all_articles = get_articles(FEEDS)

        # 3. Filter New
        new_articles = state_manager.filter_new(all_articles)

        if not new_articles:
            print("No new articles today!")
        else:
            # 4. Analyze
            if GEMINI_API_KEY:
                final_list = analyze_with_gemini(new_articles)
                method = "AI"
            else:
                final_list = score_mechanically(new_articles)
                method = "Mechanical"

            # 5. Send
            if final_list:
                send_email(final_list, method=method)

                # 6. Save State (Mark the ones we processed as seen)
                # We mark ALL new_articles found as seen, so we don't re-process
                # the "rejected" ones tomorrow.
                state_manager.save_processed(new_articles)
