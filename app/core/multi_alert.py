"""Multi-Alert Prioritizer for FixIQ.

When multiple alerts fire at the same time,
engineers don't know which one to fix first.

FixIQ automatically prioritizes alerts by:
- Service criticality (revenue, user-facing, internal)
- Severity level (critical, high, medium, low)
- Number of users affected
- Cascade potential (will this cause more failures?)
- Current error rate and latency

This is Scenario 2 of FixIQ.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Service criticality scores
SERVICE_CRITICALITY: dict[str, int] = {
    "checkout-api": 10,
    "payment-service": 10,
    "auth-service": 9,
    "api-gateway": 9,
    "database": 9,
    "user-service": 7,
    "order-service": 7,
    "inventory-service": 6,
    "notification-service": 4,
    "logging": 2,
    "monitoring": 2,
}

# Severity scores
SEVERITY_SCORES: dict[str, int] = {
    "critical": 10,
    "high": 7,
    "medium": 4,
    "low": 1,
}

# User impact per service
SERVICE_USER_IMPACT: dict[str, int] = {
    "checkout-api": 500,
    "payment-service": 500,
    "auth-service": 1000,
    "api-gateway": 2000,
    "database": 1500,
    "user-service": 800,
    "order-service": 400,
    "notification-service": 200,
    "logging": 0,
    "monitoring": 0,
}

# Cascade potential — how many services depend on this
CASCADE_POTENTIAL: dict[str, int] = {
    "database": 10,
    "api-gateway": 9,
    "auth-service": 8,
    "checkout-api": 7,
    "payment-service": 5,
    "order-service": 4,
    "user-service": 3,
    "notification-service": 2,
    "logging": 1,
    "monitoring": 1,
}


@dataclass
class PrioritizedAlert:
    """A single alert with priority score."""
    id: str
    title: str
    service: str
    severity: str
    priority_score: float
    priority_rank: int
    users_affected: int
    cascade_potential: int
    fix_within: str
    reason: str
    alert_data: dict[str, Any]


@dataclass
class MultiAlertResult:
    """Result of multi-alert prioritization."""
    total_alerts: int
    prioritized: list[PrioritizedAlert]
    critical_count: int
    high_count: int
    total_users_affected: int
    recommendation: str


class MultiAlertPrioritizer:
    """Prioritizes multiple alerts by impact and criticality."""

    def prioritize(
        self, alerts: list[dict[str, Any]]
    ) -> MultiAlertResult:
        """Prioritize multiple alerts.

        Args:
            alerts: List of alert data dictionaries

        Returns:
            Prioritized alerts with scores
        """
        scored = []

        for alert in alerts:
            score = self._calculate_priority_score(alert)
            fix_within = self._get_fix_within(score)
            reason = self._build_reason(alert, score)
            users = SERVICE_USER_IMPACT.get(
                alert.get("service", ""), 0
            )
            cascade = CASCADE_POTENTIAL.get(
                alert.get("service", ""), 1
            )

            scored.append(PrioritizedAlert(
                id=alert.get("id", "unknown"),
                title=alert.get("title", "Unknown"),
                service=alert.get("service", "unknown"),
                severity=alert.get("severity", "low"),
                priority_score=score,
                priority_rank=0,  # Set after sorting
                users_affected=users,
                cascade_potential=cascade,
                fix_within=fix_within,
                reason=reason,
                alert_data=alert,
            ))

        # Sort by priority score
        scored.sort(
            key=lambda x: x.priority_score, reverse=True
        )

        # Assign ranks
        for i, alert in enumerate(scored, 1):
            alert.priority_rank = i

        # Build summary stats
        critical = sum(
            1 for a in scored if a.severity == "critical"
        )
        high = sum(
            1 for a in scored if a.severity == "high"
        )
        total_users = sum(
            a.users_affected for a in scored
        )

        recommendation = self._build_recommendation(scored)

        logger.info(
            "Prioritized %d alerts, %d critical, %d high",
            len(scored), critical, high
        )

        return MultiAlertResult(
            total_alerts=len(scored),
            prioritized=scored,
            critical_count=critical,
            high_count=high,
            total_users_affected=total_users,
            recommendation=recommendation,
        )

    def _calculate_priority_score(
        self, alert: dict[str, Any]
    ) -> float:
        """Calculate priority score for an alert."""
        service = alert.get("service", "")
        severity = alert.get("severity", "low")
        metrics = alert.get("metrics", {})

        # Base scores
        criticality = SERVICE_CRITICALITY.get(service, 3)
        severity_score = SEVERITY_SCORES.get(severity, 1)
        cascade = CASCADE_POTENTIAL.get(service, 1)

        # Metric-based adjustments
        error_rate = metrics.get("error_rate_pct", 0)
        latency = metrics.get("latency_ms", 0)
        restart_count = metrics.get("restart_count", 0)

        # Calculate metric score
        metric_score = 0
        if error_rate > 50:
            metric_score += 3
        elif error_rate > 20:
            metric_score += 2
        elif error_rate > 5:
            metric_score += 1

        if latency > 5000:
            metric_score += 2
        elif latency > 2000:
            metric_score += 1

        if restart_count > 2:
            metric_score += 2

        # Weighted final score
        score = (
            criticality * 0.35 +
            severity_score * 0.25 +
            cascade * 0.20 +
            metric_score * 0.20
        )

        return round(score, 2)

    def _get_fix_within(self, score: float) -> str:
        """Get recommended fix time based on score."""
        if score >= 8:
            return "< 15 minutes"
        elif score >= 6:
            return "< 30 minutes"
        elif score >= 4:
            return "< 2 hours"
        else:
            return "< 24 hours"

    def _build_reason(
        self,
        alert: dict[str, Any],
        score: float,
    ) -> str:
        """Build reason for priority ranking."""
        service = alert.get("service", "unknown")
        criticality = SERVICE_CRITICALITY.get(service, 3)
        cascade = CASCADE_POTENTIAL.get(service, 1)
        users = SERVICE_USER_IMPACT.get(service, 0)

        reasons = []

        if criticality >= 9:
            reasons.append("revenue-critical service")
        elif criticality >= 7:
            reasons.append("user-facing service")
        else:
            reasons.append("internal service")

        if cascade >= 7:
            reasons.append("high cascade potential")

        if users > 500:
            reasons.append(f"~{users} users affected")

        return ", ".join(reasons) if reasons else "standard priority"

    def _build_recommendation(
        self, alerts: list[PrioritizedAlert]
    ) -> str:
        """Build overall recommendation."""
        if not alerts:
            return "No alerts to prioritize."

        top = alerts[0]
        critical_count = sum(
            1 for a in alerts if a.severity == "critical"
        )

        return (
            f"Fix {top.service} first ({top.fix_within}). "
            f"{critical_count} critical alert(s) require "
            f"immediate attention."
        )


def display_multi_alert_result(
    result: MultiAlertResult,
) -> None:
    """Display prioritized alerts in terminal."""
    BOLD = "\033[1m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    GREEN = "\033[92m"
    BLUE = "\033[94m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    print(f"\n{BOLD}{'─' * 70}{RESET}")
    print(f"{BOLD}  🚨 MULTI-ALERT PRIORITIZATION{RESET}")
    print(f"{BOLD}{'─' * 70}{RESET}")

    print(f"\n  Total alerts:   {result.total_alerts}")
    print(
        f"  Critical:       "
        f"{RED}{result.critical_count}{RESET}"
    )
    print(
        f"  High:           "
        f"{YELLOW}{result.high_count}{RESET}"
    )
    print(
        f"  Users at risk:  ~{result.total_users_affected}"
    )

    print(f"\n  {BOLD}Priority Queue:{RESET}")
    print(
        f"\n  {'#':<4} {'Service':<20} {'Severity':<10} "
        f"{'Score':<8} {'Fix Within':<15} Reason"
    )
    print(f"  {'─' * 75}")

    for alert in result.prioritized:
        color = (
            RED if alert.severity == "critical" else
            YELLOW if alert.severity == "high" else
            BLUE if alert.severity == "medium" else
            GREEN
        )
        rank_str = (
            f"{BOLD}#{alert.priority_rank}{RESET}"
            if alert.priority_rank == 1
            else f"#{alert.priority_rank}"
        )

        print(
            f"  {rank_str:<4} "
            f"{alert.service:<20} "
            f"{color}{alert.severity:<10}{RESET} "
            f"{alert.priority_score:<8} "
            f"{alert.fix_within:<15} "
            f"{DIM}{alert.reason}{RESET}"
        )

    print(f"\n  {BOLD}Recommendation:{RESET}")
    print(f"  {result.recommendation}")
    print(f"\n{BOLD}{'─' * 70}{RESET}")