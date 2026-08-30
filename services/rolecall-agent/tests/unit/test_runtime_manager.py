from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from kubernetes.client.exceptions import ApiException

from app.runtime_manager import _restore_runtime_guards


def test_existing_runtime_guards_are_patched_without_resource_versions() -> None:
    autoscaling = Mock()
    policy = Mock()
    autoscaling.create_namespaced_horizontal_pod_autoscaler.side_effect = ApiException(
        status=409
    )
    policy.create_namespaced_pod_disruption_budget.side_effect = ApiException(status=409)

    _restore_runtime_guards(
        autoscaling,
        policy,
        SimpleNamespace(runtime_media_max_nodes=3, runtime_worker_max_nodes=6),
    )

    assert autoscaling.patch_namespaced_horizontal_pod_autoscaler.call_count == 2
    assert policy.patch_namespaced_pod_disruption_budget.call_count == 2
    autoscaling.replace_namespaced_horizontal_pod_autoscaler.assert_not_called()
    policy.replace_namespaced_pod_disruption_budget.assert_not_called()
