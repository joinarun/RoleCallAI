#!/usr/bin/env bash

set -Eeuo pipefail

readonly FULL_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly FULL_REPO_ROOT="$(cd "${FULL_SCRIPT_DIR}/.." && pwd)"
readonly FULL_TF_DIR="${FULL_REPO_ROOT}/infra/terraform"
readonly FULL_TF_VARS="vars/dev.tfvars"
readonly FULL_AGENT_DIR="${FULL_REPO_ROOT}/services/rolecall-agent"
readonly FULL_OVERRIDE_TEMPLATE="${FULL_SCRIPT_DIR}/templates/rolecall_destroy_override.tf"
readonly FULL_OVERRIDE_PATH="${FULL_TF_DIR}/rolecall_destroy_override.tf"
readonly FULL_LOCAL_DIR="${FULL_REPO_ROOT}/local-data/full-environment"
readonly FULL_LOCK_DIR="${FULL_LOCAL_DIR}/operation.lock"
readonly FULL_CONFIG_FILE="${ROLECALL_CONFIG_FILE:-${FULL_REPO_ROOT}/.rolecall.local.env}"

if [[ -f "${FULL_CONFIG_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${FULL_CONFIG_FILE}"
fi

readonly FULL_PROJECT_ID="${ROLECALL_GCP_PROJECT_ID:-your-gcp-project-id}"
readonly FULL_REGION="${ROLECALL_GCP_REGION:-europe-west4}"
readonly FULL_ZONE="${ROLECALL_GCP_ZONE:-europe-west4-a}"
readonly FULL_CLUSTER="${ROLECALL_GKE_CLUSTER:-rolecall-dev}"
readonly FULL_DATABASE="${ROLECALL_FIRESTORE_DATABASE:-rolecall-dev}"
readonly FULL_DEFAULT_DATABASE="(default)"
readonly FULL_DEFAULT_DATABASE_LOCATION="${ROLECALL_DEFAULT_FIRESTORE_LOCATION:-your-existing-default-database-location}"
readonly FULL_CONTROL_SERVICE="${ROLECALL_CONTROL_SERVICE:-${FULL_CLUSTER}-control}"
readonly FULL_JOBS_SERVICE="${FULL_CLUSTER}-jobs"
readonly FULL_ARTIFACT_REPOSITORY="${FULL_CLUSTER}"
readonly FULL_NETWORK="${FULL_CLUSTER}"
readonly FULL_DRAIN_JOB="${FULL_CLUSTER}-drain-outbox"
readonly FULL_CLEANUP_JOB="${FULL_CLUSTER}-retention-cleanup"
readonly FULL_IDLE_JOB="${FULL_CLUSTER}-runtime-idle-check"
readonly FULL_BUILD_SERVICE_ACCOUNT_EMAIL="${ROLECALL_BUILD_SERVICE_ACCOUNT_EMAIL:-rolecall-build-dev@${FULL_PROJECT_ID}.iam.gserviceaccount.com}"
readonly FULL_BUILD_SERVICE_ACCOUNT="projects/${FULL_PROJECT_ID}/serviceAccounts/${FULL_BUILD_SERVICE_ACCOUNT_EMAIL}"
readonly FULL_KUBE_CONTEXT="gke_${FULL_PROJECT_ID}_${FULL_ZONE}_${FULL_CLUSTER}"

FULL_DRY_RUN=false
FULL_CONFIRM_TOKEN=""
FULL_ACTION=""
FULL_OVERRIDE_INSTALLED=false
FULL_PROTECTIONS_LOWERED=false
FULL_DESTROY_STARTED=false
FULL_DESTROY_COMPLETED=false
FULL_FROZEN=false
FULL_INITIAL_CONTROL_PUBLIC=false
FULL_INITIAL_DRAIN_STATE="MISSING"
FULL_INITIAL_CLEANUP_STATE="MISSING"
FULL_INITIAL_IDLE_STATE="MISSING"
FULL_LAST_STEP="startup"
FULL_LOCK_ACQUIRED=false

full_usage() {
  cat <<EOF
Usage: scripts/full-environment.sh <status|destroy|create> [options]

Commands:
  status    Read-only report of Terraform and major RoleCallAI resources.
  destroy   PERMANENTLY delete every Terraform-managed RoleCallAI resource,
            including the named Firestore database, rooms, transcripts,
            Memory Bank, documents, images, secrets, KMS, GKE, and public endpoints.
  create    Rebuild images and recreate the complete environment from Terraform.

Options:
  --dry-run                 Validate and print intended mutations without changing GCP.
  --confirm-token <token>   Non-interactive confirmation. Accepted tokens are:
                              delete-${FULL_PROJECT_ID}-${FULL_DATABASE}
                              create-${FULL_PROJECT_ID}-${FULL_DATABASE}
  -h, --help                Show this help.

This script is pinned by ${FULL_CONFIG_FILE}. It never targets the existing
(default) Firestore database. Enabled project APIs,
Google-managed service identities, historical logs/build records, and the shared
Cloud Build source-staging bucket are retained because they are project-scoped.
EOF
}

full_log() {
  printf '[rolecall-full] %s\n' "$*"
}

full_die() {
  printf '[rolecall-full] ERROR: %s\n' "$*" >&2
  exit 1
}

full_print_command() {
  printf '  +'
  printf ' %q' "$@"
  printf '\n'
}

full_run_mutation() {
  full_print_command "$@"
  if [[ "${FULL_DRY_RUN}" == false ]]; then
    "$@"
  fi
}

full_require_command() {
  command -v "$1" >/dev/null 2>&1 || full_die "Required command is missing: $1"
}

full_acquire_lock() {
  mkdir -p "${FULL_LOCAL_DIR}"
  if mkdir "${FULL_LOCK_DIR}" 2>/dev/null; then
    printf '%s\n' "$$" > "${FULL_LOCK_DIR}/pid"
    FULL_LOCK_ACQUIRED=true
    return
  fi

  local full_lock_pid="unknown"
  if [[ -f "${FULL_LOCK_DIR}/pid" ]]; then
    full_lock_pid="$(sed -n '1p' "${FULL_LOCK_DIR}/pid")"
  fi
  full_die "Another full-environment operation may be running (PID ${full_lock_pid}). Inspect ${FULL_LOCK_DIR}; never remove an active lock."
}

full_tf() {
  terraform -chdir="${FULL_TF_DIR}" "$@"
}

full_state_list() {
  full_tf state list 2>/dev/null || true
}

full_state_count() {
  { full_state_list | rg --invert-match '^data\.' || true; } | wc -l | tr -d '[:space:]'
}

full_state_has() {
  local full_address="$1"
  full_state_list | rg --fixed-strings --line-regexp "${full_address}" >/dev/null
}

full_firestore_exists() {
  gcloud firestore databases describe \
    --database="${FULL_DATABASE}" \
    --project="${FULL_PROJECT_ID}" \
    --format='value(name)' >/dev/null 2>&1
}

full_default_firestore_location() {
  gcloud firestore databases describe \
    --database="${FULL_DEFAULT_DATABASE}" \
    --project="${FULL_PROJECT_ID}" \
    --format='value(locationId)'
}

full_control_exists() {
  gcloud run services describe "${FULL_CONTROL_SERVICE}" \
    --project="${FULL_PROJECT_ID}" \
    --region="${FULL_REGION}" \
    --format='value(metadata.name)' >/dev/null 2>&1
}

full_cluster_exists() {
  gcloud container clusters describe "${FULL_CLUSTER}" \
    --project="${FULL_PROJECT_ID}" \
    --zone="${FULL_ZONE}" \
    --format='value(name)' >/dev/null 2>&1
}

full_control_is_public() {
  local full_member
  full_member="$(
    gcloud run services get-iam-policy "${FULL_CONTROL_SERVICE}" \
      --project="${FULL_PROJECT_ID}" \
      --region="${FULL_REGION}" \
      --flatten='bindings[].members' \
      --filter='bindings.role:roles/run.invoker AND bindings.members:allUsers' \
      --format='value(bindings.members)' 2>/dev/null || true
  )"
  [[ "${full_member}" == *allUsers* ]]
}

full_scheduler_state() {
  local full_job="$1"
  gcloud scheduler jobs describe "${full_job}" \
    --project="${FULL_PROJECT_ID}" \
    --location="${FULL_REGION}" \
    --format='value(state)' 2>/dev/null || printf 'MISSING\n'
}

full_guard() {
  if ! full_firestore_exists; then
    full_log "Named Firestore database is absent; no durable meeting work can remain there."
    return 0
  fi
  (
    cd "${FULL_AGENT_DIR}"
    uv run --frozen python "${FULL_SCRIPT_DIR}/runtime_guard.py" \
      --project "${FULL_PROJECT_ID}" \
      --database "${FULL_DATABASE}"
  )
}

full_prepare() {
  full_require_command terraform
  full_require_command gcloud
  full_require_command uv
  full_require_command rg
  full_require_command make
  full_require_command kubectl
  full_require_command curl
  full_require_command awk

  [[ "${FULL_PROJECT_ID}" != "your-gcp-project-id" ]] || \
    full_die "Configure ${FULL_CONFIG_FILE} from .rolecall.local.env.example."
  [[ "${FULL_DEFAULT_DATABASE_LOCATION}" != "your-existing-default-database-location" ]] || \
    full_die "Set ROLECALL_DEFAULT_FIRESTORE_LOCATION in ${FULL_CONFIG_FILE}."
  [[ -f "${FULL_TF_DIR}/${FULL_TF_VARS}" ]] || \
    full_die "Copy infra/terraform/vars/dev.tfvars.example to the ignored dev.tfvars and configure it."

  local full_account full_project full_default_location
  full_account="$(gcloud auth list --filter='status:ACTIVE' --format='value(account)' | sed -n '1p')"
  [[ -n "${full_account}" ]] || full_die "No active gcloud account. Run: gcloud auth login"
  full_project="$(gcloud projects describe "${FULL_PROJECT_ID}" --format='value(projectId)')"
  [[ "${full_project}" == "${FULL_PROJECT_ID}" ]] || full_die "Unexpected Google Cloud project."

  FULL_LAST_STEP="Terraform initialization"
  full_tf init -input=false >/dev/null
  full_tf validate >/dev/null

  full_default_location="$(full_default_firestore_location)"
  [[ "${full_default_location}" == "${FULL_DEFAULT_DATABASE_LOCATION}" ]] || \
    full_die "Default Firestore safety check failed: expected ${FULL_DEFAULT_DATABASE_LOCATION}, got ${full_default_location:-missing}."

  [[ -f "${FULL_OVERRIDE_TEMPLATE}" ]] || full_die "Destroy override template is missing."
  [[ ! -e "${FULL_OVERRIDE_PATH}" ]] || \
    full_die "A stale destroy override exists at ${FULL_OVERRIDE_PATH}; inspect and remove it before continuing."
}

full_confirm() {
  local full_kind="$1"
  local full_expected_token full_expected_phrase
  if [[ "${FULL_DRY_RUN}" == true ]]; then
    return
  fi
  case "${full_kind}" in
    destroy)
      full_expected_token="delete-${FULL_PROJECT_ID}-${FULL_DATABASE}"
      full_expected_phrase="DELETE ${FULL_DATABASE} FROM ${FULL_PROJECT_ID}"
      ;;
    create)
      full_expected_token="create-${FULL_PROJECT_ID}-${FULL_DATABASE}"
      full_expected_phrase="CREATE ${FULL_DATABASE} IN ${FULL_PROJECT_ID}"
      ;;
    *) full_die "Unknown confirmation type: ${full_kind}" ;;
  esac

  if [[ -n "${FULL_CONFIRM_TOKEN}" ]]; then
    [[ "${FULL_CONFIRM_TOKEN}" == "${full_expected_token}" ]] || \
      full_die "Confirmation token does not match the ${full_kind} operation."
    return
  fi

  printf 'Type exactly "%s" to continue: ' "${full_expected_phrase}"
  local full_answer
  read -r full_answer
  [[ "${full_answer}" == "${full_expected_phrase}" ]] || full_die "Confirmation did not match."
}

full_install_override() {
  [[ ! -e "${FULL_OVERRIDE_PATH}" ]] || full_die "Destroy override already exists."
  cp "${FULL_OVERRIDE_TEMPLATE}" "${FULL_OVERRIDE_PATH}"
  FULL_OVERRIDE_INSTALLED=true
}

full_remove_override() {
  if [[ "${FULL_OVERRIDE_INSTALLED}" == true && -e "${FULL_OVERRIDE_PATH}" ]]; then
    unlink "${FULL_OVERRIDE_PATH}"
  fi
  FULL_OVERRIDE_INSTALLED=false
}

full_freeze() {
  full_log "Checking for active meetings and durable post-processing work."
  full_guard || full_die "Destroy refused while meetings or outbox work are active."

  if full_control_exists && full_control_is_public; then
    FULL_INITIAL_CONTROL_PUBLIC=true
  fi
  FULL_INITIAL_DRAIN_STATE="$(full_scheduler_state "${FULL_DRAIN_JOB}")"
  FULL_INITIAL_CLEANUP_STATE="$(full_scheduler_state "${FULL_CLEANUP_JOB}")"
  FULL_INITIAL_IDLE_STATE="$(full_scheduler_state "${FULL_IDLE_JOB}")"

  full_log "Freezing new public traffic and scheduled jobs; GKE remains available for clean Helm removal."
  if full_control_exists && full_control_is_public; then
    full_run_mutation gcloud run services remove-iam-policy-binding \
      "${FULL_CONTROL_SERVICE}" \
      --project="${FULL_PROJECT_ID}" \
      --region="${FULL_REGION}" \
      --member=allUsers \
      --role=roles/run.invoker \
      --quiet
  fi
  if [[ "${FULL_INITIAL_DRAIN_STATE}" == "ENABLED" ]]; then
    full_run_mutation gcloud scheduler jobs pause "${FULL_DRAIN_JOB}" \
      --project="${FULL_PROJECT_ID}" --location="${FULL_REGION}" --quiet
  fi
  if [[ "${FULL_INITIAL_CLEANUP_STATE}" == "ENABLED" ]]; then
    full_run_mutation gcloud scheduler jobs pause "${FULL_CLEANUP_JOB}" \
      --project="${FULL_PROJECT_ID}" --location="${FULL_REGION}" --quiet
  fi
  if [[ "${FULL_INITIAL_IDLE_STATE}" == "ENABLED" ]]; then
    full_run_mutation gcloud scheduler jobs pause "${FULL_IDLE_JOB}" \
      --project="${FULL_PROJECT_ID}" --location="${FULL_REGION}" --quiet
  fi

  if [[ "${FULL_DRY_RUN}" == false ]]; then
    FULL_FROZEN=true
    full_log "Repeating the durable-state guard after the request freeze."
    full_guard || full_die "New work appeared during the freeze; deletion is cancelled."
  fi
}

full_unfreeze() {
  full_log "Restoring pre-destroy public and scheduler state."
  if [[ "${FULL_INITIAL_CONTROL_PUBLIC}" == true ]] && full_control_exists && ! full_control_is_public; then
    gcloud run services add-iam-policy-binding "${FULL_CONTROL_SERVICE}" \
      --project="${FULL_PROJECT_ID}" \
      --region="${FULL_REGION}" \
      --member=allUsers \
      --role=roles/run.invoker \
      --quiet >/dev/null || true
  fi
  if [[ "${FULL_INITIAL_DRAIN_STATE}" == "ENABLED" && "$(full_scheduler_state "${FULL_DRAIN_JOB}")" == "PAUSED" ]]; then
    gcloud scheduler jobs resume "${FULL_DRAIN_JOB}" \
      --project="${FULL_PROJECT_ID}" --location="${FULL_REGION}" --quiet || true
  fi
  if [[ "${FULL_INITIAL_CLEANUP_STATE}" == "ENABLED" && "$(full_scheduler_state "${FULL_CLEANUP_JOB}")" == "PAUSED" ]]; then
    gcloud scheduler jobs resume "${FULL_CLEANUP_JOB}" \
      --project="${FULL_PROJECT_ID}" --location="${FULL_REGION}" --quiet || true
  fi
  if [[ "${FULL_INITIAL_IDLE_STATE}" == "ENABLED" && "$(full_scheduler_state "${FULL_IDLE_JOB}")" == "PAUSED" ]]; then
    gcloud scheduler jobs resume "${FULL_IDLE_JOB}" \
      --project="${FULL_PROJECT_ID}" --location="${FULL_REGION}" --quiet || true
  fi
  FULL_FROZEN=false
}

full_protection_targets() {
  if full_state_has 'google_firestore_database.rolecall'; then
    printf '%s\n' '-target=google_firestore_database.rolecall'
  fi
  if full_state_has 'google_container_cluster.rolecall'; then
    printf '%s\n' '-target=google_container_cluster.rolecall'
  fi
  if full_state_has 'google_kms_crypto_key.seat_links'; then
    printf '%s\n' '-target=google_kms_crypto_key.seat_links'
  fi
  if full_state_has 'google_secret_manager_secret.admin_credentials'; then
    printf '%s\n' '-target=google_secret_manager_secret.admin_credentials'
  fi
  if full_state_has 'google_storage_bucket.documents'; then
    printf '%s\n' '-target=google_storage_bucket.documents'
  fi
}

full_lower_protections() {
  local full_targets=()
  while IFS= read -r full_target; do
    [[ -n "${full_target}" ]] && full_targets+=("${full_target}")
  done < <(full_protection_targets)
  if [[ "${#full_targets[@]}" -eq 0 ]]; then
    full_log "Protected Firestore, GKE, KMS, admin-secret, and document-bucket resources are absent."
    return
  fi

  full_install_override
  if [[ "${FULL_DRY_RUN}" == true ]]; then
    full_log "Previewing the protection changes required before a real destroy plan."
    full_tf plan -input=false -lock=false -var-file="${FULL_TF_VARS}" "${full_targets[@]}"
    return
  fi

  FULL_PROTECTIONS_LOWERED=true
  full_log "Temporarily disabling RoleCallAI deletion protections."
  full_tf apply -input=false -auto-approve -var-file="${FULL_TF_VARS}" "${full_targets[@]}"
}

full_restore_protections() {
  local full_targets=()
  while IFS= read -r full_target; do
    [[ -n "${full_target}" ]] && full_targets+=("${full_target}")
  done < <(full_protection_targets)
  full_remove_override
  if [[ "${#full_targets[@]}" -gt 0 ]]; then
    full_log "Re-enabling normal RoleCallAI deletion protection."
    full_tf apply -input=false -auto-approve -var-file="${FULL_TF_VARS}" \
      "${full_targets[@]}" >/dev/null || \
      printf '[rolecall-full] WARNING: automatic protection restoration failed; run terraform apply before other operations.\n' >&2
  fi
  FULL_PROTECTIONS_LOWERED=false
}

full_destroy() {
  local full_count full_timestamp full_plan full_summary
  full_count="$(full_state_count)"
  [[ "${full_count}" -gt 0 ]] || {
    full_log "Terraform state is already empty; there is nothing to destroy."
    full_status
    return
  }

  cat <<EOF
WARNING: this permanently deletes the RoleCallAI named Firestore database and
all rooms, links, transcripts, recaps, memory, documents, images, secrets,
GKE/LiveKit, Cloud Run services, networking, and public endpoints.

The unrelated ${FULL_DEFAULT_DATABASE} Firestore database in
${FULL_DEFAULT_DATABASE_LOCATION} is explicitly checked and preserved.
EOF
  FULL_LAST_STEP="operator confirmation"
  full_confirm destroy
  full_freeze
  FULL_LAST_STEP="lowering deletion protection"
  full_lower_protections

  if [[ "${FULL_DRY_RUN}" == true ]]; then
    full_log "A real run would now create and apply a saved destroy plan for ${full_count} state entries."
    full_print_command terraform -chdir="${FULL_TF_DIR}" plan -destroy \
      -var-file="${FULL_TF_VARS}" -out='<local-data destroy plan>'
    full_print_command terraform -chdir="${FULL_TF_DIR}" apply '<saved destroy plan>'
    full_log "Dry run complete; no Google Cloud resource was changed."
    return
  fi

  mkdir -p "${FULL_LOCAL_DIR}"
  full_timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  full_plan="${FULL_LOCAL_DIR}/destroy-${full_timestamp}.tfplan"
  FULL_LAST_STEP="creating the complete Terraform destroy plan"
  full_tf plan -destroy -input=false -var-file="${FULL_TF_VARS}" -out="${full_plan}"
  full_summary="$(full_tf show -no-color "${full_plan}" | sed -n '/^Plan:/p' | tail -n 1)"
  full_log "Saved destroy plan: ${full_plan}"
  full_log "${full_summary:-Destroy plan generated for ${full_count} state entries.}"

  if [[ -z "${FULL_CONFIRM_TOKEN}" ]]; then
    printf 'Final confirmation — type "DESTROY %s TERRAFORM ENTRIES": ' "${full_count}"
    local full_final_answer
    read -r full_final_answer
    [[ "${full_final_answer}" == "DESTROY ${full_count} TERRAFORM ENTRIES" ]] || \
      full_die "Final confirmation did not match."
  fi

  FULL_DESTROY_STARTED=true
  FULL_LAST_STEP="applying the saved Terraform destroy plan"
  full_tf apply -input=false "${full_plan}"
  FULL_DESTROY_COMPLETED=true
  FULL_FROZEN=false
  full_remove_override

  [[ "$(full_state_count)" == "0" ]] || full_die "Terraform state is not empty after destroy."
  if full_firestore_exists; then
    full_die "Named Firestore database still exists after destroy."
  fi
  [[ "$(full_default_firestore_location)" == "${FULL_DEFAULT_DATABASE_LOCATION}" ]] || \
    full_die "Critical safety check: the default Firestore database is missing or moved."

  printf '%s\n' "$(date -u +%s)" > "${FULL_LOCAL_DIR}/last-destroy-epoch"
  printf '%s\n' "${full_timestamp}" > "${FULL_LOCAL_DIR}/last-destroy-utc"
  full_log "Full RoleCallAI teardown completed. The default Firestore database remains untouched."
  full_status
}

full_bootstrap_targets() {
  printf '%s\n' \
    '-target=google_project_service.required' \
    '-target=google_artifact_registry_repository.rolecall' \
    '-target=google_service_account.rolecall["cloud_build"]' \
    '-target=google_project_iam_member.runtime["cloud_build:roles/artifactregistry.writer"]' \
    '-target=google_project_iam_member.runtime["cloud_build:roles/logging.logWriter"]' \
    '-target=google_storage_bucket_iam_member.cloud_build_source_viewer'
}

full_image_tag() {
  awk -F '"' '/^[[:space:]]*image_tag[[:space:]]*=/{print $2; exit}' \
    "${FULL_TF_DIR}/${FULL_TF_VARS}"
}

full_wait_for_firestore_reuse() {
  local full_marker="${FULL_LOCAL_DIR}/last-destroy-epoch"
  [[ -f "${full_marker}" ]] || return
  local full_deleted_epoch full_now full_elapsed full_remaining
  full_deleted_epoch="$(sed -n '1p' "${full_marker}")"
  [[ "${full_deleted_epoch}" =~ ^[0-9]+$ ]] || return
  full_now="$(date -u +%s)"
  full_elapsed=$((full_now - full_deleted_epoch))
  full_remaining=$((330 - full_elapsed))
  if [[ "${full_remaining}" -le 0 ]]; then
    return
  fi
  full_log "Firestore database IDs cannot be reused for five minutes; waiting ${full_remaining}s."
  while [[ "${full_remaining}" -gt 0 ]]; do
    if [[ "${full_remaining}" -gt 15 ]]; then
      sleep 15
    else
      sleep "${full_remaining}"
    fi
    full_now="$(date -u +%s)"
    full_elapsed=$((full_now - full_deleted_epoch))
    full_remaining=$((330 - full_elapsed))
  done
}

full_environment_complete() {
  full_state_has 'google_container_cluster.rolecall' && \
    full_state_has 'google_cloud_run_v2_service.control' && \
    full_state_has 'google_firestore_database.rolecall' && \
    full_state_has 'google_storage_bucket.documents' && \
    full_state_has 'google_kms_crypto_key.seat_links'
}

full_kube() {
  local full_access_token
  full_access_token="$(gcloud auth print-access-token)"
  kubectl --context="${FULL_KUBE_CONTEXT}" --token="${full_access_token}" "$@"
}

full_verify_create() {
  local full_control_url full_livekit_url full_livekit_host full_noop_plan full_plan_exit
  full_control_url="$(full_tf output -raw control_plane_url)"
  full_livekit_url="$(full_tf output -raw livekit_url)"
  full_livekit_host="${full_livekit_url#wss://}"

  gcloud container clusters get-credentials "${FULL_CLUSTER}" \
    --project="${FULL_PROJECT_ID}" --zone="${FULL_ZONE}" --quiet >/dev/null
  full_kube -n rolecall rollout status deployment/livekit-server --timeout=900s
  full_kube -n rolecall rollout status deployment/rolecall-worker --timeout=900s
  full_kube -n rolecall wait --for=condition=Ready certificate/livekit-signaling --timeout=900s
  full_kube -n rolecall wait --for=condition=Ready certificate/livekit-turn --timeout=900s

  curl --fail --silent --show-error --max-time 30 "${full_control_url}/readyz" >/dev/null
  curl --silent --show-error --output /dev/null --max-time 30 "https://${full_livekit_host}/"
  [[ "$(full_default_firestore_location)" == "${FULL_DEFAULT_DATABASE_LOCATION}" ]] || \
    full_die "Default Firestore verification failed after create."

  full_noop_plan="${FULL_LOCAL_DIR}/post-create-noop.tfplan"
  if full_tf plan -detailed-exitcode -input=false -var-file="${FULL_TF_VARS}" \
    -out="${full_noop_plan}" >/dev/null; then
    full_plan_exit=0
  else
    full_plan_exit=$?
  fi
  [[ "${full_plan_exit}" -eq 0 ]] || \
    full_die "Post-create Terraform plan is not empty (exit ${full_plan_exit})."

  full_log "Create verification passed."
  full_log "Web/control: ${full_control_url}"
  full_log "LiveKit: ${full_livekit_url}"
  full_log "TURN: $(full_tf output -raw turn_hostname)"
}

full_create() {
  local full_targets=() full_target full_tag full_timestamp full_plan
  if full_environment_complete && full_firestore_exists && full_cluster_exists \
    && full_control_exists && [[ "${FULL_DRY_RUN}" == false ]]; then
    full_log "The full environment is already represented in Terraform state."
    full_log "Use scripts/dev-runtime.sh up for a suspended environment."
    full_status
    return
  fi

  cat <<EOF
This recreates billable RoleCallAI infrastructure in ${FULL_PROJECT_ID}, including
three minimum GKE nodes, ephemeral in-cluster Redis, load balancers, Cloud Run,
Firestore, private document storage, KMS, reCAPTCHA Enterprise, and Vertex AI.
New secrets, capabilities, Memory Bank ID, reserved IPs, and sslip.io hostnames are
created. Data and links from a previous destroyed environment do not return.
EOF
  FULL_LAST_STEP="operator confirmation"
  full_confirm create

  FULL_LAST_STEP="local test and lint gate"
  full_log "Running local correctness gates before creating billable resources."
  make -C "${FULL_REPO_ROOT}" test lint

  while IFS= read -r full_target; do
    [[ -n "${full_target}" ]] && full_targets+=("${full_target}")
  done < <(full_bootstrap_targets)

  if [[ "${FULL_DRY_RUN}" == true ]]; then
    full_log "Dry-run create sequence: bootstrap APIs/build identity/repository, build three images, then apply the complete Terraform plan."
    full_print_command terraform -chdir="${FULL_TF_DIR}" apply \
      -var-file="${FULL_TF_VARS}" "${full_targets[@]}"
    full_print_command gcloud builds submit "${FULL_REPO_ROOT}" \
      --project="${FULL_PROJECT_ID}" --region="${FULL_REGION}" \
      --config="${FULL_REPO_ROOT}/cloudbuild.yaml" --substitutions='_TAG=<dev.tfvars image_tag>' \
      --service-account="${FULL_BUILD_SERVICE_ACCOUNT}"
    full_print_command terraform -chdir="${FULL_TF_DIR}" plan \
      -var-file="${FULL_TF_VARS}" -out='<local-data create plan>'
    full_print_command terraform -chdir="${FULL_TF_DIR}" apply '<saved create plan>'
    full_log "Dry run complete; no Google Cloud resource was changed."
    return
  fi

  mkdir -p "${FULL_LOCAL_DIR}"
  FULL_LAST_STEP="bootstrapping APIs, Cloud Build identity, and Artifact Registry"
  full_tf apply -input=false -auto-approve -var-file="${FULL_TF_VARS}" "${full_targets[@]}"

  full_tag="$(full_image_tag)"
  [[ "${full_tag}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || \
    full_die "Invalid or missing image_tag in ${FULL_TF_VARS}."
  FULL_LAST_STEP="building and pushing control, jobs, and worker images"
  gcloud builds submit "${FULL_REPO_ROOT}" \
    --project="${FULL_PROJECT_ID}" \
    --region="${FULL_REGION}" \
    --config="${FULL_REPO_ROOT}/cloudbuild.yaml" \
    --substitutions="_TAG=${full_tag}" \
    --service-account="${FULL_BUILD_SERVICE_ACCOUNT}"

  full_wait_for_firestore_reuse
  full_timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  full_plan="${FULL_LOCAL_DIR}/create-${full_timestamp}.tfplan"
  FULL_LAST_STEP="creating the complete Terraform create plan"
  full_tf plan -input=false -var-file="${FULL_TF_VARS}" -out="${full_plan}"
  full_log "Saved create plan: ${full_plan}"
  FULL_LAST_STEP="applying the complete Terraform create plan"
  full_tf apply -input=false "${full_plan}"

  FULL_LAST_STEP="post-create readiness and Terraform convergence checks"
  full_verify_create
  full_status
}

full_status() {
  local full_count full_mode="PARTIAL" full_named_db="absent" full_cluster="absent"
  local full_control="absent" full_jobs="absent" full_documents="absent" full_artifact="absent"
  local full_default_location
  full_count="$(full_state_count)"
  full_default_location="$(full_default_firestore_location 2>/dev/null || printf 'missing')"
  full_firestore_exists && full_named_db="present"
  full_cluster_exists && full_cluster="present"
  full_control_exists && full_control="present"
  gcloud run services describe "${FULL_JOBS_SERVICE}" --project="${FULL_PROJECT_ID}" \
    --region="${FULL_REGION}" --format='value(metadata.name)' >/dev/null 2>&1 && full_jobs="present"
  gcloud storage buckets describe "gs://${FULL_PROJECT_ID}-${FULL_CLUSTER}-documents" \
    --project="${FULL_PROJECT_ID}" >/dev/null 2>&1 && full_documents="present"
  gcloud artifacts repositories describe "${FULL_ARTIFACT_REPOSITORY}" \
    --project="${FULL_PROJECT_ID}" --location="${FULL_REGION}" \
    --format='value(name)' >/dev/null 2>&1 && full_artifact="present"

  if [[ "${full_count}" == "0" && "${full_named_db}" == "absent" && "${full_cluster}" == "absent" \
    && "${full_control}" == "absent" && "${full_documents}" == "absent" ]]; then
    full_mode="DESTROYED"
  elif full_environment_complete && [[ "${full_cluster}" == "present" && "${full_control}" == "present" ]]; then
    full_mode="DEPLOYED"
  fi

  cat <<EOF
RoleCallAI full-environment status
  mode:                    ${full_mode}
  Terraform managed entries: ${full_count}
  named Firestore:         ${full_named_db}
  default Firestore:       ${full_default_location} (must remain ${FULL_DEFAULT_DATABASE_LOCATION})
  GKE cluster:             ${full_cluster}
  Cloud Run control/jobs:  ${full_control} / ${full_jobs}
  private document bucket: ${full_documents}
  Artifact Registry:       ${full_artifact}
EOF
}

full_cleanup() {
  local full_exit=$?
  trap - EXIT
  set +e
  if [[ "${FULL_OVERRIDE_INSTALLED}" == true ]]; then
    if [[ "${full_exit}" -ne 0 && "${FULL_PROTECTIONS_LOWERED}" == true \
      && "${FULL_DESTROY_STARTED}" == false ]]; then
      full_restore_protections
    else
      full_remove_override
    fi
  fi
  if [[ "${full_exit}" -ne 0 && "${FULL_FROZEN}" == true && "${FULL_DESTROY_STARTED}" == false ]]; then
    full_unfreeze
  fi
  if [[ "${full_exit}" -ne 0 ]]; then
    printf '[rolecall-full] FAILED during: %s\n' "${FULL_LAST_STEP}" >&2
    if [[ "${FULL_DESTROY_STARTED}" == true && "${FULL_DESTROY_COMPLETED}" == false ]]; then
      printf '[rolecall-full] Terraform destroy started and is incomplete. Inspect status and rerun destroy; do not run create.\n' >&2
    fi
  fi
  if [[ "${FULL_LOCK_ACQUIRED}" == true ]]; then
    unlink "${FULL_LOCK_DIR}/pid" >/dev/null 2>&1 || true
    rmdir "${FULL_LOCK_DIR}" >/dev/null 2>&1 || true
  fi
  exit "${full_exit}"
}

trap full_cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

[[ $# -ge 1 ]] || { full_usage; exit 2; }
FULL_ACTION="$1"
shift

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      FULL_DRY_RUN=true
      ;;
    --confirm-token)
      shift
      [[ $# -gt 0 ]] || full_die "--confirm-token requires a value."
      FULL_CONFIRM_TOKEN="$1"
      ;;
    -h|--help)
      full_usage
      exit 0
      ;;
    *) full_die "Unknown option: $1" ;;
  esac
  shift
done

case "${FULL_ACTION}" in
  status|destroy|create) ;;
  -h|--help) full_usage; exit 0 ;;
  *) full_die "Unknown command: ${FULL_ACTION}" ;;
esac

if [[ "${FULL_ACTION}" != "status" ]]; then
  full_acquire_lock
fi
full_prepare

case "${FULL_ACTION}" in
  status) full_status ;;
  destroy) full_destroy ;;
  create) full_create ;;
esac
