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
readonly RUNTIME_CONTROL_SERVICE="${ROLECALL_CONTROL_SERVICE:-rolecall-dev-control}"
readonly RUNTIME_CONTROL_URL="${ROLECALL_CONTROL_URL:-https://your-control-service.run.app}"
readonly RUNTIME_LIVEKIT_HOST="${ROLECALL_LIVEKIT_HOST:-livekit.your-ip.sslip.io}"
readonly RUNTIME_MEDIA_POOL="media"
readonly RUNTIME_WORKER_POOL="workers"
readonly RUNTIME_MEDIA_MIN_NODES="1"
readonly RUNTIME_MEDIA_MAX_NODES="3"
readonly RUNTIME_WORKER_MIN_NODES="2"
readonly RUNTIME_WORKER_MAX_NODES="6"
readonly RUNTIME_KUBE_CONTEXT="gke_${RUNTIME_PROJECT_ID}_${RUNTIME_ZONE}_${RUNTIME_CLUSTER}"
readonly RUNTIME_DRAIN_JOB="${RUNTIME_CLUSTER}-drain-outbox"
readonly RUNTIME_CLEANUP_JOB="${RUNTIME_CLUSTER}-retention-cleanup"

RUNTIME_DRY_RUN=false
RUNTIME_ASSUME_YES=false

runtime_usage() {
  cat <<'EOF'
Usage: scripts/dev-runtime.sh <status|down|up> [--dry-run] [--yes]

Commands:
  status     Read-only health, capacity, scheduler, and Firestore safety report.
  down       Safely suspend public access, schedulers, RoleCall pods, and GKE nodes.
  up         Restore the Terraform minimum topology and verify public readiness.

Options:
  --dry-run  Perform read-only preflight checks and print intended mutations.
  --yes      Skip the interactive confirmation for down/up.

The down command preserves Firestore, Memorystore Redis, Memory Bank, secrets,
reserved IPs, load balancers, networking, Artifact Registry, and the GKE control
plane. It never deletes data or infrastructure.

Copy .rolecall.local.env.example to .rolecall.local.env before cloud operations.
EOF
}

runtime_log() {
  printf '[rolecall-runtime] %s\n' "$*"
}

runtime_die() {
  printf '[rolecall-runtime] ERROR: %s\n' "$*" >&2
  exit 1
}

runtime_print_command() {
  printf '  +'
  printf ' %q' "$@"
  printf '\n'
}

runtime_run_mutation() {
  runtime_print_command "$@"
  if [[ "${RUNTIME_DRY_RUN}" == false ]]; then
    "$@"
  fi
}

runtime_require_command() {
  command -v "$1" >/dev/null 2>&1 || runtime_die "Required command is missing: $1"
}

runtime_prepare() {
  runtime_require_command gcloud
  runtime_require_command kubectl
  runtime_require_command uv
  runtime_require_command curl

  [[ "${RUNTIME_PROJECT_ID}" != "your-gcp-project-id" ]] || \
    runtime_die "Configure ${RUNTIME_CONFIG_FILE} from .rolecall.local.env.example."
  [[ "${RUNTIME_CONTROL_URL}" != *your-control-service* ]] || \
    runtime_die "Set ROLECALL_CONTROL_URL in ${RUNTIME_CONFIG_FILE}."
  [[ "${RUNTIME_LIVEKIT_HOST}" != *your-ip* ]] || \
    runtime_die "Set ROLECALL_LIVEKIT_HOST in ${RUNTIME_CONFIG_FILE}."

  local runtime_account
  runtime_account="$(gcloud auth list --filter='status:ACTIVE' --format='value(account)' | sed -n '1p')"
  [[ -n "${runtime_account}" ]] || runtime_die "No active gcloud account. Run: gcloud auth login"

  gcloud projects describe "${RUNTIME_PROJECT_ID}" --format='value(projectId)' >/dev/null
  gcloud container clusters describe "${RUNTIME_CLUSTER}" \
    --project "${RUNTIME_PROJECT_ID}" \
    --zone "${RUNTIME_ZONE}" \
    --format='value(name)' >/dev/null

  if ! kubectl config get-contexts "${RUNTIME_KUBE_CONTEXT}" >/dev/null 2>&1; then
    runtime_log "Adding the target GKE context to the local kubeconfig."
    gcloud container clusters get-credentials "${RUNTIME_CLUSTER}" \
      --project "${RUNTIME_PROJECT_ID}" \
      --zone "${RUNTIME_ZONE}" \
      --quiet >/dev/null
  fi
}

# An explicit short-lived access token avoids depending on the optional
# gke-gcloud-auth-plugin executable and is never printed by this script.
runtime_kube() {
  local runtime_access_token
  runtime_access_token="$(gcloud auth print-access-token)"
  kubectl \
    --context "${RUNTIME_KUBE_CONTEXT}" \
    --token "${runtime_access_token}" \
    "$@"
}

runtime_kube_mutation() {
  runtime_print_command kubectl --context "${RUNTIME_KUBE_CONTEXT}" "$@"
  if [[ "${RUNTIME_DRY_RUN}" == false ]]; then
    runtime_kube "$@"
  fi
}

runtime_guard() {
  (
    cd "${RUNTIME_AGENT_DIR}"
    uv run --frozen python "${RUNTIME_SCRIPT_DIR}/runtime_guard.py" \
      --project "${RUNTIME_PROJECT_ID}" \
      --database "${RUNTIME_DATABASE}"
  )
}

runtime_control_is_public() {
  local runtime_member
  runtime_member="$(
    gcloud run services get-iam-policy "${RUNTIME_CONTROL_SERVICE}" \
      --project "${RUNTIME_PROJECT_ID}" \
      --region "${RUNTIME_REGION}" \
      --flatten='bindings[].members' \
      --filter='bindings.role:roles/run.invoker AND bindings.members:allUsers' \
      --format='value(bindings.members)'
  )"
  [[ "${runtime_member}" == *allUsers* ]]
}

runtime_close_control() {
  if runtime_control_is_public; then
    runtime_run_mutation gcloud run services remove-iam-policy-binding \
      "${RUNTIME_CONTROL_SERVICE}" \
      --project "${RUNTIME_PROJECT_ID}" \
      --region "${RUNTIME_REGION}" \
      --member allUsers \
      --role roles/run.invoker \
      --quiet
  else
    runtime_log "Control service is already private."
  fi
}

runtime_open_control() {
  if [[ "${RUNTIME_DRY_RUN}" == true ]]; then
    runtime_run_mutation gcloud run services add-iam-policy-binding \
      "${RUNTIME_CONTROL_SERVICE}" \
      --project "${RUNTIME_PROJECT_ID}" \
      --region "${RUNTIME_REGION}" \
      --member allUsers \
      --role roles/run.invoker \
      --quiet
  elif runtime_control_is_public; then
    runtime_log "Control service is already public."
  else
    runtime_run_mutation gcloud run services add-iam-policy-binding \
      "${RUNTIME_CONTROL_SERVICE}" \
      --project "${RUNTIME_PROJECT_ID}" \
      --region "${RUNTIME_REGION}" \
      --member allUsers \
      --role roles/run.invoker \
      --quiet
  fi
}

runtime_scheduler_state() {
  gcloud scheduler jobs describe "$1" \
    --project "${RUNTIME_PROJECT_ID}" \
    --location "${RUNTIME_REGION}" \
    --format='value(state)'
}

runtime_pause_scheduler() {
  local runtime_job="$1"
  if [[ "$(runtime_scheduler_state "${runtime_job}")" == "PAUSED" ]]; then
    runtime_log "Scheduler ${runtime_job} is already paused."
  else
    runtime_run_mutation gcloud scheduler jobs pause "${runtime_job}" \
      --project "${RUNTIME_PROJECT_ID}" \
      --location "${RUNTIME_REGION}" \
      --quiet
  fi
}

runtime_resume_scheduler() {
  local runtime_job="$1"
  if [[ "${RUNTIME_DRY_RUN}" == true ]]; then
    runtime_run_mutation gcloud scheduler jobs resume "${runtime_job}" \
      --project "${RUNTIME_PROJECT_ID}" \
      --location "${RUNTIME_REGION}" \
      --quiet
  elif [[ "$(runtime_scheduler_state "${runtime_job}")" == "ENABLED" ]]; then
    runtime_log "Scheduler ${runtime_job} is already enabled."
  else
    runtime_run_mutation gcloud scheduler jobs resume "${runtime_job}" \
      --project "${RUNTIME_PROJECT_ID}" \
      --location "${RUNTIME_REGION}" \
      --quiet
  fi
}

runtime_confirm() {
  local runtime_action="$1"
  if [[ "${RUNTIME_DRY_RUN}" == true || "${RUNTIME_ASSUME_YES}" == true ]]; then
    return
  fi
  printf 'Type %s to confirm %s: ' "${RUNTIME_CLUSTER}" "${runtime_action}"
  local runtime_answer
  read -r runtime_answer
  [[ "${runtime_answer}" == "${RUNTIME_CLUSTER}" ]] || runtime_die "Confirmation did not match."
}

runtime_status() {
  local runtime_cluster_status runtime_node_count runtime_media_scale runtime_worker_scale
  local runtime_control_access runtime_drain_state runtime_cleanup_state
  local runtime_livekit_replicas="unavailable" runtime_worker_replicas="unavailable"
  local runtime_guard_output runtime_guard_exit=0 runtime_mode="PARTIAL"

  runtime_cluster_status="$(gcloud container clusters describe "${RUNTIME_CLUSTER}" \
    --project "${RUNTIME_PROJECT_ID}" --zone "${RUNTIME_ZONE}" --format='value(status)')"
  runtime_node_count="$(gcloud container clusters describe "${RUNTIME_CLUSTER}" \
    --project "${RUNTIME_PROJECT_ID}" --zone "${RUNTIME_ZONE}" --format='value(currentNodeCount)')"
  runtime_media_scale="$(gcloud container node-pools describe "${RUNTIME_MEDIA_POOL}" \
    --cluster "${RUNTIME_CLUSTER}" --project "${RUNTIME_PROJECT_ID}" --zone "${RUNTIME_ZONE}" \
    --format='value(autoscaling.enabled,autoscaling.minNodeCount,autoscaling.maxNodeCount)')"
  runtime_worker_scale="$(gcloud container node-pools describe "${RUNTIME_WORKER_POOL}" \
    --cluster "${RUNTIME_CLUSTER}" --project "${RUNTIME_PROJECT_ID}" --zone "${RUNTIME_ZONE}" \
    --format='value(autoscaling.enabled,autoscaling.minNodeCount,autoscaling.maxNodeCount)')"
  runtime_drain_state="$(runtime_scheduler_state "${RUNTIME_DRAIN_JOB}")"
  runtime_cleanup_state="$(runtime_scheduler_state "${RUNTIME_CLEANUP_JOB}")"
  if runtime_control_is_public; then
    runtime_control_access="PUBLIC"
  else
    runtime_control_access="PRIVATE"
  fi

  if runtime_livekit_replicas="$(runtime_kube -n rolecall get deployment livekit-server \
    -o jsonpath='{.spec.replicas}/{.status.readyReplicas}' 2>/dev/null)"; then
    runtime_livekit_replicas="${runtime_livekit_replicas:-0/0}"
  fi
  if runtime_worker_replicas="$(runtime_kube -n rolecall get deployment rolecall-worker \
    -o jsonpath='{.spec.replicas}/{.status.readyReplicas}' 2>/dev/null)"; then
    runtime_worker_replicas="${runtime_worker_replicas:-0/0}"
  fi

  if runtime_guard_output="$(runtime_guard 2>&1)"; then
    runtime_guard_exit=0
  else
    runtime_guard_exit=$?
  fi

  if [[ "${runtime_node_count}" == "0" && "${runtime_control_access}" == "PRIVATE" \
    && "${runtime_drain_state}" == "PAUSED" && "${runtime_cleanup_state}" == "PAUSED" ]]; then
    runtime_mode="SUSPENDED"
  elif [[ "${runtime_node_count}" -ge 3 && "${runtime_control_access}" == "PUBLIC" \
    && "${runtime_drain_state}" == "ENABLED" && "${runtime_cleanup_state}" == "ENABLED" ]]; then
    runtime_mode="RUNNING"
  fi

  cat <<EOF
RoleCallAI dev runtime
  mode:                 ${runtime_mode}
  project/region:       ${RUNTIME_PROJECT_ID} / ${RUNTIME_REGION}
  GKE cluster:          ${RUNTIME_CLUSTER} (${runtime_cluster_status})
  current GKE nodes:    ${runtime_node_count}
  media autoscaling:    ${runtime_media_scale}  [enabled min max]
  worker autoscaling:   ${runtime_worker_scale}  [enabled min max]
  LiveKit replicas:     ${runtime_livekit_replicas}  [desired/ready]
  worker replicas:      ${runtime_worker_replicas}  [desired/ready]
  control access:       ${runtime_control_access}
  drain scheduler:      ${runtime_drain_state}
  cleanup scheduler:    ${runtime_cleanup_state}
  Firestore guard:      ${runtime_guard_output}
EOF

  if [[ "${runtime_guard_exit}" -eq 2 ]]; then
    runtime_log "Firestore guard could not authenticate. Run: gcloud auth application-default login"
  fi
}

runtime_down() {
  local runtime_initial_public=false
  local runtime_drain_was_enabled=false
  local runtime_cleanup_was_enabled=false

  runtime_log "Checking Firestore for active meetings and unpublished outbox work."
  runtime_guard || runtime_die "Suspend refused. Finish active/processing meetings and drain the outbox first."
  runtime_confirm "suspending the dev environment"

  if runtime_control_is_public; then
    runtime_initial_public=true
  fi
  if [[ "$(runtime_scheduler_state "${RUNTIME_DRAIN_JOB}")" == "ENABLED" ]]; then
    runtime_drain_was_enabled=true
  fi
  if [[ "$(runtime_scheduler_state "${RUNTIME_CLEANUP_JOB}")" == "ENABLED" ]]; then
    runtime_cleanup_was_enabled=true
  fi

  runtime_log "Freezing new public requests and scheduled work."
  runtime_close_control
  runtime_pause_scheduler "${RUNTIME_DRAIN_JOB}"
  runtime_pause_scheduler "${RUNTIME_CLEANUP_JOB}"

  if [[ "${RUNTIME_DRY_RUN}" == false ]]; then
    runtime_log "Rechecking durable state after the request freeze."
    if ! runtime_guard; then
      runtime_log "New work appeared during the freeze; restoring access and schedulers."
      if [[ "${runtime_initial_public}" == true ]]; then
        runtime_open_control
      fi
      if [[ "${runtime_drain_was_enabled}" == true ]]; then
        runtime_resume_scheduler "${RUNTIME_DRAIN_JOB}"
      fi
      if [[ "${runtime_cleanup_was_enabled}" == true ]]; then
        runtime_resume_scheduler "${RUNTIME_CLEANUP_JOB}"
      fi
      runtime_die "Suspend refused by the second Firestore safety check."
    fi
  fi

  runtime_log "Disabling GKE node-pool autoscaling."
  runtime_run_mutation gcloud container node-pools update "${RUNTIME_MEDIA_POOL}" \
    --cluster "${RUNTIME_CLUSTER}" --project "${RUNTIME_PROJECT_ID}" --zone "${RUNTIME_ZONE}" \
    --no-enable-autoscaling --quiet
  runtime_run_mutation gcloud container node-pools update "${RUNTIME_WORKER_POOL}" \
    --cluster "${RUNTIME_CLUSTER}" --project "${RUNTIME_PROJECT_ID}" --zone "${RUNTIME_ZONE}" \
    --no-enable-autoscaling --quiet

  runtime_log "Stopping the RoleCall worker and LiveKit deployments."
  runtime_kube_mutation -n rolecall scale deployment rolecall-worker --replicas=0
  runtime_kube_mutation -n rolecall scale deployment livekit-server --replicas=0
  if [[ "${RUNTIME_DRY_RUN}" == false ]]; then
    runtime_kube -n rolecall wait --for=delete pod \
      --selector='app.kubernetes.io/name=rolecall-worker' --timeout=300s
    runtime_kube -n rolecall wait --for=delete pod \
      --selector='app.kubernetes.io/name=livekit-server' --timeout=300s
  fi

  runtime_log "Scaling both GKE node pools to zero. This can take several minutes."
  runtime_run_mutation gcloud container clusters resize "${RUNTIME_CLUSTER}" \
    --node-pool "${RUNTIME_MEDIA_POOL}" --num-nodes 0 \
    --project "${RUNTIME_PROJECT_ID}" --zone "${RUNTIME_ZONE}" --quiet
  runtime_run_mutation gcloud container clusters resize "${RUNTIME_CLUSTER}" \
    --node-pool "${RUNTIME_WORKER_POOL}" --num-nodes 0 \
    --project "${RUNTIME_PROJECT_ID}" --zone "${RUNTIME_ZONE}" --quiet

  if [[ "${RUNTIME_DRY_RUN}" == true ]]; then
    runtime_log "Dry run complete; no cloud resources were changed."
  else
    runtime_log "Suspend complete. Data services remain intact; meeting URLs are unavailable."
    runtime_status
  fi
}

runtime_wait_for_platform() {
  runtime_kube wait --for=condition=Ready nodes \
    --selector="cloud.google.com/gke-nodepool=${RUNTIME_WORKER_POOL}" --timeout=900s
  runtime_kube wait --for=condition=Ready nodes \
    --selector="cloud.google.com/gke-nodepool=${RUNTIME_MEDIA_POOL}" --timeout=900s

  runtime_kube -n cert-manager rollout status deployment/cert-manager --timeout=600s
  runtime_kube -n cert-manager rollout status deployment/cert-manager-cainjector --timeout=600s
  runtime_kube -n cert-manager rollout status deployment/cert-manager-webhook --timeout=600s
  runtime_kube -n ingress-signal rollout status \
    deployment/ingress-signal-ingress-nginx-controller --timeout=600s
  runtime_kube -n ingress-turn rollout status \
    deployment/ingress-turn-ingress-nginx-controller --timeout=600s
}

runtime_up() {
  runtime_confirm "restoring the dev environment"

  runtime_log "Keeping public and scheduled work paused until the meeting stack is healthy."
  runtime_close_control
  runtime_pause_scheduler "${RUNTIME_DRAIN_JOB}"
  runtime_pause_scheduler "${RUNTIME_CLEANUP_JOB}"

  runtime_log "Restoring the three-node Terraform minimum. This can take 10-20 minutes."
  runtime_run_mutation gcloud container clusters resize "${RUNTIME_CLUSTER}" \
    --node-pool "${RUNTIME_WORKER_POOL}" --num-nodes "${RUNTIME_WORKER_MIN_NODES}" \
    --project "${RUNTIME_PROJECT_ID}" --zone "${RUNTIME_ZONE}" --quiet
  runtime_run_mutation gcloud container clusters resize "${RUNTIME_CLUSTER}" \
    --node-pool "${RUNTIME_MEDIA_POOL}" --num-nodes "${RUNTIME_MEDIA_MIN_NODES}" \
    --project "${RUNTIME_PROJECT_ID}" --zone "${RUNTIME_ZONE}" --quiet

  runtime_log "Restoring node-pool autoscaling limits."
  runtime_run_mutation gcloud container node-pools update "${RUNTIME_WORKER_POOL}" \
    --cluster "${RUNTIME_CLUSTER}" --project "${RUNTIME_PROJECT_ID}" --zone "${RUNTIME_ZONE}" \
    --enable-autoscaling --min-nodes "${RUNTIME_WORKER_MIN_NODES}" \
    --max-nodes "${RUNTIME_WORKER_MAX_NODES}" --location-policy BALANCED --quiet
  runtime_run_mutation gcloud container node-pools update "${RUNTIME_MEDIA_POOL}" \
    --cluster "${RUNTIME_CLUSTER}" --project "${RUNTIME_PROJECT_ID}" --zone "${RUNTIME_ZONE}" \
    --enable-autoscaling --min-nodes "${RUNTIME_MEDIA_MIN_NODES}" \
    --max-nodes "${RUNTIME_MEDIA_MAX_NODES}" --location-policy BALANCED --quiet

  if [[ "${RUNTIME_DRY_RUN}" == false ]]; then
    runtime_log "Waiting for GKE platform pods."
    runtime_wait_for_platform
  fi

  runtime_log "Restoring LiveKit and the ADK workers."
  runtime_kube_mutation -n rolecall scale deployment livekit-server \
    --replicas="${RUNTIME_MEDIA_MIN_NODES}"
  runtime_kube_mutation -n rolecall scale deployment rolecall-worker --replicas=2
  if [[ "${RUNTIME_DRY_RUN}" == false ]]; then
    runtime_kube -n rolecall rollout status deployment/livekit-server --timeout=900s
    runtime_kube -n rolecall rollout status deployment/rolecall-worker --timeout=900s
    runtime_kube -n rolecall wait --for=condition=Ready certificate/livekit-signaling --timeout=600s
    runtime_kube -n rolecall wait --for=condition=Ready certificate/livekit-turn --timeout=600s
  fi

  runtime_log "Restoring public access and scheduled maintenance."
  runtime_open_control
  runtime_resume_scheduler "${RUNTIME_DRAIN_JOB}"
  runtime_resume_scheduler "${RUNTIME_CLEANUP_JOB}"

  if [[ "${RUNTIME_DRY_RUN}" == true ]]; then
    runtime_log "Dry run complete; no cloud resources were changed."
  else
    runtime_log "Checking the web control plane and LiveKit TLS endpoint."
    curl --fail --silent --show-error --max-time 30 "${RUNTIME_CONTROL_URL}/readyz" >/dev/null
    curl --silent --show-error --output /dev/null --max-time 30 \
      "https://${RUNTIME_LIVEKIT_HOST}/"
    runtime_log "Resume complete."
    runtime_status
  fi
}

runtime_on_error() {
  local runtime_line="$1"
  printf '[rolecall-runtime] ERROR: command failed near line %s. Run status, then rerun up or down; operations are idempotent.\n' \
    "${runtime_line}" >&2
}

trap 'runtime_on_error ${LINENO}' ERR

[[ $# -ge 1 ]] || { runtime_usage; exit 2; }
RUNTIME_COMMAND="$1"
shift

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) RUNTIME_DRY_RUN=true ;;
    --yes) RUNTIME_ASSUME_YES=true ;;
    -h|--help) runtime_usage; exit 0 ;;
    *) runtime_die "Unknown option: $1" ;;
  esac
  shift
done

case "${RUNTIME_COMMAND}" in
  status|down|up) ;;
  -h|--help) runtime_usage; exit 0 ;;
  *) runtime_die "Unknown command: ${RUNTIME_COMMAND}" ;;
esac

runtime_prepare

case "${RUNTIME_COMMAND}" in
  status) runtime_status ;;
  down) runtime_down ;;
  up) runtime_up ;;
esac
