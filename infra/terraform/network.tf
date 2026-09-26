# One global VPC: regions talk over Google's private backbone — no VPN or peering needed.
resource "google_compute_network" "vpc" {
  name                    = "blockid-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "app" {
  name                     = "app-${var.app_region}"
  region                   = var.app_region
  network                  = google_compute_network.vpc.id
  ip_cidr_range            = "10.10.0.0/24"
  private_ip_google_access = true
}

resource "google_compute_subnetwork" "ai" {
  name                     = "ai-${var.ai_region}"
  region                   = var.ai_region
  network                  = google_compute_network.vpc.id
  ip_cidr_range            = "10.20.0.0/24"
  private_ip_google_access = true
}

# AI VM has no public IP; outbound (model downloads, Anthropic API) goes through Cloud NAT.
resource "google_compute_router" "ai" {
  name    = "ai-router"
  region  = var.ai_region
  network = google_compute_network.vpc.id
}

resource "google_compute_router_nat" "ai" {
  name                               = "ai-nat"
  router                             = google_compute_router.ai.name
  region                             = var.ai_region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

resource "google_compute_address" "app" {
  name   = "eth-blockid-au-ip"
  region = var.app_region
}

# ------------------------------------------------------------------ firewall (deny by default)
resource "google_compute_firewall" "web" {
  name          = "allow-web"
  network       = google_compute_network.vpc.name
  direction     = "INGRESS"
  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["web"]
  allow {
    protocol = "tcp"
    ports    = ["80", "443"]
  }
}

resource "google_compute_firewall" "ssh_iap" {
  name          = "allow-ssh-iap"
  network       = google_compute_network.vpc.name
  direction     = "INGRESS"
  source_ranges = var.admin_ssh_ranges
  target_tags   = ["ssh"]
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_compute_firewall" "app_to_llm" {
  name        = "allow-app-to-llm-gateway"
  network     = google_compute_network.vpc.name
  direction   = "INGRESS"
  source_tags = ["web"]
  target_tags = ["ai"]
  allow {
    protocol = "tcp"
    ports    = ["4000"] # LiteLLM gateway only; vLLM (8000) stays internal to the AI VM
  }
}

resource "google_compute_firewall" "validator_p2p" {
  count         = length(var.validator_peer_ranges) > 0 ? 1 : 0
  name          = "allow-cometbft-p2p"
  network       = google_compute_network.vpc.name
  direction     = "INGRESS"
  source_ranges = var.validator_peer_ranges
  target_tags   = ["chain"]
  allow {
    protocol = "tcp"
    ports    = ["26656"]
  }
}
