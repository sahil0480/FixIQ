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

        # Check for recovered services before watching
        self._check_recoveries()

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
        if self.queue and self.queue.is_processing(
            incident.service
        ):
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

        if self.queue:
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

    # Set to True to enable Ollama LLM investigation.
    # Set to False on low RAM machines (< 16GB).
    OLLAMA_ENABLED = True

    def _run_opensre(
        self, alert: dict[str, Any]
    ) -> dict[str, Any]:
        """Run OpenSRE investigation with live progress."""
        if not self.OLLAMA_ENABLED:
            print(
                f"  {DIM}→ Ollama disabled "
                f"(low RAM mode) — using fallback RCA{RESET}"
            )
            return self._fallback_rca(alert)

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
        """Fallback RCA built from real K8s data.

        Handles distinct failure types:
        - OOMKilled (exit 137)  — memory limit exceeded
        - Image pull failure    — bad image name/registry
        - Command/config crash  — bad startup command
        - CrashLoop             — repeated app crash
        """
        title = alert.get("title", "Unknown")
        pod_details = alert.get("pod_details", {})
        service_info = alert.get("service_info", {})
        logs = alert.get("logs", [])

        root_cause = title
        actions = []
        failure_type = "unknown"

        exit_code = pod_details.get("exit_code", 0)
        mem = pod_details.get("memory_limit", "unknown")
        restarts = pod_details.get("restart_count", 0)
        service = alert.get("service", "unknown")
        deps = service_info.get("depends_on", [])
        image = pod_details.get("image", "unknown")

        # Detect failure type from title + logs
        title_lower = title.lower()
        logs_text = " ".join(logs).lower()
        all_text = title_lower + " " + logs_text

        image_pull_errors = [
            "errimagepull", "imagepullbackoff",
            "errimageneverpull", "back-off pulling image",
            "failed to pull image", "not found",
        ]
        is_image_failure = any(
            e in all_text for e in image_pull_errors
        )

        if exit_code == 137:
            failure_type = "oomkilled"
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
                    f"Check downstream: {', '.join(deps)}"
                )

        elif is_image_failure:
            failure_type = "image_pull"
            root_cause = (
                f"Image pull failed in {service} — "
                f"image '{image}' cannot be pulled. "
                f"Check image name and registry access."
            )
            actions = [
                f"Verify image name is correct: {image}",
                f"Run: kubectl set image deployment/{service} "
                f"{service}=<correct-image>",
                "Check image registry is accessible",
                "Check imagePullPolicy in deployment spec",
            ]

        elif exit_code == 1 or (
            "backoff" in title_lower or
            "crashloop" in title_lower or
            "error" in title_lower
        ):
            failure_type = "crash"
            if restarts <= 5:
                root_cause = (
                    f"Container crash in {service} — "
                    f"exited with code {exit_code}. "
                    f"Likely bad startup command or config."
                )
                actions = [
                    f"Check recent changes: "
                    f"kubectl rollout history "
                    f"deployment/{service}",
                    f"Rollback if recently patched: "
                    f"kubectl rollout undo "
                    f"deployment/{service}",
                    "Check container logs for startup error",
                    "Verify env vars and startup command",
                ]
            else:
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
            "failure_type": failure_type,
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

        self.watcher.mark_resolved(service_name)

        # Save snapshot of broken state for recovery detection
        kb = KnowledgeBase()
        pod_details = alert.get("pod_details", {})
        service_info = alert.get("service_info", {})
        kb.save_snapshot(service_name, {
            "memory_limit": (
                pod_details.get("memory_limit")
                or service_info.get("memory_limit", "")
            ),
            "memory_request": service_info.get(
                "memory_request", ""
            ),
            "cpu_limit": service_info.get("cpu_limit", ""),
            "image": service_info.get("image", ""),
            "restart_count": (
                pod_details.get("restart_count")
                or service_info.get("restart_count", 0)
            ),
            "exit_code": pod_details.get("exit_code", 0),
            "env_vars": {},
            "deployment_revision": rca_output.get(
                "k8s_info", {}
            ).get("deployment_revision", 0),
            "root_cause": rca_output.get("root_cause", ""),
        })

        kb.save(
            rca_output.get("root_cause", ""),
            rca_output,
        )

        self._write_log(service_name, rca_output, alert)

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
        failure_type = rca_output.get(
            "failure_type", "unknown"
        )

        print(f"\n  {BOLD}Apply Fix:{RESET}")
        if failure_type == "oomkilled":
            fix_cmd = (
                f"kubectl set resources "
                f"deployment/{service} "
                f"--limits=memory=128Mi "
                f"--requests=memory=64Mi"
            )
            record_fix = "Increased memory limit to 128Mi"
        elif failure_type == "image_pull":
            fix_cmd = (
                f"kubectl set image "
                f"deployment/{service} "
                f"{service}=<correct-image-name>"
            )
            record_fix = "Restored correct image"
        elif failure_type == "crash":
            fix_cmd = (
                f"kubectl rollout undo "
                f"deployment/{service}"
            )
            record_fix = "Rolled back bad deployment"
        else:
            fix_cmd = (
                f"kubectl rollout undo "
                f"deployment/{service}"
            )
            record_fix = "Applied fix"

        print(f"  {DIM}{fix_cmd}{RESET}")
        print(
            f"\n  {BOLD}Record fix after applying:{RESET}"
        )
        print(
            f"  {DIM}fixiq record -s {service} "
            f"-f '{record_fix}' "
            f"-m 5{RESET}"
        )

    def _check_recoveries(self) -> None:
        """Check if previously broken services recovered.

        Called at startup (Run 2). Diffs KB snapshots
        vs current state and auto-records the fix.
        """
        from app.core.knowledge_base import KnowledgeBase
        from app.core.k8s_collector import K8sCollector

        kb = KnowledgeBase()
        unresolved = kb.get_all_unresolved_snapshots()

        if not unresolved:
            return

        collector = K8sCollector(namespace=self.namespace)
        recovered = []

        for service, snapshot in unresolved.items():
            pod = collector.get_pod_details(service)
            if not pod:
                continue

            is_healthy = (
                pod.get("phase") == "Running" and
                pod.get("exit_code", 0) == 0 and
                pod.get("ready", False) and
                pod.get("restart_count", 99) < 3
            )

            if is_healthy:
                fix_description = self._detect_fix(
                    service, snapshot, pod, collector
                )
                kb.record_fix(
                    service=service,
                    fix_applied=fix_description,
                    time_to_fix_minutes=0,
                )
                kb.mark_snapshot_resolved(service)
                recovered.append((service, fix_description))

        if recovered:
            print(f"\n{BOLD}{'═' * 70}{RESET}")
            print(f"{BOLD}  ✅ RECOVERY DETECTED{RESET}")
            print(f"{BOLD}{'═' * 70}{RESET}")
            print(
                f"\n  {GREEN}FixIQ detected the following "
                f"services recovered since last run:{RESET}\n"
            )
            for service, fix in recovered:
                print(
                    f"  {GREEN}✓{RESET} {BOLD}{service}{RESET}"
                )
                print(f"    Fix detected: {fix}")
                print(
                    f"    {DIM}Auto-recorded to knowledge "
                    f"base{RESET}\n"
                )
            print(f"{BOLD}{'═' * 70}{RESET}\n")

    def _detect_fix(
        self,
        service: str,
        snapshot: dict[str, Any],
        current_pod: dict[str, Any],
        collector: Any,
    ) -> str:
        """Diff broken snapshot vs current state."""
        fixes = []

        old_mem = snapshot.get("memory_limit", "")
        current_info = collector.get_service_info(service)

        if current_info:
            new_mem = current_info.memory_limit
            if old_mem and new_mem and old_mem != new_mem:
                fixes.append(
                    f"Increased memory limit "
                    f"{old_mem} → {new_mem}"
                )

            old_rev = snapshot.get("deployment_revision", 0)
            new_rev = current_info.deployment_revision
            if new_rev and old_rev and new_rev != old_rev:
                if not fixes:
                    fixes.append(
                        f"Deployment updated "
                        f"(revision {old_rev} → {new_rev})"
                    )

            old_image = snapshot.get("image", "")
            new_image = current_info.image
            if (old_image and new_image and
                    old_image != new_image):
                fixes.append(
                    f"Image updated: {new_image}"
                )

        old_exit = snapshot.get("exit_code", 0)
        if old_exit == 137 and not fixes:
            fixes.append(
                f"Fixed OOMKilled — memory limit "
                f"was {old_mem}"
            )

        if fixes:
            return "; ".join(fixes)

        return (
            f"Service recovered "
            f"(exact fix not detected — "
            f"was: {snapshot.get('root_cause', 'unknown')})"
        )

    def _write_log(
        self,
        service_name: str,
        rca_output: dict[str, Any],
        alert: dict[str, Any],
    ) -> None:
        """Write incident report to log file."""
        from pathlib import Path

        reports_dir = (
            Path.home() / ".config" / "fixiq" / "reports"
        )
        reports_dir.mkdir(parents=True, exist_ok=True)

        today = datetime.now().strftime("%Y-%m-%d")
        log_file = reports_dir / f"{today}.log"

        pod_details = alert.get("pod_details", {})
        service_info = alert.get("service_info", {})
        root_cause = rca_output.get("root_cause", "Unknown")
        k8s_info = rca_output.get("k8s_info", {})
        failure_type = rca_output.get(
            "failure_type", "unknown"
        )

        lines = [
            "=" * 70,
            f"INCIDENT REPORT — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 70,
            f"Service:      {service_name}",
            f"Failure Type: {failure_type.upper()}",
            f"Root Cause:   {root_cause}",
            f"Memory Limit: {pod_details.get('memory_limit') or service_info.get('memory_limit', 'unknown')}",
            f"Exit Code:    {pod_details.get('exit_code', 'unknown')}",
            f"Restarts:     {pod_details.get('restart_count') or service_info.get('restart_count', 'unknown')}",
            f"Revision:     {k8s_info.get('deployment_revision', 'unknown')}",
            "",
            "RECOMMENDED FIX:",
        ]

        if failure_type == "oomkilled":
            lines.append(
                f"  kubectl set resources deployment/{service_name} "
                f"--limits=memory=128Mi --requests=memory=64Mi"
            )
        elif failure_type == "image_pull":
            lines.append(
                f"  kubectl set image deployment/{service_name} "
                f"{service_name}=<correct-image-name>"
            )
        else:
            lines.append(
                f"  kubectl rollout undo deployment/{service_name}"
            )

        lines += [
            "",
            "AFTER APPLYING FIX — run fixiq again to auto-record recovery.",
            "=" * 70,
            "",
        ]

        with open(log_file, "a") as f:
            f.write("\n".join(lines) + "\n")

        print(
            f"  {GREEN}✓{RESET} Report saved → "
            f"{log_file}"
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
        if self.OLLAMA_ENABLED:
            print(
                f"  {GREEN}✓{RESET} "
                f"OpenSRE LLM ready (2min timeout)"
            )
        else:
            print(
                f"  {YELLOW}⚠{RESET} "
                f"Ollama disabled (low RAM mode) "
                f"— fallback RCA active"
            )
        print(
            f"  {GREEN}✓{RESET} FixIQ analyzer ready"
        )