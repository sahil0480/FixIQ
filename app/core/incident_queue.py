"""Incident Queue for FixIQ.

When multiple alerts fire at the same time,
FixIQ queues them by priority and processes
them in order.

Priority is based on:
- Service criticality (from system map)
- Severity level
- Users affected
- Cascade potential

Deduplication:
- Same service won't be queued twice
- Already processing services are skipped
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from queue import PriorityQueue
from typing import Any

from app.core.k8s_watcher import K8sIncident
from app.core.service_discovery import SystemMap

logger = logging.getLogger(__name__)

BOLD = "\033[1m"
RED = "\033[91m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
BLUE = "\033[94m"
DIM = "\033[2m"
RESET = "\033[0m"


@dataclass
class QueuedIncident:
    """An incident waiting in the queue."""
    priority: float
    incident: K8sIncident
    alert: dict[str, Any]
    queued_at: str
    service_criticality: int
    estimated_users: int

    def __lt__(
        self, other: "QueuedIncident"
    ) -> bool:
        """Compare for priority queue ordering."""
        return self.priority > other.priority


class IncidentQueue:
    """Manages and prioritizes multiple incidents."""

    def __init__(
        self,
        system_map: SystemMap | None = None,
    ) -> None:
        self.system_map = system_map
        self._queue: PriorityQueue = PriorityQueue()
        self._queued_services: set[str] = set()
        self._processing: set[str] = set()
        self._processed: list[QueuedIncident] = []
        self._lock = threading.Lock()

    def add(
        self,
        incident: K8sIncident,
        alert: dict[str, Any],
    ) -> None:
        """Add incident to priority queue.

        Deduplicates — same service won't be
        added twice if already queued or processing.

        Args:
            incident: Detected K8s incident
            alert: Built alert data
        """
        with self._lock:
            # Deduplicate — skip if already queued
            if incident.service in self._queued_services:
                logger.info(
                    "Skipping duplicate: %s already queued",
                    incident.service,
                )
                return

            # Skip if already processing
            if incident.service in self._processing:
                logger.info(
                    "Skipping: %s already processing",
                    incident.service,
                )
                return

            # Calculate priority score
            priority = self._calculate_priority(
                incident, alert
            )

            # Get service info from system map
            criticality = 5
            users = 100
            if self.system_map:
                svc = self.system_map.get_service(
                    incident.service
                )
                if svc:
                    criticality = svc.criticality
                    users = svc.users_affected

            queued = QueuedIncident(
                priority=priority,
                incident=incident,
                alert=alert,
                queued_at=datetime.now().isoformat(),
                service_criticality=criticality,
                estimated_users=users,
            )

            self._queue.put(queued)
            self._queued_services.add(incident.service)

            logger.info(
                "Queued incident: %s (priority=%.1f)",
                incident.service,
                priority,
            )

    def get_next(self) -> QueuedIncident | None:
        """Get highest priority incident."""
        try:
            if self._queue.empty():
                return None
            item = self._queue.get_nowait()
            # Remove from queued set
            with self._lock:
                self._queued_services.discard(
                    item.incident.service
                )
            return item
        except Exception:
            return None

    def size(self) -> int:
        """Get number of queued incidents."""
        return self._queue.qsize()

    def is_empty(self) -> bool:
        """Check if queue is empty."""
        return self._queue.empty()

    def peek_all(self) -> list[QueuedIncident]:
        """Get all queued incidents without removing."""
        items = []
        temp_queue: PriorityQueue = PriorityQueue()

        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                items.append(item)
                temp_queue.put(item)
            except Exception:
                break

        while not temp_queue.empty():
            try:
                self._queue.put(
                    temp_queue.get_nowait()
                )
            except Exception:
                break

        return sorted(
            items,
            key=lambda x: x.priority,
            reverse=True
        )

    def _calculate_priority(
        self,
        incident: K8sIncident,
        alert: dict[str, Any],
    ) -> float:
        """Calculate priority score for incident."""
        score = 0.0

        severity_scores = {
            "critical": 10,
            "high": 7,
            "medium": 4,
            "low": 1,
        }
        score += severity_scores.get(
            incident.severity, 5
        ) * 0.30

        criticality = 5
        if self.system_map:
            criticality = (
                self.system_map.get_criticality(
                    incident.service
                )
            )
        score += criticality * 0.35

        restart_count = alert.get(
            "metrics", {}
        ).get("restart_count", 0)
        if restart_count > 10:
            score += 3
        elif restart_count > 5:
            score += 2
        elif restart_count > 2:
            score += 1

        score *= 0.25

        error_rate = alert.get(
            "metrics", {}
        ).get("error_rate_pct", 0)
        if error_rate >= 100:
            score += 2
        elif error_rate >= 50:
            score += 1

        score *= 0.10

        return round(score, 2)

    def mark_processing(
        self, service: str
    ) -> None:
        """Mark service as being processed."""
        with self._lock:
            self._processing.add(service)
            self._queued_services.discard(service)

    def mark_done(
        self,
        queued: QueuedIncident
    ) -> None:
        """Mark incident as processed."""
        with self._lock:
            self._processing.discard(
                queued.incident.service
            )
        self._processed.append(queued)

    def is_processing(self, service: str) -> bool:
        """Check if service is being processed."""
        return service in self._processing

    def get_processed(
        self,
    ) -> list[QueuedIncident]:
        """Get all processed incidents."""
        return self._processed.copy()


def display_queue(
    queue: IncidentQueue,
    title: str = "INCIDENT QUEUE",
) -> None:
    """Display current incident queue."""
    items = queue.peek_all()

    print(f"\n{BOLD}{'═' * 70}{RESET}")
    print(f"{BOLD}  🚨 {title}{RESET}")
    print(f"{BOLD}{'═' * 70}{RESET}")
    print(
        f"\n  Total queued: {RED}{len(items)}{RESET}"
    )

    if not items:
        print(f"  {DIM}No incidents queued{RESET}")
        print(f"\n{BOLD}{'═' * 70}{RESET}")
        return

    print(
        f"\n  {'#':<4} {'Service':<25} "
        f"{'Severity':<12} {'Priority':<10} "
        f"{'Users':<8} Status"
    )
    print(f"  {'─' * 65}")

    for i, item in enumerate(items, 1):
        color = (
            RED if item.incident.severity == "critical"
            else YELLOW
            if item.incident.severity == "high"
            else BLUE
        )
        status = (
            f"{YELLOW}processing...{RESET}"
            if queue.is_processing(
                item.incident.service
            )
            else f"{DIM}queued{RESET}"
        )

        print(
            f"  #{i:<3} "
            f"{item.incident.service:<25} "
            f"{color}{item.incident.severity:<12}{RESET} "
            f"{item.priority:<10} "
            f"~{item.estimated_users:<8} "
            f"{status}"
        )
        print(
            f"  {DIM}     Reason: "
            f"{item.incident.reason} — "
            f"{item.incident.message[:50]}{RESET}"
        )

    print(f"\n{BOLD}{'═' * 70}{RESET}")