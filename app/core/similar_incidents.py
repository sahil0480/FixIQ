"""Similar Incidents Finder for FixIQ.

Finds past incidents similar to the current one.
Learns from history to help engineers fix faster.

The more incidents FixIQ sees, the smarter it gets.
Reduces MTTR dramatically by showing what worked before.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.core.knowledge_base import KnowledgeBase

logger = logging.getLogger(__name__)


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
    outcome: str


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

    def __init__(self) -> None:
        self.kb = KnowledgeBase()

    def find(
        self,
        root_cause: str,
        service_name: str,
        rca_output: dict[str, Any],
    ) -> SimilarIncidentsResult:
        """Find similar past incidents."""
        all_incidents = self.kb.list_all()

        if not all_incidents:
            return SimilarIncidentsResult(
                found=False,
                incidents=[],
                best_match=None,
                recommended_fix=(
                    "No history yet. "
                    "This will be saved for future reference."
                ),
                success_rate=0.0,
                avg_time_to_fix=0,
            )

        similar = []
        for incident in all_incidents:
            score = self._calculate_similarity(
                root_cause, service_name, incident
            )
            if score >= 0.3:
                similar.append(SimilarIncident(
                    id=incident.get(
                        "hash", incident.get("id", "unknown")
                    ),
                    date=incident.get("date", "unknown"),
                    root_cause=incident.get("root_cause", ""),
                    service=incident.get("service", "unknown"),
                    fix_applied=incident.get(
                        "fix_applied",
                        incident.get("fix", "Not yet applied")
                    ),
                    time_to_fix_minutes=incident.get(
                        "time_to_fix_minutes", 0
                    ),
                    similarity_score=score,
                    outcome=incident.get("outcome", "unknown"),
                ))

        similar.sort(
            key=lambda x: x.similarity_score, reverse=True
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
        recommended_fix = self._build_recommendation(similar)

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
        """Save a resolved incident via fixiq record."""
        self.kb.record_fix(
            service=service_name,
            fix_applied=fix_applied,
            time_to_fix_minutes=time_to_fix_minutes,
        )

    def _calculate_similarity(
        self,
        root_cause: str,
        service_name: str,
        incident: dict[str, Any],
    ) -> float:
        """Calculate similarity between two incidents."""
        score = 0.0

        if incident.get("service") == service_name:
            score += 0.3

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

        if incident.get("outcome") == "resolved":
            score += 0.2

        return round(min(1.0, score), 2)

    def _calculate_success_rate(
        self, incidents: list[SimilarIncident]
    ) -> float:
        if not incidents:
            return 0.0
        resolved = sum(
            1 for i in incidents if i.outcome == "resolved"
        )
        return round(resolved / len(incidents), 2)

    def _calculate_avg_time(
        self, incidents: list[SimilarIncident]
    ) -> int:
        times = [
            i.time_to_fix_minutes
            for i in incidents
            if i.time_to_fix_minutes > 0
            and i.outcome == "resolved"
        ]
        if not times:
            return 0
        return int(sum(times) / len(times))

    def _build_recommendation(
        self,
        all_similar: list[SimilarIncident],
    ) -> str:
        """Build fix recommendation.

        Prioritises resolved entries with a real fix.
        Falls back to best similarity match if none resolved.
        """
        resolved = [
            i for i in all_similar
            if i.outcome == "resolved"
            and i.fix_applied not in (
                "Not yet applied", "", "Unknown"
            )
        ]

        if resolved:
            best = resolved[0]
            score_pct = int(best.similarity_score * 100)
            avg_time = self._calculate_avg_time(all_similar)
            time_str = (
                f" Avg fix time: {avg_time} minutes."
                if avg_time > 0 else ""
            )
            return (
                f"✅ Known fix ({score_pct}% match): "
                f"{best.fix_applied}.{time_str}"
            )

        best = all_similar[0]
        score_pct = int(best.similarity_score * 100)
        return (
            f"Best match ({score_pct}% similar): "
            f"Not yet applied. "
            f"No confirmed fix recorded yet — "
            f"run 'fixiq record -s {best.service} "
            f"-f <fix>' after resolving."
        )


def display_similar_incidents(
    result: SimilarIncidentsResult,
) -> None:
    """Display similar incidents in terminal."""
    BOLD = "\033[1m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    GREEN = "\033[92m"
    RESET = "\033[0m"

    print(f"\n{BOLD}{'─' * 70}{RESET}")
    print(f"{BOLD}  🔄 SIMILAR INCIDENTS{RESET}")
    print(f"{BOLD}{'─' * 70}{RESET}")

    if not result.found:
        print(f"\n  {YELLOW}No similar incidents found.{RESET}")
        print(f"  {result.recommended_fix}")
        print(f"\n{BOLD}{'─' * 70}{RESET}")
        return

    resolved_count = sum(
        1 for i in result.incidents if i.outcome == "resolved"
    )

    print(
        f"\n  Found {GREEN}{len(result.incidents)}"
        f"{RESET} similar incidents "
        f"({GREEN}{resolved_count} resolved{RESET})"
    )
    print(
        f"  Success rate: "
        f"{GREEN}{int(result.success_rate * 100)}%{RESET}"
    )
    if result.avg_time_to_fix > 0:
        print(
            f"  Avg fix time: {result.avg_time_to_fix} minutes"
        )

    print(f"\n  {BOLD}Past Incidents:{RESET}")
    for i, incident in enumerate(result.incidents[:3], 1):
        score_pct = int(incident.similarity_score * 100)
        score_color = (
            GREEN if score_pct >= 70 else
            YELLOW if score_pct >= 40 else
            RED
        )
        outcome_color = (
            GREEN if incident.outcome == "resolved"
            else YELLOW
        )
        fix_display = (
            f"{YELLOW}Not yet applied{RESET}"
            if incident.fix_applied == "Not yet applied"
            else incident.fix_applied
        )

        print(f"\n  {BOLD}#{i}{RESET} — {incident.date[:10]}")
        print(f"  Similarity: {score_color}{score_pct}%{RESET}")
        print(f"  Service:    {incident.service}")
        print(f"  Fix:        {fix_display}")
        if incident.time_to_fix_minutes > 0:
            print(
                f"  Time:       "
                f"{incident.time_to_fix_minutes} min"
            )
        print(
            f"  Outcome:    "
            f"{outcome_color}{incident.outcome}{RESET}"
        )

    print(f"\n  {BOLD}Recommended Fix:{RESET}")
    print(f"  {result.recommended_fix}")
    print(f"\n{BOLD}{'─' * 70}{RESET}")