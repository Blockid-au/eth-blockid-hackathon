# ------------------------------------------------------------------ service accounts (least privilege)
resource "google_service_account" "app" {
  account_id   = "blockid-app-vm"
  display_name = "eth.blockid.au app + chain VM"
}

resource "google_service_account" "ai" {
  account_id   = "blockid-ai-vm"
  display_name = "Local LLM VM (vLLM + LiteLLM)"
}

locals {
  app_secrets = ["blockid-api-key", "brave-api-key", "litellm-master-key", "postgres-password", "evmd-keyring-password"]
  ai_secrets  = ["anthropic-api-key", "litellm-master-key", "hf-token"]
  all_secrets = distinct(concat(local.app_secrets, local.ai_secrets))
}

# Secret shells only — values are added by an operator (never in Terraform state):
#   echo -n "VALUE" | gcloud secrets versions add brave-api-key --data-file=-
resource "google_secret_manager_secret" "s" {
  for_each  = toset(local.all_secrets)
  secret_id = each.key
  replication {
    user_managed {
      replicas {
        location = var.app_region
      }
    }
  }
}

resource "google_secret_manager_secret_iam_member" "app" {
  for_each  = toset(local.app_secrets)
  secret_id = google_secret_manager_secret.s[each.key].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"
}

resource "google_secret_manager_secret_iam_member" "ai" {
  for_each  = toset(local.ai_secrets)
  secret_id = google_secret_manager_secret.s[each.key].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.ai.email}"
}

# The app VM may only look at and START the AI VM (for batch jobs). The AI VM stops itself when idle.
resource "google_project_iam_custom_role" "gpu_starter" {
  role_id     = "blockidGpuStarter"
  title       = "BlockID GPU starter"
  permissions = ["compute.instances.get", "compute.instances.start"]
}

resource "google_compute_instance_iam_member" "app_can_start_ai" {
  zone          = var.ai_zone
  instance_name = google_compute_instance.ai.name
  role          = google_project_iam_custom_role.gpu_starter.id
  member        = "serviceAccount:${google_service_account.app.email}"
}

resource "google_project_iam_member" "logging" {
  for_each = {
    app = google_service_account.app.email
    ai  = google_service_account.ai.email
  }
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${each.value}"
}

resource "google_project_iam_member" "metrics" {
  for_each = {
    app = google_service_account.app.email
    ai  = google_service_account.ai.email
  }
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${each.value}"
}
