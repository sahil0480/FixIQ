"""Tests for Similar Incidents Finder."""

from __future__ import annotations

import pytest
from pathlib import Path
from app.core.similar_incidents import (
    SimilarIncidentsFinder,
    SimilarIncidentsResult,
)


@pytest.fixture
def tmp_incidents(tmp_path):
    """Use temp path for knowledge base."""
    return SimilarIncidentsFinder(
        path=tmp_path / "incidents.json"
    )


@pytest.fixture
def db_rca():
    return {"root_cause": "Database connection pool exhausted"}


class TestSimilarIncidentsBasic:

    def test_returns_result(self, tmp_incidents, db_rca):
        result = tmp_incidents.find(
            "Database connection pool exhausted",
            "checkout-api",
            db_rca,
        )
        assert isinstance(result, SimilarIncidentsResult)

    def test_no_history_returns_not_found(
        self, tmp_incidents, db_rca
    ):
        result = tmp_incidents.find(
            "Database connection pool exhausted",
            "checkout-api",
            db_rca,
        )
        assert result.found is False

    def test_recommended_fix_not_empty(
        self, tmp_incidents, db_rca
    ):
        result = tmp_incidents.find(
            "Database connection pool exhausted",
            "checkout-api",
            db_rca,
        )
        assert len(result.recommended_fix) > 0


class TestSimilarIncidentsSaving:

    def test_save_and_find(self, tmp_incidents, db_rca):
        """Save an incident then find it."""
        tmp_incidents.save_incident(
            root_cause="Database connection pool exhausted",
            service_name="checkout-api",
            fix_applied="Increased pool size to 200",
            time_to_fix_minutes=12,
            outcome="resolved",
        )
        result = tmp_incidents.find(
            "Database connection pool exhausted",
            "checkout-api",
            db_rca,
        )
        assert result.found is True
        assert len(result.incidents) > 0

    def test_best_match_has_high_similarity(
        self, tmp_incidents, db_rca
    ):
        """Best match should have high similarity."""
        tmp_incidents.save_incident(
            root_cause="Database connection pool exhausted",
            service_name="checkout-api",
            fix_applied="Increased pool size to 200",
            time_to_fix_minutes=12,
            outcome="resolved",
        )
        result = tmp_incidents.find(
            "Database connection pool exhausted",
            "checkout-api",
            db_rca,
        )
        assert result.best_match is not None
        assert result.best_match.similarity_score >= 0.5

    def test_success_rate_calculated(
        self, tmp_incidents, db_rca
    ):
        """Success rate should be calculated correctly."""
        tmp_incidents.save_incident(
            root_cause="Database connection pool exhausted",
            service_name="checkout-api",
            fix_applied="Increased pool size",
            time_to_fix_minutes=12,
            outcome="resolved",
        )
        result = tmp_incidents.find(
            "Database connection pool exhausted",
            "checkout-api",
            db_rca,
        )
        assert 0.0 <= result.success_rate <= 1.0

    def test_avg_time_calculated(
        self, tmp_incidents, db_rca
    ):
        """Average time to fix should be calculated."""
        tmp_incidents.save_incident(
            root_cause="Database connection pool exhausted",
            service_name="checkout-api",
            fix_applied="Increased pool size",
            time_to_fix_minutes=12,
            outcome="resolved",
        )
        result = tmp_incidents.find(
            "Database connection pool exhausted",
            "checkout-api",
            db_rca,
        )
        assert result.avg_time_to_fix >= 0