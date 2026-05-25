"""Tests for Multi-Alert Prioritizer."""

from __future__ import annotations

import pytest
from app.core.multi_alert import (
    MultiAlertPrioritizer,
    MultiAlertResult,
    PrioritizedAlert,
)


# ─── Fixtures ───────────────────────────────────────────

@pytest.fixture
def prioritizer():
    return MultiAlertPrioritizer()


@pytest.fixture
def single_critical_alert():
    return [{
        "id": "alert-001",
        "title": "Pod OOMKilled in checkout-api",
        "severity": "critical",
        "service": "checkout-api",
        "metrics": {
            "memory_usage_mb": 980,
            "error_rate_pct": 45,
            "restart_count": 3,
        }
    }]


@pytest.fixture
def mixed_alerts():
    return [
        {
            "id": "alert-001",
            "title": "Pod OOMKilled in checkout-api",
            "severity": "critical",
            "service": "checkout-api",
            "metrics": {
                "memory_usage_mb": 980,
                "error_rate_pct": 45,
                "restart_count": 3,
            }
        },
        {
            "id": "alert-002",
            "title": "High latency in logging",
            "severity": "low",
            "service": "logging",
            "metrics": {
                "latency_ms": 800,
                "error_rate_pct": 2,
            }
        },
        {
            "id": "alert-003",
            "title": "Database connection pool exhausted",
            "severity": "critical",
            "service": "checkout-api",
            "metrics": {
                "active_connections": 200,
                "error_rate_pct": 34,
                "latency_ms": 8400,
            }
        },
        {
            "id": "alert-004",
            "title": "Auth service degraded",
            "severity": "high",
            "service": "auth-service",
            "metrics": {
                "latency_ms": 2400,
                "error_rate_pct": 8,
            }
        },
        {
            "id": "alert-005",
            "title": "Monitoring unavailable",
            "severity": "low",
            "service": "monitoring",
            "metrics": {
                "error_rate_pct": 100,
            }
        },
    ]


@pytest.fixture
def revenue_vs_internal():
    return [
        {
            "id": "alert-001",
            "title": "Monitoring down",
            "severity": "critical",
            "service": "monitoring",
            "metrics": {"error_rate_pct": 100}
        },
        {
            "id": "alert-002",
            "title": "Payment service failing",
            "severity": "high",
            "service": "payment-service",
            "metrics": {
                "error_rate_pct": 25,
                "latency_ms": 4000
            }
        },
    ]


# ─── Tests ──────────────────────────────────────────────

class TestMultiAlertBasic:
    """Basic multi-alert tests."""

    def test_returns_multi_alert_result(
        self, prioritizer, single_critical_alert
    ):
        """Should return MultiAlertResult object."""
        result = prioritizer.prioritize(single_critical_alert)
        assert isinstance(result, MultiAlertResult)

    def test_total_alerts_count(
        self, prioritizer, mixed_alerts
    ):
        """Total alerts count should match input."""
        result = prioritizer.prioritize(mixed_alerts)
        assert result.total_alerts == len(mixed_alerts)

    def test_returns_prioritized_list(
        self, prioritizer, mixed_alerts
    ):
        """Should return list of PrioritizedAlert."""
        result = prioritizer.prioritize(mixed_alerts)
        for alert in result.prioritized:
            assert isinstance(alert, PrioritizedAlert)

    def test_recommendation_not_empty(
        self, prioritizer, mixed_alerts
    ):
        """Recommendation should not be empty."""
        result = prioritizer.prioritize(mixed_alerts)
        assert len(result.recommendation) > 0

    def test_empty_alerts_handled(
        self, prioritizer
    ):
        """Should handle empty alerts list."""
        result = prioritizer.prioritize([])
        assert result.total_alerts == 0
        assert result.prioritized == []


class TestMultiAlertPriority:
    """Tests for priority ordering."""

    def test_critical_before_low(
        self, prioritizer, mixed_alerts
    ):
        """Critical alerts should rank before low alerts."""
        result = prioritizer.prioritize(mixed_alerts)
        critical_ranks = [
            a.priority_rank for a in result.prioritized
            if a.severity == "critical"
        ]
        low_ranks = [
            a.priority_rank for a in result.prioritized
            if a.severity == "low"
        ]
        assert max(critical_ranks) < min(low_ranks)

    def test_revenue_service_before_internal(
        self, prioritizer, revenue_vs_internal
    ):
        """Revenue service should rank before internal."""
        result = prioritizer.prioritize(revenue_vs_internal)
        payment_rank = next(
            a.priority_rank for a in result.prioritized
            if a.service == "payment-service"
        )
        monitoring_rank = next(
            a.priority_rank for a in result.prioritized
            if a.service == "monitoring"
        )
        assert payment_rank < monitoring_rank

    def test_ranks_are_sequential(
        self, prioritizer, mixed_alerts
    ):
        """Ranks should be 1, 2, 3... without gaps."""
        result = prioritizer.prioritize(mixed_alerts)
        ranks = sorted(
            a.priority_rank for a in result.prioritized
        )
        assert ranks == list(range(1, len(mixed_alerts) + 1))

    def test_highest_score_is_rank_one(
        self, prioritizer, mixed_alerts
    ):
        """Alert with highest score should be rank 1."""
        result = prioritizer.prioritize(mixed_alerts)
        rank_one = result.prioritized[0]
        max_score = max(
            a.priority_score for a in result.prioritized
        )
        assert rank_one.priority_score == max_score

    def test_logging_is_last(
        self, prioritizer, mixed_alerts
    ):
        """Logging service should be last priority."""
        result = prioritizer.prioritize(mixed_alerts)
        logging_alert = next(
            a for a in result.prioritized
            if a.service == "logging"
        )
        assert logging_alert.priority_rank == len(mixed_alerts)


class TestMultiAlertScoring:
    """Tests for priority score calculation."""

    def test_score_is_positive(
        self, prioritizer, mixed_alerts
    ):
        """All scores should be positive."""
        result = prioritizer.prioritize(mixed_alerts)
        for alert in result.prioritized:
            assert alert.priority_score > 0

    def test_critical_higher_score_than_low(
        self, prioritizer, mixed_alerts
    ):
        """Critical alerts should have higher score than low."""
        result = prioritizer.prioritize(mixed_alerts)
        critical_scores = [
            a.priority_score for a in result.prioritized
            if a.severity == "critical"
        ]
        low_scores = [
            a.priority_score for a in result.prioritized
            if a.severity == "low"
        ]
        assert min(critical_scores) > max(low_scores)

    def test_fix_within_set(
        self, prioritizer, mixed_alerts
    ):
        """Fix within time should be set for all alerts."""
        result = prioritizer.prioritize(mixed_alerts)
        for alert in result.prioritized:
            assert alert.fix_within != ""

    def test_critical_fix_within_15_minutes(
        self, prioritizer, single_critical_alert
    ):
        """Critical revenue service should fix within 15 min."""
        result = prioritizer.prioritize(single_critical_alert)
        top = result.prioritized[0]
        assert "15" in top.fix_within


class TestMultiAlertStats:
    """Tests for result statistics."""

    def test_critical_count_correct(
        self, prioritizer, mixed_alerts
    ):
        """Critical count should match input."""
        result = prioritizer.prioritize(mixed_alerts)
        expected = sum(
            1 for a in mixed_alerts
            if a["severity"] == "critical"
        )
        assert result.critical_count == expected

    def test_high_count_correct(
        self, prioritizer, mixed_alerts
    ):
        """High count should match input."""
        result = prioritizer.prioritize(mixed_alerts)
        expected = sum(
            1 for a in mixed_alerts
            if a["severity"] == "high"
        )
        assert result.high_count == expected

    def test_users_affected_positive(
        self, prioritizer, mixed_alerts
    ):
        """Total users affected should be positive."""
        result = prioritizer.prioritize(mixed_alerts)
        assert result.total_users_affected > 0

    def test_reason_provided(
        self, prioritizer, mixed_alerts
    ):
        """Every alert should have a reason."""
        result = prioritizer.prioritize(mixed_alerts)
        for alert in result.prioritized:
            assert len(alert.reason) > 0