"""Similar Incidents Finder for FixIQ.

Finds past incidents similar to the current one.
Learns from history to help engineers fix faster.

The more incidents FixIQ sees, the smarter it gets.
Reduces MTTR dramatically by showing what worked before.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Storage location
INCIDENTS_PATH = (
    Path.home() / ".config" / "fixiq" / "knowledge_base.json"
)


@dataclass
class SimilarIncident:
    """A similar past incident."""
    id: str
    date: str
    root_cause: str
    service: str
    fix_applied: str
    time_to_fix_minutes: int
    similarity_score: float
    outcome: str    # resolved, unresolved, partial


@dataclass
class SimilarIncidentsResult:
    """Result of similar incidents search."""
    found: bool
    incidents: list[SimilarIncident]
    best_match: SimilarIncident | None
    recommended_fix: str
    success_rate: float
    avg_time_to_fix: int


class SimilarIncidentsFinder:
    """Finds and stores similar incidents."""

    def __init__(
        self, path: Path = INCIDENTS_PATH
    ) -> None:
        self.path = path
        self._ensure_storage()

    def _ensure_storage(self) -> None:
        """Create storage if not exists."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(
                json.dumps({"incidents": []}, indent=2)
            )

    def _load(self) -> dict[str, Any]:
        """Load incidents from disk."""
        try:
            return json.loads(self.path.read_text())
        except Exception:
            return {"incidents": []}

    def _save(self, data: dict[str, Any]) -> None:
        """Save incidents to disk."""
        try:
            self.path.write_text(
                json.dumps(data, indent=2)
            )
        except Exception as exc:
            logger.warning(
                "Failed to save incidents: %s", exc
            )

    def find(
        self,
        root_cause: str,
        service_name: str,
        rca_output: dict[str, Any],
    ) -> SimilarIncidentsResult:
        """Find similar past incidents.

        Args:
            root_cause: Current root cause
            service_name: Affected service
            rca_output: RCA output from OpenSRE

        Returns:
            Similar incidents result
        """
        data = self._load()
        all_incidents = data.get("incidents", [])

        if not all_incidents:
            return SimilarIncidentsResult(
                found=False,
                incidents=[],
                best_match=None,
                recommended_fix="No history yet. "
                    "This will be saved for future reference.",
                success_rate=0.0,
                avg_time_to_fix=0,
            )

        # Score each incident
        similar = []
        for incident in all_incidents:
            score = self._calculate_similarity(
                root_cause,
                service_name,
                incident,
            )
            if score >= 0.3:
                similar.append(SimilarIncident(
                    id=incident.get("id", "unknown"),
                    date=incident.get("date", "unknown"),
                    root_cause=incident.get(
                        "root_cause", ""
                    ),
                    service=incident.get(
                        "service", "unknown"
                    ),
                    fix_applied=incident.get(
                        "fix_applied", "Unknown"
                    ),
                    time_to_fix_minutes=incident.get(
                        "time_to_fix_minutes", 0
                    ),
                    similarity_score=score,
                    outcome=incident.get(
                        "outcome", "unknown"
                    ),
                ))

        # Sort by similarity
        similar.sort(
            key=lambda x: x.similarity_score,
            reverse=True
        )
        similar = similar[:5]

        if not similar:
            return SimilarIncidentsResult(
                found=False,
                incidents=[],
                best_match=None,
                recommended_fix=(
                    "No similar incidents found. "
                    "This appears to be a new type of issue."
                ),
                success_rate=0.0,
                avg_time_to_fix=0,
            )

        best = similar[0]
        success_rate = self._calculate_success_rate(similar)
        avg_time = self._calculate_avg_time(similar)
        recommended_fix = self._build_recommendation(
            best, similar
        )

        logger.info(
            "Found %d similar incidents, "
            "best match %.0f%% similarity",
            len(similar),
            best.similarity_score * 100,
        )

        return SimilarIncidentsResult(
            found=True,
            incidents=similar,
            best_match=best,
            recommended_fix=recommended_fix,
            success_rate=success_rate,
            avg_time_to_fix=avg_time,
        )

    def save_incident(
        self,
        root_cause: str,
        service_name: str,
        fix_applied: str,
        time_to_fix_minutes: int,
        outcome: str = "resolved",
    ) -> None:
        """Save a new incident to history.

        Args:
            root_cause: Root cause of incident
            service_name: Affected service
            fix_applied: What fix was applied
            time_to_fix_minutes: How long it took
            outcome: resolved/unresolved/partial
        """
        data = self._load()

        incident_id = hashlib.md5(
            f"{root_cause}{service_name}"
            f"{datetime.now().isoformat()}".encode()
        ).hexdigest()[:8]

        incident = {
            "id": incident_id,
            "date": datetime.now().isoformat(),
            "root_cause": root_cause,
            "service": service_name,
            "fix_applied": fix_applied,
            "time_to_fix_minutes": time_to_fix_minutes,
            "outcome": outcome,
        }

        data["incidents"].append(incident)
        self._save(data)

        logger.info(
            "Saved incident %s to history",
            incident_id
        )

    def _calculate_similarity(
        self,
        root_cause: str,
        service_name: str,
        incident: dict[str, Any],
    ) -> float:
        """Calculate similarity between two incidents."""
        score = 0.0

        # Same service = high similarity
        if incident.get("service") == service_name:
            score += 0.3

        # Similar root cause
        current_words = set(root_cause.lower().split())
        past_words = set(
            incident.get("root_cause", "").lower().split()
        )

        if current_words and past_words:
            overlap = current_words & past_words
            similarity = len(overlap) / max(
                len(current_words), len(past_words)
            )
            score += similarity * 0.5

        # Resolved incidents are more valuable
        if incident.get("outcome") == "resolved":
            score += 0.2

        return round(min(1.0, score), 2)

    def _calculate_success_rate(
        self, incidents: list[SimilarIncident]
    ) -> float:
        """Calculate success rate of past fixes."""
        if not incidents:
            return 0.0
        resolved = sum(
            1 for i in incidents
            if i.outcome == "resolved"
        )
        return round(resolved / len(incidents), 2)

    def _calculate_avg_time(
        self, incidents: list[SimilarIncident]
    ) -> int:
        """Calculate average time to fix."""
        if not incidents:
            return 0
        times = [
            i.time_to_fix_minutes
            for i in incidents
            if i.time_to_fix_minutes > 0
        ]
        if not times:
            return 0
        return int(sum(times) / len(times))

    def _build_recommendation(
        self,
        best: SimilarIncident,
        all_similar: list[SimilarIncident],
    ) -> str:
        """Build fix recommendation from history."""
        score_pct = int(best.similarity_score * 100)
        success = self._calculate_success_rate(all_similar)
        avg_time = self._calculate_avg_time(all_similar)

        return (
            f"Best match ({score_pct}% similar): "
            f"{best.fix_applied}. "
            f"Success rate: {int(success * 100)}%. "
            f"Avg fix time: {avg_time} minutes."
        )


def display_similar_incidents(
    result: SimilarIncidentsResult,
) -> None:
    """Display similar incidents in terminal."""
    BOLD = "\033[1m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    GREEN = "\033[92m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    print(f"\n{BOLD}{'─' * 70}{RESET}")
    print(f"{BOLD}  🔄 SIMILAR INCIDENTS{RESET}")
    print(f"{BOLD}{'─' * 70}{RESET}")

    if not result.found:
        print(f"\n  {YELLOW}No similar incidents found.{RESET}")
        print(f"  {result.recommended_fix}")
        print(f"\n{BOLD}{'─' * 70}{RESET}")
        return

    print(
        f"\n  Found {GREEN}{len(result.incidents)}"
        f"{RESET} similar incidents"
    )
    print(
        f"  Success rate: "
        f"{GREEN}{int(result.success_rate * 100)}%{RESET}"
    )
    print(
        f"  Avg fix time: "
        f"{result.avg_time_to_fix} minutes"
    )

    print(f"\n  {BOLD}Past Incidents:{RESET}")
    for i, incident in enumerate(
        result.incidents[:3], 1
    ):
        score_pct = int(incident.similarity_score * 100)
        color = (
            GREEN if score_pct >= 70 else
            YELLOW if score_pct >= 40 else
            RED
        )
        outcome_color = (
            GREEN if incident.outcome == "resolved"
            else YELLOW
        )

        print(f"\n  {BOLD}#{i}{RESET} — "
              f"{incident.date[:10]}")
        print(
            f"  Similarity: {color}{score_pct}%{RESET}"
        )
        print(
            f"  Service:    {incident.service}"
        )
        print(
            f"  Fix:        {incident.fix_applied[:60]}"
        )
        print(
            f"  Time:       {incident.time_to_fix_minutes} min"
        )
        print(
            f"  Outcome:    "
            f"{outcome_color}{incident.outcome}{RESET}"
        )

    print(f"\n  {BOLD}Recommended Fix:{RESET}")
    print(f"  {result.recommended_fix}")
    print(f"\n{BOLD}{'─' * 70}{RESET}")