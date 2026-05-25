"""FixIQ — Intelligent Incident Fix Advisor.

Powered by OpenSRE.

Usage:
    fixiq analyze -i alert.json
    fixiq analyze -i alert.json --verify
    fixiq analyze -i alert.json --service checkout-api
    fixiq multi -i alerts.json
    fixiq multi -i alerts.json --analyze-top 3
"""

from __future__ import annotations

import json
import click
from pathlib import Path
from rich.console import Console
from rich.rule import Rule
from rich.text import Text


console = Console(
    highlight=False,
    force_terminal=True,
    color_system="truecolor",
)


@click.group()
@click.version_option(version="0.1.0", prog_name="fixiq")
def cli() -> None:
    """FixIQ — Intelligent Incident Fix Advisor powered by OpenSRE.

    \b
    Tells you:
      - Evidence chain with exact file + line numbers
      - Deployment correlation — what changed recently
      - Cascade failure analysis — what to fix first
      - Anomaly timeline — when things went wrong
      - Similar incidents — what worked before
      - Multi-alert prioritization — what to fix first

    \b
    Examples:
      fixiq analyze -i alert.json
      fixiq analyze -i alert.json --verify
      fixiq analyze -i alert.json --service checkout-api
      fixiq multi -i alerts.json
      fixiq multi -i alerts.json --analyze-top 3
    """
    pass


@cli.command(name="analyze")
@click.option(
    "--input", "-i",
    "input_file",
    required=True,
    type=click.Path(exists=True),
    help="Path to alert JSON file.",
)
@click.option(
    "--verify",
    is_flag=True,
    default=False,
    help="Verify if a previous fix worked.",
)
@click.option(
    "--service", "-s",
    default=None,
    help="Service name to analyze.",
)
def analyze_command(
    input_file: str,
    verify: bool,
    service: str | None,
) -> None:
    """Analyze an alert and show full investigation report.

    \b
    Examples:
      fixiq analyze -i alert.json
      fixiq analyze -i alert.json --verify
      fixiq analyze -i alert.json --service checkout-api
    """
    from app.core.evidence_chain import (
        EvidenceChainAnalyzer, display_evidence_chain
    )
    from app.core.deployment_correlator import (
        DeploymentCorrelator, display_deployment_correlation
    )
    from app.core.cascade_analyzer import (
        CascadeAnalyzer, display_cascade_analysis
    )
    from app.core.anomaly_timeline import (
        AnomalyTimelineAnalyzer, display_anomaly_timeline
    )
    from app.core.similar_incidents import (
        SimilarIncidentsFinder, display_similar_incidents
    )
    from app.core.impact import ImpactAnalyzer
    from app.core.urgency import UrgencyScorer
    from app.core.blast_radius import BlastRadiusAnalyzer
    from app.core.knowledge_base import KnowledgeBase

    # Print header
    _print_header()

    # Load alert
    alert_path = Path(input_file)
    try:
        alert_data = json.loads(alert_path.read_text())
        console.print(
            f"\n  Loading alert from [bold]{input_file}[/bold]..."
        )
    except Exception as exc:
        console.print(
            f"\n  [bold red]Error loading alert:[/bold red] {exc}"
        )
        return

    # Run OpenSRE investigation
    console.print("\n  Running OpenSRE investigation...")
    final_state = _run_investigation(alert_data)

    root_cause = final_state.get("root_cause", "Unknown")
    service_name = service or final_state.get(
        "service", "unknown"
    )

    console.print(
        f"\n  [bold]Root Cause:[/bold] {root_cause}"
    )

    # Verify mode
    if verify:
        _run_verification(root_cause, console)
        return

    # Run all 5 investigation modules
    console.print(
        "\n  Running deep investigation analysis..."
    )

    # 1. Evidence Chain
    console.print("  → Building evidence chain...")
    evidence = EvidenceChainAnalyzer().analyze(
        final_state, alert_data
    )
    display_evidence_chain(evidence)

    # 2. Deployment Correlation
    console.print("  → Checking deployment correlation...")
    correlation = DeploymentCorrelator().analyze(
        service_name, final_state, alert_data
    )
    display_deployment_correlation(correlation)

    # 3. Cascade Analysis
    console.print("  → Analyzing cascade failures...")
    cascade = CascadeAnalyzer().analyze(
        service_name, final_state
    )
    display_cascade_analysis(cascade)

    # 4. Anomaly Timeline
    console.print("  → Building anomaly timeline...")
    timeline = AnomalyTimelineAnalyzer().analyze(
        final_state, alert_data
    )
    display_anomaly_timeline(timeline)

    # 5. Similar Incidents
    console.print("  → Searching similar incidents...")
    similar = SimilarIncidentsFinder().find(
        root_cause, service_name, final_state
    )
    display_similar_incidents(similar)

    # FixIQ Layer — Impact, Urgency, Blast Radius
    impact = ImpactAnalyzer().analyze(
        service_name, final_state
    )
    urgency = UrgencyScorer().score(
        service_name, final_state
    )
    blast = BlastRadiusAnalyzer().analyze(
        service_name, final_state
    )

    # Display FixIQ summary
    _display_fixiq_summary(
        console, root_cause, impact, urgency, blast
    )

    # Save to knowledge base
    KnowledgeBase().save(root_cause, final_state)
    console.print(
        "\n  [dim]Incident saved to knowledge base.[/dim]"
    )


@cli.command(name="multi")
@click.option(
    "--input", "-i",
    "input_file",
    required=True,
    type=click.Path(exists=True),
    help="Path to JSON file containing multiple alerts.",
)
@click.option(
    "--analyze-top",
    "-n",
    default=1,
    show_default=True,
    help="Number of top priority alerts to fully analyze.",
)
def multi_command(
    input_file: str,
    analyze_top: int,
) -> None:
    """Prioritize multiple alerts and analyze top ones.

    \b
    Examples:
      fixiq multi -i alerts.json
      fixiq multi -i alerts.json --analyze-top 3
    """
    from app.core.multi_alert import (
        MultiAlertPrioritizer,
        display_multi_alert_result,
    )
    from app.core.evidence_chain import (
        EvidenceChainAnalyzer, display_evidence_chain
    )
    from app.core.cascade_analyzer import (
        CascadeAnalyzer, display_cascade_analysis
    )
    from app.core.urgency import UrgencyScorer
    from app.core.blast_radius import BlastRadiusAnalyzer

    # Print header
    _print_header()

    # Load alerts file
    alerts_path = Path(input_file)
    try:
        data = json.loads(alerts_path.read_text())
        alerts = data.get("alerts", [])
        console.print(
            f"\n  Loading {len(alerts)} alerts "
            f"from [bold]{input_file}[/bold]..."
        )
    except Exception as exc:
        console.print(
            f"\n  [bold red]Error loading alerts:"
            f"[/bold red] {exc}"
        )
        return

    if not alerts:
        console.print(
            "\n  [yellow]No alerts found.[/yellow]"
        )
        return

    # Prioritize alerts
    console.print("\n  Prioritizing alerts...")
    prioritizer = MultiAlertPrioritizer()
    result = prioritizer.prioritize(alerts)

    # Display priority queue
    display_multi_alert_result(result)

    # Analyze top N alerts in detail
    top_alerts = result.prioritized[:analyze_top]

    for i, prioritized_alert in enumerate(top_alerts, 1):
        alert_data = prioritized_alert.alert_data
        service = prioritized_alert.service

        console.print(
            f"\n\n  [bold]━━━ Detailed Analysis: "
            f"#{prioritized_alert.priority_rank} "
            f"{service} ━━━[/bold]"
        )

        # Run investigation
        console.print(
            "\n  Running OpenSRE investigation..."
        )
        final_state = _run_investigation(alert_data)

        root_cause = final_state.get(
            "root_cause",
            alert_data.get("title", "Unknown")
        )
        console.print(
            f"  [bold]Root Cause:[/bold] {root_cause}"
        )

        # Evidence Chain
        console.print(
            "\n  Running deep investigation analysis..."
        )
        evidence = EvidenceChainAnalyzer().analyze(
            final_state, alert_data
        )
        display_evidence_chain(evidence)

        # Cascade Analysis
        cascade = CascadeAnalyzer().analyze(
            service, final_state
        )
        display_cascade_analysis(cascade)

        # Urgency + Blast
        urgency = UrgencyScorer().score(
            service, final_state
        )
        blast = BlastRadiusAnalyzer().analyze(
            service, final_state
        )
        _display_fixiq_summary(
            console, root_cause,
            {"affected_services": []},
            urgency, blast
        )

        if i < len(top_alerts):
            console.print(
                f"\n  [dim]Moving to next alert...[/dim]"
            )


def _print_header() -> None:
    """Print FixIQ header."""
    console.print()
    console.print(Rule(style="dim"))
    header = Text()
    header.append("  FixIQ", style="bold white")
    header.append(
        "  —  Intelligent Incident Fix Advisor",
        style="dim"
    )
    console.print(header)
    powered = Text()
    powered.append("  Powered by OpenSRE", style="dim")
    console.print(powered)
    console.print(Rule(style="dim"))


def _run_investigation(
    alert_data: dict
) -> dict:
    """Run OpenSRE investigation."""
    try:
        from opensre.investigate import run_investigation
        return run_investigation(alert_data)
    except Exception:
        return {
            "root_cause": alert_data.get(
                "title",
                alert_data.get("message", "Unknown")
            ),
            "recommended_actions": [],
            "service": alert_data.get(
                "service", "unknown"
            ),
            "evidence_entries": [],
            "report": "",
        }


def _display_fixiq_summary(
    console: Console,
    root_cause: str,
    impact: dict,
    urgency: dict,
    blast: dict,
) -> None:
    """Display FixIQ summary section."""
    console.print()
    console.print(Rule(style="dim"))
    console.print(
        Text("  FixIQ Summary", style="bold white")
    )
    console.print(Rule(style="dim"))

    # Impact
    console.print("\n  [bold]📊 AFFECTED SERVICES[/bold]")
    services = impact.get("affected_services", [])
    if services:
        for svc in services:
            console.print(f"  • {svc}")
    else:
        console.print("  [dim]See cascade analysis above[/dim]")

    # Urgency
    console.print("\n  [bold]⏰ URGENCY[/bold]")
    score = urgency.get("score", "UNKNOWN")
    level = urgency.get("level", 0)
    color = (
        "red" if level >= 8 else
        "yellow" if level >= 5 else
        "green"
    )
    console.print(
        f"  Score: [{color}]{score} ({level}/10)[/{color}]"
    )
    console.print(
        f"  Fix within: {urgency.get('fix_within', 'N/A')}"
    )

    # Blast Radius
    console.print("\n  [bold]⚠️  BLAST RADIUS[/bold]")
    console.print(
        f"  Users impacted: "
        f"~{blast.get('users_impacted', 0)}"
    )
    peak = blast.get("peak_traffic", False)
    peak_str = (
        "[red]YES — proceed with caution[/red]"
        if peak else "[green]NO[/green]"
    )
    console.print(f"  Peak traffic: {peak_str}")
    console.print(
        f"  Recommendation: "
        f"{blast.get('recommendation', 'N/A')}"
    )
    console.print()
    console.print(Rule(style="dim"))


def _run_verification(
    root_cause: str,
    console: Console,
) -> None:
    """Run fix verification."""
    from app.core.knowledge_base import KnowledgeBase

    console.print(
        "\n  [bold]🔍 VERIFICATION MODE[/bold]"
    )
    kb = KnowledgeBase()
    past = kb.lookup(root_cause)

    if not past:
        console.print(
            "  [yellow]No previous fix found.[/yellow]"
        )
        console.print(
            "  Run without --verify first to record incident."
        )
        return

    console.print(
        f"\n  Previous fix: {past.get('fix', 'N/A')}"
    )
    console.print(
        f"  Recorded: {past.get('date', 'N/A')[:10]}"
    )
    console.print(
        f"  Occurrences: {past.get('occurrences', 1)}"
    )
    console.print(
        "\n  [dim]Re-run without --verify to check "
        "if issue is still present.[/dim]"
    )


if __name__ == "__main__":
    cli()