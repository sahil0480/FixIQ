"""Knowledge Base for FixIQ.

Stores and retrieves past incidents and fixes.
Learns from history to help engineers faster.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Storage location
KB_PATH = Path.home() / ".config" / "fixiq" / "knowledge_base.json"


class KnowledgeBase:
    """Stores and retrieves past incidents and fixes."""

    def __init__(self, path: Path = KB_PATH) -> None:
        self.path = path
        self._ensure_storage()

    def _ensure_storage(self) -> None:
        """Create storage directory and file if not exists."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(
                json.dumps({"incidents": []}, indent=2)
            )

    def _load(self) -> dict[str, Any]:
        """Load knowledge base from disk."""
        try:
            return json.loads(self.path.read_text())
        except Exception as exc:
            logger.warning("Failed to load knowledge base: %s", exc)
            return {"incidents": []}

    def _save(self, data: dict[str, Any]) -> None:
        """Save knowledge base to disk."""
        try:
            self.path.write_text(json.dumps(data, indent=2))
        except Exception as exc:
            logger.warning("Failed to save knowledge base: %s", exc)

    def _hash(self, root_cause: str) -> str:
        """Create a hash for the root cause."""
        return hashlib.md5(
            root_cause.lower().strip().encode()
        ).hexdigest()[:8]

    def lookup(self, root_cause: str) -> dict[str, Any] | None:
        """Look up a past incident by root cause.

        Args:
            root_cause: The root cause to look up

        Returns:
            Past incident data or None if not found
        """
        data = self._load()
        issue_hash = self._hash(root_cause)

        for incident in data["incidents"]:
            if incident.get("hash") == issue_hash:
                logger.info(
                    "Found past incident in knowledge base: %s",
                    issue_hash
                )
                return incident

        return None

    def save(
        self,
        root_cause: str,
        rca_output: dict[str, Any],
        fix_applied: str | None = None,
    ) -> None:
        """Save an incident to the knowledge base.

        Args:
            root_cause: The root cause of the incident
            rca_output: The RCA output from OpenSRE
            fix_applied: Description of fix that was applied
        """
        data = self._load()
        issue_hash = self._hash(root_cause)

        # Check if already exists
        for incident in data["incidents"]:
            if incident.get("hash") == issue_hash:
                # Update existing
                incident["last_seen"] = datetime.now().isoformat()
                incident["occurrences"] = incident.get(
                    "occurrences", 1
                ) + 1
                if fix_applied:
                    incident["fix"] = fix_applied
                    incident["fix_date"] = datetime.now().isoformat()
                self._save(data)
                logger.info(
                    "Updated incident in knowledge base: %s",
                    issue_hash
                )
                return

        # Add new incident
        incident = {
            "hash": issue_hash,
            "root_cause": root_cause,
            "date": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
            "occurrences": 1,
            "fix": fix_applied or "Not yet applied",
            "fix_date": None,
            "service": rca_output.get("service", "unknown"),
        }

        data["incidents"].append(incident)
        self._save(data)
        logger.info(
            "Saved new incident to knowledge base: %s",
            issue_hash
        )

    def list_all(self) -> list[dict[str, Any]]:
        """List all incidents in the knowledge base.

        Returns:
            List of all incidents
        """
        data = self._load()
        return data.get("incidents", [])

    def clear(self) -> None:
        """Clear the knowledge base."""
        self._save({"incidents": []})
        logger.info("Knowledge base cleared")