"""Impact Analyzer for FixIQ.

Analyzes which services and files are impacted
by the detected issue.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Service dependency map
# In real world this would be read from k8s/docker configs
SERVICE_DEPENDENCIES: dict[str, list[str]] = {
    "checkout-api": ["payment-service", "order-service", "user-dashboard"],
    "payment-service": ["checkout-api", "billing-service"],
    "auth-service": ["checkout-api", "payment-service", "admin-panel"],
    "database": ["checkout-api", "payment-service", "auth-service"],
    "api-gateway": ["checkout-api", "auth-service", "payment-service"],
    "order-service": ["notification-service", "inventory-service"],
    "user-service": ["checkout-api", "auth-service"],
}

# File patterns for each service type
SERVICE_FILES: dict[str, list[str]] = {
    "kubernetes": [
        "k8s/deployments/*.yaml",
        "k8s/services/*.yaml",
        "helm/values.yaml",
    ],
    "config": [
        ".env",
        ".env.example",
        "app/config.py",
    ],
    "code": [
        "app/",
        "tests/",
    ],
    "database": [
        "k8s/statefulsets/*.yaml",
        "migrations/",
        "app/database/",
    ],
}


class ImpactAnalyzer:
    """Analyzes impact of an incident."""

    def analyze(
        self,
        service_name: str,
        rca_output: dict[str, Any],
    ) -> dict[str, Any]:
        """Analyze the impact of an incident.

        Args:
            service_name: Name of the affected service
            rca_output: RCA output from OpenSRE

        Returns:
            Impact analysis results
        """
        root_cause = rca_output.get("root_cause", "").lower()

        affected_services = self._get_affected_services(service_name)
        affected_files = self._get_affected_files(root_cause)

        logger.info(
            "Impact analysis: %d services, %d files affected",
            len(affected_services),
            len(affected_files),
        )

        return {
            "primary_service": service_name,
            "affected_services": affected_services,
            "affected_files": affected_files,
            "total_services": len(affected_services),
            "total_files": len(affected_files),
        }

    def _get_affected_services(
        self, service_name: str
    ) -> list[str]:
        """Get list of services affected by the incident."""
        # Direct dependents
        dependents = SERVICE_DEPENDENCIES.get(service_name, [])

        # Format with dependency info
        result = []
        for svc in dependents:
            result.append(f"{svc}  (depends on {service_name})")

        if not result:
            result.append(f"{service_name}  (isolated service)")

        return result

    def _get_affected_files(self, root_cause: str) -> list[str]:
        """Get list of files to check based on root cause."""
        files = []

        if any(k in root_cause for k in [
            "pod", "memory", "cpu", "kubernetes",
            "deployment", "container", "oomkilled"
        ]):
            files.extend(SERVICE_FILES["kubernetes"])

        if any(k in root_cause for k in [
            "config", "env", "variable", "key",
            "missing", "secret"
        ]):
            files.extend(SERVICE_FILES["config"])

        if any(k in root_cause for k in [
            "database", "db", "query", "connection",
            "postgres", "mysql", "mongo"
        ]):
            files.extend(SERVICE_FILES["database"])

        if any(k in root_cause for k in [
            "exception", "error", "bug", "import",
            "module", "function"
        ]):
            files.extend(SERVICE_FILES["code"])

        # Default if nothing matched
        if not files:
            files = ["app/", "k8s/", ".env"]

        return list(dict.fromkeys(files))  # Remove duplicates