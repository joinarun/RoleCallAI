locals {
  control_env = merge(local.common_env, {
    ROLECALL_COOKIE_SECURE = "true"
    ROLECALL_SERVICE_NAME  = "rolecall-control"
  })
  jobs_env = merge(local.common_env, {
    ROLECALL_COOKIE_SECURE           = "true"
    ROLECALL_PUBSUB_AUDIENCE         = local.jobs_url
    ROLECALL_PUBSUB_INVOKER_EMAIL    = google_service_account.rolecall["pubsub_push"].email
    ROLECALL_SCHEDULER_INVOKER_EMAIL = google_service_account.rolecall["scheduler"].email
    ROLECALL_SERVICE_NAME            = "rolecall-jobs"
  })
}

resource "google_cloud_run_v2_service" "control" {
  name                = local.control_service_name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false
  labels              = var.labels

  template {
    service_account                  = google_service_account.rolecall["control"].email
    timeout                          = "60s"
    max_instance_request_concurrency = 80

    scaling {
      min_instance_count = var.control_min_instances
      max_instance_count = 10
    }

    vpc_access {
      egress = "PRIVATE_RANGES_ONLY"
      network_interfaces {
        network    = google_compute_network.rolecall.name
        subnetwork = google_compute_subnetwork.rolecall.name
      }
    }

    containers {
      name  = "control"
      image = local.images.control

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      dynamic "env" {
        for_each = local.control_env
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name = "ROLECALL_COOKIE_SIGNING_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.rolecall["cookie-signing-key"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "ROLECALL_LIVEKIT_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.rolecall["livekit-api-key"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "ROLECALL_LIVEKIT_API_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.rolecall["livekit-api-secret"].secret_id
            version = "latest"
          }
        }
      }
      startup_probe {
        initial_delay_seconds = 2
        timeout_seconds       = 2
        period_seconds        = 5
        failure_threshold     = 12
        http_get {
          path = "/healthz"
          port = 8080
        }
      }

      liveness_probe {
        timeout_seconds   = 2
        period_seconds    = 30
        failure_threshold = 3
        http_get {
          path = "/healthz"
          port = 8080
        }
      }
    }
  }

  depends_on = [
    google_artifact_registry_repository.rolecall,
    google_project_iam_member.runtime,
    google_secret_manager_secret_version.rolecall,
    google_secret_manager_secret_version.admin_credentials_bootstrap,
    google_secret_manager_secret_iam_member.admin_credentials_control,
    google_kms_crypto_key.seat_links,
  ]
}

resource "google_cloud_run_v2_service" "jobs" {
  name                = local.jobs_service_name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  deletion_protection = false
  labels              = var.labels

  template {
    service_account                  = google_service_account.rolecall["jobs"].email
    timeout                          = "900s"
    max_instance_request_concurrency = 4

    scaling {
      min_instance_count = 0
      max_instance_count = 10
    }

    vpc_access {
      egress = "PRIVATE_RANGES_ONLY"
      network_interfaces {
        network    = google_compute_network.rolecall.name
        subnetwork = google_compute_subnetwork.rolecall.name
      }
    }

    containers {
      name  = "jobs"
      image = local.images.jobs

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "4Gi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      dynamic "env" {
        for_each = local.jobs_env
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name = "ROLECALL_COOKIE_SIGNING_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.rolecall["cookie-signing-key"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "ROLECALL_LIVEKIT_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.rolecall["livekit-api-key"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "ROLECALL_LIVEKIT_API_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.rolecall["livekit-api-secret"].secret_id
            version = "latest"
          }
        }
      }

      startup_probe {
        initial_delay_seconds = 2
        timeout_seconds       = 2
        period_seconds        = 5
        failure_threshold     = 12
        http_get {
          path = "/healthz"
          port = 8080
        }
      }
    }
  }

  depends_on = [
    google_artifact_registry_repository.rolecall,
    google_project_iam_member.runtime,
    google_secret_manager_secret_version.rolecall,
    google_storage_bucket.documents,
  ]
}

resource "google_cloud_run_v2_job" "runtime" {
  for_each = {
    wake    = local.runtime_wake_job
    suspend = local.runtime_suspend_job
  }

  name                = each.value
  location            = var.region
  deletion_protection = false
  labels              = var.labels

  template {
    task_count  = 1
    parallelism = 1

    template {
      service_account = google_service_account.rolecall["runtime_manager"].email
      timeout         = "1200s"
      max_retries     = 0

      containers {
        name    = "runtime-manager"
        image   = local.runtime_job_image
        command = ["/opt/rolecall-venv/bin/python", "-m", "app.runtime_manager"]

        dynamic "env" {
          for_each = local.common_env
          content {
            name  = env.key
            value = env.value
          }
        }

        env {
          name  = "ROLECALL_RUNTIME_ACTION"
          value = each.key
        }
        env {
          name  = "ROLECALL_RUNTIME_OPERATION_ID"
          value = "overridden-at-dispatch"
        }
        env {
          name = "ROLECALL_COOKIE_SIGNING_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.rolecall["cookie-signing-key"].secret_id
              version = "latest"
            }
          }
        }

        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }
      }
    }
  }

  depends_on = [
    google_project_iam_member.runtime,
    google_secret_manager_secret_version.rolecall,
    google_container_cluster.rolecall,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "control_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.control.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "jobs_invoker" {
  for_each = toset(["pubsub_push", "scheduler"])
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.jobs.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.rolecall[each.value].email}"
}
