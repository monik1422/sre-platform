# Architecture

## 10,000-ft view

```
                         ┌──────────────────────────────────────────────┐
                         │                  k3s (1 node)                 │
                         │                                                │
   git push ──▶ GitHub ──┼─▶ Argo CD ──(app-of-apps)──▶ everything below │
                         │      │                                         │
                         │      ▼                                         │
   ┌─────────────────────┼──────────────────────────────────────────┐   │
   │ observability ns     │                                          │   │
   │   Prometheus  ◀── scrape ── sample-api /metrics                 │   │
   │   Alertmanager ◀── SLO burn-rate rules                          │   │
   │   Loki        ◀── OTLP logs ── OTel Collector ◀── stdout tail   │   │
   │   Tempo       ◀── OTLP traces ── OTel Collector ◀── sample-api  │   │
   │   Grafana     ── datasources + RED/SLO dashboard                │   │
   └─────────────────────┼──────────────────────────────────────────┘   │
   ┌─────────────────────┼──────────────┐  ┌───────────────────────────┐ │
   │ sample-api ns       │              │  │ temporal ns               │ │
   │   sample-api (x2)    │              │  │   Temporal (dev server)   │ │
   │   RED metrics/traces/logs + /fault  │  │   + Web UI                │ │
   └──────────────────────────────────────┘  └────────────▲────────────┘ │
   ┌────────────────────────────────────────────┐         │              │
   │ ai-sre ns                                    │         │ workflows    │
   │   Temporal worker ── RCAWorkflow ────────────┼─────────┘              │
   │                  └── SyntheticMonitor         │                        │
   │   queries Prometheus/Loki/Tempo/Alertmanager  │                        │
   │   + read-only Kube API ── calls Claude ── RCA │                        │
   └───────────────────────────────────────────────┘                        │
                         └──────────────────────────────────────────────────┘
```

## Signal paths (deliberately idiomatic per signal)

| Signal  | Path                                                            | Why |
|---------|-----------------------------------------------------------------|-----|
| Metrics | app `/metrics` → **ServiceMonitor** → Prometheus (pull)         | Pull model is the Prometheus-native contract; ServiceMonitor keeps discovery in Git. |
| Traces  | app → OTLP → **OTel Collector** → Tempo (push)                  | OTLP is vendor-neutral; the Collector decouples the app from the backend. |
| Logs    | app stdout JSON → **Collector filelog** → Loki (OTLP)           | App stays dumb (writes stdout); the platform owns shipping. |

The single OTel Collector runs as a **daemonset** because on one node that is
both the per-node log agent and the OTLP gateway. At multi-node scale this
splits into an agent daemonset (logs + forward) and a gateway deployment
(tail-sampling, aggregation) — noted in the roadmap.

## Cross-signal correlation (what makes it *actionable*)

- Every `sample-api` log line carries `trace_id` / `span_id` from the active
  span. Grafana's Loki datasource has a **derived field** turning `trace_id`
  into a one-click jump to the Tempo trace.
- Tempo is configured with **traces→logs** and **traces→metrics**, and its
  metrics-generator emits **RED span metrics + a service graph** into Prometheus.
- The AI SRE agent consumes all four backends, so its RCA reasons across the
  same correlated signals a human would.

## GitOps model

`bootstrap.sh` is the only imperative step. It installs k3s + Argo CD, seeds
the one un-committable secret, and applies a single **root Application**. That
root renders every child Application in `argocd/apps/` (the *app-of-apps*
pattern). Sync order is controlled with `argocd.argoproj.io/sync-wave`:

```
wave -1  namespaces
wave  0  kube-prometheus-stack, loki, tempo
wave  1  otel-collector, temporal
wave  2  platform-config (PrometheusRule, dashboards, datasources)
wave  3  sample-api, ai-sre-agent
```

Two **AppProjects** (`platform`, `apps`) bound which repos, namespaces, and
cluster-scoped resources each set of workloads may touch — a blast-radius
boundary for the GitOps controller itself.

## Security posture

- **Namespace isolation** with Pod Security Standards labels (`restricted`
  enforced on our own workloads).
- **NetworkPolicies**: default-deny ingress+egress in every namespace we own,
  then explicit least-privilege allows (see each `*/deploy/30-networkpolicy.yaml`).
- **Workload hardening**: non-root, `readOnlyRootFilesystem`, all capabilities
  dropped, seccomp `RuntimeDefault`, resource requests+limits, liveness/
  readiness/startup probes, PodDisruptionBudget, `automountServiceAccountToken`
  off unless required.
- **RBAC**: the agent's ServiceAccount has read-only `pods`/`events` in exactly
  two namespaces — nothing else.
- **Secrets**: the LLM key is seeded out-of-band and never committed; the
  production pattern (External Secrets / Sealed Secrets) is documented in ADR-005.
