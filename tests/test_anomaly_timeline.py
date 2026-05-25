"""Tests for Anomaly Timeline Analyzer."""

from __future__ import annotations

import pytest
from app.core.anomaly_timeline import (
    AnomalyTimelineAnalyzer,
    AnomalyTimeline,
)


@pytest.fixture
def analyzer():
    return AnomalyTimelineAnalyzer()


@pytest.fixture
def oomkilled_rca():
    return {"root_cause": "Pod OOMKilled memory limit exceeded"}


@pytest.fixture
def db_rca():
    return {"root_cause": "Database connection pool exhausted"}


@pytest.fixture
def oomkilled_alert():
    return {
        "timestamp": "2026-05-25T16:00:00Z",
        "metrics": {
            "memory_usage_mb": 980,
            "error_rate_pct": 45,
        }
    }


@pytest.fixture
def db_alert():
    return {
        "timestamp": "2026-05-25T16:00:00Z",
        "metrics": {
            "active_connections": 200,
            "error_rate_pct": 34,
            "latency_ms": 8400,
        }
    }


class TestAnomalyTimelineBasic:

    def test_returns_anomaly_timeline(
        self, analyzer, oomkilled_rca, oomkilled_alert
    ):
        result = analyzer.analyze(
            oomkilled_rca, oomkilled_alert
        )
        assert isinstance(result, AnomalyTimeline)

    def test_has_anomalies(
        self, analyzer, oomkilled_rca, oomkilled_alert
    ):
        result = analyzer.analyze(
            oomkilled_rca, oomkilled_alert
        )
        assert len(result.anomalies) > 0

    def test_first_failing_metric_set(
        self, analyzer, oomkilled_rca, oomkilled_alert
    ):
        result = analyzer.analyze(
            oomkilled_rca, oomkilled_alert
        )
        assert result.first_failing_metric != ""

    def test_summary_not_empty(
        self, analyzer, db_rca, db_alert
    ):
        result = analyzer.analyze(db_rca, db_alert)
        assert len(result.summary) > 0

    def test_detection_lag_non_negative(
        self, analyzer, db_rca, db_alert
    ):
        result = analyzer.analyze(db_rca, db_alert)
        assert result.detection_lag_seconds >= 0


class TestAnomalyTimelineMetrics:

    def test_memory_detected_for_oomkilled(
        self, analyzer, oomkilled_rca, oomkilled_alert
    ):
        result = analyzer.analyze(
            oomkilled_rca, oomkilled_alert
        )
        metrics = [a.metric for a in result.anomalies]
        assert "memory" in metrics

    def test_connections_detected_for_db(
        self, analyzer, db_rca, db_alert
    ):
        result = analyzer.analyze(db_rca, db_alert)
        metrics = [a.metric for a in result.anomalies]
        assert "connections" in metrics or \
               "error_rate" in metrics

    def test_anomaly_has_normal_value(
        self, analyzer, oomkilled_rca, oomkilled_alert
    ):
        result = analyzer.analyze(
            oomkilled_rca, oomkilled_alert
        )
        for anomaly in result.anomalies:
            assert anomaly.normal_value != ""

    def test_anomaly_has_current_value(
        self, analyzer, oomkilled_rca, oomkilled_alert
    ):
        result = analyzer.analyze(
            oomkilled_rca, oomkilled_alert
        )
        for anomaly in result.anomalies:
            assert anomaly.current_value != ""

    def test_anomaly_severity_valid(
        self, analyzer, db_rca, db_alert
    ):
        result = analyzer.analyze(db_rca, db_alert)
        valid = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
        for anomaly in result.anomalies:
            assert anomaly.severity in valid