"""Tests for Evidence Chain Analyzer."""

from __future__ import annotations

import pytest
from app.core.evidence_chain import (
    EvidenceChainAnalyzer,
    EvidenceItem,
    EvidenceChain,
)


# ─── Fixtures ───────────────────────────────────────────

@pytest.fixture
def oomkilled_alert():
    return {
        "title": "Pod OOMKilled in checkout-api",
        "service": "checkout-api",
        "timestamp": "2026-05-25T16:00:00Z",
        "metrics": {
            "memory_usage_mb": 980,
            "memory_limit_mb": 512,
            "restart_count": 3,
            "error_rate_pct": 45,
        },
        "logs": [],
    }


@pytest.fixture
def db_connection_alert():
    return {
        "title": "Database connection pool exhausted",
        "service": "checkout-api",
        "timestamp": "2026-05-25T16:00:00Z",
        "metrics": {
            "active_connections": 200,
            "max_connections": 200,
            "error_rate_pct": 34,
            "latency_ms": 8400,
        },
        "logs": [
            "ERROR checkout.py:184 DatabaseConnectionError: "
            "max connections exceeded",
            "ERROR pool.py:92 ConnectionPool: "
            "all connections busy",
            "WARNING checkout.py:201 "
            "Retrying connection attempt 3/3",
        ],
    }


@pytest.fixture
def cascade_alert():
    return {
        "title": "Multiple service failures detected",
        "service": "api-gateway",
        "timestamp": "2026-05-25T16:00:00Z",
        "metrics": {
            "error_rate_pct": 67,
            "latency_ms": 12000,
        },
        "logs": [
            "CRITICAL api-gateway.py:45 "
            "Multiple upstream failures",
            "ERROR checkout.py:184 "
            "DatabaseConnectionError: pool exhausted",
            "ERROR payment.py:67 "
            "Upstream checkout-api timeout",
            "ERROR order.py:123 "
            "Service checkout-api unavailable",
        ],
    }


@pytest.fixture
def empty_rca():
    return {
        "root_cause": "Unknown",
        "evidence_entries": [],
        "report": "",
    }


@pytest.fixture
def db_rca():
    return {
        "root_cause": "Database connection pool exhausted",
        "evidence_entries": [],
        "report": "",
    }


@pytest.fixture
def analyzer():
    return EvidenceChainAnalyzer()


# ─── Tests ──────────────────────────────────────────────

class TestEvidenceChainBasic:
    """Basic evidence chain tests."""

    def test_returns_evidence_chain(
        self, analyzer, db_rca, db_connection_alert
    ):
        """Should return EvidenceChain object."""
        result = analyzer.analyze(db_rca, db_connection_alert)
        assert isinstance(result, EvidenceChain)

    def test_root_trigger_from_rca(
        self, analyzer, db_rca, db_connection_alert
    ):
        """Root trigger should come from RCA output."""
        result = analyzer.analyze(db_rca, db_connection_alert)
        assert "database" in result.root_trigger.lower() or \
               "connection" in result.root_trigger.lower()

    def test_root_trigger_fallback(
        self, analyzer, empty_rca, oomkilled_alert
    ):
        """Should fall back to alert title when RCA unknown."""
        result = analyzer.analyze(empty_rca, oomkilled_alert)
        assert result.root_trigger != ""

    def test_confidence_between_zero_and_one(
        self, analyzer, db_rca, db_connection_alert
    ):
        """Confidence should always be between 0 and 1."""
        result = analyzer.analyze(db_rca, db_connection_alert)
        assert 0.0 <= result.confidence <= 1.0

    def test_summary_is_not_empty(
        self, analyzer, db_rca, db_connection_alert
    ):
        """Summary should always be provided."""
        result = analyzer.analyze(db_rca, db_connection_alert)
        assert len(result.summary) > 0


class TestEvidenceChainLogs:
    """Tests for log extraction."""

    def test_extracts_log_lines(
        self, analyzer, db_rca, db_connection_alert
    ):
        """Should extract evidence from alert log lines."""
        result = analyzer.analyze(db_rca, db_connection_alert)
        sources = [i.source for i in result.items]
        assert "log" in sources

    def test_extracts_file_and_line(
        self, analyzer, db_rca, db_connection_alert
    ):
        """Should extract file name and line number from logs."""
        result = analyzer.analyze(db_rca, db_connection_alert)
        files_with_lines = [
            i for i in result.items
            if i.file and i.line
        ]
        assert len(files_with_lines) > 0

    def test_detects_correct_file(
        self, analyzer, db_rca, db_connection_alert
    ):
        """Should detect checkout.py as affected file."""
        result = analyzer.analyze(db_rca, db_connection_alert)
        file_names = [
            i.file for i in result.items if i.file
        ]
        assert any("checkout" in f for f in file_names)

    def test_detects_correct_line_number(
        self, analyzer, db_rca, db_connection_alert
    ):
        """Should detect line 184 in checkout.py."""
        result = analyzer.analyze(db_rca, db_connection_alert)
        lines = [
            i.line for i in result.items
            if i.file and "checkout" in i.file
        ]
        assert 184 in lines

    def test_detects_pool_file(
        self, analyzer, db_rca, db_connection_alert
    ):
        """Should detect pool.py as affected file."""
        result = analyzer.analyze(db_rca, db_connection_alert)
        file_names = [
            i.file for i in result.items if i.file
        ]
        assert any("pool" in f for f in file_names)

    def test_cascade_alert_detects_multiple_files(
        self, analyzer, empty_rca, cascade_alert
    ):
        """Should detect 4 files in cascade alert."""
        result = analyzer.analyze(empty_rca, cascade_alert)
        assert len(result.affected_files) >= 3

    def test_detects_severity_correctly(
        self, analyzer, db_rca, db_connection_alert
    ):
        """ERROR logs should be classified as ERROR severity."""
        result = analyzer.analyze(db_rca, db_connection_alert)
        error_items = [
            i for i in result.items
            if i.severity == "ERROR"
        ]
        assert len(error_items) > 0

    def test_detects_warning_severity(
        self, analyzer, db_rca, db_connection_alert
    ):
        """WARNING logs should be classified as WARNING."""
        result = analyzer.analyze(db_rca, db_connection_alert)
        warning_items = [
            i for i in result.items
            if i.severity == "WARNING"
        ]
        assert len(warning_items) > 0


class TestEvidenceChainMetrics:
    """Tests for metric extraction."""

    def test_extracts_metrics(
        self, analyzer, db_rca, db_connection_alert
    ):
        """Should extract metric anomalies."""
        result = analyzer.analyze(db_rca, db_connection_alert)
        metric_items = [
            i for i in result.items
            if i.source == "metric"
        ]
        assert len(metric_items) > 0

    def test_high_error_rate_is_critical(
        self, analyzer, db_rca, db_connection_alert
    ):
        """Error rate 34% should be CRITICAL."""
        result = analyzer.analyze(db_rca, db_connection_alert)
        critical_metrics = [
            i for i in result.items
            if i.source == "metric" and
            i.severity == "CRITICAL" and
            "error" in i.message.lower()
        ]
        assert len(critical_metrics) > 0

    def test_high_latency_detected(
        self, analyzer, db_rca, db_connection_alert
    ):
        """Latency 8400ms should be detected as anomaly."""
        result = analyzer.analyze(db_rca, db_connection_alert)
        latency_items = [
            i for i in result.items
            if "latency" in i.message.lower() or
            "8400" in i.message
        ]
        assert len(latency_items) > 0

    def test_oomkilled_memory_detected(
        self, analyzer, empty_rca, oomkilled_alert
    ):
        """Memory 980MB should be detected as anomaly."""
        result = analyzer.analyze(empty_rca, oomkilled_alert)
        memory_items = [
            i for i in result.items
            if "memory" in i.message.lower() or
            "980" in i.message
        ]
        assert len(memory_items) > 0


class TestEvidenceChainConfidence:
    """Tests for confidence scoring."""

    def test_confidence_higher_with_files(
        self, analyzer, db_rca, db_connection_alert
    ):
        """Confidence should be higher when files detected."""
        result_with_logs = analyzer.analyze(
            db_rca, db_connection_alert
        )
        result_no_logs = analyzer.analyze(
            db_rca, {"title": "test", "metrics": {}}
        )
        assert (
            result_with_logs.confidence >=
            result_no_logs.confidence
        )

    def test_confidence_never_exceeds_one(
        self, analyzer, empty_rca, cascade_alert
    ):
        """Confidence should never exceed 1.0."""
        result = analyzer.analyze(empty_rca, cascade_alert)
        assert result.confidence <= 1.0

    def test_confidence_never_below_zero(
        self, analyzer, empty_rca, oomkilled_alert
    ):
        """Confidence should never go below 0.0."""
        result = analyzer.analyze(empty_rca, oomkilled_alert)
        assert result.confidence >= 0.0