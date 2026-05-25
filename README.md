# FixIQ — Powered by OpenSRE

> Intelligent Incident Fix Advisor for Cloud-Native Systems

FixIQ goes beyond basic root cause analysis. When an alert fires,
FixIQ runs a deep investigation and tells you exactly what broke,
why it broke, what else is affected, and how urgent it is to fix.

---

## The Problem

When production breaks, engineers waste time:
- Reading through hundreds of log lines manually
- Checking which services are affected one by one
- Googling the same fixes they applied last month
- Figuring out which alert to fix first when 5 fire at once

## The Solution

FixIQ automates the deep investigation work so engineers can
focus on fixing, not investigating.

---

## Features

### Single Alert Analysis
```bash
fixiq analyze -i alert.json --service checkout-api
```

| Feature | What it does |
|---------|-------------|
| 🔍 Evidence Chain | Exact file + line numbers where errors occurred |
| 🚀 Deployment Correlation | Links incident to recent Git commits |
| ⚡ Cascade Analysis | Which services fail next and fix order |
| 📈 Anomaly Timeline | Which metric failed first and detection lag |
| 🔄 Similar Incidents | Past incidents and what fixed them |
| 📊 Impact Analysis | All affected services |
| ⏰ Urgency Score | CRITICAL/HIGH/MEDIUM/LOW with fix-within time |
| ⚠️ Blast Radius | Users affected, teams, peak traffic warning |

### Multi-Alert Prioritization
```bash
fixiq multi -i alerts.json --analyze-top 3
```

When multiple alerts fire at once, FixIQ automatically
prioritizes them by service criticality, severity, users
affected and cascade potential.

### Fix Verification
```bash
fixiq analyze -i alert.json --verify
```

Re-run after applying a fix to verify the issue is resolved.

---

## Installation

From source:
```bash
git clone https://github.com/sahil0480/FixIQ.git
cd FixIQ
pip install -e .
```

---

## Quick Start

```bash
# Analyze a single alert
fixiq analyze -i alert.json --service checkout-api

# Prioritize multiple alerts
fixiq multi -i alerts.json

# Analyze top 3 priority alerts in detail
fixiq multi -i alerts.json --analyze-top 3

# Verify a fix worked
fixiq analyze -i alert.json --verify
```

---

## Alert Format

Single alert:
```json
{
  "title": "Pod OOMKilled in checkout-api",
  "severity": "critical",
  "service": "checkout-api",
  "timestamp": "2026-05-25T16:00:00Z",
  "metrics": {
    "memory_usage_mb": 980,
    "error_rate_pct": 45,
    "restart_count": 3
  },
  "logs": [
    "ERROR checkout.py:184 DatabaseConnectionError",
    "ERROR pool.py:92 ConnectionPool: all connections busy"
  ]
}
```

Multiple alerts:
```json
{
  "alerts": [
    {
      "id": "alert-001",
      "title": "Pod OOMKilled",
      "severity": "critical",
      "service": "checkout-api"
    },
    {
      "id": "alert-002",
      "title": "High latency",
      "severity": "low",
      "service": "logging"
    }
  ]
}
```

---

## Example Output

🔍 EVIDENCE CHAIN
──────────────────────────────────────────────────────
Root Trigger: Database connection pool exhausted
Confidence: 80%
Evidence Timeline:

[CRITICAL] Database connection pool exhausted
[ERROR]    checkout.py:184 DatabaseConnectionError
→ checkout.py:184
[ERROR]    pool.py:92 ConnectionPool: all connections busy
→ pool.py:92
[CRITICAL] Error rate: 34%
[CRITICAL] Latency: 8400ms

Affected Files:

checkout.py:184  (2 occurrences)
pool.py:92       (1 occurrence)

⚡ CASCADE FAILURE ANALYSIS
──────────────────────────────────────────────────────
● [CRITICAL] checkout-api
→ [HIGH] payment-service
→ [HIGH] order-service
→ [HIGH] user-dashboard
→ [MEDIUM] billing-service
→ [MEDIUM] notification-service
Fix Order:

checkout-api
payment-service
order-service

⏰ URGENCY: CRITICAL (9/10) — Fix within < 15 minutes
⚠️  BLAST RADIUS: ~500 users — Peak traffic: YES

---

## Architecture
fixiq analyze -i alert.json
↓
Phase 1 — OpenSRE Investigation (LLM-powered)
↓
Phase 2 — FixIQ Deep Analysis
├── Evidence Chain Analyzer
├── Deployment Correlator
├── Cascade Failure Analyzer
├── Anomaly Timeline Analyzer
├── Similar Incidents Finder
├── Impact Analyzer
├── Urgency Scorer
└── Blast Radius Analyzer
↓
Unified Report + Knowledge Base

---

## Configuration

FixIQ uses OpenSRE for investigation. Configure your LLM in `.env`:

```bash
# Ollama (local, free)
LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3.2:3b
OLLAMA_BASE_URL=http://localhost:11434

# Gemini (free tier available)
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_key_here

# Anthropic
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your_key_here
```

---

## Running Tests

```bash
python -m pytest tests/ -v
```

103 tests — all passing.

---

## Knowledge Base

FixIQ automatically saves every incident to:
`~/.config/fixiq/knowledge_base.json`

Over time it learns what fixes work and surfaces
similar past incidents when a known issue reoccurs.

---

## License

Apache 2.0 — see [LICENSE](LICENSE)

Built on top of [OpenSRE](https://github.com/Tracer-Cloud/opensre)
(Apache 2.0, Copyright 2026 Tracer Cloud)

---

## Author

**Sahil Shaikh**
- GitHub: [@sahil0480](https://github.com/sahil0480)
- MSc Cloud Computing
- Open Source Contributor @ OpenSRE