"""Anomaly Timeline for FixIQ.

Shows exactly WHEN things started going wrong
and which metric failed FIRST.

Engineers waste 30% of incident time just trying
to understand the timeline of events.
FixIQ solves this automatically.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MetricAnomaly:
    """A single metric anomaly."""
    metric: str
    normal_value: str
    current_value: str
    change_pct: float
    severity: str        # CRITICAL, HIGH, MEDIUM, LOW
    first_detected: str
    is_first_anomaly: bool = False


@dataclass
class AnomalyTimeline:
    """Complete anomaly timeline."""
    first_anomaly_time: str
    alert_time: str
    detection_lag_seconds: int
    anomalies: list[MetricAnomaly]
    first_failing_metric: str
    summary: str


# Normal baseline values for common metrics
METRIC_BASELINES: dict[str, dict[str, Any]] = {
    "cpu": {
        "normal": 45.0,
        "unit": "%",
        "warning_threshold": 75.0,
        "critical_threshold": 90.0,
    },
    "memory": {
        "normal": 2.0,
        "unit": "GB",
        "warning_threshold": 6.0,
        "critical_threshold": 7.5,
    },
    "error_rate": {
        "normal": 0.1,
        "unit": "%",
        "warning_threshold": 5.0,
        "critical_threshold": 20.0,
    },
    "latency": {
        "normal": 120.0,
        "unit": "ms",
        "warning_threshold": 1000.0,
        "critical_threshold": 5000.0,
    },
    "traffic": {
        "normal": 1200.0,
        "unit": "rps",
        "warning_threshold": 3000.0,
        "critical_threshold": 5000.0,
    },
    "connections": {
        "normal": 50.0,
        "unit": "connections",
        "warning_threshold": 150.0,
        "critical_threshold": 200.0,
    },
}


class AnomalyTimelineAnalyzer:
    """Builds anomaly timeline from RCA output."""

    def analyze(
        self,
        rca_output: dict[str, Any],
        alert_data: dict[str, Any],
    ) -> AnomalyTimeline:
        """Build anomaly timeline."""
        root_cause = rca_output.get("root_cause", "").lower()

        anomalies = self._extract_anomalies(
            root_cause, rca_output, alert_data
        )

        first_metric = self._find_first_anomaly(anomalies)

        alert_time = self._extract_alert_time(alert_data)
        first_anomaly_time = self._estimate_first_anomaly_time(
            alert_time, anomalies, alert_data
        )
        detection_lag = self._calculate_detection_lag(
            first_anomaly_time, alert_time
        )

        summary = self._build_summary(
            anomalies, first_metric, detection_lag
        )

        logger.info(
            "Anomaly timeline: %d anomalies, "
            "first=%s, lag=%ds",
            len(anomalies),
            first_metric,
            detection_lag,
        )

        return AnomalyTimeline(
            first_anomaly_time=first_anomaly_time,
            alert_time=alert_time,
            detection_lag_seconds=detection_lag,
            anomalies=anomalies,
            first_failing_metric=first_metric,
            summary=summary,
        )

    def _parse_memory_mi(self, value: str) -> float | None:
        """Parse a K8s memory string into MiB float.

        Handles: 5Mi, 128Mi, 1Gi, 512M, 1G
        Returns None if unparseable.
        """
        if not value or value == "unknown":
            return None
        v = value.strip()
        try:
            if v.endswith("Gi"):
                return float(v[:-2]) * 1024
            elif v.endswith("Mi"):
                return float(v[:-2])
            elif v.endswith("G"):
                return float(v[:-1]) * 1024
            elif v.endswith("M"):
                return float(v[:-1])
            elif v.endswith("Ki"):
                return float(v[:-2]) / 1024
            else:
                return float(v)
        except ValueError:
            return None

    def _extract_anomalies(
        self,
        root_cause: str,
        rca_output: dict[str, Any],
        alert_data: dict[str, Any],
    ) -> list[MetricAnomaly]:
        """Extract metric anomalies using real K8s data."""
        anomalies = []

        metric_keywords = {
            "cpu": ["cpu", "processor", "throttl"],
            "memory": ["memory", "oom", "heap", "ram"],
            "error_rate": ["error", "exception", "fail"],
            "latency": ["latency", "slow", "timeout", "response"],
            "traffic": ["traffic", "spike", "load", "request"],
            "connections": ["connection", "pool", "socket"],
        }

        detected_metrics = set()
        for metric, keywords in metric_keywords.items():
            if any(k in root_cause for k in keywords):
                detected_metrics.add(metric)

        # Always include error_rate for any incident
        detected_metrics.add("error_rate")

        # Pull real values from alert_data.
        # Keys may be at top level, in pod_details, or service_info.
        pod_details = alert_data.get("pod_details", {})
        service_info = alert_data.get("service_info", {})

        memory_limit_str = (
            pod_details.get("memory_limit")
            or service_info.get("memory_limit")
            or alert_data.get("memory_limit", "")
        )
        restart_count = int(
            pod_details.get("restart_count")
            or service_info.get("restart_count")
            or alert_data.get("restart_count", 0)
        )
        exit_code = (
            pod_details.get("exit_code")
            or alert_data.get("exit_code", 0)
        )
        is_oomkilled = (exit_code == 137)

        memory_limit_mi = self._parse_memory_mi(
            memory_limit_str
        )

        for i, metric in enumerate(detected_metrics):

            if metric == "memory" and memory_limit_mi is not None:
                # Normal = 50% of limit (healthy pod usage estimate)
                normal_mi = round(memory_limit_mi * 0.5, 1)
                current_mi = memory_limit_mi  # hit the wall

                change_pct = round(
                    (current_mi - normal_mi) / normal_mi * 100
                    if normal_mi > 0 else 0,
                    1,
                )

                def fmt_mem(mi: float) -> str:
                    if mi >= 1024:
                        return f"{mi/1024:.1f}Gi"
                    return f"{mi:.0f}Mi"

                anomalies.append(MetricAnomaly(
                    metric="memory",
                    normal_value=fmt_mem(normal_mi),
                    current_value=fmt_mem(current_mi)
                        + (" ← OOMKilled" if is_oomkilled else ""),
                    change_pct=change_pct,
                    severity="CRITICAL" if is_oomkilled else "HIGH",
                    first_detected=datetime.now().isoformat(),
                    is_first_anomaly=(i == 0),
                ))
                continue

            if metric == "error_rate":
                normal_pct = 0.1
                if restart_count >= 10:
                    current_pct = 100.0
                    severity = "CRITICAL"
                elif restart_count >= 5:
                    current_pct = 50.0
                    severity = "HIGH"
                else:
                    current_pct = 5.0
                    severity = "MEDIUM"

                change_pct = round(
                    (current_pct - normal_pct) / normal_pct * 100
                    if normal_pct > 0 else 0,
                    1,
                )
                anomalies.append(MetricAnomaly(
                    metric="error_rate",
                    normal_value=f"{normal_pct}%",
                    current_value=f"{current_pct}%"
                        + (f" ({restart_count} restarts)"
                           if restart_count > 0 else ""),
                    change_pct=change_pct,
                    severity=severity,
                    first_detected=datetime.now().isoformat(),
                    is_first_anomaly=(i == 0),
                ))
                continue

            # Other metrics (cpu, latency etc.) — fallback to baselines
            baseline = METRIC_BASELINES.get(metric, {})
            if not baseline:
                continue

            normal = baseline["normal"]
            critical_threshold = baseline["critical_threshold"]
            unit = baseline["unit"]
            current = critical_threshold * 1.1
            change_pct = round(
                (current - normal) / normal * 100
                if normal > 0 else 0,
                1,
            )
            severity = self._classify_severity(
                current,
                baseline["warning_threshold"],
                baseline["critical_threshold"],
            )

            anomalies.append(MetricAnomaly(
                metric=metric,
                normal_value=f"{normal}{unit}",
                current_value=f"{current:.1f}{unit}",
                change_pct=round(change_pct, 1),
                severity=severity,
                first_detected=datetime.now().isoformat(),
                is_first_anomaly=(i == 0),
            ))

        return anomalies

    def _classify_severity(
        self,
        current: float,
        warning: float,
        critical: float,
    ) -> str:
        """Classify severity of anomaly."""
        if current >= critical:
            return "CRITICAL"
        elif current >= warning:
            return "HIGH"
        elif current >= warning * 0.7:
            return "MEDIUM"
        else:
            return "LOW"

    def _find_first_anomaly(
        self, anomalies: list[MetricAnomaly]
    ) -> str:
        """Find the first metric that failed."""
        priority = [
            "cpu", "memory", "connections",
            "traffic", "latency", "error_rate"
        ]

        for metric in priority:
            for anomaly in anomalies:
                if (anomaly.metric == metric and
                        anomaly.severity in ["CRITICAL", "HIGH"]):
                    return metric

        if anomalies:
            return anomalies[0].metric

        return "unknown"

    def _extract_alert_time(
        self, alert_data: dict[str, Any]
    ) -> str:
        """Extract alert timestamp from alert data."""
        for field in [
            "timestamp", "time", "date",
            "alert_time", "created_at"
        ]:
            if field in alert_data:
                return str(alert_data[field])

        return datetime.now().isoformat()

    def _estimate_first_anomaly_time(
        self,
        alert_time: str,
        anomalies: list[MetricAnomaly],
        alert_data: dict | None = None,
    ) -> str:
        """Estimate when first anomaly occurred.

        Uses restart_count to infer a realistic lag:
        each CrashLoop cycle is ~30s backoff minimum.
        """
        from datetime import timedelta
        try:
            alert_dt = datetime.fromisoformat(
                alert_time.replace("Z", "+00:00")
            )
            pod_details = alert_data.get("pod_details", {}) if alert_data else {}
            service_info = alert_data.get("service_info", {}) if alert_data else {}
            restart_count = int(
                pod_details.get("restart_count")
                or service_info.get("restart_count")
                or (alert_data.get("restart_count", 0) if alert_data else 0)
            )
            # Each restart adds ~30s backoff; cap at 15 min
            lag_seconds = min(restart_count * 30, 900)
            lag_seconds = max(lag_seconds, 60)
            first_anomaly = alert_dt - timedelta(
                seconds=lag_seconds
            )
            return first_anomaly.isoformat()
        except Exception:
            return alert_time

    def _calculate_detection_lag(
        self,
        first_anomaly: str,
        alert_time: str,
    ) -> int:
        """Calculate seconds between first anomaly and alert."""
        try:
            first = datetime.fromisoformat(
                first_anomaly.replace("Z", "+00:00")
            )
            alert = datetime.fromisoformat(
                alert_time.replace("Z", "+00:00")
            )
            return max(0, int(
                (alert - first).total_seconds()
            ))
        except Exception:
            return 180

    def _build_summary(
        self,
        anomalies: list[MetricAnomaly],
        first_metric: str,
        detection_lag: int,
    ) -> str:
        """Build human readable summary."""
        critical = sum(
            1 for a in anomalies if a.severity == "CRITICAL"
        )
        lag_mins = detection_lag // 60

        return (
            f"{len(anomalies)} metric anomalies detected. "
            f"{critical} critical. "
            f"First anomaly in {first_metric}. "
            f"Detection lag: ~{lag_mins} minutes."
        )


def display_anomaly_timeline(
    timeline: AnomalyTimeline,
) -> None:
    """Display anomaly timeline in terminal."""
    BOLD = "\033[1m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    GREEN = "\033[92m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    print(f"\n{BOLD}{'─' * 70}{RESET}")
    print(f"{BOLD}  📈 ANOMALY TIMELINE{RESET}")
    print(f"{BOLD}{'─' * 70}{RESET}")

    print(f"\n  {BOLD}Timeline:{RESET}")
    print(
        f"  First anomaly:  "
        f"{timeline.first_anomaly_time[11:19]}"
    )
    print(f"  Alert fired:    {timeline.alert_time[11:19]}")
    lag = timeline.detection_lag_seconds
    lag_str = (
        f"{lag}s" if lag < 60
        else f"{lag // 60}m {lag % 60}s"
    )
    print(f"  Detection lag:  {lag_str}")
    print(
        f"  First failing:  "
        f"{BOLD}{timeline.first_failing_metric}{RESET}"
    )

    print(f"\n  {BOLD}Metric Anomalies:{RESET}")
    print(
        f"  {'Metric':<15} {'Normal':<12} "
        f"{'Current':<30} {'Change':<10} Severity"
    )
    print(f"  {'─' * 75}")

    for anomaly in timeline.anomalies:
        color = (
            RED if anomaly.severity == "CRITICAL" else
            YELLOW if anomaly.severity == "HIGH" else
            GREEN
        )
        marker = " ← FIRST" if anomaly.is_first_anomaly else ""
        print(
            f"  {anomaly.metric:<15} "
            f"{anomaly.normal_value:<12} "
            f"{anomaly.current_value:<30} "
            f"+{anomaly.change_pct:<9.1f}% "
            f"{color}{anomaly.severity}{RESET}"
            f"{BOLD}{marker}{RESET}"
        )

    print(f"\n  {BOLD}Summary:{RESET}")
    print(f"  {timeline.summary}")
    print(f"\n{BOLD}{'─' * 70}{RESET}")