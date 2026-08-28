# Development suspend and resume runbook

The local operator script provides a reversible, data-preserving way to stop the
expensive meeting runtime when it is not in use.

This is the right workflow for a short pause. For a permanent teardown that also
deletes Redis, GKE, load balancers, stored meeting data, images, and secrets, use
the separately guarded [full teardown/recreate runbook](FULL_TEARDOWN.md).

## Prerequisites

- `gcloud`, `kubectl`, `uv`, and `curl` are installed.
- Your active `gcloud` identity can administer the RoleCallAI dev resources.
- Application Default Credentials can read the named Firestore database.

Authenticate once if needed:

```bash
gcloud auth login
gcloud auth application-default login
```

For destructive-action safety, the script reads project and endpoint coordinates
from the ignored `.rolecall.local.env`. It remains pinned to the configured
region, zone, cluster, and named Firestore database and refuses to inspect
`(default)`.

```bash
cp .rolecall.local.env.example .rolecall.local.env
```

## Commands

Run these from the repository root:

```bash
# Read-only report
make runtime-status

# Preview every mutation; this does not stop anything
./scripts/dev-runtime.sh down --dry-run --yes

# Suspend; requires typing rolecall-dev unless --yes is supplied
make runtime-down

# Restore and run readiness checks
make runtime-up
```

Automated local use may call `./scripts/dev-runtime.sh down --yes` and
`./scripts/dev-runtime.sh up --yes`. Each operation is idempotent: if it is
interrupted, inspect with `status` and rerun the intended command.

## What `down` does

1. Reads only aggregate-safe Firestore state and refuses to proceed if any
   occurrence is in `LOBBY`, `STARTING`, `RUNNING`, `ENDING`, or `PROCESSING`, or
   if the transactional outbox has unpublished work.
2. Removes the public Cloud Run invoker binding so no participant can arrive in
   the middle of shutdown, then pauses both Scheduler jobs.
3. Repeats the Firestore guard. If new work appeared, it restores the access and
   scheduler state and exits.
4. Disables autoscaling for both node pools, scales the LiveKit and worker
   Deployments to zero, and resizes the media and worker pools to zero nodes.

No room, transcript, recap, capability, secret, IP address, image, or memory is
deleted.

## What remains and why

| Retained resource | Reason | Idle cost characteristic |
| --- | --- | --- |
| Named Firestore database | Preserves rooms, links, history, and recap data. | Operations/storage based; low at dev volume. |
| Memorystore Redis Basic | Google provides no stop/start action; deleting it is destructive and changes its private IP. | About $37/month in the current estimate. |
| GKE control plane | Keeps the cluster and Terraform/Helm state recoverable. | $0-$73/month depending on the billing-account GKE credit. |
| Load balancers and reserved IPs | Preserve the disposable LiveKit/TURN hostnames and certificates. | Forwarding-rule/IP charges continue. |
| VPC, NAT gateway, secrets, Artifact Registry, Pub/Sub, Memory Bank | Preserve networking, credentials, images, queues, and retained memory. | Mostly low fixed or usage-based charges. |
| Cloud Run services | Both are configured with minimum instances `0`; public control access is removed and schedulers are paused. | Zero compute while uninvoked; stored images remain. |

Using the current cost model, suspending removes roughly **$345/month** of VM,
boot-disk, and assigned-node NAT run rate. The residual is approximately
**$60-$135/month plus low-volume storage/operations**, chiefly Redis, public
edge resources, and possibly the GKE management fee. These are planning numbers,
not a billing guarantee.

The full teardown workflow can remove the GKE cluster, Redis, load balancers,
and all other RoleCallAI resources. It is separate because it permanently loses
meeting data and produces new endpoints and credentials when recreated.

## What `up` does

1. Keeps schedulers paused while infrastructure starts.
2. Restores two worker nodes and one media node.
3. Restores worker autoscaling `2-6` and media autoscaling `1-3`.
4. Waits for ingress-nginx and cert-manager, then restores one LiveKit pod and
   two ADK worker pods.
5. Waits for both certificates, restores public access and Scheduler, and probes
   the Cloud Run `/readyz` endpoint and LiveKit TLS endpoint.

Startup normally takes 10-20 minutes. If the environment remains suspended into
a certificate renewal window, cert-manager renews after resume and startup may
take longer.

## Important Terraform rule

`down` intentionally creates temporary Terraform drift by setting node counts
and node-pool autoscaling to zero and removing public Cloud Run access. Do not run
`terraform apply` while the environment is suspended. Run `make runtime-up`
first; it restores the values declared in Terraform, after which a plan should
again be empty.

Google documents that Cloud Run services with no minimum instances can scale to
zero, while a Standard GKE cluster does not automatically scale the whole cluster
to zero. The explicit node-pool resize is therefore necessary:

- [Cloud Run instance autoscaling](https://docs.cloud.google.com/run/docs/about-instance-autoscaling)
- [GKE cluster autoscaler behavior](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/cluster-autoscaler)
- [GKE resize command](https://docs.cloud.google.com/sdk/gcloud/reference/container/clusters/resize)
- [Memorystore instance management](https://docs.cloud.google.com/memorystore/docs/redis/create-manage-instances)
