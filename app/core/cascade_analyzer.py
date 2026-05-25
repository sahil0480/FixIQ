"""Cascade Failure Analyzer for FixIQ.

Analyzes how a failure cascades through your system.
Shows the full chain of failures and what to fix FIRST.

Most incidents are NOT single failures.
They're cascades where one failure triggers another.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CascadeLevel:
    """A single level in the cascade chain."""
    level: int
    service: str
    failure: str
    severity: str        # CRITICAL, HIGH, MEDIUM, LOW
    triggered_by: str    # What caused this level
    recovery: str        # How to fix this level


@dataclass
class CascadeAnalysis:
    """Complete cascade analysis result."""
    root_service: str
    levels: list[CascadeLevel]
    total_affected: int
    fix_order: list[str]
    summary: str


# Service dependency graph
# Shows which services depend on which
SERVICE_GRAPH: dict[str, list[str]] = {
    "database": [
        "checkout-api",
        "payment-service",
        "auth-service",
        "user-service",
    ],
    "checkout-api": [
        "payment-service",
        "order-service",
        "user-dashboard",
    ],
    "auth-service": [
        "checkout-api",
        "payment-service",
        "admin-panel",
    ],
    "api-gateway": [
        "checkout-api",
        "auth-service",
        "payment-service",
    ],
    "payment-service": [
        "billing-service",
        "notification-service",
    ],
    "order-service": [
        "notification-service",
        "inventory-service",
    ],
    "message-queue": [
        "notification-service",
        "order-service",
        "inventory-service",
    ],
}

# Failure patterns for each issue type
FAILURE_PATTERNS: dict[str, dict[str, str]] = {
    "memory": {
        "trigger": "Memory limit exceeded — OOMKilled",
        "cascade": "Service becomes unresponsive",
        "recovery": "Increase memory limit and restart pod",
    },
    "cpu": {
        "trigger": "CPU throttling detected",
        "cascade": "Request timeouts increase",
        "recovery": "Scale horizontally or optimize CPU usage",
    },
    "database": {
        "trigger": "Database connection pool exhausted",
        "cascade": "All dependent services start failing",
        "recovery": "Increase connection pool size",
    },
    "network": {
        "trigger": "Network connectivity issues",
        "cascade": "Inter-service communication fails",
        "recovery": "Check network policies and DNS",
    },
    "config": {
        "trigger": "Configuration error detected",
        "cascade": "Service fails to start or function",
        "recovery": "Fix configuration and redeploy",
    },
    "timeout": {
        "trigger": "Request timeouts cascading",
        "cascade": "Upstream services start queuing",
        "recovery": "Identify slow service and optimize",
    },
}


class CascadeAnalyzer:
    """Analyzes cascade failures in a distributed system."""

    def analyze(
        self,
        service_name: str,
        rca_output: dict[str, Any],
    ) -> CascadeAnalysis:
        """Analyze cascade failure from a service.

        Args:
            service_name: Name of the root failing service
            rca_output: RCA output from OpenSRE

        Returns:
            Complete cascade analysis
        """
        root_cause = rca_output.get("root_cause", "").lower()

        # Identify failure type
        failure_type = self._identify_failure_type(root_cause)
        pattern = FAILURE_PATTERNS.get(
            failure_type, FAILURE_PATTERNS["config"]
        )

        # Build cascade levels
        levels = self._build_cascade_levels(
            service_name, pattern, root_cause
        )

        # Determine fix order
        fix_order = self._determine_fix_order(levels)

        # Build summary
        summary = self._build_summary(
            service_name, levels, failure_type
        )

        logger.info(
            "Cascade analysis: %d levels, root=%s",
            len(levels), service_name
        )

        return CascadeAnalysis(
            root_service=service_name,
            levels=levels,
            total_affected=len(levels),
            fix_order=fix_order,
            summary=summary,
        )

    def _identify_failure_type(
        self, root_cause: str
    ) -> str:
        """Identify the type of failure."""
        keywords = {
            "memory": ["memory", "oom", "oomkilled", "heap"],
            "cpu": ["cpu", "throttl", "processor"],
            "database": [
                "database", "db", "connection", "pool",
                "postgres", "mysql", "mongo"
            ],
            "network": ["network", "dns", "connect", "timeout"],
            "config": ["config", "env", "variable", "secret"],
            "timeout": ["timeout", "latency", "slow", "response"],
        }

        for failure_type, words in keywords.items():
            if any(w in root_cause for w in words):
                return failure_type

        return "config"

    def _build_cascade_levels(
        self,
        root_service: str,
        pattern: dict[str, str],
        root_cause: str,
    ) -> list[CascadeLevel]:
        """Build cascade levels from root service."""
        levels = []

        # Level 0 — Root service
        levels.append(CascadeLevel(
            level=0,
            service=root_service,
            failure=pattern["trigger"],
            severity="CRITICAL",
            triggered_by="Root cause",
            recovery=pattern["recovery"],
        ))

        # Level 1 — Direct dependents
        direct_deps = SERVICE_GRAPH.get(root_service, [])
        for i, dep in enumerate(direct_deps[:3]):
            levels.append(CascadeLevel(
                level=1,
                service=dep,
                failure=f"{pattern['cascade']} in {dep}",
                severity="HIGH",
                triggered_by=root_service,
                recovery=f"Will recover after {root_service} is fixed",
            ))

        # Level 2 — Secondary dependents
        for dep in direct_deps[:2]:
            secondary = SERVICE_GRAPH.get(dep, [])
            for sec in secondary[:2]:
                # Avoid duplicates
                existing = [l.service for l in levels]
                if sec not in existing:
                    levels.append(CascadeLevel(
                        level=2,
                        service=sec,
                        failure=f"Degraded due to {dep} failure",
                        severity="MEDIUM",
                        triggered_by=dep,
                        recovery=(
                            f"Will recover after {dep} recovers"
                        ),
                    ))

        return levels

    def _determine_fix_order(
        self, levels: list[CascadeLevel]
    ) -> list[str]:
        """Determine the order to fix services."""
        # Always fix root cause first
        order = []
        seen = set()

        for level_num in [0, 1, 2]:
            for level in levels:
                if (level.level == level_num and
                        level.service not in seen):
                    order.append(level.service)
                    seen.add(level.service)

        return order

    def _build_summary(
        self,
        root_service: str,
        levels: list[CascadeLevel],
        failure_type: str,
    ) -> str:
        """Build human readable summary."""
        affected = len(levels)
        critical = sum(1 for l in levels if l.severity == "CRITICAL")
        high = sum(1 for l in levels if l.severity == "HIGH")

        return (
            f"{failure_type.upper()} failure in {root_service} "
            f"cascaded to {affected} services "
            f"({critical} critical, {high} high severity). "
            f"Fix {root_service} first to stop the cascade."
        )


def display_cascade_analysis(
    analysis: CascadeAnalysis,
) -> None:
    """Display cascade analysis in terminal."""
    BOLD = "\033[1m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    print(f"\n{BOLD}{'─' * 70}{RESET}")
    print(f"{BOLD}  ⚡ CASCADE FAILURE ANALYSIS{RESET}")
    print(f"{BOLD}{'─' * 70}{RESET}")

    print(f"\n  {BOLD}Failure Chain:{RESET}")

    for level in analysis.levels:
        indent = "  " * (level.level + 1)
        color = (
            RED if level.severity == "CRITICAL" else
            YELLOW if level.severity == "HIGH" else
            BLUE
        )
        arrow = "→" if level.level > 0 else "●"

        print(
            f"\n  {indent}{arrow} [{color}{level.severity}{RESET}] "
            f"{BOLD}{level.service}{RESET}"
        )
        print(f"  {indent}  {level.failure}")
        print(
            f"  {indent}  {DIM}Fix: {level.recovery}{RESET}"
        )

    print(f"\n  {BOLD}Fix Order:{RESET}")
    for i, service in enumerate(analysis.fix_order, 1):
        print(f"  {i}. {service}")

    print(f"\n  {BOLD}Summary:{RESET}")
    print(f"  {analysis.summary}")
    print(f"\n{BOLD}{'─' * 70}{RESET}")