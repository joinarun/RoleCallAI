locals {
  event_routes = {
    postprocess = {
      topic = "rolecall-postprocess"
      path  = "/v1/internal/pubsub/postprocess"
    }
    cleanup = {
      topic = "rolecall-cleanup"
      path  = "/v1/internal/pubsub/cleanup"
    }
    document_index = {
      topic = "rolecall-document-index"
      path  = "/v1/internal/pubsub/document-index"
    }
    runtime = {
      topic = "rolecall-runtime-control"
      path  = "/v1/internal/pubsub/runtime"
    }
  }
}

resource "google_pubsub_topic" "events" {
  for_each                   = local.event_routes
  name                       = each.value.topic
  message_retention_duration = "604800s"
  labels                     = var.labels

  depends_on = [google_project_service.required]
}

resource "google_pubsub_topic" "dead_letter" {
  for_each                   = local.event_routes
  name                       = "${each.value.topic}-dead-letter"
  message_retention_duration = "1209600s"
  labels                     = var.labels

  depends_on = [google_project_service.required]
}

resource "google_service_account_iam_member" "pubsub_oidc" {
  service_account_id = google_service_account.rolecall["pubsub_push"].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_project_service_identity.pubsub.email}"
}

resource "google_pubsub_subscription" "push" {
  for_each = local.event_routes
  name     = "${each.value.topic}-push-${var.environment}"
  topic    = google_pubsub_topic.events[each.key].id

  ack_deadline_seconds       = 600
  message_retention_duration = "604800s"
  retain_acked_messages      = false
  enable_message_ordering    = false

  expiration_policy {
    ttl = ""
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead_letter[each.key].id
    max_delivery_attempts = 5
  }

  push_config {
    push_endpoint = "${local.jobs_url}${each.value.path}"
    oidc_token {
      service_account_email = google_service_account.rolecall["pubsub_push"].email
      audience              = local.jobs_url
    }
    attributes = {
      x-goog-version = "v1"
    }
  }

  depends_on = [
    google_cloud_run_v2_service_iam_member.jobs_invoker,
    google_project_iam_member.pubsub_service_agent_publish,
    google_project_iam_member.pubsub_service_agent_subscribe,
    google_service_account_iam_member.pubsub_oidc,
  ]
}

resource "google_cloud_scheduler_job" "drain_outbox" {
  name             = "${local.prefix}-drain-outbox"
  description      = "Publish transactional outbox records without exposing payloads to logs"
  region           = var.region
  schedule         = "* * * * *"
  time_zone        = "Etc/UTC"
  attempt_deadline = "320s"

  retry_config {
    retry_count          = 3
    min_backoff_duration = "10s"
    max_backoff_duration = "120s"
    max_doublings        = 3
  }

  http_target {
    uri         = "${local.jobs_url}/v1/internal/jobs/drain-outbox"
    http_method = "POST"
    headers = {
      "Content-Type" = "application/json"
    }
    oidc_token {
      service_account_email = google_service_account.rolecall["scheduler"].email
      audience              = local.jobs_url
    }
  }

  depends_on = [google_cloud_run_v2_service_iam_member.jobs_invoker]
}

resource "google_cloud_scheduler_job" "cleanup" {
  name             = "${local.prefix}-retention-cleanup"
  description      = "Delete expired Firestore, Session, and Memory Bank data"
  region           = var.region
  schedule         = "17 2 * * *"
  time_zone        = "Etc/UTC"
  attempt_deadline = "1800s"

  retry_config {
    retry_count          = 3
    min_backoff_duration = "30s"
    max_backoff_duration = "600s"
    max_doublings        = 3
  }

  http_target {
    uri         = "${local.jobs_url}/v1/internal/jobs/cleanup"
    http_method = "POST"
    headers = {
      "Content-Type" = "application/json"
    }
    oidc_token {
      service_account_email = google_service_account.rolecall["scheduler"].email
      audience              = local.jobs_url
    }
  }

  depends_on = [google_cloud_run_v2_service_iam_member.jobs_invoker]
}

resource "google_cloud_scheduler_job" "runtime_idle_check" {
  name             = "${local.prefix}-runtime-idle-check"
  description      = "Suspend the voice plane after 30 minutes without genuine activity"
  region           = var.region
  schedule         = "*/5 * * * *"
  time_zone        = "Etc/UTC"
  attempt_deadline = "320s"

  retry_config {
    retry_count          = 3
    min_backoff_duration = "10s"
    max_backoff_duration = "120s"
    max_doublings        = 3
  }

  http_target {
    uri         = "${local.jobs_url}/v1/internal/jobs/runtime-idle-check"
    http_method = "POST"
    headers = {
      "Content-Type" = "application/json"
    }
    oidc_token {
      service_account_email = google_service_account.rolecall["scheduler"].email
      audience              = local.jobs_url
    }
  }

  depends_on = [google_cloud_run_v2_service_iam_member.jobs_invoker]
}
