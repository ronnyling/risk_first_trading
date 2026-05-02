# External Research Infrastructure

## hermes-agentic/

Git submodule: `https://github.com/NousResearch/hermes-agent.git`

### Model Selection

- **hermes-agent (standard)** — USE
- **hermes-agent-self-evolution** — FORBIDDEN (self-evolving system)

### Operating Constraints

This agent is configured as a STATELESS, EPISODIC BATCH RESEARCH RUNNER.

| Capability | Allowed |
|------------|---------|
| 24/7 persistent assistant | NO |
| Memory-retaining agent | NO |
| Self-evolving system | NO |
| Stateless batch runner | YES |
| Episodic execution | YES |

No run may depend on prior runs except via human-approved policy artifacts.

**Clarification A — How Hermes Is Invoked:**
Hermes Agentic is invoked manually or via a scheduler (cron/CI), never by the trading system itself.

**Clarification B — Stateless Means "No Memory Beside Artifacts":**
Hermes Agentic is stateless; the only allowed persistence across runs is through human-approved policy artifacts. This blocks subtle memory accumulation (vector DBs, cached reasoning, etc.).

### Integration Contract (Non-Negotiable)

**Allowed interaction paths:**
- Hermes writes artifacts to: `data/hermes_runs/`, `data/hermes_proposals/`, `data/hermes_alerts/`, `docs/hermes_actions/*.md`
- Streamlit dashboard reads these artifacts for human review
- Human approves/declines via Streamlit
- Copilot implements code changes from MD handoff specs

**Forbidden interaction paths:**
- Direct Python imports from `external/hermes-agentic/`
- Runtime execution of Hermes code
- API calls to Hermes from the trading engine
- Any mock or simulation of Hermes behavior

### Hermes Contract Version (Optional — Recommended)

In Hermes-produced artifacts (JSON + MD), include:
```json
"hermes_contract_version": "v1"
```

Benefits:
- Future Hermes upgrades remain compatible
- Streamlit can validate contracts explicitly
- Unknown Hermes outputs can be rejected safely

### Code Tuning Responsibility

Hermes produces MD specs describing what should change.
Human approves or rejects intent.
AI plan agent / copilot implements Python code changes.
Copilot marks completion explicitly in .kilo / policy ledger.

**Hermes must never tune Python directly.**

### Architectural Invariant

```
Hermes proposes → Human approves → Copilot edits code → Policy updates → Orchestrator executes
```

No exceptions.

### One-Sentence Rule

If an AI can change how it behaves without producing an artifact
that a human approves, it does not belong in this system.