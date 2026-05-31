"""Service Discovery for FixIQ.

Automatically discovers all services deployed
in your Kubernetes cluster.

When FixIQ starts it scans the cluster and builds
a real system map — no hardcoded data needed.

This means FixIQ knows YOUR application:
- All deployed services
- Their resource limits
- Their dependencies (from real env var VALUES)
- Their criticality
- Their health status
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# ANSI colors
BOLD = "\033[1m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
DIM = "\033[2m"
RESET = "\033[0m"


@dataclass
class ServiceConfig:
    """Real configuration for a discovered service."""
    name: str
    namespace: str
    image: str
    replicas: int
    ready_replicas: int
    memory_limit: str
    memory_request: str
    cpu_limit: str
    cpu_request: str
    ports: list[int]
    env_vars: list[str]
    env_values: dict[str, str]
    labels: dict[str, str]
    depends_on: list[str]
    criticality: int
    users_affected: int
    is_healthy: bool
    restart_count: int
    pod_status: str
    last_updated: str


@dataclass
class SystemMap:
    """Complete map of all services in the cluster."""
    namespace: str
    services: dict[str, ServiceConfig]
    total_services: int
    healthy_services: int
    unhealthy_services: int
    last_discovered: str

    def get_service(
        self, name: str
    ) -> ServiceConfig | None:
        """Get service config by name."""
        return self.services.get(name)

    def get_unhealthy(self) -> list[ServiceConfig]:
        """Get all unhealthy services."""
        return [
            s for s in self.services.values()
            if not s.is_healthy
        ]

    def get_dependents(
        self, service_name: str
    ) -> list[str]:
        """Get services that depend on this service."""
        return [
            name for name, svc in self.services.items()
            if service_name in svc.depends_on
        ]

    def get_criticality(
        self, service_name: str
    ) -> int:
        """Get criticality score for a service."""
        svc = self.services.get(service_name)
        return svc.criticality if svc else 5


class ServiceDiscovery:
    """Discovers all services in K8s cluster."""

    CRITICAL_KEYWORDS = [
        "payment", "checkout", "order", "auth",
        "api-gateway", "gateway", "database", "db"
    ]
    HIGH_KEYWORDS = [
        "user", "account", "product", "inventory",
        "restaurant", "menu", "kitchen"
    ]
    LOW_KEYWORDS = [
        "logging", "monitoring", "metrics",
        "analytics", "internal"
    ]

    def __init__(
        self, namespace: str = "default"
    ) -> None:
        self.namespace = namespace
        self._system_map: SystemMap | None = None

    def _get_all_pods(self) -> dict[str, dict]:
        """Bulk-fetch ALL pods once and index by app label.

        One kubectl call instead of N calls (one per service).
        Much faster under cluster stress.
        """
        try:
            result = subprocess.run(
                [
                    "kubectl", "get", "pods",
                    "-n", self.namespace,
                    "-o", "json",
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if result.returncode != 0:
                return {}
            data = json.loads(result.stdout)
            index: dict[str, dict] = {}
            for pod in data.get("items", []):
                app_label = (
                    pod.get("metadata", {})
                    .get("labels", {})
                    .get("app", "")
                )
                if app_label and app_label not in index:
                    status = pod.get("status", {})
                    cs = status.get("containerStatuses", [{}])
                    container_status = cs[0] if cs else {}
                    index[app_label] = {
                        "phase": status.get("phase", "Unknown"),
                        "restart_count": container_status.get(
                            "restartCount", 0
                        ),
                        "ready": container_status.get(
                            "ready", False
                        ),
                    }
            return index
        except Exception as exc:
            logger.warning("Failed to bulk-fetch pods: %s", exc)
            return {}

    def discover(self) -> SystemMap:
        """Discover all services in cluster."""
        print(
            f"\n  🔍 Discovering services in "
            f"namespace: {self.namespace}..."
        )

        services = {}
        deployments = self._get_deployments()

        # ONE bulk pod fetch instead of N individual calls
        all_pods = self._get_all_pods()
        if not all_pods and deployments:
            logger.warning(
                "Pod bulk-fetch returned nothing — "
                "pod status will show as Unknown"
            )

        for deployment in deployments:
            config = self._build_service_config(
                deployment, pod_cache=all_pods
            )
            if config:
                services[config.name] = config
                status = (
                    "✓" if config.is_healthy else "✗"
                )
                print(
                    f"  {status} Found: {config.name} "
                    f"({config.image.split(':')[0].split('/')[-1]}) "
                    f"— {config.pod_status} "
                    f"restarts={config.restart_count}"
                )

        # Discover REAL dependencies from env var VALUES
        services = self._discover_dependencies(services)

        healthy = sum(
            1 for s in services.values()
            if s.is_healthy
        )

        self._system_map = SystemMap(
            namespace=self.namespace,
            services=services,
            total_services=len(services),
            healthy_services=healthy,
            unhealthy_services=len(services) - healthy,
            last_discovered=datetime.now().isoformat(),
        )

        print(
            f"\n  ✅ Discovered {len(services)} services "
            f"({healthy} healthy, "
            f"{len(services) - healthy} unhealthy)"
        )

        return self._system_map

    def get_system_map(self) -> SystemMap | None:
        """Get cached system map."""
        return self._system_map

    def _get_deployments(self) -> list[dict]:
        """Get all deployments from K8s."""
        try:
            result = subprocess.run(
                [
                    "kubectl", "get", "deployments",
                    "-n", self.namespace,
                    "-o", "json",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                return []
            data = json.loads(result.stdout)
            return data.get("items", [])
        except Exception as exc:
            logger.warning(
                "Failed to get deployments: %s", exc
            )
            return []

    def _build_service_config(
        self,
        deployment: dict,
        pod_cache: dict[str, dict] | None = None,
    ) -> ServiceConfig | None:
        """Build service config from deployment."""
        try:
            metadata = deployment.get("metadata", {})
            spec = deployment.get("spec", {})
            status = deployment.get("status", {})

            name = metadata.get("name", "")
            if not name:
                return None

            containers = spec.get(
                "template", {}
            ).get("spec", {}).get("containers", [{}])
            container = containers[0] \
                if containers else {}
            resources = container.get("resources", {})
            limits = resources.get("limits", {})
            requests = resources.get("requests", {})

            ports = [
                p.get("containerPort", 0)
                for p in container.get("ports", [])
            ]

            # Store BOTH names and values of env vars
            env_vars = []
            env_values = {}
            for e in container.get("env", []):
                env_name = e.get("name", "")
                env_val = e.get("value", "")
                if env_name:
                    env_vars.append(env_name)
                    env_values[env_name] = env_val

            # Use pod cache (bulk fetch) — no per-service kubectl call
            if pod_cache is not None:
                pod_info = pod_cache.get(name, {})
            else:
                pod_info = self._get_pod_info(name)

            criticality = self._calculate_criticality(
                name
            )
            users = self._estimate_users(
                name, criticality
            )

            ready = status.get("readyReplicas", 0) or 0
            desired = spec.get("replicas", 1) or 1
            is_healthy = (
                ready >= desired and
                pod_info.get("restart_count", 0) < 5
            )

            return ServiceConfig(
                name=name,
                namespace=self.namespace,
                image=container.get(
                    "image", "unknown"
                ),
                replicas=desired,
                ready_replicas=ready,
                memory_limit=limits.get(
                    "memory", "unknown"
                ),
                memory_request=requests.get(
                    "memory", "unknown"
                ),
                cpu_limit=limits.get(
                    "cpu", "unknown"
                ),
                cpu_request=requests.get(
                    "cpu", "unknown"
                ),
                ports=ports,
                env_vars=env_vars,
                env_values=env_values,
                labels=metadata.get("labels", {}),
                depends_on=[],
                criticality=criticality,
                users_affected=users,
                is_healthy=is_healthy,
                restart_count=pod_info.get(
                    "restart_count", 0
                ),
                pod_status=pod_info.get(
                    "phase", "Unknown"
                ),
                last_updated=metadata.get(
                    "creationTimestamp", ""
                ),
            )

        except Exception as exc:
            logger.warning(
                "Failed to build service config: %s",
                exc
            )
            return None

    def _get_pod_info(
        self, service_name: str
    ) -> dict[str, Any]:
        """Get pod status for a service (fallback, single service)."""
        try:
            result = subprocess.run(
                [
                    "kubectl", "get", "pods",
                    "-n", self.namespace,
                    "-l", f"app={service_name}",
                    "-o", "json",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return {}

            data = json.loads(result.stdout)
            items = data.get("items", [])
            if not items:
                return {}

            pod = items[0]
            status = pod.get("status", {})
            cs = status.get(
                "containerStatuses", [{}]
            )
            container_status = cs[0] if cs else {}

            return {
                "phase": status.get(
                    "phase", "Unknown"
                ),
                "restart_count": container_status.get(
                    "restartCount", 0
                ),
                "ready": container_status.get(
                    "ready", False
                ),
            }
        except Exception:
            return {}

    def _discover_dependencies(
        self,
        services: dict[str, ServiceConfig],
    ) -> dict[str, ServiceConfig]:
        """Discover real dependencies from env var VALUES.

        Checks if env var VALUES contain service names.
        e.g. ORDER_SERVICE_URL=http://order-service
             → depends on order-service
        """
        try:
            for name, config in services.items():
                deps = []

                # Check env var VALUES for service names
                for env_name, env_value in \
                        config.env_values.items():
                    for other_name in services:
                        if other_name == name:
                            continue
                        # Check if service name appears
                        # in the env var value
                        if other_name in env_value:
                            if other_name not in deps:
                                deps.append(other_name)
                                logger.info(
                                    "Found dependency: "
                                    "%s → %s "
                                    "(via %s=%s)",
                                    name,
                                    other_name,
                                    env_name,
                                    env_value,
                                )

                config.depends_on = deps

        except Exception as exc:
            logger.warning(
                "Failed to discover dependencies: %s",
                exc
            )

        return services

    def _calculate_criticality(
        self, service_name: str
    ) -> int:
        """Calculate criticality score for service."""
        name_lower = service_name.lower()

        for keyword in self.CRITICAL_KEYWORDS:
            if keyword in name_lower:
                return 9

        for keyword in self.HIGH_KEYWORDS:
            if keyword in name_lower:
                return 7

        for keyword in self.LOW_KEYWORDS:
            if keyword in name_lower:
                return 2

        return 5

    def _estimate_users(
        self,
        service_name: str,
        criticality: int,
    ) -> int:
        """Estimate users affected by service."""
        if criticality >= 9:
            return 500
        elif criticality >= 7:
            return 200
        elif criticality >= 5:
            return 100
        else:
            return 0


def display_system_map(
    system_map: SystemMap
) -> None:
    """Display discovered system map."""
    print(f"\n{BOLD}{'═' * 70}{RESET}")
    print(
        f"{BOLD}  🗺️  SYSTEM MAP — "
        f"{system_map.namespace}{RESET}"
    )
    print(f"{BOLD}{'═' * 70}{RESET}")
    print(
        f"\n  Total services:   "
        f"{system_map.total_services}"
    )
    print(
        f"  Healthy:          "
        f"{GREEN}{system_map.healthy_services}{RESET}"
    )
    print(
        f"  Unhealthy:        "
        f"{RED}{system_map.unhealthy_services}{RESET}"
    )

    print(
        f"\n  {'Service':<25} {'Status':<12} "
        f"{'Memory':<10} {'Restarts':<10} "
        f"Criticality"
    )
    print(f"  {'─' * 65}")

    for name, svc in system_map.services.items():
        status_color = GREEN if svc.is_healthy else RED
        status = (
            "✓ Healthy" if svc.is_healthy
            else "✗ Unhealthy"
        )
        crit_color = (
            RED if svc.criticality >= 9 else
            YELLOW if svc.criticality >= 6 else
            GREEN
        )
        print(
            f"  {name:<25} "
            f"{status_color}{status:<12}{RESET} "
            f"{svc.memory_limit:<10} "
            f"{svc.restart_count:<10} "
            f"{crit_color}{svc.criticality}/10{RESET}"
        )
        if svc.depends_on:
            print(
                f"  {DIM}  → depends on: "
                f"{', '.join(svc.depends_on)}{RESET}"
            )

    # Show dependency tree
    print(f"\n  {BOLD}Dependency Tree:{RESET}")
    roots = [
        name for name, svc in system_map.services.items()
        if not svc.depends_on
    ]
    dependents_map = {
        name: system_map.get_dependents(name)
        for name in system_map.services
    }

    printed = set()
    for root in roots:
        _print_tree(
            root,
            system_map.services,
            dependents_map,
            printed,
            indent=0,
        )

    print(f"\n{BOLD}{'═' * 70}{RESET}")


def _print_tree(
    service: str,
    services: dict[str, ServiceConfig],
    dependents_map: dict[str, list[str]],
    printed: set,
    indent: int,
) -> None:
    """Print service dependency tree."""
    if service in printed:
        return
    printed.add(service)

    svc = services.get(service)
    if not svc:
        return

    prefix = "  " + "  " * indent
    arrow = "→ " if indent > 0 else "● "
    color = (
        RED if svc.criticality >= 9 else
        YELLOW if svc.criticality >= 6 else
        GREEN
    )
    health = (
        f"{GREEN}✓{RESET}"
        if svc.is_healthy else f"{RED}✗{RESET}"
    )

    print(
        f"{prefix}{arrow}{color}{service}{RESET} "
        f"{health} "
        f"{DIM}(criticality={svc.criticality}/10, "
        f"users=~{svc.users_affected}){RESET}"
    )

    for dependent in dependents_map.get(service, []):
        _print_tree(
            dependent,
            services,
            dependents_map,
            printed,
            indent + 1,
        )