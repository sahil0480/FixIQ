"""Tests for Urgency Scorer."""

from __future__ import annotations

import pytest
from app.core.urgency import UrgencyScorer


@pytest.fixture
def scorer():
    return UrgencyScorer()


@pytest.fixture
def oomkilled_rca():
    return {"root_cause": "Pod OOMKilled memory limit exceeded"}


@pytest.fixture
def db_rca():
    return {"root_cause": "Database connection pool exhausted"}


@pytest.fixture
def config_rca():
    return {"root_cause": "Missing environment variable"}


@pytest.fixture
def unknown_rca():
    return {"root_cause": "Unknown"}


class TestUrgencyScorerBasic:

    def test_returns_dict(self, scorer, oomkilled_rca):
        result = scorer.score("checkout-api", oomkilled_rca)
        assert isinstance(result, dict)

    def test_has_required_fields(self, scorer, oomkilled_rca):
        result = scorer.score("checkout-api", oomkilled_rca)
        assert "score" in result
        assert "level" in result
        assert "fix_within" in result
        assert "reason" in result

    def test_level_between_1_and_10(
        self, scorer, oomkilled_rca
    ):
        result = scorer.score("checkout-api", oomkilled_rca)
        assert 1 <= result["level"] <= 10

    def test_score_label_not_empty(
        self, scorer, oomkilled_rca
    ):
        result = scorer.score("checkout-api", oomkilled_rca)
        assert result["score"] in [
            "CRITICAL", "HIGH", "MEDIUM", "LOW"
        ]


class TestUrgencyServiceCriticality:

    def test_checkout_api_is_critical(
        self, scorer, oomkilled_rca
    ):
        result = scorer.score("checkout-api", oomkilled_rca)
        assert result["level"] >= 8

    def test_logging_is_low(self, scorer, unknown_rca):
        result = scorer.score("logging", unknown_rca)
        assert result["level"] <= 5

    def test_monitoring_is_low(self, scorer, unknown_rca):
        result = scorer.score("monitoring", unknown_rca)
        assert result["level"] <= 5

    def test_auth_service_is_high(
        self, scorer, config_rca
    ):
        result = scorer.score("auth-service", config_rca)
        assert result["level"] >= 6

    def test_revenue_service_fix_within_15(
        self, scorer, oomkilled_rca
    ):
        result = scorer.score("checkout-api", oomkilled_rca)
        assert "15" in result["fix_within"]

    def test_internal_service_fix_within_24h(
        self, scorer, unknown_rca
    ):
        result = scorer.score("logging", unknown_rca)
        assert "24" in result["fix_within"]