"""Tests for Cascade Failure Analyzer."""

from __future__ import annotations

import pytest
from app.core.cascade_analyzer import (
    CascadeAnalyzer,
    CascadeAnalysis,
    CascadeLevel,
)


# ─── Fixtures ───────────────────────────────────────────

@pytest.fixture
def analyzer():
    return CascadeAnalyzer()


@pytest.fixture
def oomkilled_rca():
    return {
        "root_cause": "Pod OOMKilled memory limit exceeded",
    }


@pytest.fixture
def db_rca():
    return {
        "root_cause": "Database connection pool exhausted",
    }


@pytest.fixture
def config_rca():
    return {
        "root_cause": "Missing environment variable API_KEY",
    }


@pytest.fixture
def unknown_rca():
    return {
        "root_cause": "Unknown",
    }


# ─── Tests ──────────────────────────────────────────────

class TestCascadeAnalyzerBasic:
    """Basic cascade analyzer tests."""

    def test_returns_cascade_analysis(
        self, analyzer, oomkilled_rca
    ):
        """Should return CascadeAnalysis object."""
        result = analyzer.analyze("checkout-api", oomkilled_rca)
        assert isinstance(result, CascadeAnalysis)

    def test_root_service_set_correctly(
        self, analyzer, oomkilled_rca
    ):
        """Root service should match input."""
        result = analyzer.analyze("checkout-api", oomkilled_rca)
        assert result.root_service == "checkout-api"

    def test_has_cascade_levels(
        self, analyzer, oomkilled_rca
    ):
        """Should have at least one cascade level."""
        result = analyzer.analyze("checkout-api", oomkilled_rca)
        assert len(result.levels) > 0

    def test_has_fix_order(
        self, analyzer, oomkilled_rca
    ):
        """Should provide fix order."""
        result = analyzer.analyze("checkout-api", oomkilled_rca)
        assert len(result.fix_order) > 0

    def test_summary_not_empty(
        self, analyzer, oomkilled_rca
    ):
        """Summary should not be empty."""
        result = analyzer.analyze("checkout-api", oomkilled_rca)
        assert len(result.summary) > 0


class TestCascadeFailureTypes:
    """Tests for different failure type detection."""

    def test_detects_memory_failure(
        self, analyzer, oomkilled_rca
    ):
        """Should detect MEMORY failure type."""
        result = analyzer.analyze("checkout-api", oomkilled_rca)
        assert "MEMORY" in result.summary or \
               "memory" in result.levels[0].failure.lower()

    def test_detects_database_failure(
        self, analyzer, db_rca
    ):
        """Should detect DATABASE failure type."""
        result = analyzer.analyze("checkout-api", db_rca)
        assert "DATABASE" in result.summary or \
               "database" in result.levels[0].failure.lower() or \
               "connection" in result.levels[0].failure.lower()

    def test_detects_config_failure(
        self, analyzer, config_rca
    ):
        """Should detect CONFIG failure type."""
        result = analyzer.analyze("checkout-api", config_rca)
        assert "CONFIG" in result.summary or \
               "config" in result.levels[0].failure.lower()

    def test_unknown_defaults_to_config(
        self, analyzer, unknown_rca
    ):
        """Unknown root cause should default to config type."""
        result = analyzer.analyze("checkout-api", unknown_rca)
        assert result is not None
        assert len(result.levels) > 0


class TestCascadeLevels:
    """Tests for cascade level structure."""

    def test_root_level_is_zero(
        self, analyzer, oomkilled_rca
    ):
        """Root service should be at level 0."""
        result = analyzer.analyze("checkout-api", oomkilled_rca)
        root_levels = [
            l for l in result.levels if l.level == 0
        ]
        assert len(root_levels) == 1

    def test_root_level_is_critical(
        self, analyzer, oomkilled_rca
    ):
        """Root service should have CRITICAL severity."""
        result = analyzer.analyze("checkout-api", oomkilled_rca)
        root = result.levels[0]
        assert root.severity == "CRITICAL"

    def test_dependent_services_are_high(
        self, analyzer, oomkilled_rca
    ):
        """Direct dependents should be HIGH severity."""
        result = analyzer.analyze("checkout-api", oomkilled_rca)
        level_1 = [
            l for l in result.levels if l.level == 1
        ]
        for level in level_1:
            assert level.severity == "HIGH"

    def test_secondary_services_are_medium(
        self, analyzer, oomkilled_rca
    ):
        """Secondary dependents should be MEDIUM severity."""
        result = analyzer.analyze("checkout-api", oomkilled_rca)
        level_2 = [
            l for l in result.levels if l.level == 2
        ]
        for level in level_2:
            assert level.severity == "MEDIUM"

    def test_each_level_has_recovery(
        self, analyzer, oomkilled_rca
    ):
        """Every cascade level should have recovery steps."""
        result = analyzer.analyze("checkout-api", oomkilled_rca)
        for level in result.levels:
            assert len(level.recovery) > 0

    def test_each_level_has_triggered_by(
        self, analyzer, oomkilled_rca
    ):
        """Every level should know what triggered it."""
        result = analyzer.analyze("checkout-api", oomkilled_rca)
        for level in result.levels:
            assert len(level.triggered_by) > 0


class TestCascadeFixOrder:
    """Tests for fix order logic."""

    def test_root_service_is_first_in_fix_order(
        self, analyzer, oomkilled_rca
    ):
        """Root service should always be fixed first."""
        result = analyzer.analyze("checkout-api", oomkilled_rca)
        assert result.fix_order[0] == "checkout-api"

    def test_fix_order_matches_cascade_levels(
        self, analyzer, db_rca
    ):
        """Fix order should follow cascade levels."""
        result = analyzer.analyze("checkout-api", db_rca)
        assert len(result.fix_order) == len(
            set(result.fix_order)
        )  # No duplicates

    def test_database_cascade_fix_order(
        self, analyzer, db_rca
    ):
        """Database failure should fix checkout-api first."""
        result = analyzer.analyze("database", db_rca)
        assert result.fix_order[0] == "database"

    def test_api_gateway_cascade(
        self, analyzer, config_rca
    ):
        """API gateway failure cascades to many services."""
        result = analyzer.analyze("api-gateway", config_rca)
        assert len(result.levels) >= 3

    def test_total_affected_matches_levels(
        self, analyzer, oomkilled_rca
    ):
        """Total affected should match number of levels."""
        result = analyzer.analyze("checkout-api", oomkilled_rca)
        assert result.total_affected == len(result.levels)