variable "gcp_project_id" {
  description = "The ID of the Google Cloud Project"
  type        = string
}

variable "gcp_region" {
  description = "Region for GCP resources"
  type        = string
  default     = "us-central1"
}

variable "github_owner" {
  description = "GitHub username or organization name"
  type        = string
}

variable "github_repo_name" {
  description = "The name of the GitHub repository"
  type        = string
}
