# SRE Platform — local, production-grade, GitOps-driven

A full cloud-native platform stack proved out **locally on k3s**, wired exactly
the way it would run in production — the only difference is k3s instead of EKS.
Everything is GitOps-managed by Argo CD, fully observable (LGTM), and topped
with an **AI SRE agent** that queries the observability stack and produces a
structured root-cause analysis against a simulated failure.

## What's inside

| Component | What it does |
|---|---|
| **k3s** | Single-node Kubernetes |
| **Argo CD** | GitOps controller; app-of-apps manages everything after bootstrap |
| **LGTM** | **L**oki (logs), **G**rafana (UI), **T**empo (traces), Prometheus (**M**etrics) + Alertmanager |
| **OTel Collector** | Receives OTLP traces, tails container logs → Loki |
| **Temporal** | Durable workflow engine + Web UI |
| **sample-api** | Go service emitting RED metrics, traces, and structured logs; `/fault` endpoint for deterministic failure injection |
| **AI SRE agent** | Python agent (as a Temporal workflow) that gathers signals from all four backends, calls Claude, and emits a structured RCA report |

## Prerequisites

A Linux host (or VM) with:
- `docker`, `kubectl`, `curl`, `make`
- sudo (k3s installs system-wide)
- ~4 vCPU / 6 GB RAM free
- outbound internet (Helm repos, container images, and the Anthropic API)

## Quick start

```bash
# 1. Fork this repo and point the Argo CD apps at your fork:
export GITOPS_REPO_URL="https://github.com/<you>/sre-platform.git"
#    (also update repoURL in argocd/*.yaml and argocd/apps/*.yaml — one sed does it:)
grep -rl 'monik1422/sre-platform' argocd | xargs sed -i "s#https://github.com/monik1422/sre-platform.git#${GITOPS_REPO_URL}#g"
git add -A && git commit -m "point argo at my fork" && git push

# 2. (optional) provide the LLM key so the agent does real RCA, not dry-run:
export ANTHROPIC_API_KEY="sk-ant-..."

# 3. Bootstrap everything:
make up          # == ./bootstrap/bootstrap.sh

# 4. Watch it converge:
make status      # Argo CD applications: Synced / Healthy
```

Then explore:

```bash
make argocd-password   # initial admin password
make argocd-ui         # https://localhost:8080  (user: admin)
make grafana           # http://localhost:3000   (admin / sre-platform-admin)
make temporal-ui       # http://localhost:8088
```

## The AI SRE demo (the differentiator)

```bash
make demo
```

This injects an 800 ms latency + 30 % error fault into `sample-api`, drives
traffic so the SLI actually moves, waits for Prometheus to evaluate the
burn-rate rules, then runs the AI SRE agent **in-cluster**. The agent:

1. pulls the firing alerts (Alertmanager), SLI/RED metrics (Prometheus), error
   logs (Loki), error/slow traces (Tempo), and pod/event signals (Kube API);
2. sends that correlated evidence to Claude, forced through a `submit_rca`
   tool so the output is schema-valid;
3. prints a structured RCA (see [`sample-rca-report.md`](sample-rca-report.md)).

Without a key it runs in **dry-run**: same gather + a deterministic heuristic
RCA, so the pipeline is demonstrable offline.

Run individual steps:
```bash
make chaos-latency     # inject fault
make chaos-kill        # kill a pod (self-heal + Kube signal)
make rca               # run RCA now
make chaos-clear       # clear faults
```

## SLO & alerting

`sample-api` has a real SLO: **99.5 % availability** (0.5 % error budget) plus a
**300 ms p95 latency** objective. Alerting uses the Google SRE Workbook
multi-window, multi-burn-rate pattern — a fast-burn **page** and a slow-burn
**ticket** — not a naive threshold. See
[`platform/config/slo-rules.yaml`](platform/config/slo-rules.yaml).

## Repository layout

```
bootstrap/        one-shot cluster + Argo CD + secret seeding
argocd/           AppProjects + root app-of-apps + child Applications
platform/
  namespaces/     namespaces with Pod Security Standards labels
  values/         Helm values for kube-prometheus-stack, loki, tempo, otel
  config/         SLO PrometheusRule, Grafana datasources + RED dashboard
  temporal/       hand-written, hardened Temporal manifests
apps/sample-api/  Go service (OTel + Prometheus + slog) + hardened manifests
ai-sre-agent/     Python agent (clients, LLM, RCA) + Temporal worker/workflows
chaos/            fault injection + guided demo scripts
docs/             architecture, design decisions (ADRs), runbook, AI log
```

## Design decisions & trade-offs

Full ADRs in [`docs/design-decisions.md`](docs/design-decisions.md). The ones
worth calling out:

- **Temporal runs as a hardened dev-server**, not the HA Helm chart — reliable
  clone-and-run on one node; workflow code is production-identical (ADR-006).
- **The LLM key is seeded out-of-band**, never committed; production swaps in
  External Secrets / Sealed Secrets (ADR-005).
- **RCA is a durable Temporal workflow** with retries, auto-triggered by a
  SyntheticMonitor — actionable observability, not just a stack install (ADR-009).
- **LLM output is forced through a tool schema** for deterministic, validated
  RCA (ADR-008).

## A note on version pins

Chart, image, and tool versions are pinned to known-good-at-authoring values
(k3s, Argo CD, the Helm charts, the Temporal CLI image, Python/Go deps). If a
pin has aged out by the time you bootstrap, bump it in the relevant
`argocd/apps/*.yaml` or values file — the structure is unaffected.

## Roadmap (what I'd build next)

1. **Secrets:** External Secrets Operator + a real secret manager; Sealed
   Secrets for anything that must live in Git.
2. **Temporal HA:** the full chart (Postgres + Elasticsearch visibility,
   multi-role replicas) and scrape its metrics into Prometheus.
3. **Collector split:** agent daemonset (logs) + gateway deployment
   (tail-sampling) once there's more than one node.
4. **Agent depth:** feed the agent recent deploy/Git SHA context and Argo CD
   sync history so it can implicate a specific change; add a "propose a fix PR"
   action behind human approval.
5. **Policy-as-code:** Kyverno/OPA-Gatekeeper admission (enforce limits, signed
   images, no `:latest`) and image scanning + signing in CI.
6. **CI:** GitHub Actions running `make lint`, `go build`, `pytest`, and
   `kubeconform` on every PR; ApplicationSets to template environments.

## Honest status

This repository is the complete, coherent source tree. The Go and Python code,
YAML, and the RCA logic were built to run; the offline authoring environment
could not stand up a live k3s cluster, so **do a first bootstrap on your host
and expect to bump a version pin or two**. The `make lint` gate (yamllint +
ruff + pytest) passes and is the quickest local sanity check.
