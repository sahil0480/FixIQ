"""Urgency Scorer for FixIQ.

Scores how urgent an incident is based on
service type, time of day and impact.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Service criticality levels
# Higher = more critical
SERVICE_CRITICALITY: dict[str, int] = {
    "checkout-api": 10,      # Revenue critical
    "payment-service": 10,   # Revenue critical
    "auth-service": 9,       # All users affected
    "api-gateway": 9,        # All traffic affected
    "database": 9,           # Data critical
    "user-service": 7,       # User facing
    "order-service": 7,      # Revenue related
    "notification-service": 4,  # Non critical
    "logging": 2,            # Internal only
    "monitoring": 2,         # Internal only
}

# Peak traffic hours (24h format)
PEAK_HOURS = list(range(8, 10)) + list(range(12, 14)) + list(range(18, 22))


class UrgencyScorer:
    """Scores urgency of an incident."""

    def score(
        self,
        service_name: str,
        rca_output: dict[str, Any],
    ) -> dict[str, Any]:
        """Score the urgency of an incident.

        Args:
            service_name: Name of the affected service
            rca_output: RCA output from OpenSRE

        Returns:
            Urgency score and details
        """
        root_cause = rca_output.get("root_cause", "").lower()

        # Base score from service criticality
        base_score = SERVICE_CRITICALITY.get(service_name, 5)

        # Adjust for issue type
        issue_score = self._score_issue_type(root_cause)

        # Adjust for time of day
        time_multiplier = self._get_time_multiplier()

        # Calculate final score
        final_score = min(10, int((base_score + issue_score) / 2 * time_multiplier))

        # Determine label and fix time
        label, fix_within, reason = self._get_label(
            final_score, service_name, root_cause
        )

        logger.info(
            "Urgency score for %s: %s (%d/10)",
            service_name, label, final_score
        )

        return {
            "score": label,
            "level": final_score,
            "fix_within": fix_within,
            "reason": reason,
            "is_peak_traffic": self._is_peak_traffic(),
        }

    def _score_issue_type(self, root_cause: str) -> int:
        """Score based on issue type."""
        if any(k in root_cause for k in [
            "oomkilled", "crashloop", "crash",
            "down", "unavailable", "outage"
        ]):
            return 10  # Complete failure

        if any(k in root_cause for k in [
            "high cpu", "high memory", "slow",
            "timeout", "latency"
        ]):
            return 7  # Degraded performance

        if any(k in root_cause for k in [
            "config", "missing", "env",
            "warning", "deprecated"
        ]):
            return 4  # Configuration issue

        return 5  # Default

    def _get_time_multiplier(self) -> float:
        """Get time-based multiplier."""
        if self._is_peak_traffic():
            return 1.2  # 20% more urgent during peak
        return 1.0

    def _is_peak_traffic(self) -> bool:
        """Check if current time is peak traffic."""
        current_hour = datetime.now().hour
        return current_hour in PEAK_HOURS

    def _get_label(
        self,
        score: int,
        service_name: str,
        root_cause: str,
    ) -> tuple[str, str, str]:
        """Get urgency label, fix time and reason."""
        if score >= 9:
            return (
                "CRITICAL",
                "< 15 minutes",
                f"Revenue-impacting service ({service_name})"
            )
        elif score >= 7:
            return (
                "HIGH",
                "< 30 minutes",
                f"User-facing service degraded ({service_name})"
            )
        elif score >= 5:
            return (
                "MEDIUM",
                "< 2 hours",
                f"Service impacted but workarounds exist"
            )
        else:
            return (
                "LOW",
                "< 24 hours",
                f"Non-critical service or minor issue"
            )