# RoleCallAI development infrastructure

This stack uses the project supplied in the ignored `vars/dev.tfvars`, and is
intentionally pinned to `europe-west4`, the Vertex AI `eu` multi-region endpoint
for Gemini 3.7 inference, and the named Firestore Native database
`rolecall-dev`. No resource references or imports the existing `(default)`
database.

It plans the complete development topology: named regional Firestore, Cloud Run control/jobs, Pub/Sub push and dead letters, Agent Engine Sessions/Memory Bank, zonal public GKE Standard, dedicated LiveKit media nodes, general worker nodes, fixed `sslip.io` WSS/TURN IPs, certificates, monitoring, and retention backstops.

## Approval-gated sequence

1. Run `make terraform-validate`.
2. Run `make terraform-plan` and generate the inventory with `./scripts/terraform-inventory.sh`.
3. Review `rolecall-dev.tfplan`, `resource-inventory.txt`, and `COST_ESTIMATE.md`.
4. Stop and obtain explicit approval.
5. After approval only, bootstrap APIs and Artifact Registry, run the manual Cloud Build command from the Terraform output, and then apply the reviewed full plan. A plan must be regenerated if any input or image tag changes.

Terraform state contains generated development secret material even though Secret Manager is the runtime source of truth. Keep state local, encrypted, and uncommitted. Before apply, verify the ACME contact in `vars/dev.tfvars`.

Start from the committed template:

```bash
cp vars/dev.tfvars.example vars/dev.tfvars
```

## Full teardown and recreation

Do not invoke a raw `terraform destroy`. The named Firestore database and GKE
cluster intentionally have deletion protection, and recreation requires images
to be rebuilt after Artifact Registry is restored. Use the repository wrapper:

```bash
make environment-status
./scripts/full-environment.sh destroy --dry-run
make environment-destroy
make environment-create
```

The wrapper checks the unrelated `(default)` Firestore location, refuses to
delete while meetings or outbox work remain, temporarily lowers only the two
deletion protections, applies saved plans, bootstraps Artifact Registry before
rebuilding images, and verifies a no-op Terraform plan after recreation. The
complete boundary and partial-failure procedure are in
[`docs/FULL_TEARDOWN.md`](../../docs/FULL_TEARDOWN.md).
