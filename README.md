# FixIQ

> Automated Incident Response Pipeline for Kubernetes

FixIQ watches your Kubernetes cluster, detects incidents the moment
they happen, investigates them automatically, and tells you exactly
what broke, why it broke, and how to fix it — in under 3 minutes.

No manual log reading. No grepping events. No Googling the same fix
you applied last month.

---

## The Problem

When production breaks, engineers waste time:
- Manually checking `kubectl get pods` to find what's broken
- Reading through hundreds of log lines
- Figuring out which of 5 simultaneous alerts to fix first
- Applying the same fix they applied last month — from memory

**Average incident investigation time: 30–90 minutes.**

## The Solution

FixIQ automates the entire investigation so engineers can focus
on applying the fix, not finding it.

**Average FixIQ investigation time: under 3 minutes.**

---

## How It Works

FixIQ runs in three modes automatically:

### Run 1 — Something Breaks
```
fixiq watch --namespace default
```
Step 1: Service Discovery
Scans your cluster, builds dependency tree,
scores criticality per service
Step 2: Incident Detection
Watches Kubernetes events in real time
Detects: OOMKilled, CrashLoop, ImagePullBackOff
Queues multiple incidents by priority
Step 3: Investigation (per incident)
Identifies failure type from real K8s data:
exit code 137        → OOMKilled
ErrImageNeverPull    → Bad image
exit code 1          → Crash / bad command
Builds evidence chain with confidence score
Maps cascade — which services are affected
Checks knowledge base — has this happened before?
Step 4: Output
Specific root cause (not "pod crashed")
Correct fix command per failure type
Log file saved to ~/.config/fixiq/reports/
Snapshot of broken state saved for recovery detection

### Run 2 — After You Fix It
fixiq watch --namespace default

FixIQ detects recovered services automatically
Diffs broken snapshot vs current state:
"image was nginx:nonexistent, now correct"
"memory was 5Mi, now 128Mi"
"revision changed 14 → 15"
Auto-records the fix to knowledge base
No manual fixiq record needed

### Run 3 — Normal Operation
fixiq watch --namespace default

All services healthy — watches silently
When something breaks, full pipeline runs again
Similar incidents shows: "100% match — known fix"

---

## Features

| Feature | What it does |
|---------|-------------|
| 🔍 Evidence Chain | Confidence-scored evidence timeline from real K8s data |
| ⚡ Cascade Analysis | Which services are affected and fix order |
| 📈 Anomaly Timeline | Which metric failed first, detection lag |
| 🔄 Similar Incidents | Past incidents matched by failure type |
| 📋 Knowledge Base | Learns from every incident automatically |
| 🔁 Recovery Detection | Auto-detects and records fixes on next run |
| 📄 Log Reports | Daily incident reports saved to disk |
| ⏰ Urgency Score | CRITICAL/HIGH/MEDIUM with fix-within time |
| 🗺️ System Map | Real dependency tree from K8s env vars |

---

## Installation

```bash
git clone https://github.com/sahil0480/FixIQ.git
cd FixIQ
pip install -e .
```

**Optional — LLM Investigation (deeper RCA):**

Ollama (free, local):
```bash
ollama pull llama3.2
export FIXIQ_LLM_PROVIDER=ollama
```

Claude API (faster, higher quality):
```bash
export FIXIQ_LLM_PROVIDER=claude
export ANTHROPIC_API_KEY=your_key_here
```

Without an LLM configured, FixIQ uses fallback RCA — which
correctly identifies OOMKilled, image pull failures, and crash
loops from real K8s data alone.

---

## Quick Start

```bash
# Watch your cluster for incidents
fixiq watch --namespace default

# Watch a specific namespace
fixiq watch --namespace production

# Record a fix after applying it manually
fixiq record -s payment-gateway -f 'Rolled back bad deployment' -m 3
```

---

## Example Output
══════════════════════════════════════════════════════════════════
FixIQ — Automated Incident Pipeline
══════════════════════════════════════════════════════════════════
✓ Kubernetes watcher ready
✓ Service discovery ready
✓ Incident queue ready
✓ FixIQ analyzer ready
🗺️  SYSTEM MAP — default
Total services: 4 | Healthy: 4 | Unhealthy: 0
Service           Status      Memory   Restarts  Criticality
kitchen-service   ✓ Healthy   128Mi    0         7/10
order-service     ✓ Healthy   128Mi    1         9/10
payment-gateway   ✓ Healthy   128Mi    0         9/10
restaurant-api    ✓ Healthy   128Mi    0         7/10
→ depends on: order-service, payment-gateway
══════════════════════════════════════════════════════════════════
🔬 INVESTIGATING: payment-gateway
Priority: 0.41 | Criticality: 9/10 | Users: ~500
══════════════════════════════════════════════════════════════════
✓ Exit code: 1  (crash — bad startup command)
✓ Restarts: 4
✓ Memory limit: 128Mi
Root Cause:
Container crash in payment-gateway — exited with code 1.
Likely bad startup command or config.
Confidence: 70%
Recommended Actions:
→ kubectl rollout history deployment/payment-gateway
→ kubectl rollout undo deployment/payment-gateway
→ Check container logs for startup error
Apply Fix:
kubectl rollout undo deployment/payment-gateway
✓ Report saved → ~/.config/fixiq/reports/2026-05-31.log

---

## Recovery Detection

On the next run after fixing a pod, FixIQ automatically detects
what changed and records it:
✅ RECOVERY DETECTED
✓ payment-gateway
Fix detected: Deployment updated (revision 15 → 16)
Auto-recorded to knowledge base
✓ restaurant-api
Fix detected: Image updated: localhost/restaurant-api:latest
Auto-recorded to knowledge base

---

## Knowledge Base

FixIQ learns from every incident:
First incident:   "Never seen this before"
Second incident:  "Similar to previous — here's what worked"
Third incident:   "100% match — apply this fix immediately"

Stored at `~/.config/fixiq/knowledge_base.json`

The similarity engine understands failure types — it won't
recommend a memory fix for an image pull failure.

---

## LLM Configuration

FixIQ works without an LLM. With one configured, investigations
are deeper and more specific.

```bash
# Ollama (free, local, requires 8GB+ RAM)
export FIXIQ_LLM_PROVIDER=ollama
export FIXIQ_OLLAMA_MODEL=llama3.2
export FIXIQ_OLLAMA_URL=http://localhost:11434

# Claude (Anthropic API, fastest, highest quality)
export FIXIQ_LLM_PROVIDER=claude
export ANTHROPIC_API_KEY=your_key_here

# Disabled (fallback RCA only)
export FIXIQ_LLM_PROVIDER=none
```

---

## Architecture
fixiq watch
↓
Service Discovery     — real K8s deployments + dependencies
↓
Recovery Detection    — diffs snapshots, auto-records fixes
↓
K8s Event Watcher     — real-time incident detection
↓
Incident Queue        — priority ordered by criticality
↓
Investigation
├── LLM Analysis    — Ollama / Claude (optional)
├── Fallback RCA    — real K8s data (always available)
└── Deep Analysis
├── Evidence Chain Analyzer
├── Cascade Failure Analyzer
├── Anomaly Timeline Analyzer
├── Similar Incidents Finder
├── Urgency Scorer
└── Blast Radius Analyzer
↓
Unified Report + Log File + Knowledge Base Snapshot

---

## Failure Types Detected

| Failure | Detection | Fix Command |
|---------|-----------|-------------|
| OOMKilled | exit code 137 | `kubectl set resources` |
| Image pull | ErrImageNeverPull | `kubectl set image` |
| Crash loop | exit code 1, BackOff | `kubectl rollout undo` |
| Config error | env var crash | `kubectl rollout undo` |

---

## Running Tests

```bash
python -m pytest tests/ -v
```

---

## Roadmap
v1.0.0 (current)
✅ Real-time incident detection
✅ Failure-type aware RCA
✅ Recovery detection + auto-record
✅ Knowledge base learning
✅ LLM support (Ollama + Claude)
✅ Daily log reports
v1.1.0 (next)
⬜ fixiq status — quick cluster health view
⬜ fixiq history — incident log browser
⬜ Config file support
v2.0.0 (planned)
⬜ Slack / Teams notifications
⬜ Multi-namespace support
⬜ Web dashboard

---

## License

Apache 2.0 — see [LICENSE](LICENSE)

---

## Author

**Sahil Shaikh**
- GitHub: [@sahil0480](https://github.com/sahil0480)
- MSc Cloud Computing
