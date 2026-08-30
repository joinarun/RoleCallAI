data "google_project" "current" {
  project_id = var.project_id
}

locals {
  prefix               = "rolecall-${var.environment}"
  artifact_repo        = "rolecall-${var.environment}"
  artifact_host        = "${var.region}-docker.pkg.dev"
  control_service_name = "${local.prefix}-control"
  jobs_service_name    = "${local.prefix}-jobs"
  runtime_wake_job     = "${local.prefix}-runtime-wake"
  runtime_suspend_job  = "${local.prefix}-runtime-suspend"
  control_url          = "https://${local.control_service_name}-${data.google_project.current.number}.${var.region}.run.app"
  jobs_url             = "https://${local.jobs_service_name}-${data.google_project.current.number}.${var.region}.run.app"
  images = {
    control = "${local.artifact_host}/${var.project_id}/${local.artifact_repo}/control:${var.image_tag}"
    jobs    = "${local.artifact_host}/${var.project_id}/${local.artifact_repo}/jobs:${var.image_tag}"
    worker  = "${local.artifact_host}/${var.project_id}/${local.artifact_repo}/worker:${var.image_tag}"
  }
  livekit_hostname = "livekit.${replace(google_compute_address.livekit_signaling.address, ".", "-")}.sslip.io"
  turn_hostname    = "turn.${replace(google_compute_address.livekit_turn.address, ".", "-")}.sslip.io"
  livekit_url      = "wss://${local.livekit_hostname}"
  common_env = {
    ROLECALL_ENV                                       = "dev"
    ROLECALL_PROJECT_ID                                = var.project_id
    ROLECALL_REGION                                    = var.region
    ROLECALL_FIRESTORE_DATABASE                        = var.firestore_database
    ROLECALL_REPOSITORY                                = "firestore"
    ROLECALL_PUBLIC_BASE_URL                           = local.control_url
    ROLECALL_LIVEKIT_URL                               = local.livekit_url
    ROLECALL_LIVE_MODEL                                = "gemini-live-2.5-flash-native-audio"
    ROLECALL_SUMMARY_MODEL                             = "gemini-3.7-flash"
    ROLECALL_SUMMARY_MODEL_LOCATION                    = var.summary_model_location
    ROLECALL_AGENT_ENGINE_ID                           = google_vertex_ai_reasoning_engine.memory.name
    ROLECALL_ADMIN_CREDENTIALS_SECRET                  = google_secret_manager_secret.admin_credentials.id
    ROLECALL_SEAT_LINK_KMS_KEY                         = google_kms_crypto_key.seat_links.id
    ROLECALL_RECAPTCHA_SITE_KEY                        = google_recaptcha_enterprise_key.admin_login.name
    ROLECALL_RECAPTCHA_ALLOWED_HOSTNAMES               = trimprefix(local.control_url, "https://")
    ROLECALL_RECAPTCHA_BYPASS                          = "false"
    ROLECALL_DOCUMENTS_BUCKET                          = google_storage_bucket.documents.name
    ROLECALL_DOCUMENT_INDEX_TOPIC                      = "rolecall-document-index"
    ROLECALL_DOCUMENT_MALWARE_SCAN_COMMAND             = "clamscan --no-summary"
    ROLECALL_DOCUMENT_MALWARE_SCAN_REQUIRED            = "true"
    ROLECALL_RUNTIME_DEFAULT_STATUS                    = "SLEEPING"
    ROLECALL_RUNTIME_WAKE_JOB                          = local.runtime_wake_job
    ROLECALL_RUNTIME_SUSPEND_JOB                       = local.runtime_suspend_job
    ROLECALL_GKE_CLUSTER                               = google_container_cluster.rolecall.name
    ROLECALL_GKE_ZONE                                  = var.zone
    ROLECALL_LIVEKIT_SIGNALING_IP                      = google_compute_address.livekit_signaling.address
    ROLECALL_LIVEKIT_TURN_IP                           = google_compute_address.livekit_turn.address
    ROLECALL_IMMEDIATE_OUTBOX_PUBLISH                  = "true"
    GOOGLE_GENAI_USE_VERTEXAI                          = "true"
    GOOGLE_CLOUD_PROJECT                               = var.project_id
    GOOGLE_CLOUD_LOCATION                              = var.region
    OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT = "NO_CONTENT"
    ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS               = "false"
  }
}
