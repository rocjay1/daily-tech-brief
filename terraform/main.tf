terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.gcp_project_id
  region  = var.gcp_region
}

# 1. Enable Required APIs
resource "google_project_service" "services" {
  for_each = toset([
    "iam.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "secretmanager.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "generativelanguage.googleapis.com" # Enable Gemini API
  ])
  service            = each.key
  disable_on_destroy = false
}

# 2. Secret Manager: Create containers for secrets
resource "google_secret_manager_secret" "gmail_pass" {
  secret_id = "gmail-app-password"
  replication {
    auto {}
  }
  depends_on = [google_project_service.services]
}

resource "google_secret_manager_secret" "gemini_key" {
  secret_id = "gemini-api-key"
  replication {
    auto {}
  }
  depends_on = [google_project_service.services]
}

# 3. Service Account for GitHub Actions
resource "google_service_account" "github_runner" {
  account_id   = "github-actions-runner"
  display_name = "GitHub Actions Service Account"
}

# 4. IAM: Grant specific access to secrets
resource "google_secret_manager_secret_iam_member" "gmail_access" {
  secret_id = google_secret_manager_secret.gmail_pass.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.github_runner.email}"
}

resource "google_secret_manager_secret_iam_member" "gemini_access" {
  secret_id = google_secret_manager_secret.gemini_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.github_runner.email}"
}

# 5. Workload Identity Federation
resource "google_iam_workload_identity_pool" "github_pool" {
  workload_identity_pool_id = "github-actions-pool"
  display_name              = "GitHub Actions Pool"
  disabled                  = false
}

resource "google_iam_workload_identity_pool_provider" "github_provider" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github_pool.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-provider"
  display_name                       = "GitHub Provider"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.repository" = "assertion.repository"
  }

  attribute_condition = "assertion.repository_owner == '${var.github_owner}'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# 6. Bind GitHub Repo to Service Account
resource "google_service_account_iam_member" "wif_binding" {
  service_account_id = google_service_account.github_runner.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github_pool.name}/attribute.repository/${var.github_owner}/${var.github_repo_name}"
}

# 7. Outputs
output "workload_identity_provider" {
  value = google_iam_workload_identity_pool_provider.github_provider.name
}

output "service_account_email" {
  value = google_service_account.github_runner.email
}
