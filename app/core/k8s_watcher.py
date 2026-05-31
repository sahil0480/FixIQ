"""Kubernetes Event Watcher for FixIQ.

Watches Kubernetes events in real time and
automatically detects incidents.

When an incident is detected it automatically
triggers the full FixIQ pipeline.

Smart deduplication:
- Ignores events older than 5 minutes on startup
- Tracks seen event IDs to avoid reprocessing
- Tracks resolved services to avoid re-investigating
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Events that indicate an incident
INCIDENT_EVENTS = {
    "OOMKilling": "critical",
    "OOMKilled": "critical",
    "BackOff": "high",
    "CrashLoopBackOff": "critical",
    "Failed": "high",
    "Killing": "high",
    "Unhealthy": "medium",
    "NodeNotReady": "critical",
    "Evicted": "high",
    "FailedScheduling": "medium",
    "ImagePullBackOff": "high",
    "ErrImagePull": "high",
}

# How long to ignore a resolved service (seconds)
RESOLVED_COOLDOWN = 600  # 10 minutes

# Max age of events to process on startup (seconds)
STARTUP_EVENT_MAX_AGE = 300  # 5 minutes


@dataclass
class K8sIncident:
    """A detected Kubernetes incident."""
    id: str
    timestamp: str
    service: str
    namespace: str
    pod: str
    reason: str
    message: str
    severity: str
    raw_event: dict[str, Any]


class K8sWatcher:
    """Watches Kubernetes events in real time."""

    def __init__(
        self,
        namespace: str = "default",
        poll_interval: int = 5,
    ) -> None:
        self.namespace = namespace
        self.poll_interval = poll_interval
        self._seen_events: set[str] = set()
        self._resolved_services: dict[str, float] = {}
        self._startup_time = time.time()
        self._is_startup = True
        self._running = False

    def watch(
        self,
        on_incident: Callable[[K8sIncident], None],
    ) -> None:
        """Watch for incidents and call callback."""
        self._running = True

        print(f"\n  👀 Watching Kubernetes events...")
        print(f"  Namespace: {self.namespace}")
        print(f"  Poll interval: {self.poll_interval}s")
        print(f"  Press Ctrl+C to stop\n")

        self._seed_seen_events()
        self._is_startup = False

        while self._running:
            try:
                incidents = self._check_for_incidents()
                for incident in incidents:
                    on_incident(incident)
                time.sleep(self.poll_interval)
            except KeyboardInterrupt:
                print("\n  Stopping watcher...")
                self._running = False
                break
            except Exception as exc:
                logger.warning(
                    "Watcher error: %s", exc
                )
                time.sleep(self.poll_interval)

    def _seed_seen_events(self) -> None:
        """Mark existing old events as seen on startup."""
        try:
            result = subprocess.run(
                [
                    "kubectl", "get", "events",
                    "-n", self.namespace,
                    "--sort-by=.lastTimestamp",
                    "-o", "json",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                return

            data = json.loads(result.stdout)
            events = data.get("items", [])
            seeded = 0

            now = datetime.now(timezone.utc)

            for event in events:
                event_type = event.get("type", "")
                if event_type != "Warning":
                    continue

                metadata = event.get("metadata", {})
                event_id = metadata.get("uid", "")
                if not event_id:
                    continue

                last_timestamp = event.get(
                    "lastTimestamp", ""
                )
                if last_timestamp:
                    try:
                        event_time = datetime.fromisoformat(
                            last_timestamp.replace(
                                "Z", "+00:00"
                            )
                        )
                        age = (
                            now - event_time
                        ).total_seconds()

                        if age > STARTUP_EVENT_MAX_AGE:
                            self._seen_events.add(event_id)
                            seeded += 1
                    except Exception:
                        self._seen_events.add(event_id)
                        seeded += 1
                else:
                    self._seen_events.add(event_id)
                    seeded += 1

            if seeded > 0:
                print(
                    f"  [Startup] Marked {seeded} old "
                    f"events as seen — only new incidents "
                    f"will trigger investigations"
                )

        except Exception as exc:
            logger.warning(
                "Failed to seed seen events: %s", exc
            )

    def mark_resolved(self, service: str) -> None:
        """Mark a service as resolved."""
        self._resolved_services[service] = time.time()
        logger.info(
            "Marked %s as resolved for %ds",
            service,
            RESOLVED_COOLDOWN,
        )

    def is_resolved(self, service: str) -> bool:
        """Check if service was recently resolved."""
        if service not in self._resolved_services:
            return False
        age = time.time() - self._resolved_services[service]
        if age > RESOLVED_COOLDOWN:
            del self._resolved_services[service]
            return False
        return True

    def stop(self) -> None:
        """Stop watching."""
        self._running = False

    def _check_for_incidents(
        self,
    ) -> list[K8sIncident]:
        """Check for new incidents in K8s events."""
        incidents = []

        try:
            result = subprocess.run(
                [
                    "kubectl", "get", "events",
                    "-n", self.namespace,
                    "--sort-by=.lastTimestamp",
                    "-o", "json",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                return []

            data = json.loads(result.stdout)
            events = data.get("items", [])

            for event in events:
                incident = self._process_event(event)
                if incident:
                    incidents.append(incident)

        except Exception as exc:
            logger.warning(
                "Failed to check events: %s", exc
            )

        return incidents

    def _process_event(
        self, event: dict[str, Any]
    ) -> K8sIncident | None:
        """Process a single K8s event."""
        reason = event.get("reason", "")
        event_type = event.get("type", "")

        if event_type != "Warning":
            return None

        severity = INCIDENT_EVENTS.get(reason)
        if not severity:
            return None

        metadata = event.get("metadata", {})
        event_id = metadata.get("uid", "")

        if not event_id or event_id in self._seen_events:
            return None

        last_timestamp = event.get("lastTimestamp", "")
        if last_timestamp:
            try:
                event_time = datetime.fromisoformat(
                    last_timestamp.replace("Z", "+00:00")
                )
                now = datetime.now(timezone.utc)
                age = (now - event_time).total_seconds()

                if self._is_startup and \
                        age > STARTUP_EVENT_MAX_AGE:
                    self._seen_events.add(event_id)
                    return None

            except Exception:
                pass

        self._seen_events.add(event_id)

        involved = event.get("involvedObject", {})
        service = involved.get("name", "unknown")
        service_name = self._extract_service_name(service)

        if self.is_resolved(service_name):
            logger.info(
                "Skipping %s — recently resolved",
                service_name,
            )
            return None

        message = event.get("message", "")
        namespace = involved.get(
            "namespace", self.namespace
        )
        timestamp = event.get(
            "lastTimestamp",
            datetime.now().isoformat()
        )

        pod = ""
        if involved.get("kind") == "Pod":
            pod = service

        return K8sIncident(
            id=event_id,
            timestamp=timestamp,
            service=service_name,
            namespace=namespace,
            pod=pod,
            reason=reason,
            message=message,
            severity=severity,
            raw_event=event,
        )

    def _extract_service_name(
        self, pod_name: str
    ) -> str:
        """Extract service name from pod name."""
        parts = pod_name.split("-")
        if len(parts) > 2:
            return "-".join(parts[:-2])
        return pod_name

    def get_pod_details(
        self, service_name: str
    ) -> dict[str, Any]:
        """Get real pod details for a service.

        Prefers the unhealthy/newest pod over old
        healthy pods left running during rolling updates.
        """
        try:
            result = subprocess.run(
                [
                    "kubectl", "get", "pods",
                    "-n", self.namespace,
                    "-l", f"app={service_name}",
                    "-o", "json",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                return {}

            data = json.loads(result.stdout)
            items = data.get("items", [])
            if not items:
                return {}

            # Sort by creationTimestamp — newest first
            items.sort(
                key=lambda p: p.get(
                    "metadata", {}
                ).get("creationTimestamp", ""),
                reverse=True,
            )

            # Prefer unhealthy pod over healthy one
            # (rolling update leaves old healthy pod running)
            def is_unhealthy(p: dict) -> bool:
                phase = p.get("status", {}).get(
                    "phase", ""
                )
                cs = p.get("status", {}).get(
                    "containerStatuses", [{}]
                )
                c = cs[0] if cs else {}
                exit_code = (
                    c.get("lastState", {})
                    .get("terminated", {})
                    .get("exitCode", 0)
                )
                ready = c.get("ready", True)
                return (
                    phase in ("Failed", "Pending") or
                    not ready or
                    exit_code != 0 or
                    c.get("restartCount", 0) > 0
                )

            unhealthy = [p for p in items if is_unhealthy(p)]
            pod = unhealthy[0] if unhealthy else items[0]

            status = pod.get("status", {})
            spec = pod.get("spec", {})
            containers = spec.get("containers", [{}])
            container = containers[0] \
                if containers else {}
            resources = container.get("resources", {})
            limits = resources.get("limits", {})
            requests = resources.get("requests", {})

            container_statuses = status.get(
                "containerStatuses", [{}]
            )
            cs = container_statuses[0] \
                if container_statuses else {}
            last_state = cs.get("lastState", {})
            terminated = last_state.get("terminated", {})

            return {
                "pod_name": pod.get(
                    "metadata", {}
                ).get("name", ""),
                "phase": status.get("phase", "Unknown"),
                "restart_count": cs.get(
                    "restartCount", 0
                ),
                "exit_code": terminated.get(
                    "exitCode", 0
                ),
                "memory_limit": limits.get(
                    "memory", "unknown"
                ),
                "memory_request": requests.get(
                    "memory", "unknown"
                ),
                "cpu_limit": limits.get(
                    "cpu", "unknown"
                ),
                "image": container.get(
                    "image", "unknown"
                ),
                "ready": cs.get("ready", False),
            }

        except Exception as exc:
            logger.warning(
                "Failed to get pod details: %s", exc
            )
            return {}

    def get_recent_logs(
        self,
        service_name: str,
        lines: int = 20,
    ) -> list[str]:
        """Get real recent logs from a pod."""
        logs = []

        for flag in ["--previous", ""]:
            try:
                cmd = [
                    "kubectl", "logs",
                    f"deployment/{service_name}",
                    f"--tail={lines}",
                    "-n", self.namespace,
                ]
                if flag:
                    cmd.append(flag)

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

                if result.returncode == 0 \
                        and result.stdout:
                    logs = [
                        line for line in
                        result.stdout.strip().split("\n")
                        if line.strip()
                    ]
                    break

            except Exception:
                continue

        return logs

    def build_alert(
        self, incident: K8sIncident
    ) -> dict[str, Any]:
        """Build a FixIQ alert from a K8s incident."""
        pod_details = self.get_pod_details(
            incident.service
        )
        logs = self.get_recent_logs(incident.service)

        structured_logs = []
        for log in logs:
            if any(k in log.lower() for k in [
                "error", "exception", "failed",
                "oom", "kill", "crash"
            ]):
                structured_logs.append(f"ERROR {log}")
            elif any(k in log.lower() for k in [
                "warn", "warning"
            ]):
                structured_logs.append(f"WARNING {log}")
            else:
                structured_logs.append(log)

        structured_logs.append(
            f"CRITICAL k8s_event: {incident.reason} "
            f"- {incident.message}"
        )

        return {
            "title": (
                f"{incident.reason} in {incident.service}"
            ),
            "message": incident.message,
            "severity": incident.severity,
            "service": incident.service,
            "namespace": incident.namespace,
            "timestamp": incident.timestamp,
            "source": "kubernetes",
            "labels": {
                "pod": incident.pod,
                "reason": incident.reason,
                "namespace": incident.namespace,
            },
            "metrics": {
                "restart_count": pod_details.get(
                    "restart_count", 0
                ),
                "exit_code": pod_details.get(
                    "exit_code", 0
                ),
                "memory_limit": pod_details.get(
                    "memory_limit", "unknown"
                ),
                "ready": pod_details.get(
                    "ready", False
                ),
                "error_rate_pct": (
                    100 if not pod_details.get(
                        "ready", False
                    ) else 0
                ),
            },
            "logs": structured_logs[:20],
            "pod_details": pod_details,
        }