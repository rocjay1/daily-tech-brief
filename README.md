# Automated Tech Briefing System 🚀

A Python-based RSS aggregator that sends a daily email summary of Cloud, Azure, and AI engineering news. It runs on GitHub Actions and uses Google Cloud Workload Identity Federation for keyless authentication.

## Prerequisites

* **Google Cloud Project:** You need a GCP project with billing enabled (usage will be well within the free tier).
* **Gmail App Password:**
    1. Go to your Google Account > Security > 2-Step Verification.
    2. Scroll to the bottom and select "App passwords".
    3. Name it "Tech Brief Bot" and copy the 16-character code.

## Setup Instructions

### 1. Terraform (Infrastructure)

Navigate to the `terraform/` directory.

Create a `terraform.tfvars` file:

```hcl
gcp_project_id   = "your-project-id-here"
github_owner     = "YourGitHubUsername"
github_repo_name = "daily-tech-brief" # Match your repo name exactly
```

Initialize and Apply:

```bash
terraform init
terraform apply
```

> **Note the Outputs:** Terraform will output `workload_identity_provider` and `service_account_email`. You will need these for the GitHub Actions workflow.

### 2. Add Secret to GCP

For security, we didn't put the password in Terraform. Add it manually via CLI:

```bash
# Replace 'your-app-password' with the 16-char Gmail code
echo -n "your-app-password" | gcloud secrets versions add gmail-app-password --data-file=-
```

Or do this in the Google Cloud Console under **Security > Secret Manager**.

### 3. Configure GitHub Secrets

We will store sensitive and project-specific values as **GitHub Actions Secrets**.

1. Go to your GitHub Repository > **Settings > Secrets and variables > Actions**.
2. Click on the **Secrets** tab and click **New repository secret**.
3. Add the following secrets:

   | Secret Name | Value | Description |
   | :--- | :--- | :--- |
   | `GCP_PROJECT_ID` | `your-project-id` | Your Google Cloud Project ID. |
   | `GCP_PROJECT_NUM` | `123456789012` | Your Google Cloud Project Number (found on the Dashboard). |
   | `EMAIL_USER` | `your.email@gmail.com` | The Gmail address sending the briefing. |

### 4. Configure GitHub Actions

The workflow file (`.github/workflows/daily_scan.yml`) is already configured to use the secrets you just created.

* It uses `${{ secrets.GCP_PROJECT_ID }}` and `${{ secrets.GCP_PROJECT_NUM }}` to authenticate via Workload Identity Federation.
* It uses `${{ secrets.EMAIL_USER }}` to set the sender address.

**No manual edits to the YAML file are required.**

### 5. Deploy

Commit and push your code to the `main` branch.

```bash
git add .
git commit -m "Initial commit: Automated Briefing System"
git push origin main
```

### 6. Test

1. Go to your GitHub Repository > **Actions** tab.
2. Select **Daily Tech Brief** and click **Run workflow**.

Check your email! 📧
