"""FixIQ Automated Pipeline.

Full automated pipeline:
1. K8s Watcher detects incident
2. OpenSRE runs real LLM investigation
3. FixIQ runs deep analysis
4. Unified report displayed

No manual steps — fully automated!
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
import os
from datetime import datetime
from typing import Any

from app.core.k8s_watcher import K8sIncident, K8sWatcher

logger = logging.getLogger(__name__)

# ANSI colors
BOLD = "\033[1m"
RED = "\033[91m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
BLUE = "\033[94m"
DIM = "\033[2m"
RESET = "\033[0m"


class FixIQPipeline:
    """Full automated FixIQ pipeline."""

    def __init__(
        self,
        namespace: str = "default",
        opensre_path: str | None = None,
    ) -> None:
        self.namespace = namespace
        self.opensre_path = (
            opensre_path or
            os.path.expanduser("~/opensre")
        )
        self.watcher = K8sWatcher(namespace=namespace)
        self._processed: set[str] = set()

    def run(self) -> None:
        """Start the automated pipeline."""
        self._print_banner()
        self.watcher.watch(
            on_incident=self._handle_incident
        )

    def _print_banner(self) -> None:
        """Print pipeline banner."""
        print(f"\n{BOLD}{'═' * 70}{RESET}")
        print(f"{BOLD}  FixIQ — Automated Incident Pipeline{RESET}")
        print(f"{DIM}  Powered by OpenSRE{RESET}")
        print(f"{BOLD}{'═' * 70}{RESET}")
        print(f"\n  {GREEN}✓{RESET} Kubernetes watcher started")
        print(f"  {GREEN}✓{RESET} OpenSRE LLM ready")
        print(f"  {GREEN}✓{RESET} FixIQ analyzer ready")
        print(
            f"\n  {DIM}Waiting for incidents in "
            f"namespace: {self.namespace}{RESET}\n"
        )

    def _handle_incident(
        self, incident: K8sIncident
    ) -> None:
        """Handle a detected incident."""
        # Deduplicate — don't process same service twice
        # within 60 seconds
        dedup_key = (
            f"{incident.service}:{incident.reason}"
        )
        if dedup_key in self._processed:
            return
        self._processed.add(dedup_key)

        print(f"\n{BOLD}{'─' * 70}{RESET}")
        print(
            f"{RED}{BOLD}  🚨 INCIDENT DETECTED{RESET}"
        )
        print(f"{BOLD}{'─' * 70}{RESET}")
        print(
            f"\n  Service:   {BOLD}{incident.service}{RESET}"
        )
        print(f"  Reason:    {RED}{incident.reason}{RESET}")
        print(f"  Severity:  {incident.severity.upper()}")
        print(f"  Pod:       {incident.pod}")
        print(
            f"  Time:      {incident.timestamp[:19]}"
        )
        print(f"  Message:   {incident.message[:80]}")

        # Build alert from real K8s data
        print(
            f"\n  {BLUE}→ Building alert from "
            f"Kubernetes data...{RESET}"
        )
        alert = self.watcher.build_alert(incident)

        # Show what we collected
        pod_details = alert.get("pod_details", {})
        if pod_details:
            print(
                f"  {GREEN}✓{RESET} Pod status: "
                f"{pod_details.get('phase', 'Unknown')}"
            )
            print(
                f"  {GREEN}✓{RESET} Restart count: "
                f"{pod_details.get('restart_count', 0)}"
            )
            print(
                f"  {GREEN}✓{RESET} Memory limit: "
                f"{pod_details.get('memory_limit', 'unknown')}"
            )
            print(
                f"  {GREEN}✓{RESET} Exit code: "
                f"{pod_details.get('exit_code', 0)}"
            )

        logs = alert.get("logs", [])
        print(
            f"  {GREEN}✓{RESET} Collected "
            f"{len(logs)} log lines"
        )

        # Run OpenSRE investigation
        print(
            f"\n  {BLUE}→ Running OpenSRE "
            f"investigation (Ollama LLM)...{RESET}"
        )
        rca_output = self._run_opensre(alert)

        root_cause = rca_output.get(
            "root_cause", "Unknown"
        )
        print(
            f"  {GREEN}✓{RESET} Root cause: "
            f"{root_cause}"
        )

        # Run FixIQ deep analysis
        print(
            f"\n  {BLUE}→ Running FixIQ "
            f"deep analysis...{RESET}"
        )
        self._run_fixiq_analysis(
            alert, rca_output, incident.service
        )

        # Clear dedup after 60 seconds
        import threading
        def clear_dedup():
            import time
            time.sleep(60)
            self._processed.discard(dedup_key)
        threading.Thread(
            target=clear_dedup, daemon=True
        ).start()

    def _run_opensre(
        self, alert: dict[str, Any]
    ) -> dict[str, Any]:
        """Run OpenSRE investigation on the alert."""
        try:
            # Write alert to temp file
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".json",
                delete=False,
            ) as f:
                json.dump(alert, f)
                alert_file = f.name

            # Run opensre investigate
            opensre_venv = os.path.join(
                self.opensre_path,
                ".venv/bin/opensre"
            )

            if not os.path.exists(opensre_venv):
                opensre_venv = "opensre"

            result = subprocess.run(
                [
                    opensre_venv,
                    "investigate",
                    "-i", alert_file,
                ],
                capture_output=True,
                text=True,
                timeout=300,  # 5 min timeout
                cwd=self.opensre_path,
            )

            # Parse output
            rca_output = self._parse_opensre_output(
                result.stdout, result.stderr, alert
            )

            # Cleanup
            os.unlink(alert_file)

            return rca_output

        except subprocess.TimeoutExpired:
            print(
                f"  {YELLOW}⚠ OpenSRE investigation "
                f"timed out{RESET}"
            )
            return self._fallback_rca(alert)
        except Exception as exc:
            logger.warning(
                "OpenSRE investigation failed: %s", exc
            )
            return self._fallback_rca(alert)

    def _parse_opensre_output(
        self,
        stdout: str,
        stderr: str,
        alert: dict[str, Any],
    ) -> dict[str, Any]:
        """Parse OpenSRE investigation output."""
        output = stdout + stderr

        # Extract root cause from output
        root_cause = alert.get("title", "Unknown")

        # Look for root cause patterns
        import re
        patterns = [
            r"[Rr]oot [Cc]ause[:\s]+(.+?)(?:\n|$)",
            r"[Cc]ause[:\s]+(.+?)(?:\n|$)",
            r"[Dd]iagnosis[:\s]+(.+?)(?:\n|$)",
        ]

        for pattern in patterns:
            match = re.search(pattern, output)
            if match:
                found = match.group(1).strip()
                if len(found) > 10:
                    root_cause = found
                    break

        # Extract recommended actions
        actions = []
        action_patterns = [
            r"[Rr]ecommend(?:ed)?\s+[Aa]ction[s]?[:\s]+(.+?)(?:\n\n|$)",
            r"[Ss]uggestion[s]?[:\s]+(.+?)(?:\n|$)",
            r"[Ff]ix[:\s]+(.+?)(?:\n|$)",
        ]

        for pattern in action_patterns:
            matches = re.findall(pattern, output)
            actions.extend(matches[:3])

        return {
            "root_cause": root_cause,
            "recommended_actions": actions[:5],
            "raw_output": output[:2000],
            "evidence_entries": [],
            "report": output[:1000],
            "service": alert.get("service", "unknown"),
        }

    def _fallback_rca(
        self, alert: dict[str, Any]
    ) -> dict[str, Any]:
        """Fallback RCA when OpenSRE fails."""
        title = alert.get("title", "Unknown incident")
        pod_details = alert.get("pod_details", {})

        # Build RCA from K8s data directly
        root_cause = title
        if pod_details.get("exit_code") == 137:
            root_cause = (
                f"Pod OOMKilled — memory limit "
                f"{pod_details.get('memory_limit', 'unknown')} "
                f"exceeded. Restart count: "
                f"{pod_details.get('restart_count', 0)}"
            )

        return {
            "root_cause": root_cause,
            "recommended_actions": [
                "Check pod memory usage",
                "Increase memory limit",
                "Check for memory leaks",
            ],
            "evidence_entries": [],
            "report": root_cause,
            "service": alert.get("service", "unknown"),
        }

    def _run_fixiq_analysis(
        self,
        alert: dict[str, Any],
        rca_output: dict[str, Any],
        service_name: str,
    ) -> None:
        """Run full FixIQ deep analysis."""
        from app.core.evidence_chain import (
            EvidenceChainAnalyzer,
            display_evidence_chain,
        )
        from app.core.cascade_analyzer import (
            CascadeAnalyzer,
            display_cascade_analysis,
        )
        from app.core.anomaly_timeline import (
            AnomalyTimelineAnalyzer,
            display_anomaly_timeline,
        )
        from app.core.similar_incidents import (
            SimilarIncidentsFinder,
            display_similar_incidents,
        )
        from app.core.urgency import UrgencyScorer
        from app.core.blast_radius import (
            BlastRadiusAnalyzer
        )
        from app.core.k8s_collector import K8sCollector
        from app.core.knowledge_base import KnowledgeBase

        # Get REAL K8s data
        collector = K8sCollector(
            namespace=self.namespace
        )
        k8s_info = collector.get_service_info(
            service_name
        )

        # Enrich RCA with real K8s data
        if k8s_info:
            rca_output["k8s_info"] = {
                "memory_limit": k8s_info.memory_limit,
                "memory_request": k8s_info.memory_request,
                "restart_count": k8s_info.restart_count,
                "pod_status": k8s_info.pod_status,
                "deployment_revision": (
                    k8s_info.deployment_revision
                ),
                "real_dependents": k8s_info.dependents,
                "real_events": [
                    e.get("message", "")
                    for e in k8s_info.recent_events[:5]
                ],
            }
            print(
                f"  {GREEN}✓{RESET} Real K8s data: "
                f"memory={k8s_info.memory_limit}, "
                f"restarts={k8s_info.restart_count}"
            )

        print()

        # 1. Evidence Chain
        evidence = EvidenceChainAnalyzer().analyze(
            rca_output, alert
        )
        display_evidence_chain(evidence)

        # 2. Cascade Analysis with real dependents
        if k8s_info and k8s_info.dependents:
            print(
                f"\n  {GREEN}✓{RESET} Real K8s dependents: "
                f"{k8s_info.dependents}"
            )
        cascade = CascadeAnalyzer().analyze(
            service_name, rca_output
        )
        display_cascade_analysis(cascade)

        # 3. Anomaly Timeline
        timeline = AnomalyTimelineAnalyzer().analyze(
            rca_output, alert
        )
        display_anomaly_timeline(timeline)

        # 4. Similar Incidents
        similar = SimilarIncidentsFinder().find(
            rca_output.get("root_cause", ""),
            service_name,
            rca_output,
        )
        display_similar_incidents(similar)

        # 5. Urgency + Blast
        urgency = UrgencyScorer().score(
            service_name, rca_output
        )
        blast = BlastRadiusAnalyzer().analyze(
            service_name, rca_output
        )

        # Final summary
        self._print_final_summary(
            rca_output, urgency, blast, k8s_info
        )

        # Save to knowledge base
        KnowledgeBase().save(
            rca_output.get("root_cause", ""),
            rca_output,
        )

        print(
            f"\n  {GREEN}✓{RESET} Incident saved "
            f"to knowledge base"
        )
        print(f"\n{BOLD}{'═' * 70}{RESET}")
        print(
            f"{GREEN}{BOLD}  ✅ Pipeline complete!"
            f"{RESET}"
        )
        print(f"{BOLD}{'═' * 70}{RESET}\n")

    def _print_final_summary(
        self,
        rca_output: dict[str, Any],
        urgency: dict[str, Any],
        blast: dict[str, Any],
        k8s_info: Any,
    ) -> None:
        """Print final pipeline summary."""
        print(f"\n{BOLD}{'─' * 70}{RESET}")
        print(f"{BOLD}  📋 FINAL SUMMARY{RESET}")
        print(f"{BOLD}{'─' * 70}{RESET}")

        print(
            f"\n  Root Cause: "
            f"{rca_output.get('root_cause', 'Unknown')}"
        )

        score = urgency.get("score", "UNKNOWN")
        level = urgency.get("level", 0)
        color = (
            RED if level >= 8 else
            YELLOW if level >= 5 else
            GREEN
        )
        print(
            f"  Urgency:    "
            f"{color}{score} ({level}/10){RESET}"
        )
        print(
            f"  Fix within: "
            f"{urgency.get('fix_within', 'N/A')}"
        )
        print(
            f"  Users at risk: "
            f"~{blast.get('users_impacted', 0)}"
        )

        if k8s_info:
            print(f"\n  Real K8s State:")
            print(
                f"  Memory limit: {k8s_info.memory_limit}"
            )
            print(
                f"  Restarts: {k8s_info.restart_count}"
            )
            print(
                f"  Pod status: {k8s_info.pod_status}"
            )

        actions = rca_output.get(
            "recommended_actions", []
        )
        if actions:
            print(f"\n  Recommended Actions:")
            for action in actions[:3]:
                print(f"  → {action}")