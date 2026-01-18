# Setup Guide

## Prerequisites

* **Google Cloud Project:** You need a GCP project with billing enabled.
  * *Note: Usage (Firestore, Secret Manager, Cloud Run/Functions equivalent) is typically well within the free tier.*
* **Gmail App Password:**
    1. Go to your Google Account > Security > 2-Step Verification.
    2. Scroll to the bottom and select "App passwords".
    3. Name it "Tech Brief Bot" and copy the 16-character code.
* **Google Gemini API Key:**
    1. Go to [Google AI Studio](https://aistudio.google.com/).
    2. Create an API Key.

## Setup Instructions

### 1. Terraform (Infrastructure)

Navigate to the `infra/` directory.

Create a `terraform.tfvars` file:

```hcl
gcp_project_id   = "your-project-id-here"
gcp_region       = "us-central1" # or your preferred region
github_owner     = "YourGitHubUsername"
github_repo_name = "daily-tech-brief" # Match your repo name exactly
```

Initialize and Apply:

```bash
terraform init
terraform apply
```

> **What this builds:**
>
> * Enables APIs: Firestore, Secret Manager, Gemini (Generative Language), IAM.
> * Creates a Firestore Database (Native mode).
> * Creates Secret Manager slots for your passwords.
> * Sets up Workload Identity Federation for GitHub Actions.

**Note the Outputs:** Terraform will output `workload_identity_provider` and `service_account_email`.

### 2. Add Secrets to GCP

We store sensitive values in Google Secret Manager, not in code.

```bash
# Add Gmail App Password
echo -n "your-16-char-password" | gcloud secrets versions add gmail-app-password --data-file=-

# Add Gemini API Key
echo -n "your-gemini-api-key" | gcloud secrets versions add gemini-api-key --data-file=-
```

Or add them manually in the Google Cloud Console under **Security > Secret Manager**.

### 3. Configure GitHub Secrets

Store environment-specific variables in **GitHub Actions Secrets**.

1. Go to your GitHub Repository > **Settings > Secrets and variables > Actions**.
2. Add the following **Repository secrets**:

| Secret Name       | Value              | Description                                            |
| :---------------- | :----------------- | :----------------------------------------------------- |
| `GCP_PROJECT_ID`  | `your-project-id`  | Your Google Cloud Project ID.                          |
| `GCP_PROJECT_NUM` | `123456789012`     | Your Project Number (found on GCP Dashboard).          |
| `EMAIL_USER`      | `sender@gmail.com` | The Gmail address sending the briefing.                |
| `EMAIL_RECIPIENT` | `you@example.com`  | (Optional) Who receives the email. Defaults to sender. |

### 4. Deploy & Run

The workflow file (`.github/workflows/daily_scan.yml`) is pre-configured.

1. Commit and push your changes to `main`.
2. Go to the **Actions** tab in GitHub.
3. Select **Daily Tech Brief** and click **Run workflow**.
