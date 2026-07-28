# AI interaction log

This platform was built AI-first. This document is the **curated** log: the
decisions and prompts that shaped the design, plus where the raw transcripts
live. Keep it honest — reviewers can tell curated summaries from real sessions,
so the full unedited chats are attached rather than paraphrased away.

## Tools used
- **Claude (Anthropic)** — primary design & implementation partner: architecture,
  all manifests, the Go service, and the AI SRE agent + Temporal workflows.
- *(attach any others you used, e.g. Claude Code / Cursor / editor Copilot,
  with their raw logs under `docs/transcripts/`.)*

## How AI was leveraged (as an accelerator, not autopilot)
1. **Architecture framing.** Asked the model to lay out signal paths and argue
   the trade-off between "everything through OTLP" vs. idiomatic per-signal
   paths. Chose pull-metrics / push-traces-logs (ADR-004) from that discussion.
2. **GitOps skeleton.** Generated the app-of-apps + AppProject structure, then
   hardened sync-waves so CRDs land before the resources that need them.
3. **Code generation with review.** The Go service and Python agent were
   generated, then I reviewed and corrected: OTel `codes.Error` import, semconv
   version drift, and the structured-metadata trace-id extraction in Loki.
4. **De-risking.** The model initially reached for the Temporal Helm chart; we
   reasoned through its single-node fragility and switched to a hardened
   dev-server deployment (ADR-006). Same for secrets (ADR-005).
5. **Guardrails.** Forced the LLM's RCA output through Anthropic tool-use with a
   pydantic-generated schema (ADR-008) so the agent is deterministic-shaped.

## Distilled decision log
> The full turn-by-turn transcript is in `docs/transcripts/`. Highlights:

- **Prompt:** "First Staff SRE at a B2B SaaS+AI startup — prove the full stack
  locally on k3s, production-grade, with an AI SRE agent doing RCA against a
  simulated failure." → produced the component list and the repo layout.
- **Decision:** app-of-apps + two AppProjects for blast-radius isolation.
- **Decision:** one OTel Collector daemonset (agent+gateway) on a single node;
  documented the multi-node split.
- **Decision:** SLO = 99.5% availability; multi-window multi-burn-rate alerts
  (Google SRE workbook) rather than a naive threshold.
- **Decision:** RCA as a durable Temporal workflow with per-activity retries;
  SyntheticMonitor auto-triggers it — kills two requirements with one coherent
  design (ADR-009).
- **Fixes caught in review:** `go.sum` offline handling (ADR-007), Loki OTLP
  label names (`service_name`), NetworkPolicy egress for the Anthropic call,
  PSS-`restricted` compliance on every pod.

## Attaching raw transcripts
Export each full session (Claude share link export, or copy the chat) into
`docs/transcripts/NN-topic.md`. Do not trim them — the point is to show how AI
was actually used, including the dead ends and corrections. Suggested files:

```
docs/transcripts/
  01-architecture-and-scope.md
  02-gitops-and-observability.md
  03-sample-api-and-instrumentation.md
  04-ai-sre-agent-and-temporal.md
  05-review-and-fixes.md
```

> Note for this submission: replace the bullet summaries above with, or
> supplement them by, your verbatim exported chats. This file is the index;
> the transcripts are the evidence.
