"""Blast Radius Analyzer for FixIQ.

Analyzes who and what gets affected
if we apply the fix.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Estimated users per service
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

# Teams responsible for each service
SERVICE_TEAMS: dict[str, list[str]] = {
    "checkout-api": ["checkout", "payments", "platform"],
    "payment-service": ["payments", "finance"],
    "auth-service": ["security", "platform"],
    "api-gateway": ["platform", "infrastructure"],
    "database": ["infrastructure", "dba"],
    "user-service": ["user-experience", "platform"],
    "order-service": ["checkout", "fulfilment"],
    "notification-service": ["communications"],
    "logging": ["infrastructure"],
    "monitoring": ["infrastructure", "sre"],
}

# Peak traffic hours
PEAK_HOURS = list(range(8, 10)) + list(range(12, 14)) + list(range(18, 22))


class BlastRadiusAnalyzer:
    """Analyzes blast radius of applying a fix."""

    def analyze(
        self,
        service_name: str,
        rca_output: dict[str, Any],
    ) -> dict[str, Any]:
        """Analyze the blast radius of a fix.

        Args:
            service_name: Name of the affected service
            rca_output: RCA output from OpenSRE

        Returns:
            Blast radius analysis results
        """
        users_impacted = SERVICE_USER_IMPACT.get(service_name, 100)
        teams = SERVICE_TEAMS.get(service_name, ["unknown"])
        is_peak = self._is_peak_traffic()

        safety_level = self._get_safety_level(
            users_impacted, is_peak
        )

        recommendation = self._get_recommendation(
            safety_level, is_peak
        )

        logger.info(
            "Blast radius for %s: ~%d users, %s",
            service_name, users_impacted, safety_level
        )

        return {
            "users_impacted": users_impacted,
            "teams_affected": ", ".join(teams),
            "peak_traffic": is_peak,
            "safety_level": safety_level,
            "recommendation": recommendation,
        }

    def _is_peak_traffic(self) -> bool:
        """Check if current time is peak traffic."""
        current_hour = datetime.now().hour
        return current_hour in PEAK_HOURS

    def _get_safety_level(
        self,
        users_impacted: int,
        is_peak: bool,
    ) -> str:
        """Get safety level for applying fix."""
        if is_peak and users_impacted > 500:
            return "HIGH RISK"
        elif is_peak and users_impacted > 100:
            return "MEDIUM RISK"
        elif users_impacted > 500:
            return "MEDIUM RISK"
        else:
            return "LOW RISK"

    def _get_recommendation(
        self,
        safety_level: str,
        is_peak: bool,
    ) -> str:
        """Get recommendation based on safety level."""
        if safety_level == "HIGH RISK":
            return (
                "Consider waiting for off-peak hours. "
                "Notify affected teams before applying fix."
            )
        elif safety_level == "MEDIUM RISK":
            return (
                "Notify affected teams before applying fix. "
                "Have rollback plan ready."
            )
        else:
            return "Safe to proceed. Monitor after applying fix."