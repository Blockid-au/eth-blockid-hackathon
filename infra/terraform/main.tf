terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0"
    }
  }
  # Recommended: remote state in a GCS bucket with versioning.
  # backend "gcs" { bucket = "blockid-tfstate" prefix = "eth-platform" }
}

provider "google" {
  project = var.project_id
}

# ------------------------------------------------------------------ variables
variable "project_id" {
  type        = string
  description = "GCP project id"
}

variable "app_region" {
  type    = string
  default = "australia-southeast1" # Sydney: web, API, chain, database, KYC data
}

variable "app_zone" {
  type    = string
  default = "australia-southeast1-b"
}

variable "app_machine_type" {
  type    = string
  default = "n2-standard-8" # 8 vCPU / 32 GB
}

variable "ai_region" {
  type    = string
  default = "asia-southeast1" # Singapore: nearest region with L4 / RTX PRO 6000 (not available in Sydney)
}

variable "ai_zone" {
  type    = string
  default = "asia-southeast1-c"
}

variable "ai_machine_type" {
  type        = string
  default     = "g2-standard-8" # 1x L4 24GB. Upgrade: g4-standard-48 (1x RTX PRO 6000 96GB)
  description = "GPU VM for the local model"
}

variable "ai_provisioning_model" {
  type        = string
  default     = "SPOT" # batch jobs resume from checkpoints, so pre-emption is acceptable
  description = "SPOT or STANDARD"
}

variable "domain" {
  type    = string
  default = "eth.blockid.au"
}

variable "admin_ssh_ranges" {
  type        = list(string)
  default     = ["35.235.240.0/20"] # IAP TCP forwarding only — no public SSH
  description = "Source ranges allowed to reach port 22"
}

variable "validator_peer_ranges" {
  type        = list(string)
  default     = []
  description = "Partner validator IPs allowed on the CometBFT P2P port (26656)"
}

# ------------------------------------------------------------------ outputs
output "app_public_ip" {
  value       = google_compute_address.app.address
  description = "Point the A record of eth.blockid.au here"
}

output "ai_internal_ip" {
  value = google_compute_instance.ai.network_interface[0].network_ip
}

output "secrets_to_fill" {
  value = [for s in google_secret_manager_secret.s : s.secret_id]
}
