resource "google_compute_network" "rolecall" {
  name                    = local.prefix
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"

  depends_on = [google_project_service.required]
}

resource "google_compute_subnetwork" "rolecall" {
  name          = "${local.prefix}-subnet"
  region        = var.region
  network       = google_compute_network.rolecall.id
  ip_cidr_range = "10.72.0.0/20"

  secondary_ip_range {
    range_name    = "${local.prefix}-pods"
    ip_cidr_range = "10.80.0.0/16"
  }

  secondary_ip_range {
    range_name    = "${local.prefix}-services"
    ip_cidr_range = "10.73.0.0/20"
  }

  private_ip_google_access = true
}

resource "google_compute_router" "rolecall" {
  name    = "${local.prefix}-router"
  region  = var.region
  network = google_compute_network.rolecall.id
}

resource "google_compute_router_nat" "rolecall" {
  name                               = "${local.prefix}-nat"
  router                             = google_compute_router.rolecall.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

resource "google_compute_address" "livekit_signaling" {
  name         = "${local.prefix}-livekit"
  region       = var.region
  address_type = "EXTERNAL"
  network_tier = "PREMIUM"
}

resource "google_compute_address" "livekit_turn" {
  name         = "${local.prefix}-turn"
  region       = var.region
  address_type = "EXTERNAL"
  network_tier = "PREMIUM"
}

resource "google_compute_firewall" "livekit_media" {
  name          = "${local.prefix}-media"
  network       = google_compute_network.rolecall.name
  direction     = "INGRESS"
  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["rolecall-media"]

  allow {
    protocol = "tcp"
    ports    = ["7881", "5349"]
  }

  allow {
    protocol = "udp"
    ports    = ["3478", "50000-60000"]
  }

  log_config {
    metadata = "EXCLUDE_ALL_METADATA"
  }
}
