"""FixIQ Automated Pipeline.

Full automated pipeline:
1. Service Discovery — learns YOUR system
2. K8s Watcher — detects incidents
3. Incident Queue — prioritizes multiple alerts
4. OpenSRE — real LLM investigation with live progress
5. FixIQ — deep analysis
6. Unified report

No manual steps — fully automated!
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from typing import Any

from app.core.k8s_watcher import K8sIncident, K8sWatcher
from app.core.service_discovery import (
    ServiceDiscovery,
    SystemMap,
    display_system_map,
)
from app.core.incident_queue import (
    IncidentQueue,
    display_queue,
)

logger = logging.getLogger(__name__)

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
        self.discovery = ServiceDiscovery(
            namespace=namespace
        )
        self.queue: IncidentQueue | None = None
        self._system_map: SystemMap | None = None
        self._worker_thread: threading.Thread | None = None
        self._running = False

    def run(self) -> None:
        """Start the automated pipeline."""
        self._print_banner()

        print(f"\n{BOLD}{'─' * 70}{RESET}")
        print(f"{BOLD}  STEP 1 — Service Discovery{RESET}")
        print(f"{BOLD}{'─' * 70}{RESET}")

        self._system_map = self.discovery.discover()
        display_system_map(self._system_map)

        self.queue = IncidentQueue(
            system_map=self._system_map
        )

        self._running = True
        self._worker_thread = threading.Thread(
            target=self._process_queue,
            daemon=True,
        )
        self._worker_thread.start()

        print(f"\n{BOLD}{'─' * 70}{RESET}")
        print(
            f"{BOLD}  STEP 2 — Watching for Incidents{RESET}"
        )
        print(f"{BOLD}{'─' * 70}{RESET}")

        try:
            self.watcher.watch(
                on_incident=self._on_incident_detected
            )
        except KeyboardInterrupt:
            self._running = False
            print("\n  Stopping pipeline...")

    def _on_incident_detected(
        self, incident: K8sIncident
    ) -> None:
        """Called when K8s incident is detected."""
        if not self.queue:
            return

        # Skip if already processing
        if self.queue.is_processing(incident.service):
            return

        # Skip if already queued
        if incident.service in \
                self.queue._queued_services:
            return

        print(
            f"\n{RED}{BOLD}  🚨 INCIDENT DETECTED: "
            f"{incident.reason} in "
            f"{incident.service}{RESET}"
        )

        alert = self.watcher.build_alert(incident)

        if self._system_map:
            svc = self._system_map.get_service(
                incident.service
            )
            if svc:
                alert["service_info"] = {
                    "criticality": svc.criticality,
                    "users_affected": svc.users_affected,
                    "memory_limit": svc.memory_limit,
                    "restart_count": svc.restart_count,
                    "is_healthy": svc.is_healthy,
                    "depends_on": svc.depends_on,
                    "image": svc.image,
                }
                print(
                    f"  {GREEN}✓{RESET} Service known: "
                    f"criticality={svc.criticality}/10, "
                    f"users=~{svc.users_affected}"
                )

        self.queue.add(incident, alert)
        queue_size = self.queue.size()
        if queue_size > 1:
            display_queue(
                self.queue,
                f"{queue_size} INCIDENTS QUEUED"
            )

    def _process_queue(self) -> None:
        """Worker thread — processes incidents in order."""
        while self._running:
            if self.queue and not self.queue.is_empty():
                queued = self.queue.get_next()
                if queued:
                    self.queue.mark_processing(
                        queued.incident.service
                    )
                    try:
                        self._handle_incident(queued)
                    finally:
                        self.queue.mark_done(queued)
            else:
                time.sleep(2)

    def _handle_incident(self, queued: Any) -> None:
        """Handle a single queued incident."""
        incident = queued.incident
        alert = queued.alert

        # Check if service already recovered
        from app.core.k8s_collector import K8sCollector
        collector = K8sCollector(
            namespace=self.namespace
        )
        pod = collector.get_pod_details(
            incident.service
        )

        if (pod and
                pod.get("phase") == "Running" and
                pod.get("restart_count", 0) == 0 and
                pod.get("exit_code", 0) == 0 and
                pod.get("ready", False)):
            print(
                f"\n  {GREEN}✓{RESET} "
                f"{incident.service} already recovered "
                f"— skipping investigation"
            )
            self.watcher.mark_resolved(incident.service)
            return

        print(f"\n{BOLD}{'═' * 70}{RESET}")
        print(
            f"{BOLD}  🔬 INVESTIGATING: "
            f"{incident.service}{RESET}"
        )
        print(
            f"  Priority: {queued.priority} | "
            f"Criticality: "
            f"{queued.service_criticality}/10 | "
            f"Users: ~{queued.estimated_users}"
        )
        print(f"{BOLD}{'═' * 70}{RESET}")

        pod_details = alert.get("pod_details", {})
        if pod_details:
            exit_code = pod_details.get("exit_code", 0)
            oom_label = (
                " ← OOMKilled!"
                if exit_code == 137 else ""
            )
            print(
                f"\n  {GREEN}✓{RESET} Pod: "
                f"{pod_details.get('pod_name', 'unknown')}"
            )
            print(
                f"  {GREEN}✓{RESET} Status: "
                f"{pod_details.get('phase', 'unknown')}"
            )
            print(
                f"  {GREEN}✓{RESET} Restarts: "
                f"{pod_details.get('restart_count', 0)}"
            )
            print(
                f"  {GREEN}✓{RESET} Memory limit: "
                f"{pod_details.get('memory_limit', 'unknown')}"
            )
            print(
                f"  {GREEN}✓{RESET} Exit code: "
                f"{exit_code}{oom_label}"
            )

        service_info = alert.get("service_info", {})
        if service_info:
            deps = service_info.get("depends_on", [])
            if deps:
                print(
                    f"  {GREEN}✓{RESET} "
                    f"Downstream services affected: "
                    f"{', '.join(deps)}"
                )
            else:
                print(
                    f"  {DIM}  No downstream services "
                    f"in cluster{RESET}"
                )

        print(
            f"\n  {BLUE}→ Running OpenSRE "
            f"investigation (Ollama LLM)...{RESET}"
        )
        rca_output = self._run_opensre(alert)
        root_cause = rca_output.get(
            "root_cause", "Unknown"
        )
        print(
            f"  {GREEN}✓{RESET} Root cause: {root_cause}"
        )

        k8s_info = collector.get_service_info(
            incident.service
        )

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
            if service_info.get("depends_on"):
                rca_output["k8s_info"][
                    "real_dependents"
                ] = service_info["depends_on"]

            print(
                f"  {GREEN}✓{RESET} Real K8s data: "
                f"memory={k8s_info.memory_limit}, "
                f"restarts={k8s_info.restart_count}, "
                f"revision={k8s_info.deployment_revision}"
            )

        print(
            f"\n  {BLUE}→ Running FixIQ "
            f"deep analysis...{RESET}\n"
        )
        self._run_fixiq_analysis(
            alert, rca_output, incident.service
        )

    def _run_opensre(
        self, alert: dict[str, Any]
    ) -> dict[str, Any]:
        """Run OpenSRE investigation with live progress."""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".json",
                delete=False,
            ) as f:
                json.dump(alert, f)
                alert_file = f.name

            opensre_venv = os.path.join(
                self.opensre_path,
                ".venv/bin/opensre"
            )
            if not os.path.exists(opensre_venv):
                opensre_venv = "opensre"

            process = subprocess.Popen(
                [
                    opensre_venv,
                    "investigate",
                    "-i", alert_file,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.opensre_path,
            )

            progress_messages = [
                "Analyzing alert data...",
                "Querying Kubernetes events...",
                "Running LLM investigation...",
                "Building root cause hypothesis...",
                "Analyzing service dependencies...",
                "Generating recommendations...",
                "Validating findings...",
                "Finalizing investigation...",
            ]

            start_time = time.time()
            msg_index = 0
            timeout = 120
            last_print = 0

            print(
                f"  {DIM}[00:00] Starting "
                f"investigation...{RESET}"
            )

            while process.poll() is None:
                elapsed = int(
                    time.time() - start_time
                )

                if elapsed > timeout:
                    process.kill()
                    mins = elapsed // 60
                    secs = elapsed % 60
                    print(
                        f"\n  {YELLOW}⚠ OpenSRE timed out "
                        f"after {mins:02d}:{secs:02d} "
                        f"— using fallback RCA{RESET}"
                    )
                    try:
                        os.unlink(alert_file)
                    except Exception:
                        pass
                    return self._fallback_rca(alert)

                if elapsed - last_print >= 10:
                    mins = elapsed // 60
                    secs = elapsed % 60
                    msg = progress_messages[
                        msg_index % len(progress_messages)
                    ]
                    print(
                        f"  {DIM}[{mins:02d}:{secs:02d}]"
                        f"{RESET}   🤖 {msg}"
                    )
                    msg_index += 1
                    last_print = elapsed

                time.sleep(1)

            stdout, stderr = process.communicate()
            elapsed = int(time.time() - start_time)
            mins = elapsed // 60
            secs = elapsed % 60
            print(
                f"  {GREEN}✓{RESET} Investigation "
                f"complete in {mins:02d}:{secs:02d}"
            )

            rca = self._parse_opensre_output(
                stdout, stderr, alert
            )
            try:
                os.unlink(alert_file)
            except Exception:
                pass
            return rca

        except Exception as exc:
            logger.warning(
                "OpenSRE failed: %s", exc
            )
            return self._fallback_rca(alert)

    def _parse_opensre_output(
        self,
        stdout: str,
        stderr: str,
        alert: dict[str, Any],
    ) -> dict[str, Any]:
        """Parse OpenSRE investigation output."""
        import re
        output = stdout + stderr
        root_cause = alert.get("title", "Unknown")

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

        actions = []
        action_patterns = [
            r"[Rr]ecommend(?:ed)?\s+[Aa]ction[s]?"
            r"[:\s]+(.+?)(?:\n|$)",
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
        """Fallback RCA built from real K8s data."""
        title = alert.get("title", "Unknown")
        pod_details = alert.get("pod_details", {})
        service_info = alert.get("service_info", {})

        root_cause = title
        actions = []

        exit_code = pod_details.get("exit_code", 0)
        mem = pod_details.get("memory_limit", "unknown")
        restarts = pod_details.get("restart_count", 0)
        service = alert.get("service", "unknown")
        deps = service_info.get("depends_on", [])

        if exit_code == 137:
            root_cause = (
                f"Pod OOMKilled in {service} — "
                f"memory limit {mem} exceeded. "
                f"Restart count: {restarts}"
            )
            actions = [
                f"Increase memory limit above {mem}",
                "Check for memory leaks in application",
                "Monitor memory after applying fix",
            ]
            if deps:
                actions.append(
                    f"Check downstream: "
                    f"{', '.join(deps)}"
                )
        elif "BackOff" in title or "CrashLoop" in title:
            root_cause = (
                f"Container crash loop in {service} — "
                f"check application logs and config"
            )
            actions = [
                "Check container logs for errors",
                "Verify configuration and env vars",
                f"Check memory limit: {mem}",
            ]

        return {
            "root_cause": root_cause,
            "recommended_actions": actions,
            "evidence_entries": [],
            "report": root_cause,
            "service": service,
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
        from app.core.knowledge_base import KnowledgeBase

        service_info = alert.get("service_info", {})
        if service_info:
            rca_output["service_criticality"] = (
                service_info.get("criticality", 5)
            )
            rca_output["service_users"] = (
                service_info.get("users_affected", 100)
            )

        evidence = EvidenceChainAnalyzer().analyze(
            rca_output, alert
        )
        display_evidence_chain(evidence)

        cascade = CascadeAnalyzer().analyze(
            service_name, rca_output
        )
        display_cascade_analysis(cascade)

        timeline = AnomalyTimelineAnalyzer().analyze(
            rca_output, alert
        )
        display_anomaly_timeline(timeline)

        similar = SimilarIncidentsFinder().find(
            rca_output.get("root_cause", ""),
            service_name,
            rca_output,
        )
        display_similar_incidents(similar)

        urgency = UrgencyScorer().score(
            service_name, rca_output
        )
        blast = BlastRadiusAnalyzer().analyze(
            service_name, rca_output
        )

        self._print_final_summary(
            rca_output, urgency, blast, service_info
        )

        # Mark resolved — watcher ignores for 10 min
        self.watcher.mark_resolved(service_name)

        KnowledgeBase().save(
            rca_output.get("root_cause", ""),
            rca_output,
        )

        print(
            f"\n  {GREEN}✓{RESET} Saved to knowledge base"
        )
        print(
            f"  {GREEN}✓{RESET} {service_name} marked "
            f"as resolved (10min cooldown)"
        )
        print(f"\n{BOLD}{'═' * 70}{RESET}")
        print(
            f"{GREEN}{BOLD}  ✅ Pipeline complete "
            f"for {service_name}!{RESET}"
        )
        print(f"{BOLD}{'═' * 70}{RESET}\n")

        if self.queue and not self.queue.is_empty():
            remaining = self.queue.size()
            print(
                f"\n  {YELLOW}⚠ {remaining} more "
                f"incident(s) in queue "
                f"— processing next...{RESET}\n"
            )

    def _print_final_summary(
        self,
        rca_output: dict[str, Any],
        urgency: dict[str, Any],
        blast: dict[str, Any],
        service_info: dict[str, Any],
    ) -> None:
        """Print final pipeline summary."""
        print(f"\n{BOLD}{'─' * 70}{RESET}")
        print(f"{BOLD}  📋 FINAL SUMMARY{RESET}")
        print(f"{BOLD}{'─' * 70}{RESET}")

        print(
            f"\n  Root Cause: "
            f"{rca_output.get('root_cause', 'Unknown')}"
        )

        level = urgency.get("level", 0)
        score = urgency.get("score", "UNKNOWN")
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

        users = service_info.get(
            "users_affected",
            blast.get("users_impacted", 0)
        )
        print(f"  Users at risk: ~{users}")

        actions = rca_output.get(
            "recommended_actions", []
        )
        if actions:
            print(f"\n  Recommended Actions:")
            for action in actions[:3]:
                if action.strip():
                    print(
                        f"  {GREEN}→{RESET} {action}"
                    )

        service = rca_output.get("service", "unknown")
        print(f"\n  {BOLD}Apply Fix:{RESET}")
        print(
            f"  {DIM}kubectl set resources "
            f"deployment/{service} "
            f"--limits=memory=128Mi "
            f"--requests=memory=64Mi{RESET}"
        )
        print(
            f"\n  {BOLD}Record fix after applying:{RESET}"
        )
        print(
            f"  {DIM}fixiq record -s {service} "
            f"-f 'Increased memory to 128Mi' "
            f"-m 5{RESET}"
        )

    def _print_banner(self) -> None:
        """Print pipeline banner."""
        print(f"\n{BOLD}{'═' * 70}{RESET}")
        print(
            f"{BOLD}  FixIQ — Automated Incident "
            f"Pipeline{RESET}"
        )
        print(f"{DIM}  Powered by OpenSRE{RESET}")
        print(f"{BOLD}{'═' * 70}{RESET}")
        print(
            f"\n  {GREEN}✓{RESET} Kubernetes watcher ready"
        )
        print(
            f"  {GREEN}✓{RESET} Service discovery ready"
        )
        print(
            f"  {GREEN}✓{RESET} Incident queue ready"
        )
        print(
            f"  {GREEN}✓{RESET} "
            f"OpenSRE LLM ready (2min timeout)"
        )
        print(
            f"  {GREEN}✓{RESET} FixIQ analyzer ready"
        )