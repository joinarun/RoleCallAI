output "approval_gate" {
  value = "STOP: review rolecall-dev.tfplan, resource-inventory.txt, and COST_ESTIMATE.md before terraform apply or image deployment."
}

output "control_plane_url" {
  value = local.control_url
}

output "jobs_url" {
  value = local.jobs_url
}

output "livekit_url" {
  value = local.livekit_url
}

output "turn_hostname" {
  value = local.turn_hostname
}

output "reserved_ips" {
  value = {
    signaling = google_compute_address.livekit_signaling.address
    turn      = google_compute_address.livekit_turn.address
  }
}

output "firestore_database" {
  value = google_firestore_database.rolecall.name
}

output "artifact_repository" {
  value = google_artifact_registry_repository.rolecall.id
}

output "agent_engine_memory_bank" {
  value = google_vertex_ai_reasoning_engine.memory.name
}

output "gke_cluster" {
  value = {
    name     = google_container_cluster.rolecall.name
    location = google_container_cluster.rolecall.location
  }
}

output "manual_build_command" {
  value = "gcloud builds submit --project=${var.project_id} --region=${var.region} --config=cloudbuild.yaml --substitutions=_TAG=${var.image_tag} --service-account=${google_service_account.rolecall["cloud_build"].id}"
}
