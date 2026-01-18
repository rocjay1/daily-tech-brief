Daily Tech Brief
================

Automated, AI-curated daily tech news briefing sent email. It runs on GitHub Actions, uses Google Cloud Firestore for deduplication, and leverages Google Gemini 2.0 Flash to intelligently curate and summarize the most relevant articles.

Features
--------

- **Smart Curation**: Uses Google Gemini 2.0 Flash to analyze headlines and select high-signal articles.
- **Deduplication**: Tracks seen articles via Google Cloud Firestore to prevent repeats.
- **Keyless Security**: Authenticates to Google Cloud via Workload Identity Federation.
- **Automated Delivery**: Runs automatically Mon-Fri at 7:00 AM CST via GitHub Actions.

Documentation
-------------

- [System Architecture](docs/ARCHITECTURE.md)
- [Setup Guide](docs/SETUP.md)

Local Development
-----------------

1. **Prerequisites**: Ensure you have Python 3.12+ and a Google Cloud Project with Gemini API enabled.
2. **Setup**: Run `pip install -r requirements.txt` to install dependencies.
3. **Run**: Execute `python src/daily_brief.py`. Note: This requires environment variables (GCP_PROJECT_ID, EMAIL_USER, etc.) to be set.
