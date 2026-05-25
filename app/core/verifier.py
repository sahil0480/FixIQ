"""Fix Verifier for FixIQ.

Verifies if a previously applied fix worked
by re-running investigation and comparing results.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.core.knowledge_base import KnowledgeBase

logger = logging.getLogger(__name__)

# ANSI colors
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"
DIM = "\033[2m"


class FixVerifier:
    """Verifies if a previously applied fix worked."""

    def __init__(self) -> None:
        self.kb = KnowledgeBase()

    def verify(
        self,
        root_cause: str,
        new_rca_output: dict[str, Any],
    ) -> dict[str, Any]:
        """Verify if a fix worked.

        Compares new RCA output with previous incident
        to determine if the issue was resolved.

        Args:
            root_cause: Original root cause
            new_rca_output: New RCA output after fix

        Returns:
            Verification result
        """
        past_incident = self.kb.lookup(root_cause)

        if not past_incident:
            return {
                "status": "no_history",
                "message": "No previous fix found to verify.",
                "resolved": False,
            }

        new_root_cause = new_rca_output.get(
            "root_cause", ""
        ).lower()
        original_root_cause = root_cause.lower()

        # Check if same issue still present
        is_resolved = not self._is_same_issue(
            original_root_cause, new_root_cause
        )

        if is_resolved:
            # Update knowledge base
            self.kb.save(
                root_cause=root_cause,
                rca_output=new_rca_output,
                fix_applied=past_incident.get("fix"),
            )
            return {
                "status": "resolved",
                "message": "Issue appears to be resolved!",
                "resolved": True,
                "previous_fix": past_incident.get("fix"),
                "time_to_fix": self._calculate_time(
                    past_incident.get("date")
                ),
            }
        else:
            return {
                "status": "unresolved",
                "message": "Issue still present after fix.",
                "resolved": False,
                "previous_fix": past_incident.get("fix"),
                "new_root_cause": new_root_cause,
                "suggestion": "Previous fix did not work. Try a different approach.",
            }

    def _is_same_issue(
        self,
        original: str,
        new: str,
    ) -> bool:
        """Check if two root causes describe the same issue."""
        # Extract key terms
        original_terms = set(original.split())
        new_terms = set(new.split())

        # Check overlap
        overlap = original_terms & new_terms
        if not overlap:
            return False

        # Calculate similarity
        similarity = len(overlap) / max(
            len(original_terms), len(new_terms)
        )

        return similarity > 0.3

    def _calculate_time(
        self, start_time: str | None
    ) -> str:
        """Calculate time elapsed since incident started."""
        if not start_time:
            return "Unknown"

        try:
            start = datetime.fromisoformat(start_time)
            elapsed = datetime.now() - start
            minutes = int(elapsed.total_seconds() / 60)

            if minutes < 60:
                return f"{minutes} minutes"
            else:
                hours = minutes // 60
                return f"{hours} hours {minutes % 60} minutes"
        except Exception:
            return "Unknown"


def display_verification_result(
    result: dict[str, Any],
) -> None:
    """Display verification result to the engineer."""
    print(f"\n{BOLD}{'─' * 60}{RESET}")
    print(f"{BOLD}  🔍 Fix Verification Result{RESET}")
    print(f"{BOLD}{'─' * 60}{RESET}")

    status = result.get("status")
    message = result.get("message", "")

    if status == "resolved":
        print(f"\n  {GREEN}{BOLD}✅ RESOLVED{RESET}")
        print(f"  {message}")
        print(f"\n  Previous fix: {result.get('previous_fix', 'N/A')}")
        print(f"  Time to fix: {result.get('time_to_fix', 'N/A')}")
        print(f"\n  {DIM}Fix saved to knowledge base for future reference.{RESET}")

    elif status == "unresolved":
        print(f"\n  {RED}{BOLD}❌ STILL BROKEN{RESET}")
        print(f"  {message}")
        print(f"\n  Previous fix tried: {result.get('previous_fix', 'N/A')}")
        print(f"  New root cause: {result.get('new_root_cause', 'N/A')}")
        print(f"\n  {YELLOW}Suggestion: {result.get('suggestion', 'N/A')}{RESET}")
        print(f"\n  {DIM}Run fixiq analyze again for fresh RCA.{RESET}")

    elif status == "no_history":
        print(f"\n  {YELLOW}⚠️  NO HISTORY{RESET}")
        print(f"  {message}")
        print(f"\n  {DIM}Run fixiq analyze first to record the incident.{RESET}")

    print(f"\n{BOLD}{'─' * 60}{RESET}\n")