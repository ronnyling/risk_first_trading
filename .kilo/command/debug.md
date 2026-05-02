---
description: "Strict persistent-bug debugging protocol — trace state ownership, lifecycle, and divergence point only. No fixes, no summaries, no speculation."
---

# Persistent Bug Debugging

You are executing the **Persistent Bug Protocol**. This bug has survived multiple fix attempts. Treat it with maximum rigor.

## Rules

- Follow the Workspace Debugging Protocol strictly.
- Focus **only** on identifying state ownership, lifecycle, and the exact divergence point.
- Do **not** provide summaries, conceptual explanations, or speculative fixes.
- Be precise and explicit.
- Do **not** propose solutions until explicitly asked.

## Required Analysis Structure

### Step 1: Confirmed Facts

State only what is definitively known, backed by code or observed behavior:
- Exact state(s) involved (variable values, store contents, DOM state, cache entries)
- Where each state is owned (which component, service, store, cache, or module holds the source of truth)
- How the state is read by the system or UI
- Concrete evidence (file paths, line numbers, output, stack traces)

### Step 2: Assumptions

List beliefs that are plausible but not yet verified:
- What is believed to be true about the state or flow
- What evidence would confirm or disprove each assumption

### Step 3: Unknowns / Needs Verification

List what must be checked before proceeding:
- Specific files, functions, or data flows that need inspection
- Runtime behaviors that need observation
- State transitions that need tracing

### Step 4: Divergence Point

Identify the **exact step** where expected behavior diverges from actual behavior:
- Before this step: state is correct
- After this step: state is incorrect or behavior is wrong
- What changed at this point (input, timing, side effect, mutation)

## Forbidden

- Do NOT propose fixes
- Do NOT summarize the codebase
- Do NOT explain what things are conceptually
- Do NOT speculate about causes without evidence
- Do NOT suggest "try X" without completing the full analysis first
