# Loaded temporarily by scripts/full-environment.sh only.
#
# The normal Terraform configuration intentionally prevents deletion of the
# named Firestore database and GKE cluster. The full-destroy workflow first
# applies this override to lower those protections, creates a saved destroy
# plan, and removes this file on every exit path.

resource "google_firestore_database" "rolecall" {
  delete_protection_state = "DELETE_PROTECTION_DISABLED"
  deletion_policy         = "DELETE"

  lifecycle {
    prevent_destroy = false
  }
}

resource "google_container_cluster" "rolecall" {
  deletion_protection = false
}

resource "google_kms_crypto_key" "seat_links" {
  lifecycle {
    prevent_destroy = false
  }
}

resource "google_secret_manager_secret" "admin_credentials" {
  lifecycle {
    prevent_destroy = false
  }
}

resource "google_storage_bucket" "documents" {
  force_destroy = true
}
