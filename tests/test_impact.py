"""Tests for Impact Analyzer."""

from __future__ import annotations

import pytest
from app.core.impact import ImpactAnalyzer


@pytest.fixture
def analyzer():
    return ImpactAnalyzer()


@pytest.fixture
def oomkilled_rca():
    return {
        "root_cause": "Pod OOMKilled memory limit exceeded"
    }


@pytest.fixture
def db_rca():
    return {
        "root_cause": "Database connection pool exhausted"
    }


class TestImpactAnalyzerBasic:

    def test_returns_dict(self, analyzer, oomkilled_rca):
        result = analyzer.analyze(
            "checkout-api", oomkilled_rca
        )
        assert isinstance(result, dict)

    def test_has_required_fields(
        self, analyzer, oomkilled_rca
    ):
        result = analyzer.analyze(
            "checkout-api", oomkilled_rca
        )
        assert "affected_services" in result
        assert "affected_files" in result
        assert "primary_service" in result

    def test_primary_service_correct(
        self, analyzer, oomkilled_rca
    ):
        result = analyzer.analyze(
            "checkout-api", oomkilled_rca
        )
        assert result["primary_service"] == "checkout-api"

    def test_affected_services_not_empty(
        self, analyzer, oomkilled_rca
    ):
        result = analyzer.analyze(
            "checkout-api", oomkilled_rca
        )
        assert len(result["affected_services"]) > 0

    def test_affected_files_not_empty(
        self, analyzer, oomkilled_rca
    ):
        result = analyzer.analyze(
            "checkout-api", oomkilled_rca
        )
        assert len(result["affected_files"]) > 0


class TestImpactAnalyzerServices:

    def test_checkout_api_dependents(
        self, analyzer, oomkilled_rca
    ):
        result = analyzer.analyze(
            "checkout-api", oomkilled_rca
        )
        services_str = " ".join(
            result["affected_services"]
        )
        assert "payment" in services_str or \
               "order" in services_str

    def test_database_files_detected(
        self, analyzer, db_rca
    ):
        result = analyzer.analyze(
            "checkout-api", db_rca
        )
        files_str = " ".join(result["affected_files"])
        assert len(files_str) > 0

    def test_kubernetes_files_for_oomkilled(
        self, analyzer, oomkilled_rca
    ):
        result = analyzer.analyze(
            "checkout-api", oomkilled_rca
        )
        files_str = " ".join(result["affected_files"])
        assert "k8s" in files_str or \
               "yaml" in files_str or \
               "helm" in files_str