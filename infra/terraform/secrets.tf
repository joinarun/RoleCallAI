resource "random_id" "livekit_api_key" {
  byte_length = 12
}

resource "random_password" "livekit_api_secret" {
  length  = 48
  special = false
}

resource "random_password" "cookie_signing_key" {
  length  = 64
  special = false
}

resource "random_password" "redis_password" {
  length  = 40
  special = false
}

locals {
  secret_values = {
    cookie-signing-key = random_password.cookie_signing_key.result
    livekit-api-key    = random_id.livekit_api_key.hex
    livekit-api-secret = random_password.livekit_api_secret.result
  }
  secret_access = {
    control-cookie = { account = "control", secret = "cookie-signing-key" }
    control-key    = { account = "control", secret = "livekit-api-key" }
    control-secret = { account = "control", secret = "livekit-api-secret" }
    jobs-cookie    = { account = "jobs", secret = "cookie-signing-key" }
    jobs-key       = { account = "jobs", secret = "livekit-api-key" }
    jobs-secret    = { account = "jobs", secret = "livekit-api-secret" }
    worker-key     = { account = "worker", secret = "livekit-api-key" }
    worker-secret  = { account = "worker", secret = "livekit-api-secret" }
    runtime-cookie = { account = "runtime_manager", secret = "cookie-signing-key" }
  }
}

resource "google_secret_manager_secret" "admin_credentials" {
  secret_id = "${local.prefix}-admin-credentials"
  labels    = var.labels

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_iam_member" "admin_credentials_control" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.admin_credentials.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.rolecall["control"].email}"
}

# Cloud Run requires the referenced `latest` version to exist before the first
# revision can be created. This value is intentionally not a usable credential;
# the trusted-terminal rotation script adds the first real Argon2id version.
resource "google_secret_manager_secret_version" "admin_credentials_bootstrap" {
  secret = google_secret_manager_secret.admin_credentials.id
  secret_data = jsonencode({
    username      = "disabled-until-rotated"
    password_hash = "invalid-argon2id-hash"
    version       = 0
  })
}

resource "google_secret_manager_secret" "rolecall" {
  for_each  = local.secret_values
  secret_id = "${local.prefix}-${each.key}"
  labels    = var.labels

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "rolecall" {
  for_each    = local.secret_values
  secret      = google_secret_manager_secret.rolecall[each.key].id
  secret_data = each.value
}

resource "google_secret_manager_secret_iam_member" "runtime" {
  for_each  = local.secret_access
  project   = var.project_id
  secret_id = google_secret_manager_secret.rolecall[each.value.secret].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.rolecall[each.value.account].email}"
}
