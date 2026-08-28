locals {
  service_accounts = {
    control     = "rolecall-control-${var.environment}"
    jobs        = "rolecall-jobs-${var.environment}"
    worker      = "rolecall-worker-${var.environment}"
    gke_nodes   = "rolecall-gke-${var.environment}"
    pubsub_push = "rolecall-pubsub-${var.environment}"
    scheduler   = "rolecall-scheduler-${var.environment}"
    cloud_build = "rolecall-build-${var.environment}"
  }
  project_roles = {
    control = toset([
      "roles/datastore.user",
      "roles/logging.logWriter",
      "roles/monitoring.metricWriter",
      "roles/cloudtrace.agent",
      "roles/pubsub.publisher",
    ])
    jobs = toset([
      "roles/aiplatform.user",
      "roles/datastore.user",
      "roles/logging.logWriter",
      "roles/monitoring.metricWriter",
      "roles/cloudtrace.agent",
      "roles/pubsub.publisher",
    ])
    worker = toset([
      "roles/aiplatform.user",
      "roles/datastore.user",
      "roles/logging.logWriter",
      "roles/monitoring.metricWriter",
      "roles/cloudtrace.agent",
      "roles/pubsub.publisher",
    ])
    gke_nodes = toset([
      "roles/artifactregistry.reader",
      "roles/logging.logWriter",
      "roles/monitoring.metricWriter",
      "roles/monitoring.viewer",
    ])
    cloud_build = toset([
      "roles/artifactregistry.writer",
      "roles/logging.logWriter",
    ])
  }
  flattened_project_roles = flatten([
    for account, roles in local.project_roles : [
      for role in roles : { account = account, role = role }
    ]
  ])
}

resource "google_service_account" "rolecall" {
  for_each     = local.service_accounts
  account_id   = each.value
  display_name = "RoleCallAI ${replace(each.key, "_", " ")} (${var.environment})"
}

resource "google_project_iam_member" "runtime" {
  for_each = {
    for item in local.flattened_project_roles : "${item.account}:${item.role}" => item
  }
  project = var.project_id
  role    = each.value.role
  member  = "serviceAccount:${google_service_account.rolecall[each.value.account].email}"
}

resource "google_service_account_iam_member" "worker_identity" {
  service_account_id = google_service_account.rolecall["worker"].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[rolecall/rolecall-worker]"
}

resource "google_project_iam_member" "pubsub_service_agent_publish" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_project_service_identity.pubsub.email}"
}

resource "google_project_iam_member" "pubsub_service_agent_subscribe" {
  project = var.project_id
  role    = "roles/pubsub.subscriber"
  member  = "serviceAccount:${google_project_service_identity.pubsub.email}"
}

resource "google_storage_bucket_iam_member" "cloud_build_source_viewer" {
  bucket = "${var.project_id}_cloudbuild"
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.rolecall["cloud_build"].email}"
}
