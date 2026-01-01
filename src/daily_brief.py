import feedparser
import smtplib
import os
import json
import google.generativeai as genai
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

# --- CONFIGURATION ---

FEEDS = {
    "GitHub Engineering": "https://github.blog/category/engineering/feed/",
    "LWN (Linux Kernel)": "https://lwn.net/headlines/rss",
    "Azure Blog": "https://azure.microsoft.com/en-us/blog/feed/",
    "Azure Tools (Terraform)": "https://techcommunity.microsoft.com/gscwv57232/rss/board?board.id=AzureToolsBlog",
    "Latent Space (AI Engineering)": "https://www.latent.space/feed",
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

# Env Vars
EMAIL_SENDER = os.environ.get("EMAIL_USER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASS")
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT", EMAIL_SENDER)
GEMINI_API_KEY = os.environ.get("GEMINI_KEY")

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587


def get_articles(feeds):
    """Fetches all articles from feeds."""
    raw_items = []
    print(f"--- Starting Scan for {datetime.now().strftime('%Y-%m-%d')} ---")

    for source, url in feeds.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                title = entry.title if hasattr(entry, "title") else ""
                summary = entry.summary if hasattr(entry, "summary") else ""
                link = entry.link if hasattr(entry, "link") else "#"
                # Basic cleaning
                text_content = f"{title} - {summary[:300]}"

                raw_items.append(
                    {
                        "source": source,
                        "title": title,
                        "link": link,
                        "summary": summary[:200] + "...",
                        "full_text": text_content,
                    }
                )
        except Exception as e:
            print(f"Error parsing {source}: {e}")
            continue
    return raw_items


def score_mechanically(articles):
    """Fallback: Scored by keywords."""
    print("🤖 No API Key found (or error). Using Mechanical Scoring.")
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
    return scored[:15]


def analyze_with_gemini(articles):
    """AI: Uses Gemini to curate the list."""
    print("✨ API Key found. Asking Gemini to curate the list...")

    # 1. Pre-filter slightly to avoid sending 100+ items (Token optimization)
    candidates = articles[:60]

    # 2. Prepare Prompt
    items_str = json.dumps(
        [
            {"id": i, "source": a["source"], "text": a["full_text"]}
            for i, a in enumerate(candidates)
        ]
    )

    prompt = f"""
    You are an intelligent assistant for a Cloud System Engineer at Epic Systems. 
    Role: Focus on Azure, Terraform, Python, Linux Kernel, and AI Engineering (LLMs).
    
    Task: Review these RSS headlines and pick the Top 10 most relevant items.
    
    Criteria:
    - High Priority: Major Terraform/Azure updates, Practical AI Engineering, Security vulnerabilities, Linux deep-dives.
    - Ignore: Generic marketing, beginner tutorials, or non-technical news.
    
    Input Data:
    {items_str}
    
    Output Format: JSON only. A list of objects with fields: "id" (int) and "analysis" (string - a 1 sentence explanation of why this matters to my specific job).
    """

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(
            prompt, generation_config={"response_mime_type": "application/json"}
        )

        selections = json.loads(response.text)

        final_list = []
        for sel in selections:
            if sel["id"] < len(candidates):
                original = candidates[sel["id"]]
                original["reason"] = sel["analysis"]
                original["tags"] = ["AI Selected"]
                final_list.append(original)

        return final_list

    except Exception as e:
        print(f"⚠️ Gemini Error: {e}")
        print("Falling back to mechanical scoring...")
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
                <p style="margin:5px 0 0; opacity: 0.9;">Top {len(articles)} Stories for Epic IT</p>
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
        all_articles = get_articles(FEEDS)

        if GEMINI_API_KEY:
            final_list = analyze_with_gemini(all_articles)
            send_email(final_list, method="AI")
        else:
            final_list = score_mechanically(all_articles)
            send_email(final_list, method="Mechanical")
