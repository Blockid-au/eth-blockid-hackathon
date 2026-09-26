# ------------------------------------------------------------------ VM-A: app + chain (Sydney)
resource "google_compute_disk" "app_data" {
  name = "app-data"
  zone = var.app_zone
  type = "pd-ssd"
  size = 500 # Postgres, chain state, evidence store, audit log
}

resource "google_compute_resource_policy" "daily_snapshot" {
  name   = "daily-snapshot-14d"
  region = var.app_region
  snapshot_schedule_policy {
    schedule {
      daily_schedule {
        days_in_cycle = 1
        start_time    = "16:00" # 02:00 Sydney
      }
    }
    retention_policy {
      max_retention_days    = 14
      on_source_disk_delete = "KEEP_AUTO_SNAPSHOTS"
    }
    snapshot_properties {
      storage_locations = [var.app_region]
    }
  }
}

resource "google_compute_disk_resource_policy_attachment" "app_data" {
  name = google_compute_resource_policy.daily_snapshot.name
  disk = google_compute_disk.app_data.name
  zone = var.app_zone
}

resource "google_compute_instance" "app" {
  name         = "blockid-app"
  zone         = var.app_zone
  machine_type = var.app_machine_type
  tags         = ["web", "ssh", "chain"]

  boot_disk {
    initialize_params {
      image = "ubuntu-os-cloud/ubuntu-2404-lts-amd64"
      size  = 100
      type  = "pd-balanced"
    }
  }

  attached_disk {
    source      = google_compute_disk.app_data.id
    device_name = "app-data"
  }

  network_interface {
    subnetwork = google_compute_subnetwork.app.id
    network_ip = "10.10.0.10"
    access_config {
      nat_ip = google_compute_address.app.address
    }
  }

  service_account {
    email  = google_service_account.app.email
    scopes = ["cloud-platform"] # effective rights come from IAM bindings above
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  metadata = {
    enable-oslogin = "TRUE"
    domain         = var.domain
    startup-script = file("${path.module}/../../scripts/bootstrap-app-vm.sh")
  }

  allow_stopping_for_update = true
}

# ------------------------------------------------------------------ VM-B: local AI (Singapore)
resource "google_compute_instance" "ai" {
  name         = "blockid-ai"
  zone         = var.ai_zone
  machine_type = var.ai_machine_type
  tags         = ["ai", "ssh"]

  boot_disk {
    initialize_params {
      image = "ubuntu-os-cloud/ubuntu-2204-lts"
      size  = 200 # model weights cache
      type  = "pd-balanced"
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.ai.id
    network_ip = "10.20.0.10"
    # no access_config: no public IP
  }

  scheduling {
    provisioning_model          = var.ai_provisioning_model
    preemptible                 = var.ai_provisioning_model == "SPOT"
    automatic_restart           = var.ai_provisioning_model == "SPOT" ? false : true
    on_host_maintenance         = "TERMINATE" # required for GPU VMs
    instance_termination_action = var.ai_provisioning_model == "SPOT" ? "STOP" : null
  }

  service_account {
    email  = google_service_account.ai.email
    scopes = ["cloud-platform"]
  }

  shielded_instance_config {
    enable_secure_boot = false # NVIDIA driver install from the startup script needs unsigned modules
  }

  metadata = {
    enable-oslogin = "TRUE"
    startup-script = file("${path.module}/../../scripts/bootstrap-ai-vm.sh")
  }

  # The worker starts this VM on demand; it stops itself after IDLE_MINUTES without requests.
  desired_status            = "TERMINATED"
  allow_stopping_for_update = true

  lifecycle {
    ignore_changes = [desired_status]
  }
}
