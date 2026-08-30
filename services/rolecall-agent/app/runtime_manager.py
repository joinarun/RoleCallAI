"""Cloud Run Job entry point that suspends and restores the GKE voice plane."""

from __future__ import annotations

import base64
import logging
import os
import time
from collections.abc import Callable

import google.auth
from google.auth.transport.requests import AuthorizedSession
from google.auth.transport.requests import Request as AuthRequest
from google.cloud import container_v1
from kubernetes import client
from kubernetes.client.exceptions import ApiException

from app.config import get_settings
from app.domain.enums import RuntimeStatus
from app.services.runtime import RuntimeService
from app.storage.factory import get_repository

logger = logging.getLogger(__name__)

DEPLOYMENTS = {
    "rolecall": {"rolecall-redis": 1, "livekit-server": 1, "rolecall-worker": 2},
    "cert-manager": {
        "cert-manager": 1,
        "cert-manager-cainjector": 1,
        "cert-manager-webhook": 1,
    },
    "ingress-signal": {"ingress-signal-ingress-nginx-controller": 1},
    "ingress-turn": {"ingress-turn-ingress-nginx-controller": 1},
}
INGRESS_SERVICES = {
    "ingress-signal": "ingress-signal-ingress-nginx-controller",
    "ingress-turn": "ingress-turn-ingress-nginx-controller",
}


def _kubernetes_clients(settings):  # type: ignore[no-untyped-def]
    manager = container_v1.ClusterManagerClient()
    name = f"projects/{settings.project_id}/locations/{settings.gke_zone}/clusters/{settings.gke_cluster}"
    cluster = manager.get_cluster(name=name)
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(AuthRequest())
    configuration = client.Configuration()
    configuration.host = f"https://{cluster.endpoint}"
    configuration.api_key = {"authorization": f"Bearer {credentials.token}"}
    configuration.ssl_ca_cert = _write_ca(cluster.master_auth.cluster_ca_certificate)
    api_client = client.ApiClient(configuration)
    return (
        client.AppsV1Api(api_client),
        client.CoreV1Api(api_client),
        client.AutoscalingV2Api(api_client),
        client.PolicyV1Api(api_client),
    )


def _write_ca(encoded: str) -> str:
    path = "/tmp/rolecall-gke-ca.crt"
    with open(path, "wb") as handle:
        handle.write(base64.b64decode(encoded))
    return path


def _gke_post(settings, pool: str, method: str, payload: dict[str, object]) -> None:  # type: ignore[no-untyped-def]
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    session = AuthorizedSession(credentials)
    base = (
        f"https://container.googleapis.com/v1/projects/{settings.project_id}/zones/"
        f"{settings.gke_zone}/clusters/{settings.gke_cluster}/nodePools/{pool}"
    )
    response = session.post(f"{base}/{method}", json=payload, timeout=60)
    response.raise_for_status()
    operation = response.json()
    operation_name = str(operation.get("name", ""))
    if not operation_name:
        return
    operation_url = (
        f"https://container.googleapis.com/v1/projects/{settings.project_id}/zones/"
        f"{settings.gke_zone}/operations/{operation_name}"
    )
    _wait_until(
        lambda: _operation_done(session, operation_url),
        600,
        f"GKE node-pool operation {method} did not finish",
    )


def _operation_done(session: AuthorizedSession, url: str) -> bool:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    operation = response.json()
    if operation.get("status") != "DONE":
        return False
    if operation.get("error"):
        raise RuntimeError("GKE node-pool operation failed")
    return True


def _set_pool_size(settings, pool: str, count: int) -> None:  # type: ignore[no-untyped-def]
    _gke_post(settings, pool, "setSize", {"nodeCount": count})


def _set_pool_autoscaling(
    settings,
    pool: str,
    enabled: bool,
    minimum: int,
    maximum: int,  # type: ignore[no-untyped-def]
) -> None:
    autoscaling: dict[str, object] = {"enabled": enabled}
    if enabled:
        autoscaling.update(
            {
                "minNodeCount": minimum,
                "maxNodeCount": maximum,
                "locationPolicy": "BALANCED",
            }
        )
    _gke_post(settings, pool, "setAutoscaling", {"autoscaling": autoscaling})


def _wait_until(predicate: Callable[[], bool], timeout: int, message: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(5)
    raise TimeoutError(message)


def _scale(apps: client.AppsV1Api, namespace: str, name: str, replicas: int) -> None:
    try:
        apps.patch_namespaced_deployment_scale(name, namespace, {"spec": {"replicas": replicas}})
    except ApiException as exc:
        if exc.status != 404:
            raise


def _deployment_ready(apps: client.AppsV1Api, namespace: str, name: str, replicas: int) -> bool:
    try:
        value = apps.read_namespaced_deployment_status(name, namespace)
    except ApiException as exc:
        if exc.status == 404:
            return replicas == 0
        raise
    ready = int(value.status.ready_replicas or 0)
    available = int(value.status.available_replicas or 0)
    if replicas == 0:
        return ready == 0 and available == 0
    return ready >= replicas and available >= replicas


def _ready_node_count(core: client.CoreV1Api, pool: str) -> int:
    count = 0
    for node in core.list_node(label_selector=f"cloud.google.com/gke-nodepool={pool}").items:
        if any(
            condition.type == "Ready" and condition.status == "True"
            for condition in (node.status.conditions or [])
        ):
            count += 1
    return count


def _service_has_load_balancer(core: client.CoreV1Api, namespace: str, service_name: str) -> bool:
    service = core.read_namespaced_service_status(service_name, namespace)
    ingress = service.status.load_balancer.ingress or []
    return bool(ingress)


def _service_has_ready_endpoints(core: client.CoreV1Api, namespace: str, service_name: str) -> bool:
    endpoints = core.read_namespaced_endpoints(service_name, namespace)
    return any(subset.addresses for subset in (endpoints.subsets or []))


def _delete_runtime_guards(
    autoscaling: client.AutoscalingV2Api, policy: client.PolicyV1Api
) -> None:
    for name in ("rolecall-worker", "livekit-server"):
        try:
            autoscaling.delete_namespaced_horizontal_pod_autoscaler(name, "rolecall")
        except ApiException as exc:
            if exc.status != 404:
                raise
        try:
            policy.delete_namespaced_pod_disruption_budget(name, "rolecall")
        except ApiException as exc:
            if exc.status != 404:
                raise


def _restore_runtime_guards(
    autoscaling: client.AutoscalingV2Api,
    policy: client.PolicyV1Api,
    settings,  # type: ignore[no-untyped-def]
) -> None:
    for name, minimum, maximum in (
        ("livekit-server", 1, settings.runtime_media_max_nodes),
        ("rolecall-worker", 2, settings.runtime_worker_max_nodes),
    ):
        body = client.V2HorizontalPodAutoscaler(
            metadata=client.V1ObjectMeta(name=name),
            spec=client.V2HorizontalPodAutoscalerSpec(
                min_replicas=minimum,
                max_replicas=maximum,
                scale_target_ref=client.V2CrossVersionObjectReference(
                    api_version="apps/v1", kind="Deployment", name=name
                ),
                metrics=[
                    client.V2MetricSpec(
                        type="Resource",
                        resource=client.V2ResourceMetricSource(
                            name="cpu",
                            target=client.V2MetricTarget(
                                type="Utilization", average_utilization=65
                            ),
                        ),
                    )
                ],
            ),
        )
        try:
            autoscaling.create_namespaced_horizontal_pod_autoscaler("rolecall", body)
        except ApiException as exc:
            if exc.status == 409:
                autoscaling.replace_namespaced_horizontal_pod_autoscaler(name, "rolecall", body)
            else:
                raise
        pdb = client.V1PodDisruptionBudget(
            metadata=client.V1ObjectMeta(name=name),
            spec=client.V1PodDisruptionBudgetSpec(
                min_available=1,
                selector=client.V1LabelSelector(match_labels={"app.kubernetes.io/name": name}),
            ),
        )
        try:
            policy.create_namespaced_pod_disruption_budget("rolecall", pdb)
        except ApiException as exc:
            if exc.status == 409:
                policy.replace_namespaced_pod_disruption_budget(name, "rolecall", pdb)
            else:
                raise


def suspend(operation_id: str) -> None:
    settings = get_settings()
    runtime = RuntimeService(get_repository(), settings)
    runtime.update_transition(
        operation_id, RuntimeStatus.SUSPENDING, 10, "Stopping public media endpoints"
    )
    apps, core, autoscaling, policy = _kubernetes_clients(settings)
    if not runtime.suspension_can_continue(operation_id):
        wake(operation_id)
        return
    _delete_runtime_guards(autoscaling, policy)
    for namespace, service_name in INGRESS_SERVICES.items():
        core.patch_namespaced_service(
            service_name,
            namespace,
            {"spec": {"type": "ClusterIP", "externalTrafficPolicy": None}},
        )
    if not runtime.suspension_can_continue(operation_id):
        wake(operation_id)
        return
    runtime.update_transition(
        operation_id, RuntimeStatus.SUSPENDING, 35, "Scaling voice workloads to zero"
    )
    for namespace, deployments in DEPLOYMENTS.items():
        for name in deployments:
            _scale(apps, namespace, name, 0)
    _wait_until(
        lambda: all(
            _deployment_ready(apps, namespace, name, 0)
            for namespace, deployments in DEPLOYMENTS.items()
            for name in deployments
        ),
        300,
        "Voice deployments did not stop",
    )
    if not runtime.suspension_can_continue(operation_id):
        wake(operation_id)
        return
    runtime.update_transition(
        operation_id, RuntimeStatus.SUSPENDING, 70, "Resizing GKE node pools to zero"
    )
    for pool in (settings.gke_media_pool, settings.gke_worker_pool):
        _set_pool_autoscaling(settings, pool, False, 0, 0)
        _set_pool_size(settings, pool, 0)
        if not runtime.suspension_can_continue(operation_id):
            wake(operation_id)
            return
    if runtime.finalize_suspend(operation_id).status != RuntimeStatus.SLEEPING:
        wake(operation_id)


def wake(operation_id: str) -> None:
    settings = get_settings()
    runtime = RuntimeService(get_repository(), settings)
    runtime.update_transition(
        operation_id, RuntimeStatus.WAKING, 10, "Restoring GKE worker and media nodes"
    )
    _set_pool_size(settings, settings.gke_worker_pool, settings.runtime_worker_min_nodes)
    _set_pool_size(settings, settings.gke_media_pool, settings.runtime_media_min_nodes)
    apps, core, autoscaling, policy = _kubernetes_clients(settings)
    _wait_until(
        lambda: (
            _ready_node_count(core, settings.gke_worker_pool) >= settings.runtime_worker_min_nodes
            and _ready_node_count(core, settings.gke_media_pool) >= settings.runtime_media_min_nodes
        ),
        600,
        "GKE nodes did not become available",
    )
    runtime.update_transition(
        operation_id, RuntimeStatus.WAKING, 35, "Starting Redis and certificate services"
    )
    _scale(apps, "rolecall", "rolecall-redis", 1)
    for name in DEPLOYMENTS["cert-manager"]:
        _scale(apps, "cert-manager", name, 1)
    _wait_until(
        lambda: _deployment_ready(apps, "rolecall", "rolecall-redis", 1),
        240,
        "Redis did not become ready",
    )
    runtime.update_transition(
        operation_id, RuntimeStatus.WAKING, 55, "Restoring LiveKit and TURN endpoints"
    )
    for namespace, service_name in INGRESS_SERVICES.items():
        address = (
            settings.livekit_signaling_ip
            if namespace == "ingress-signal"
            else settings.livekit_turn_ip
        )
        core.patch_namespaced_service(
            service_name,
            namespace,
            {
                "spec": {
                    "type": "LoadBalancer",
                    "loadBalancerIP": address,
                    "externalTrafficPolicy": "Local",
                }
            },
        )
        _scale(apps, namespace, service_name, 1)
    _scale(apps, "rolecall", "livekit-server", 1)
    _scale(apps, "rolecall", "rolecall-worker", 2)
    runtime.update_transition(
        operation_id, RuntimeStatus.WAKING, 75, "Waiting for voice health checks"
    )
    _wait_until(
        lambda: (
            _deployment_ready(apps, "rolecall", "livekit-server", 1)
            and _deployment_ready(apps, "rolecall", "rolecall-worker", 2)
            and all(
                _deployment_ready(apps, namespace, name, 1)
                for namespace, name in INGRESS_SERVICES.items()
            )
            and _service_has_ready_endpoints(core, "rolecall", "livekit-server")
            and all(
                _service_has_load_balancer(core, namespace, name)
                for namespace, name in INGRESS_SERVICES.items()
            )
        ),
        600,
        "Voice workloads did not become healthy",
    )
    _restore_runtime_guards(autoscaling, policy, settings)
    _set_pool_autoscaling(
        settings,
        settings.gke_media_pool,
        True,
        settings.runtime_media_min_nodes,
        settings.runtime_media_max_nodes,
    )
    _set_pool_autoscaling(
        settings,
        settings.gke_worker_pool,
        True,
        settings.runtime_worker_min_nodes,
        settings.runtime_worker_max_nodes,
    )
    runtime.update_transition(operation_id, RuntimeStatus.READY, 100, "Voice services are ready")


def main() -> None:
    action = os.environ.get("ROLECALL_RUNTIME_ACTION", "")
    operation_id = os.environ.get("ROLECALL_RUNTIME_OPERATION_ID", "")
    if action not in {"wake", "suspend"} or not operation_id:
        raise ValueError("Runtime job action and operation ID are required")
    try:
        wake(operation_id) if action == "wake" else suspend(operation_id)
        logger.info("event=runtime_transition_succeeded action=%s", action)
    except Exception as exc:
        settings = get_settings()
        RuntimeService(get_repository(), settings).update_transition(
            operation_id,
            RuntimeStatus.ERROR,
            0,
            "Runtime transition failed; inspect redacted job diagnostics",
            error_code=type(exc).__name__,
        )
        logger.error(
            "event=runtime_transition_failed action=%s error_type=%s",
            action,
            type(exc).__name__,
        )
        raise


if __name__ == "__main__":
    main()
