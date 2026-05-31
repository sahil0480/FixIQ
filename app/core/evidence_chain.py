"""Evidence Chain Analyzer for FixIQ.

Builds a step-by-step chain of evidence showing
exactly WHY and HOW an incident occurred.

This is the most novel feature of FixIQ.
No existing tool shows a complete evidence chain
with exact file + line numbers.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EvidenceItem:
    """Single piece of evidence in the chain."""
    timestamp: str
    source: str        # log, metric, trace, code
    severity: str      # INFO, WARNING, ERROR, CRITICAL
    message: str
    file: str | None = None
    line: int | None = None
    code_snippet: str | None = None


@dataclass
class EvidenceChain:
    """Complete evidence chain for an incident."""
    root_trigger: str
    items: list[EvidenceItem]
    affected_files: list[dict[str, Any]]
    summary: str
    confidence: float


class EvidenceChainAnalyzer:
    """Builds evidence chain from RCA output."""

    def analyze(
        self,
        rca_output: dict[str, Any],
        alert_data: dict[str, Any],
    ) -> EvidenceChain:
        """Build complete evidence chain."""
        evidence_items = []

        raw_entries = rca_output.get("evidence_entries", [])
        for entry in raw_entries:
            item = self._parse_evidence_entry(entry)
            if item:
                evidence_items.append(item)

        log_evidence = self._extract_log_evidence(rca_output)
        evidence_items.extend(log_evidence)

        alert_log_evidence = self._extract_alert_logs(alert_data)
        evidence_items.extend(alert_log_evidence)

        metric_evidence = self._extract_metric_evidence(alert_data)
        evidence_items.extend(metric_evidence)

        affected_files = self._extract_file_locations(
            rca_output, evidence_items
        )

        evidence_items.sort(key=lambda x: x.timestamp)

        root_trigger = self._identify_root_trigger(
            evidence_items, rca_output
        )

        summary = self._build_summary(
            root_trigger, evidence_items, affected_files
        )

        confidence = self._calculate_confidence(
            evidence_items, affected_files, alert_data
        )

        logger.info(
            "Built evidence chain: %d items, %d files, %.0f%% confidence",
            len(evidence_items),
            len(affected_files),
            confidence * 100,
        )

        return EvidenceChain(
            root_trigger=root_trigger,
            items=evidence_items,
            affected_files=affected_files,
            summary=summary,
            confidence=confidence,
        )

    def _parse_evidence_entry(
        self, entry: dict[str, Any]
    ) -> EvidenceItem | None:
        """Parse a single evidence entry from OpenSRE."""
        try:
            content = entry.get("content", "")
            timestamp = entry.get(
                "timestamp",
                datetime.now().isoformat()
            )
            source = entry.get("type", "log")

            severity = "INFO"
            if any(k in content.lower() for k in [
                "error", "exception", "failed", "failure"
            ]):
                severity = "ERROR"
            elif any(k in content.lower() for k in [
                "warning", "warn", "degraded"
            ]):
                severity = "WARNING"
            elif any(k in content.lower() for k in [
                "critical", "fatal", "crash"
            ]):
                severity = "CRITICAL"

            file_match = re.search(
                r'([a-zA-Z_/]+\.py)[:\s]+(\d+)', content
            )
            file_name = None
            line_num = None
            if file_match:
                file_name = file_match.group(1)
                line_num = int(file_match.group(2))

            return EvidenceItem(
                timestamp=timestamp,
                source=source,
                severity=severity,
                message=content[:200],
                file=file_name,
                line=line_num,
            )
        except Exception as exc:
            logger.warning(
                "Failed to parse evidence entry: %s", exc
            )
            return None

    def _extract_log_evidence(
        self, rca_output: dict[str, Any]
    ) -> list[EvidenceItem]:
        """Extract evidence from log-style RCA output."""
        items = []
        root_cause = rca_output.get("root_cause", "")
        report = rca_output.get("report", "")

        error_patterns = [
            r'(\w+Error|\w+Exception).*?(?:at|in)\s+'
            r'(\S+\.py)[:\s]+(\d+)',
            r'File "([^"]+\.py)", line (\d+)',
            r'(\w+\.py):(\d+):\s*(ERROR|WARNING|CRITICAL)',
        ]

        for pattern in error_patterns:
            matches = re.finditer(
                pattern, report, re.IGNORECASE
            )
            for match in matches:
                groups = match.groups()
                item = EvidenceItem(
                    timestamp=datetime.now().isoformat(),
                    source="log",
                    severity="ERROR",
                    message=match.group(0)[:200],
                    file=groups[-2] if len(groups) >= 2
                    else None,
                    line=int(groups[-1])
                    if groups[-1].isdigit() else None,
                )
                items.append(item)

        if root_cause and root_cause != "Unknown":
            items.append(EvidenceItem(
                timestamp=datetime.now().isoformat(),
                source="rca",
                severity="CRITICAL",
                message=root_cause,
            ))

        return items

    def _extract_alert_logs(
        self, alert_data: dict[str, Any]
    ) -> list[EvidenceItem]:
        """Extract evidence directly from alert log lines."""
        items = []
        logs = alert_data.get("logs", [])

        for log in logs:
            severity = "INFO"
            if log.startswith("CRITICAL"):
                severity = "CRITICAL"
            elif log.startswith("ERROR"):
                severity = "ERROR"
            elif log.startswith("WARNING"):
                severity = "WARNING"

            file_match = re.search(
                r'([a-zA-Z_/]+\.py):(\d+)', log
            )
            file_name = None
            line_num = None
            if file_match:
                file_name = file_match.group(1)
                line_num = int(file_match.group(2))

            items.append(EvidenceItem(
                timestamp=datetime.now().isoformat(),
                source="log",
                severity=severity,
                message=log[:200],
                file=file_name,
                line=line_num,
            ))

        return items

    def _extract_metric_evidence(
        self, alert_data: dict[str, Any]
    ) -> list[EvidenceItem]:
        """Extract evidence from alert metrics."""
        items = []
        metrics = alert_data.get("metrics", {})

        if not metrics:
            return items

        metric_checks = {
            "memory_usage_mb": (
                512, "Memory usage: {val}MB"
            ),
            "cpu_usage_pct": (
                90, "CPU usage: {val}%"
            ),
            "error_rate_pct": (
                10, "Error rate: {val}%"
            ),
            "active_connections": (
                150, "Active connections: {val}"
            ),
            "restart_count": (
                2, "Pod restart count: {val}"
            ),
            "latency_ms": (
                3000, "Latency: {val}ms"
            ),
        }

        for metric, (threshold, msg_template) in \
                metric_checks.items():
            value = metrics.get(metric)
            if value is not None and value > threshold:
                severity = (
                    "CRITICAL" if value > threshold * 1.5
                    else "ERROR"
                )
                items.append(EvidenceItem(
                    timestamp=datetime.now().isoformat(),
                    source="metric",
                    severity=severity,
                    message=msg_template.format(val=value),
                ))

        return items

    def _extract_file_locations(
        self,
        rca_output: dict[str, Any],
        evidence_items: list[EvidenceItem],
    ) -> list[dict[str, Any]]:
        """Extract exact file locations from evidence."""
        files = {}

        for item in evidence_items:
            if item.file:
                key = item.file
                if key not in files:
                    files[key] = {
                        "file": item.file,
                        "line": item.line,
                        "severity": item.severity,
                        "occurrences": 1,
                        "messages": [item.message],
                    }
                else:
                    files[key]["occurrences"] += 1
                    files[key]["messages"].append(
                        item.message
                    )

        severity_order = {
            "CRITICAL": 0,
            "ERROR": 1,
            "WARNING": 2,
            "INFO": 3
        }
        return sorted(
            files.values(),
            key=lambda x: severity_order.get(
                x["severity"], 4
            )
        )

    def _identify_root_trigger(
        self,
        items: list[EvidenceItem],
        rca_output: dict[str, Any],
    ) -> str:
        """Identify the root trigger of the incident."""
        root_cause = rca_output.get("root_cause", "")
        if root_cause and root_cause != "Unknown":
            return root_cause

        for item in items:
            if item.severity in ["CRITICAL", "ERROR"]:
                return item.message

        return "Root cause could not be determined"

    def _build_summary(
        self,
        root_trigger: str,
        items: list[EvidenceItem],
        affected_files: list[dict[str, Any]],
    ) -> str:
        """Build human readable summary."""
        error_count = sum(
            1 for i in items if i.severity == "ERROR"
        )
        critical_count = sum(
            1 for i in items if i.severity == "CRITICAL"
        )
        file_count = len(affected_files)

        return (
            f"Found {critical_count} critical and "
            f"{error_count} error events across "
            f"{file_count} files. "
            f"Root trigger: {root_trigger[:100]}"
        )

    def _calculate_confidence(
        self,
        items: list[EvidenceItem],
        affected_files: list[dict[str, Any]],
        alert_data: dict[str, Any] | None = None,
    ) -> float:
        """Calculate confidence in the evidence chain.

        Scores based on K8s data quality since we rarely
        have file/line numbers for container incidents.
        """
        score = 0.0

        # Base: evidence items collected
        if len(items) >= 5:
            score += 0.15
        elif len(items) >= 2:
            score += 0.10
        elif len(items) >= 1:
            score += 0.05

        # Clear critical root cause (not "Unknown")
        rca_items = [
            i for i in items
            if i.source == "rca" and i.severity == "CRITICAL"
        ]
        if rca_items:
            score += 0.20

        # Real K8s data — check pod_details and service_info
        pod_details = {}
        service_info = {}
        if alert_data:
            pod_details = alert_data.get("pod_details", {})
            service_info = alert_data.get("service_info", {})

        has_exit_code = bool(pod_details.get("exit_code"))
        has_memory_limit = bool(
            pod_details.get("memory_limit")
            or service_info.get("memory_limit")
        )
        has_restart_count = bool(
            pod_details.get("restart_count")
            or service_info.get("restart_count")
        )

        # Exit code — we know HOW it died
        if has_exit_code:
            score += 0.15

        # Memory limit — we know the resource config
        if has_memory_limit:
            score += 0.15

        # Restart count — how long it has been failing
        if has_restart_count:
            restart_count = int(
                pod_details.get("restart_count")
                or service_info.get("restart_count", 0)
            )
            if restart_count >= 10:
                score += 0.15
            elif restart_count >= 3:
                score += 0.10
            else:
                score += 0.05

        # OOMKilled confirmed (exit 137) — definitive cause
        if pod_details.get("exit_code") == 137:
            score += 0.20

        # File locations found (rare but valuable)
        if len(affected_files) >= 1:
            score += 0.10

        return round(min(1.0, score), 2)


def display_evidence_chain(chain: EvidenceChain) -> None:
    """Display evidence chain in terminal."""
    BOLD = "\033[1m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    GREEN = "\033[92m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    print(f"\n{BOLD}{'─' * 70}{RESET}")
    print(f"{BOLD}  🔍 EVIDENCE CHAIN{RESET}")
    print(f"{BOLD}{'─' * 70}{RESET}")

    print(f"\n  {BOLD}Root Trigger:{RESET}")
    print(f"  {chain.root_trigger}")
    print(
        f"  {DIM}Confidence: "
        f"{int(chain.confidence * 100)}%{RESET}"
    )

    if chain.items:
        print(f"\n  {BOLD}Evidence Timeline:{RESET}")
        for i, item in enumerate(chain.items[:8], 1):
            color = (
                RED if item.severity == "CRITICAL" else
                YELLOW if item.severity == "ERROR" else
                GREEN
            )
            print(
                f"\n  {i}. [{color}{item.severity}{RESET}] "
                f"{DIM}{item.source.upper()}{RESET} "
                f"{DIM}{item.timestamp[11:19]}{RESET}"
            )
            print(f"     {item.message[:100]}")
            if item.file and item.line:
                print(
                    f"     {BOLD}→ {item.file}:"
                    f"{item.line}{RESET}"
                )

    if chain.affected_files:
        print(f"\n  {BOLD}Affected Files:{RESET}")
        for f in chain.affected_files[:5]:
            line_str = (
                f":{f['line']}" if f.get('line') else ""
            )
            print(
                f"  • {f['file']}{line_str}  "
                f"({f['occurrences']} occurrence(s))"
            )

    print(f"\n  {BOLD}Summary:{RESET}")
    print(f"  {chain.summary}")
    print(f"\n{BOLD}{'─' * 70}{RESET}")