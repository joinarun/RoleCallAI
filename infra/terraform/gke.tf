resource "google_container_cluster" "rolecall" {
  name     = local.prefix
  location = var.zone

  network    = google_compute_network.rolecall.name
  subnetwork = google_compute_subnetwork.rolecall.name

  remove_default_node_pool = true
  initial_node_count       = 1
  deletion_protection      = true

  networking_mode = "VPC_NATIVE"
  ip_allocation_policy {
    cluster_secondary_range_name  = "${local.prefix}-pods"
    services_secondary_range_name = "${local.prefix}-services"
  }

  release_channel {
    channel = "REGULAR"
  }

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  secret_manager_config {
    enabled = true
    rotation_config {
      enabled           = true
      rotation_interval = "300s"
    }
  }

  secret_sync_config {
    enabled = true
    rotation_config {
      enabled           = true
      rotation_interval = "300s"
    }
  }

  addons_config {
    horizontal_pod_autoscaling {
      disabled = false
    }
    http_load_balancing {
      disabled = false
    }
    gce_persistent_disk_csi_driver_config {
      enabled = true
    }
  }

  network_policy {
    enabled  = true
    provider = "PROVIDER_UNSPECIFIED"
  }

  logging_config {
    enable_components = ["SYSTEM_COMPONENTS", "WORKLOADS", "APISERVER"]
  }

  monitoring_config {
    enable_components = [
      "SYSTEM_COMPONENTS",
      "APISERVER",
      "SCHEDULER",
      "CONTROLLER_MANAGER",
      "STORAGE",
      "HPA",
      "POD",
      "DAEMONSET",
      "DEPLOYMENT",
      "STATEFULSET",
    ]
    managed_prometheus {
      enabled = true
    }
  }

  vertical_pod_autoscaling {
    enabled = true
  }

  master_auth {
    client_certificate_config {
      issue_client_certificate = false
    }
  }

  node_pool_defaults {
    node_config_defaults {
      insecure_kubelet_readonly_port_enabled = "FALSE"
      # The max-throughput Fluent Bit profile reserves about 2 vCPU per node.
      # Standard logging is sufficient for this low-volume, redacted dev stack
      # and lets the worker pool fit its configured two-node minimum.
      logging_variant = "DEFAULT"
    }
  }

  resource_labels = var.labels

  maintenance_policy {
    recurring_window {
      start_time = "2026-01-04T01:00:00Z"
      end_time   = "2026-01-04T05:00:00Z"
      recurrence = "FREQ=WEEKLY;BYDAY=SU"
    }
  }

  depends_on = [
    google_project_service.required,
    google_project_iam_member.runtime,
  ]
}

resource "google_container_node_pool" "media" {
  name               = "media"
  cluster            = google_container_cluster.rolecall.id
  location           = var.zone
  initial_node_count = var.media_min_nodes

  autoscaling {
    min_node_count  = var.media_min_nodes
    max_node_count  = var.media_max_nodes
    location_policy = "BALANCED"
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }

  node_config {
    machine_type    = "e2-standard-4"
    disk_type       = "pd-balanced"
    disk_size_gb    = 50
    image_type      = "COS_CONTAINERD"
    service_account = google_service_account.rolecall["gke_nodes"].email
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    tags            = ["rolecall-media"]
    logging_variant = "DEFAULT"

    labels = {
      rolecall-pool = "media"
    }

    taint {
      key    = "rolecall.ai/media"
      value  = "true"
      effect = "NO_SCHEDULE"
    }

    workload_metadata_config {
      mode = "GKE_METADATA"
    }

    shielded_instance_config {
      enable_secure_boot          = true
      enable_integrity_monitoring = true
    }

    metadata = {
      disable-legacy-endpoints = "true"
    }
  }
}

resource "google_container_node_pool" "workers" {
  name               = "workers"
  cluster            = google_container_cluster.rolecall.id
  location           = var.zone
  initial_node_count = var.worker_min_nodes

  autoscaling {
    min_node_count  = var.worker_min_nodes
    max_node_count  = var.worker_max_nodes
    location_policy = "BALANCED"
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }

  node_config {
    machine_type    = "e2-standard-4"
    disk_type       = "pd-balanced"
    disk_size_gb    = 50
    image_type      = "COS_CONTAINERD"
    service_account = google_service_account.rolecall["gke_nodes"].email
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    logging_variant = "DEFAULT"

    labels = {
      rolecall-pool = "workers"
    }

    workload_metadata_config {
      mode = "GKE_METADATA"
    }

    shielded_instance_config {
      enable_secure_boot          = true
      enable_integrity_monitoring = true
    }

    metadata = {
      disable-legacy-endpoints = "true"
    }
  }
}
