"""Tests for Blast Radius Analyzer."""

from __future__ import annotations

import pytest
from app.core.blast_radius import BlastRadiusAnalyzer


@pytest.fixture
def analyzer():
    return BlastRadiusAnalyzer()


@pytest.fixture
def rca():
    return {"root_cause": "Pod OOMKilled"}


class TestBlastRadiusBasic:

    def test_returns_dict(self, analyzer, rca):
        result = analyzer.analyze("checkout-api", rca)
        assert isinstance(result, dict)

    def test_has_required_fields(self, analyzer, rca):
        result = analyzer.analyze("checkout-api", rca)
        assert "users_impacted" in result
        assert "teams_affected" in result
        assert "peak_traffic" in result
        assert "safety_level" in result
        assert "recommendation" in result

    def test_users_impacted_positive(self, analyzer, rca):
        result = analyzer.analyze("checkout-api", rca)
        assert result["users_impacted"] >= 0

    def test_recommendation_not_empty(self, analyzer, rca):
        result = analyzer.analyze("checkout-api", rca)
        assert len(result["recommendation"]) > 0


class TestBlastRadiusServices:

    def test_checkout_api_high_impact(self, analyzer, rca):
        result = analyzer.analyze("checkout-api", rca)
        assert result["users_impacted"] >= 500

    def test_api_gateway_highest_impact(self, analyzer, rca):
        result = analyzer.analyze("api-gateway", rca)
        assert result["users_impacted"] >= 2000

    def test_logging_zero_impact(self, analyzer, rca):
        result = analyzer.analyze("logging", rca)
        assert result["users_impacted"] == 0

    def test_monitoring_zero_impact(self, analyzer, rca):
        result = analyzer.analyze("monitoring", rca)
        assert result["users_impacted"] == 0

    def test_teams_affected_not_empty(self, analyzer, rca):
        result = analyzer.analyze("checkout-api", rca)
        assert len(result["teams_affected"]) > 0

    def test_peak_traffic_is_bool(self, analyzer, rca):
        result = analyzer.analyze("checkout-api", rca)
        assert isinstance(result["peak_traffic"], bool)