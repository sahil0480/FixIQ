"""Deployment Correlator for FixIQ.

Automatically correlates incidents with recent deployments.
90% of incidents happen after deployments.

This tells engineers:
- What was deployed recently
- Which files changed
- Whether the deployment caused the incident
- Whether to rollback
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class Deployment:
    """A recent deployment."""
    version: str
    timestamp: str
    service: str
    deployed_by: str
    changed_files: list[str]
    commit_message: str
    correlation_score: float = 0.0


@dataclass
class DeploymentCorrelation:
    """Result of deployment correlation analysis."""
    has_recent_deployment: bool
    deployments: list[Deployment]
    most_likely_culprit: Deployment | None
    correlation_score: float
    recommendation: str
    rollback_command: str | None


class DeploymentCorrelator:
    """Correlates incidents with recent deployments."""

    def __init__(
        self,
        github_token: str | None = None,
        repo: str | None = None,
    ) -> None:
        self.github_token = (
            github_token or os.getenv("GITHUB_TOKEN", "")
        )
        self.repo = repo or os.getenv("GITHUB_REPO", "")

    def analyze(
        self,
        service_name: str,
        rca_output: dict[str, Any],
        alert_data: dict[str, Any],
    ) -> DeploymentCorrelation:
        """Analyze correlation between incident and deployments.

        Args:
            service_name: Name of the affected service
            rca_output: RCA output from OpenSRE
            alert_data: Original alert data

        Returns:
            Deployment correlation analysis
        """
        # Try to get recent deployments
        deployments = self._get_recent_deployments(service_name)

        if not deployments:
            return DeploymentCorrelation(
                has_recent_deployment=False,
                deployments=[],
                most_likely_culprit=None,
                correlation_score=0.0,
                recommendation=(
                    "No recent deployments found. "
                    "Issue may be infrastructure related."
                ),
                rollback_command=None,
            )

        # Score each deployment
        root_cause = rca_output.get("root_cause", "")
        for deployment in deployments:
            deployment.correlation_score = (
                self._score_correlation(
                    deployment, root_cause, alert_data
                )
            )

        # Find most likely culprit
        culprit = max(
            deployments,
            key=lambda d: d.correlation_score
        )

        # Build recommendation
        recommendation = self._build_recommendation(
            culprit, deployments
        )

        # Build rollback command
        rollback_cmd = self._build_rollback_command(
            service_name, culprit
        )

        logger.info(
            "Deployment correlation: %d deployments, "
            "highest score %.0f%%",
            len(deployments),
            culprit.correlation_score * 100,
        )

        return DeploymentCorrelation(
            has_recent_deployment=True,
            deployments=deployments,
            most_likely_culprit=culprit,
            correlation_score=culprit.correlation_score,
            recommendation=recommendation,
            rollback_command=rollback_cmd,
        )

    def _get_recent_deployments(
        self, service_name: str
    ) -> list[Deployment]:
        """Get recent deployments from Git or GitHub."""
        deployments = []

        # Try Git log first
        git_deployments = self._get_git_deployments()
        if git_deployments:
            deployments.extend(git_deployments)

        # Try GitHub releases if token available
        if self.github_token and self.repo:
            github_deployments = self._get_github_releases()
            deployments.extend(github_deployments)

        return deployments[:5]  # Return last 5

    def _get_git_deployments(self) -> list[Deployment]:
        """Get recent deployments from Git log."""
        try:
            result = subprocess.run(
                [
                    "git", "log",
                    "--oneline",
                    "--format=%H|%ai|%an|%s",
                    "-10"
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode != 0:
                return []

            deployments = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) < 4:
                    continue

                commit_hash, timestamp, author, message = parts[:4]

                # Get changed files
                changed = self._get_changed_files(commit_hash)

                deployments.append(Deployment(
                    version=commit_hash[:7],
                    timestamp=timestamp,
                    service="unknown",
                    deployed_by=author,
                    changed_files=changed,
                    commit_message=message,
                ))

            return deployments

        except Exception as exc:
            logger.warning("Failed to get git deployments: %s", exc)
            return []

    def _get_changed_files(self, commit_hash: str) -> list[str]:
        """Get files changed in a commit."""
        try:
            result = subprocess.run(
                ["git", "diff-tree", "--no-commit-id",
                 "-r", "--name-only", commit_hash],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return []
            return result.stdout.strip().split("\n")[:10]
        except Exception:
            return []

    def _get_github_releases(self) -> list[Deployment]:
        """Get recent releases from GitHub API."""
        try:
            url = (
                f"https://api.github.com/repos/"
                f"{self.repo}/releases?per_page=5"
            )
            headers = {
                "Authorization": f"token {self.github_token}",
                "Accept": "application/vnd.github.v3+json",
            }
            response = httpx.get(url, headers=headers, timeout=5)
            response.raise_for_status()

            deployments = []
            for release in response.json():
                deployments.append(Deployment(
                    version=release.get("tag_name", "unknown"),
                    timestamp=release.get(
                        "published_at",
                        datetime.now().isoformat()
                    ),
                    service="unknown",
                    deployed_by=release.get(
                        "author", {}
                    ).get("login", "unknown"),
                    changed_files=[],
                    commit_message=release.get("name", ""),
                ))
            return deployments

        except Exception as exc:
            logger.warning(
                "Failed to get GitHub releases: %s", exc
            )
            return []

    def _score_correlation(
        self,
        deployment: Deployment,
        root_cause: str,
        alert_data: dict[str, Any],
    ) -> float:
        """Score how likely a deployment caused the incident."""
        score = 0.0

        # Recent deployment = higher score
        try:
            deploy_time = datetime.fromisoformat(
                deployment.timestamp.replace("Z", "+00:00")
            )
            now = datetime.now(deploy_time.tzinfo)
            hours_ago = (
                now - deploy_time
            ).total_seconds() / 3600

            if hours_ago < 1:
                score += 0.4   # Very recent
            elif hours_ago < 6:
                score += 0.3   # Recent
            elif hours_ago < 24:
                score += 0.2   # Today
            elif hours_ago < 48:
                score += 0.1   # Yesterday
        except Exception:
            score += 0.1

        # Changed files match root cause
        if deployment.changed_files:
            root_lower = root_cause.lower()
            for f in deployment.changed_files:
                if any(k in f.lower() for k in
                       root_lower.split()[:5]):
                    score += 0.2
                    break

        # Commit message mentions service
        if any(k in deployment.commit_message.lower() for k in [
            "fix", "feat", "refactor", "update", "change"
        ]):
            score += 0.1

        return round(min(1.0, score), 2)

    def _build_recommendation(
        self,
        culprit: Deployment,
        deployments: list[Deployment],
    ) -> str:
        """Build recommendation based on correlation."""
        score = culprit.correlation_score

        if score >= 0.7:
            return (
                f"HIGH correlation with deployment "
                f"{culprit.version} by {culprit.deployed_by}. "
                f"Consider rollback immediately."
            )
        elif score >= 0.4:
            return (
                f"MEDIUM correlation with deployment "
                f"{culprit.version}. "
                f"Review changed files before deciding on rollback."
            )
        else:
            return (
                "LOW correlation with recent deployments. "
                "Issue likely infrastructure or config related."
            )

    def _build_rollback_command(
        self,
        service_name: str,
        culprit: Deployment,
    ) -> str | None:
        """Build rollback command."""
        if culprit.correlation_score < 0.4:
            return None

        return (
            f"kubectl rollout undo deployment/{service_name}\n"
            f"# OR rollback to specific version:\n"
            f"git revert {culprit.version}"
        )


def display_deployment_correlation(
    correlation: DeploymentCorrelation,
) -> None:
    """Display deployment correlation in terminal."""
    BOLD = "\033[1m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    GREEN = "\033[92m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    print(f"\n{BOLD}{'─' * 70}{RESET}")
    print(f"{BOLD}  🚀 DEPLOYMENT CORRELATION{RESET}")
    print(f"{BOLD}{'─' * 70}{RESET}")

    if not correlation.has_recent_deployment:
        print(f"\n  {YELLOW}No recent deployments found.{RESET}")
        print(f"  {correlation.recommendation}")
        return

    culprit = correlation.most_likely_culprit
    if culprit:
        score_pct = int(correlation.correlation_score * 100)
        color = (
            RED if score_pct >= 70 else
            YELLOW if score_pct >= 40 else
            GREEN
        )

        print(f"\n  {BOLD}Most Likely Culprit:{RESET}")
        print(f"  Version:    {culprit.version}")
        print(f"  Deployed:   {culprit.timestamp[:19]}")
        print(f"  By:         {culprit.deployed_by}")
        print(f"  Message:    {culprit.commit_message[:60]}")
        print(
            f"  Correlation: {color}{score_pct}%{RESET}"
        )

        if culprit.changed_files:
            print(f"\n  {BOLD}Changed Files:{RESET}")
            for f in culprit.changed_files[:5]:
                if f:
                    print(f"  • {f}")

    print(f"\n  {BOLD}Recommendation:{RESET}")
    print(f"  {correlation.recommendation}")

    if correlation.rollback_command:
        print(f"\n  {BOLD}Rollback Command:{RESET}")
        for line in correlation.rollback_command.split("\n"):
            print(f"  {DIM}{line}{RESET}")

    print(f"\n{BOLD}{'─' * 70}{RESET}")