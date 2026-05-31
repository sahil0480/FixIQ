"""Kubernetes Real Data Collector for FixIQ.

Reads REAL data from Kubernetes cluster:
- Pod status and events
- Deployment history and resource limits
- Container logs
- Resource usage

This replaces all hardcoded data with real K8s data.
"""

from __future__ import annotations

import logging
import subprocess
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class K8sServiceInfo:
    """Real Kubernetes service information."""
    name: str
    namespace: str
    replicas: int
    ready_replicas: int
    memory_limit: str
    memory_request: str
    cpu_limit: str
    cpu_request: str
    image: str
    restart_count: int
    pod_status: str
    pod_conditions: list[dict]
    recent_events: list[dict]
    deployment_revision: int
    labels: dict[str, str]
    dependents: list[str]


@dataclass
class K8sClusterInfo:
    """Real Kubernetes cluster information."""
    services: dict[str, K8sServiceInfo]
    total_pods: int
    failing_pods: list[str]
    recent_events: list[dict]


class K8sCollector:
    """Collects real data from Kubernetes cluster."""

    def __init__(self, namespace: str = "default") -> None:
        self.namespace = namespace
        self._available = self._check_kubectl()

    def _check_kubectl(self) -> bool:
        """Check if kubectl is available."""
        try:
            result = subprocess.run(
                ["kubectl", "version", "--client"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _run_kubectl(
        self, args: list[str], timeout: int = 10
    ) -> dict | list | None:
        """Run kubectl command and return JSON output."""
        try:
            cmd = ["kubectl"] + args + [
                "-o", "json",
                "-n", self.namespace
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
            return None
        except Exception as exc:
            logger.warning(
                "kubectl command failed: %s", exc
            )
            return None

    def _run_kubectl_raw(
        self, args: list[str], timeout: int = 10
    ) -> str:
        """Run kubectl command and return raw output."""
        try:
            cmd = ["kubectl"] + args + [
                "-n", self.namespace
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.stdout
        except Exception:
            return ""

    def get_service_info(
        self, service_name: str
    ) -> K8sServiceInfo | None:
        """Get real info for a service from K8s."""
        if not self._available:
            return None

        try:
            deployment = self._run_kubectl([
                "get", "deployment", service_name
            ])

            if not deployment:
                return None

            spec = deployment.get("spec", {})
            status = deployment.get("status", {})
            containers = spec.get(
                "template", {}
            ).get("spec", {}).get("containers", [{}])
            container = containers[0] if containers else {}
            resources = container.get("resources", {})
            limits = resources.get("limits", {})
            requests = resources.get("requests", {})

            pods_data = self._run_kubectl([
                "get", "pods",
                "-l", f"app={service_name}"
            ])

            restart_count = 0
            pod_status = "Unknown"
            pod_conditions = []

            if pods_data:
                items = pods_data.get("items", [])
                if items:
                    # Sort newest first, prefer unhealthy pod
                    items.sort(
                        key=lambda p: p.get(
                            "metadata", {}
                        ).get("creationTimestamp", ""),
                        reverse=True,
                    )

                    def _is_unhealthy(p: dict) -> bool:
                        phase = p.get(
                            "status", {}
                        ).get("phase", "")
                        cs = p.get("status", {}).get(
                            "containerStatuses", [{}]
                        )
                        c = cs[0] if cs else {}
                        return (
                            phase in ("Failed", "Pending")
                            or not c.get("ready", True)
                            or c.get("restartCount", 0) > 0
                        )

                    unhealthy = [
                        p for p in items
                        if _is_unhealthy(p)
                    ]
                    pod = (
                        unhealthy[0]
                        if unhealthy else items[0]
                    )
                    pod_status_obj = pod.get("status", {})
                    pod_status = pod_status_obj.get(
                        "phase", "Unknown"
                    )
                    pod_conditions = pod_status_obj.get(
                        "conditions", []
                    )
                    container_statuses = pod_status_obj.get(
                        "containerStatuses", []
                    )
                    if container_statuses:
                        restart_count = (
                            container_statuses[0].get(
                                "restartCount", 0
                            )
                        )

            events = self._get_events(service_name)
            dependents = self._get_dependents(service_name)

            annotations = deployment.get(
                "metadata", {}
            ).get("annotations", {})
            revision = int(annotations.get(
                "deployment.kubernetes.io/revision", 1
            ))

            return K8sServiceInfo(
                name=service_name,
                namespace=self.namespace,
                replicas=spec.get("replicas", 1),
                ready_replicas=status.get(
                    "readyReplicas", 0
                ),
                memory_limit=limits.get(
                    "memory", "unknown"
                ),
                memory_request=requests.get(
                    "memory", "unknown"
                ),
                cpu_limit=limits.get("cpu", "unknown"),
                cpu_request=requests.get(
                    "cpu", "unknown"
                ),
                image=container.get("image", "unknown"),
                restart_count=restart_count,
                pod_status=pod_status,
                pod_conditions=pod_conditions,
                recent_events=events,
                deployment_revision=revision,
                labels=deployment.get(
                    "metadata", {}
                ).get("labels", {}),
                dependents=dependents,
            )

        except Exception as exc:
            logger.exception(
                "Failed to get service info: %s", exc
            )
            return None

    def _get_events(
        self, service_name: str
    ) -> list[dict]:
        """Get real Kubernetes events for a service."""
        try:
            output = self._run_kubectl_raw([
                "get", "events",
                "--field-selector",
                f"involvedObject.name={service_name}",
                "--sort-by=.lastTimestamp",
            ])

            events = []
            for line in output.strip().split("\n")[1:]:
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 5:
                        events.append({
                            "time": parts[0],
                            "type": parts[1],
                            "reason": parts[2],
                            "message": " ".join(parts[4:]),
                        })
            return events[-10:]

        except Exception:
            return []

    def _get_dependents(
        self, service_name: str
    ) -> list[str]:
        """Get services that depend on this service."""
        try:
            services_data = self._run_kubectl([
                "get", "deployments"
            ])

            if not services_data:
                return []

            dependents = []
            items = services_data.get("items", [])

            for item in items:
                name = item.get(
                    "metadata", {}
                ).get("name", "")
                if name == service_name:
                    continue

                containers = item.get(
                    "spec", {}
                ).get("template", {}).get(
                    "spec", {}
                ).get("containers", [])

                for container in containers:
                    env_vars = container.get("env", [])
                    for env in env_vars:
                        value = env.get("value", "")
                        if service_name in value:
                            dependents.append(name)
                            break

            return dependents

        except Exception:
            return []

    def get_cluster_info(self) -> K8sClusterInfo:
        """Get overall cluster information."""
        try:
            pods_data = self._run_kubectl([
                "get", "pods"
            ])

            total_pods = 0
            failing_pods = []

            if pods_data:
                items = pods_data.get("items", [])
                total_pods = len(items)
                for pod in items:
                    phase = pod.get(
                        "status", {}
                    ).get("phase", "")
                    name = pod.get(
                        "metadata", {}
                    ).get("name", "")
                    if phase not in [
                        "Running", "Succeeded"
                    ]:
                        failing_pods.append(name)

            events_output = self._run_kubectl_raw([
                "get", "events",
                "--sort-by=.lastTimestamp",
            ])

            recent_events = []
            for line in events_output.strip().split(
                "\n"
            )[1:]:
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 5:
                        recent_events.append({
                            "time": parts[0],
                            "type": parts[1],
                            "reason": parts[2],
                            "message": " ".join(
                                parts[4:]
                            ),
                        })

            return K8sClusterInfo(
                services={},
                total_pods=total_pods,
                failing_pods=failing_pods,
                recent_events=recent_events[-20:],
            )

        except Exception as exc:
            logger.exception(
                "Failed to get cluster info: %s", exc
            )
            return K8sClusterInfo(
                services={},
                total_pods=0,
                failing_pods=[],
                recent_events=[],
            )

    def get_pod_logs(
        self,
        service_name: str,
        lines: int = 50,
    ) -> list[str]:
        """Get real pod logs."""
        try:
            output = self._run_kubectl_raw([
                "logs",
                f"deployment/{service_name}",
                f"--tail={lines}",
                "--previous",
            ])
            if not output:
                output = self._run_kubectl_raw([
                    "logs",
                    f"deployment/{service_name}",
                    f"--tail={lines}",
                ])
            return [
                l for l in
                output.strip().split("\n")
                if l.strip()
            ]
        except Exception:
            return []

    def is_available(self) -> bool:
        """Check if K8s cluster is accessible."""
        return self._available

    def get_pod_details(
        self, service_name: str
    ) -> dict[str, Any]:
        """Get pod details — delegates to watcher logic."""
        from app.core.k8s_watcher import K8sWatcher
        w = K8sWatcher(namespace=self.namespace)
        return w.get_pod_details(service_name)