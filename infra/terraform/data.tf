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
    "admin_sessions",
    "capability_sessions",
    "document_chunks",
    "document_versions",
    "login_failures",
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

resource "google_firestore_index" "admin_room_list" {
  project    = var.project_id
  database   = google_firestore_database.rolecall.name
  collection = "rooms"

  fields {
    field_path = "owner_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "updated_at"
    order      = "DESCENDING"
  }
}

resource "google_firestore_index" "document_list" {
  project    = var.project_id
  database   = google_firestore_database.rolecall.name
  collection = "documents"

  fields {
    field_path = "room_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "deleted_at"
    order      = "ASCENDING"
  }
  fields {
    field_path = "created_at"
    order      = "ASCENDING"
  }
}

resource "google_firestore_index" "document_versions" {
  project    = var.project_id
  database   = google_firestore_database.rolecall.name
  collection = "document_versions"

  fields {
    field_path = "room_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "document_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "version"
    order      = "DESCENDING"
  }
}

resource "google_firestore_index" "login_throttle" {
  project    = var.project_id
  database   = google_firestore_database.rolecall.name
  collection = "login_failures"

  fields {
    field_path = "key"
    order      = "ASCENDING"
  }
  fields {
    field_path = "occurred_at"
    order      = "ASCENDING"
  }
}

resource "google_firestore_index" "document_vector" {
  project    = var.project_id
  database   = google_firestore_database.rolecall.name
  collection = "document_chunks"

  fields {
    field_path = "room_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "version_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "embedding"
    vector_config {
      dimension = 768
      flat {}
    }
  }
}

resource "google_storage_bucket" "documents" {
  name                        = "${var.project_id}-${local.prefix}-documents"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = var.labels

  soft_delete_policy {
    retention_duration_seconds = 604800
  }

  lifecycle_rule {
    condition {
      age = var.retention_days
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_kms_key_ring" "rolecall" {
  name     = local.prefix
  location = var.region

  depends_on = [google_project_service.required]
}

resource "google_kms_crypto_key" "seat_links" {
  name                       = "participant-seat-links"
  key_ring                   = google_kms_key_ring.rolecall.id
  rotation_period            = "7776000s"
  destroy_scheduled_duration = "2592000s"

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_recaptcha_enterprise_key" "admin_login" {
  display_name = "${local.prefix}-admin-login"
  project      = var.project_id
  labels       = var.labels

  web_settings {
    integration_type  = "CHECKBOX"
    allowed_domains   = [trimprefix(local.control_url, "https://")]
    allow_all_domains = false
  }

  depends_on = [google_project_service.required]
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
