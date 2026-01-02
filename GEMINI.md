# Daily Tech Brief - Gemini Context

## Project Overview

**Daily Tech Brief** is an automated RSS aggregator and curation system designed for Cloud and DevOps Engineers. It fetches news from various technical sources (Azure, Linux, AI, DevOps), deduplicates them against a history database, and uses **Google Gemini 2.0 Flash** to select and summarize the most relevant "high-signal" articles.

**Key Technologies:**

* **Python 3:** Core logic for fetching, analyzing, and emailing.
* **Google Gemini 2.0 Flash:** AI model for content curation and summarization.
* **Google Cloud Firestore:** NoSQL database for tracking seen articles (deduplication).
* **Terraform:** Infrastructure as Code (IaC) for provisioning GCP resources.
* **GitHub Actions:** CI/CD for scheduled daily execution.

## Architecture

1. **Ingest:** Python script fetches RSS feeds defined in `src/daily_brief.py`.
2. **Deduplicate:** Checks article URLs against Firestore to skip previously processed items.
3. **Analyze:**
    * **Primary:** Sends content to Gemini 2.0 Flash for semantic analysis and ranking.
    * **Fallback:** Uses keyword-based weighting if the AI API is unavailable.
4. **Notify:** Formats the top 15 articles into an HTML email and sends it via SMTP (Gmail).
5. **Persist:** Saves the IDs of processed articles to Firestore.

## Building and Running

### Prerequisites

* Python 3.10+
* Google Cloud Project (with Billing enabled)
* Terraform installed
* Gmail App Password (for sending emails)
* Google Gemini API Key

### Local Development

1. **Environment Setup:**

    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    ```

2. **Configuration (Environment Variables):**
    Export the following variables before running locally:

    ```bash
    export EMAIL_USER="your-email@gmail.com"
    export EMAIL_PASS="your-app-password"
    export EMAIL_RECIPIENT="recipient@example.com"
    export GEMINI_KEY="your-gemini-api-key"
    export GCP_PROJECT_ID="your-gcp-project-id"
    ```

3. **Run the Script:**

    ```bash
    python src/daily_brief.py
    ```

### Infrastructure (Terraform)

Infrastructure is managed in the `terraform/` directory.

1. **Initialize:**

    ```bash
    cd terraform
    terraform init
    ```

2. **Apply:**
    Create a `terraform.tfvars` file (see `README.md` for details) and run:

    ```bash
    terraform apply
    ```

## Development Conventions

* **Code Style:** Follows standard Python PEP 8 guidelines.
* **Configuration:** All sensitive values (API keys, passwords) must be loaded via environment variables. **Never hardcode secrets.**
* **Infrastructure:** All cloud resources should be defined in Terraform, not created manually in the console.
* **Logic:**
  * `src/daily_brief.py` is the entry point.
  * `StateManager` class handles database interactions.
  * `FEEDS` dictionary controls the RSS sources.
