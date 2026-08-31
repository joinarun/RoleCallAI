# RoleCallAI development infrastructure

This stack uses the project supplied in the ignored `vars/dev.tfvars`, and is
intentionally pinned to `europe-west4`, the Vertex AI `eu` multi-region endpoint
for Gemini 3.7 inference, and the named Firestore Native database
`rolecall-dev`. No resource references or imports the existing `(default)`
database.

It plans the complete development topology: named regional Firestore with vector
indexes, private document storage, Cloud KMS, reCAPTCHA, Cloud Run control/jobs
and runtime Jobs, Pub/Sub push/dead letters, Agent Platform Memory Bank, zonal
public GKE Standard, dedicated LiveKit media nodes, ephemeral in-cluster Redis,
fixed `sslip.io` WSS/TURN IPs, certificates, monitoring, and retention backstops.

## Approval-gated sequence

1. Run `make terraform-validate`.
2. Run `make terraform-plan` and generate the inventory with `./scripts/terraform-inventory.sh`.
3. Review `rolecall-dev.tfplan`, `resource-inventory.txt`, and `COST_ESTIMATE.md`.
4. Stop and obtain explicit approval.
5. After approval only, bootstrap APIs and Artifact Registry, run the manual
   Cloud Build command from the Terraform output, and then apply the reviewed
   full plan. A plan must be regenerated if any input or image tag changes.
6. Before rotating legacy links, export `rolecall-dev`, confirm every room is
   idle, generate the shared admin credential in a trusted terminal, and run the
   count-only migration. Never capture plaintext credentials or links in logs.

Terraform state contains generated development secret material even though
Secret Manager is the runtime source of truth. Keep state, saved plans and
variable files local, encrypted, and uncommitted. Before apply, verify the ACME
contact in `vars/dev.tfvars`.

The committed conservative defaults use `e2-standard-2` for both node pools,
250m CPU / 2 GiB ADK worker scheduling requests, and unchanged 2 vCPU / 4 GiB
worker limits. Machine types and worker requests are explicit variables in the
example tfvars so a later production profile can be raised without rewriting
the Helm release.

`runtime_job_image_tag` may be set independently when only the sleep/wake job
implementation changes. Leaving it empty keeps the lifecycle jobs on
`image_tag`; using a separate immutable tag avoids restarting the web, async or
meeting-worker releases for an operations-only fix.

The last applied release, live revision identifiers, migration counts and
acceptance evidence are recorded in
[`docs/DEPLOYMENT.md`](../../docs/DEPLOYMENT.md). Because runtime sleep creates
intentional reversible drift, wake the voice plane before generating a normal
Terraform convergence plan.

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
delete while meetings or outbox work remain, temporarily lowers only the
Firestore/KMS/Secret/GCS lifecycle protections, applies saved plans, bootstraps
Artifact Registry before rebuilding images, and verifies a no-op Terraform plan
after recreation. The complete boundary and partial-failure procedure are in
[`docs/FULL_TEARDOWN.md`](../../docs/FULL_TEARDOWN.md).
