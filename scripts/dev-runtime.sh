#!/usr/bin/env bash

set -Eeuo pipefail

readonly RUNTIME_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly RUNTIME_REPO_ROOT="$(cd "${RUNTIME_SCRIPT_DIR}/.." && pwd)"
readonly RUNTIME_AGENT_DIR="${RUNTIME_REPO_ROOT}/services/rolecall-agent"
readonly RUNTIME_CONFIG_FILE="${ROLECALL_CONFIG_FILE:-${RUNTIME_REPO_ROOT}/.rolecall.local.env}"

if [[ -f "${RUNTIME_CONFIG_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${RUNTIME_CONFIG_FILE}"
fi

readonly RUNTIME_PROJECT_ID="${ROLECALL_GCP_PROJECT_ID:-your-gcp-project-id}"
readonly RUNTIME_REGION="${ROLECALL_GCP_REGION:-europe-west4}"
readonly RUNTIME_ZONE="${ROLECALL_GCP_ZONE:-europe-west4-a}"
readonly RUNTIME_CLUSTER="${ROLECALL_GKE_CLUSTER:-rolecall-dev}"
readonly RUNTIME_DATABASE="${ROLECALL_FIRESTORE_DATABASE:-rolecall-dev}"
readonly RUNTIME_WAKE_JOB="${ROLECALL_RUNTIME_WAKE_JOB:-${RUNTIME_CLUSTER}-runtime-wake}"
readonly RUNTIME_SUSPEND_JOB="${ROLECALL_RUNTIME_SUSPEND_JOB:-${RUNTIME_CLUSTER}-runtime-suspend}"
readonly RUNTIME_IDLE_SCHEDULER_JOB="${ROLECALL_RUNTIME_IDLE_SCHEDULER_JOB:-${RUNTIME_CLUSTER}-runtime-idle-check}"

RUNTIME_DRY_RUN=false
RUNTIME_ASSUME_YES=false
RUNTIME_IDLE_SCHEDULER_WAS_ENABLED=false

runtime_usage() {
  cat <<'EOF'
Usage: scripts/dev-runtime.sh <status|down|up> [--dry-run] [--yes]

  status  Show durable runtime state, GKE node pools and recent transition jobs.
  down    Guard against active meetings, then run the Cloud Run suspend job.
  up      Run the Cloud Run wake job and wait for end-to-end readiness.

The Cloud Run web/admin service and schedulers remain available. Down removes
the LiveKit/TURN load balancers and scales Redis, LiveKit, workers and both GKE
node pools to zero. Firestore, GCS, KMS, secrets, reserved IPs, Artifact Registry
and the GKE control plane remain billable at their low idle rates.
EOF
}

runtime_die() { printf '[rolecall-runtime] ERROR: %s\n' "$*" >&2; exit 1; }
runtime_log() { printf '[rolecall-runtime] %s\n' "$*"; }

runtime_require() {
  command -v "$1" >/dev/null 2>&1 || runtime_die "Required command is missing: $1"
}

runtime_prepare() {
  runtime_require gcloud
  runtime_require uv
  [[ "${RUNTIME_PROJECT_ID}" != "your-gcp-project-id" ]] || \
    runtime_die "Configure ${RUNTIME_CONFIG_FILE} from .rolecall.local.env.example."
  [[ "${RUNTIME_DATABASE}" != "(default)" ]] || runtime_die "The default Firestore database is forbidden."
  gcloud projects describe "${RUNTIME_PROJECT_ID}" --format='value(projectId)' >/dev/null
}

runtime_confirm() {
  local action="$1"
  if [[ "${RUNTIME_DRY_RUN}" == true || "${RUNTIME_ASSUME_YES}" == true ]]; then return; fi
  printf 'Type %s to confirm %s: ' "${RUNTIME_CLUSTER}" "${action}"
  local answer
  read -r answer
  [[ "${answer}" == "${RUNTIME_CLUSTER}" ]] || runtime_die "Confirmation did not match."
}

runtime_operation() {
  local action="$1"
  (
    cd "${RUNTIME_AGENT_DIR}"
    uv run --frozen python "${RUNTIME_SCRIPT_DIR}/runtime-operation.py" "${action}" \
      --project "${RUNTIME_PROJECT_ID}" --database "${RUNTIME_DATABASE}"
  )
}

runtime_pause_idle_scheduler() {
  local state
  state="$(gcloud scheduler jobs describe "${RUNTIME_IDLE_SCHEDULER_JOB}" \
    --project "${RUNTIME_PROJECT_ID}" --location "${RUNTIME_REGION}" \
    --format='value(state)')"
  if [[ "${state}" == "ENABLED" ]]; then
    runtime_log "Pausing ${RUNTIME_IDLE_SCHEDULER_JOB} during the manual transition."
    gcloud scheduler jobs pause "${RUNTIME_IDLE_SCHEDULER_JOB}" \
      --project "${RUNTIME_PROJECT_ID}" --location "${RUNTIME_REGION}" --quiet
    RUNTIME_IDLE_SCHEDULER_WAS_ENABLED=true
  fi
}

runtime_resume_idle_scheduler() {
  if [[ "${RUNTIME_IDLE_SCHEDULER_WAS_ENABLED}" == true ]]; then
    runtime_log "Resuming ${RUNTIME_IDLE_SCHEDULER_JOB}."
    gcloud scheduler jobs resume "${RUNTIME_IDLE_SCHEDULER_JOB}" \
      --project "${RUNTIME_PROJECT_ID}" --location "${RUNTIME_REGION}" --quiet
    RUNTIME_IDLE_SCHEDULER_WAS_ENABLED=false
  fi
}

runtime_execute() {
  local action="$1" job operation operation_status execution_status
  job="${RUNTIME_WAKE_JOB}"
  [[ "${action}" == "wake" ]] || job="${RUNTIME_SUSPEND_JOB}"
  if [[ "${RUNTIME_DRY_RUN}" == true ]]; then
    runtime_log "Would pause ${RUNTIME_IDLE_SCHEDULER_JOB}, create a guarded ${action} operation, execute Cloud Run Job ${job}, then resume the Scheduler."
    return
  fi
  runtime_pause_idle_scheduler
  set +e
  operation="$(runtime_operation "${action}")"
  operation_status=$?
  set -e
  if [[ ${operation_status} -ne 0 ]]; then
    runtime_resume_idle_scheduler
    return "${operation_status}"
  fi
  if [[ "${operation}" == already:* ]]; then
    runtime_log "Runtime is ${operation#already:}; no transition is needed."
    runtime_resume_idle_scheduler
    return
  fi
  runtime_log "Executing ${job}; this can take up to 20 minutes."
  set +e
  gcloud run jobs execute "${job}" \
    --project "${RUNTIME_PROJECT_ID}" \
    --region "${RUNTIME_REGION}" \
    --update-env-vars "ROLECALL_RUNTIME_OPERATION_ID=${operation}" \
    --wait --quiet
  execution_status=$?
  set -e
  runtime_resume_idle_scheduler
  return "${execution_status}"
}

runtime_status() {
  local media_nodes worker_nodes
  media_nodes="$(gcloud container node-pools describe media --cluster "${RUNTIME_CLUSTER}" --project "${RUNTIME_PROJECT_ID}" --zone "${RUNTIME_ZONE}" --format='value(status,autoscaling.enabled,autoscaling.minNodeCount,autoscaling.maxNodeCount,initialNodeCount)' 2>/dev/null || printf 'missing')"
  worker_nodes="$(gcloud container node-pools describe workers --cluster "${RUNTIME_CLUSTER}" --project "${RUNTIME_PROJECT_ID}" --zone "${RUNTIME_ZONE}" --format='value(status,autoscaling.enabled,autoscaling.minNodeCount,autoscaling.maxNodeCount,initialNodeCount)' 2>/dev/null || printf 'missing')"
  printf 'RoleCallAI voice runtime\n'
  printf '  project:       %s\n' "${RUNTIME_PROJECT_ID}"
  printf '  cluster:       %s / %s\n' "${RUNTIME_CLUSTER}" "${RUNTIME_ZONE}"
  printf '  media pool:    %s\n' "${media_nodes}"
  printf '  worker pool:   %s\n' "${worker_nodes}"
  gcloud run jobs executions list --project "${RUNTIME_PROJECT_ID}" --region "${RUNTIME_REGION}" \
    --filter="metadata.name~'${RUNTIME_CLUSTER}-runtime'" --limit=4 \
    --format='table(metadata.name,status.conditions[0].type,status.startTime,status.completionTime)' || true
}

main() {
  [[ $# -ge 1 ]] || { runtime_usage; exit 2; }
  local action="$1"; shift
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run) RUNTIME_DRY_RUN=true ;;
      --yes) RUNTIME_ASSUME_YES=true ;;
      -h|--help) runtime_usage; exit 0 ;;
      *) runtime_die "Unknown option: $1" ;;
    esac
    shift
  done
  runtime_prepare
  case "${action}" in
    status) runtime_status ;;
    down) runtime_confirm down; runtime_execute suspend ;;
    up) runtime_confirm up; runtime_execute wake ;;
    *) runtime_usage; exit 2 ;;
  esac
}

main "$@"
