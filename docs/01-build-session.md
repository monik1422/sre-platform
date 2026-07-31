# Transcript 01 — Build Session (Design + Implementation)

> Curated log of the design and implementation phase. The raw chat export is the
> primary evidence; this narrative captures the decisions, prompts, and
> corrections in the order they happened. Tool used: Anthropic Claude.

## Scope of this session

Take the assessment brief (a production-grade, GitOps-managed platform on
Kubernetes with an LGTM observability stack, Temporal, a sample instrumented
service, and an AI SRE agent that does RCA against a simulated failure) from a
blank repo to a complete, buildable source tree with meaningful git history.

## Framing & architecture decisions

**Prompt (paraphrased):** "First Staff SRE at a B2B SaaS + AI startup — prove the
full stack locally on k3s, production-grade, with an AI SRE agent doing RCA
against a simulated failure. Design it and build the repo."

Key decisions reached, each captured as an ADR in `docs/design-decisions.md`:

- **Monorepo** for clone-and-bootstrap simplicity (ADR-001); noted the team-scale
  split of app-source vs. config repos as the trade-off.
- **App-of-apps + two AppProjects** (`platform`, `apps`) for per-component health,
  ordered rollout, and blast-radius isolation (ADR-002).
- **Upstream Helm charts via Argo multi-source** (chart + `$values` from Git)
  rather than forking charts (ADR-003).
- **Idiomatic path per signal** (ADR-004): metrics *pulled* via ServiceMonitor;
  traces and logs *pushed* via OTLP through a single OTel Collector. Decided
  against "everything through OTLP" and documented why.
- **SLO + multi-window multi-burn-rate alerting** from the Google SRE Workbook:
  99.5% availability, 0.5% error budget, fast-burn page vs. slow-burn ticket.
- **RCA as a durable Temporal workflow** (ADR-009) — this satisfies both the
  "operational Temporal workflow" and "AI SRE agent" requirements with one
  coherent design, and is the day-2 differentiator.
- **LLM output forced through a tool schema** (ADR-008) so the agent returns
  validated, structured RCA every time instead of scraped prose.
- **Secrets seeded out-of-band** by the bootstrap, never committed; production
  pattern is External Secrets Operator / Sealed Secrets (ADR-005).
- **Temporal as a hardened dev-server** for reliable single-node bootstrap, with
  the HA-chart trade-off documented (ADR-006).

## What got built

- **GitOps:** `argocd/projects.yaml` (two AppProjects), `argocd/root-app.yaml`
  (app-of-apps, recursive), and child Applications per component with
  `sync-wave` ordering (namespaces → backends → collector/temporal → config →
  apps).
- **Observability:** Helm values for kube-prometheus-stack, Loki, Tempo, and the
  OTel Collector; a `PrometheusRule` with recording rules + the four alerts; a
  Grafana datasources ConfigMap wiring trace↔log↔metric correlation; and a RED
  dashboard as code.
- **sample-api (Go):** RED metrics with SLO-locked names, OTLP traces with a
  `downstream.db-query` child span, `slog` JSON logs carrying `trace_id`, and a
  `/fault` endpoint for deterministic failure injection. Hardened deploy
  (distroless nonroot, restricted PSS, probes, PDB, NetworkPolicy).
- **AI SRE agent (Python):** read-only clients for Prometheus/Loki/Tempo/
  Alertmanager/Kube API; a pydantic `RCAReport` schema; a forced-tool-use LLM
  call; a Markdown report renderer; and an offline dry-run heuristic path.
- **Temporal layer:** `RCAWorkflow` (gather → analyze → report, each with retry
  policies) and `SyntheticMonitorWorkflow` (probe → auto-trigger RCA on sustained
  failure), plus the worker and hardened deploy.
- **Chaos + docs:** fault-injection and guided-demo scripts; architecture,
  ADRs, runbook, and this AI log.

## Corrections made during review (AI as accelerator, not autopilot)

- Fixed OTel Go imports to use `go.opentelemetry.io/otel/codes` and
  `attribute.String` for the environment resource attribute.
- Locked the Prometheus metric names (`http_requests_total{...}`,
  `http_request_duration_seconds{...}`) to exactly match the SLO recording rules
  — a mismatch would silently read the SLI as zero.
- Chose Loki's OTLP resource label `service_name` for the agent's log queries.
- Reasoned through and rejected the Temporal Helm chart for single-node use in
  favour of a hardened dev-server (later revisited during deployment — see
  transcript 02).
- Handled `go.sum` at Docker build time (`go mod tidy`) since the module proxy
  isn't reachable in the authoring environment (ADR-007).

## Validation performed in the authoring environment

- `python -m pytest` on the agent: passing.
- `ruff` on the agent source: clean.
- `yamllint` across all manifests: clean.
- Every YAML document parses; the embedded Grafana dashboard JSON is valid.
- Go compilation and a live cluster were **not** possible in the authoring
  sandbox — flagged honestly, and deferred to the deployment session (transcript
  02), which is where the real integration bugs surfaced and were fixed.

## Git history

Built as incremental, scoped commits (scaffolding → bootstrap → GitOps →
namespaces → observability → SLO/config → temporal → sample-api → agent core →
agent workflows → chaos → docs), not a single final commit — per the
deliverable requirement.
