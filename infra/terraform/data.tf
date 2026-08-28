resource "google_firestore_database" "rolecall" {
  project                           = var.project_id
  name                              = var.firestore_database
  location_id                       = var.region
  type                              = "FIRESTORE_NATIVE"
  concurrency_mode                  = "OPTIMISTIC"
  delete_protection_state           = "DELETE_PROTECTION_ENABLED"
  deletion_policy                   = "ABANDON"
  point_in_time_recovery_enablement = "POINT_IN_TIME_RECOVERY_DISABLED"

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_project_service.required]
}

resource "google_firestore_field" "ttl" {
  for_each = toset([
    "capability_sessions",
    "occurrences",
    "transcript_segments",
  ])

  project    = var.project_id
  database   = google_firestore_database.rolecall.name
  collection = each.value
  field      = "expires_at"

  ttl_config {}
}

resource "google_firestore_index" "occurrence_history" {
  project    = var.project_id
  database   = google_firestore_database.rolecall.name
  collection = "occurrences"

  fields {
    field_path = "room_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "created_at"
    order      = "DESCENDING"
  }
}

resource "google_firestore_index" "transcript_sequence" {
  project    = var.project_id
  database   = google_firestore_database.rolecall.name
  collection = "transcript_segments"

  fields {
    field_path = "occurrence_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "sequence"
    order      = "ASCENDING"
  }
}

resource "google_firestore_index" "outbox_pending" {
  project    = var.project_id
  database   = google_firestore_database.rolecall.name
  collection = "outbox"

  fields {
    field_path = "published_at"
    order      = "ASCENDING"
  }
  fields {
    field_path = "created_at"
    order      = "ASCENDING"
  }
}

resource "google_artifact_registry_repository" "rolecall" {
  location      = var.region
  repository_id = local.artifact_repo
  description   = "Manual development images for RoleCallAI"
  format        = "DOCKER"
  labels        = var.labels

  cleanup_policy_dry_run = false

  cleanup_policies {
    id     = "delete-untagged"
    action = "DELETE"
    condition {
      tag_state  = "UNTAGGED"
      older_than = "604800s"
    }
  }

  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 10
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_redis_instance" "rolecall" {
  name               = local.prefix
  region             = var.region
  tier               = "BASIC"
  memory_size_gb     = 1
  redis_version      = "REDIS_7_2"
  authorized_network = google_compute_network.rolecall.id
  connect_mode       = "PRIVATE_SERVICE_ACCESS"
  display_name       = "RoleCallAI development routing and rate limits"
  labels             = var.labels

  auth_enabled            = false
  transit_encryption_mode = "DISABLED"

  redis_configs = {
    "maxmemory-policy" = "allkeys-lru"
  }

  maintenance_policy {
    weekly_maintenance_window {
      day = "SUNDAY"
      start_time {
        hours   = 3
        minutes = 0
        seconds = 0
        nanos   = 0
      }
    }
  }

  depends_on = [google_service_networking_connection.private_services]
}

resource "google_vertex_ai_reasoning_engine" "memory" {
  provider     = google-beta
  display_name = "${local.prefix}-memory"
  description  = "Regional Sessions and 90-day Memory Bank for stable room and seat continuity"
  region       = var.region

  context_spec {
    memory_bank_config {
      generation_config {
        model = "projects/${var.project_id}/locations/${var.summary_model_location}/publishers/google/models/gemini-3.7-flash"
      }
      similarity_search_config {
        embedding_model = "projects/${var.project_id}/locations/${var.region}/publishers/google/models/gemini-embedding-001"
      }
      disable_memory_revisions = false
      ttl_config {
        memory_revision_default_ttl = "${var.retention_days * 86400}s"
        granular_ttl_config {
          create_ttl           = "${var.retention_days * 86400}s"
          generate_created_ttl = "${var.retention_days * 86400}s"
          generate_updated_ttl = "${var.retention_days * 86400}s"
        }
      }
    }
  }

  depends_on = [google_project_service.required]
}
