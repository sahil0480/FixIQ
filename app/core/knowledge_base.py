"""Knowledge Base for FixIQ.

Single source of truth for all incident history.
Used by both the pipeline (auto-save) and the CLI
(fixiq record) to store and retrieve incidents.

Schema (one entry per unique root cause hash):
{
    "hash":               str,   # md5 of root_cause
    "root_cause":         str,
    "service":            str,
    "date":               str,   # first seen
    "last_seen":          str,
    "occurrences":        int,
    "fix_applied":        str,   # "Not yet applied" until recorded
    "fix_date":           str | null,
    "time_to_fix_minutes":int,
    "outcome":            str    # "unknown" | "resolved" | "partial"
}
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

KB_PATH = (
    Path.home() / ".config" / "fixiq" / "knowledge_base.json"
)


class KnowledgeBase:
    """Stores and retrieves past incidents and fixes."""

    def __init__(self, path: Path = KB_PATH) -> None:
        self.path = path
        self._ensure_storage()

    def _ensure_storage(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(
                json.dumps({"incidents": []}, indent=2)
            )

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text())
        except Exception as exc:
            logger.warning("Failed to load KB: %s", exc)
            return {"incidents": []}

    def _save(self, data: dict[str, Any]) -> None:
        try:
            self.path.write_text(
                json.dumps(data, indent=2)
            )
        except Exception as exc:
            logger.warning("Failed to save KB: %s", exc)

    def _hash(self, root_cause: str) -> str:
        import re
        # Strip restart count so same issue with different
        # restart counts maps to the same hash
        normalised = re.sub(
            r'\. Restart count: \d+', '', root_cause
        ).lower().strip()
        return hashlib.md5(normalised.encode()).hexdigest()[:8]

    def save(
        self,
        root_cause: str,
        rca_output: dict[str, Any],
        fix_applied: str | None = None,
    ) -> None:
        """Auto-save incident when pipeline detects it.

        If same root cause seen before, increments occurrences.
        Does NOT overwrite a real fix with 'Not yet applied'.
        """
        data = self._load()
        issue_hash = self._hash(root_cause)
        service = (
            rca_output.get("service")
            or rca_output.get("k8s_info", {}).get("service", "unknown")
        )

        for incident in data["incidents"]:
            if incident.get("hash") == issue_hash:
                incident["last_seen"] = datetime.now().isoformat()
                incident["occurrences"] = (
                    incident.get("occurrences", 1) + 1
                )
                # Only update fix if a real one is being recorded
                if fix_applied and fix_applied != "Not yet applied":
                    incident["fix_applied"] = fix_applied
                    incident["fix_date"] = datetime.now().isoformat()
                    incident["outcome"] = "resolved"
                self._save(data)
                return

        incident = {
            "hash": issue_hash,
            "root_cause": root_cause,
            "service": service,
            "date": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
            "occurrences": 1,
            "fix_applied": fix_applied or "Not yet applied",
            "fix_date": None,
            "time_to_fix_minutes": 0,
            "outcome": "unknown",
        }

        data["incidents"].append(incident)
        self._save(data)
        logger.info("Saved new incident: %s", issue_hash)

    def record_fix(
        self,
        service: str,
        fix_applied: str,
        time_to_fix_minutes: int = 0,
    ) -> bool:
        """Record a confirmed fix for a service.

        Updates the most recent unresolved incident for the
        service. Returns True if an incident was updated.
        """
        data = self._load()
        updated = False

        for incident in reversed(data["incidents"]):
            if incident.get("service") == service:
                incident["fix_applied"] = fix_applied
                incident["fix_date"] = datetime.now().isoformat()
                incident["outcome"] = "resolved"
                if time_to_fix_minutes > 0:
                    incident["time_to_fix_minutes"] = (
                        time_to_fix_minutes
                    )
                updated = True
                logger.info(
                    "Recorded fix for %s: %s", service, fix_applied
                )
                break

        if not updated:
            data["incidents"].append({
                "hash": self._hash(
                    f"{service}_{fix_applied}"
                ),
                "root_cause": f"Incident in {service}",
                "service": service,
                "date": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat(),
                "occurrences": 1,
                "fix_applied": fix_applied,
                "fix_date": datetime.now().isoformat(),
                "time_to_fix_minutes": time_to_fix_minutes,
                "outcome": "resolved",
            })

        self._save(data)
        return updated

    def lookup(
        self, root_cause: str
    ) -> dict[str, Any] | None:
        """Look up a past incident by root cause hash."""
        data = self._load()
        issue_hash = self._hash(root_cause)
        for incident in data["incidents"]:
            if incident.get("hash") == issue_hash:
                return incident
        return None

    def list_all(self) -> list[dict[str, Any]]:
        """List all incidents in the knowledge base."""
        return self._load().get("incidents", [])

    def clear(self) -> None:
        """Clear the knowledge base."""
        self._save({"incidents": []})
        logger.info("Knowledge base cleared")