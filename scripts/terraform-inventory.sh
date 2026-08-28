#!/usr/bin/env bash
set -euo pipefail

PLAN_PATH="${1:-infra/terraform/rolecall-dev.tfplan}"
OUTPUT_PATH="${2:-infra/terraform/resource-inventory.txt}"
PLAN_DIR="$(cd "$(dirname "$PLAN_PATH")" && pwd)"
PLAN_FILE="$(basename "$PLAN_PATH")"

MANAGED_COUNT="$(terraform -chdir="$PLAN_DIR" state list | wc -l | tr -d ' ')"
CHANGE_LINES="$(
  terraform -chdir="$PLAN_DIR" show -json "$PLAN_FILE" \
    | jq -r '.resource_changes[] | select(.change.actions != ["no-op"]) | [.address, (.change.actions | join(","))] | @tsv' \
    | sort
)"
CHANGE_COUNT="$(printf '%s\n' "$CHANGE_LINES" | sed '/^$/d' | wc -l | tr -d ' ')"

{
  printf '# Terraform plan inventory generated %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  printf '# Managed resource instances in state: %s\n' "$MANAGED_COUNT"
  printf '# Pending resource changes: %s\n' "$CHANGE_COUNT"
  if [[ -n "$CHANGE_LINES" ]]; then
    printf '%s\n' "$CHANGE_LINES"
  fi
} > "$OUTPUT_PATH"

printf 'Wrote %s\n' "$OUTPUT_PATH"
