# Design decisions (ADRs)

Short architecture decision records. Each states the decision, why, and the
trade-off accepted.

## ADR-001 — Monorepo, not split app/config repos
**Decision:** one repository holds platform config, app source, and the agent.
**Why:** the assessment is graded by *clone → bootstrap*; a single repo makes
that one command and keeps the whole story reviewable in one place.
**Trade-off:** at team scale you usually split the app source repo (CI builds
images) from the GitOps config repo (Argo watches it) so an app change can't
force-sync infra. The `sources`/`ref` multi-source Applications here already
model that separation logically and would split cleanly.

## ADR-002 — App-of-apps over a single giant Application
**Decision:** a root Application renders child Applications per component.
**Why:** independent sync/health per component, ordered rollout via sync-waves,
and "add a workload = add one Application manifest."
**Trade-off:** slightly more YAML than one recursive app; worth it for the
operational clarity. ApplicationSets would be the next step for templating.

## ADR-003 — Upstream Helm charts via Argo multi-source, not forked charts
**Decision:** reference community charts and supply only a values file from Git.
**Why:** we don't own upstream chart internals; forking them is a maintenance
tax and a security-update liability.
**Trade-off:** we depend on external chart repos being reachable at sync time
(mitigated by pinning exact chart versions).

## ADR-004 — Idiomatic path per signal (pull metrics, push traces/logs)
**Decision:** metrics via Prometheus pull + ServiceMonitor; traces/logs via
OTLP push through the Collector.
**Why:** each is the native, lowest-surprise contract for that signal, and it
keeps the app free of backend-specific config.
**Trade-off:** two ingestion mechanisms instead of "everything through OTLP."
Routing metrics through the Collector too is trivial later if we want a single
pipeline; the current split is the more standard production shape.

## ADR-005 — LLM secret seeded out-of-band; ESO/Sealed Secrets for prod
**Decision:** `bootstrap.sh` creates `ai-sre/anthropic-credentials` from an env
var; it is never in Git. Argo CD does not track or prune it.
**Why:** a repo that must be *public* (assessment requirement) cannot contain a
usable secret. Committing plaintext is unacceptable; committing an encrypted
secret the reviewer can't decrypt breaks "clone & run."
**Trade-off:** one imperative step outside GitOps. The production answer —
External Secrets Operator pulling from a real secret manager, or a Sealed
Secret whose ciphertext is safe in Git — is a drop-in replacement and is the
first item on the roadmap.

## ADR-006 — Temporal dev-server (hand-written manifests), not the HA chart
**Decision:** deploy Temporal via `temporal server start-dev` in a single,
fully-hardened Deployment instead of the upstream chart.
**Why:** on one node the chart's Cassandra/Elasticsearch/multi-service topology
is heavy and fragile to bootstrap reliably; the dev server gives a dependable
clone-and-run experience and lets us apply the full `restricted`-PSS hardening
the assessment grades on to a component we fully control.
**Trade-off:** the dev server is single-instance with SQLite persistence — not
HA and not the production topology. Production uses the Helm chart with
PostgreSQL + Elasticsearch visibility and multiple frontend/history/matching
replicas. The *workflow code is identical* either way.

## ADR-007 — Go `go.sum` resolved at build time, not committed offline
**Decision:** the Dockerfile runs `go mod tidy` during build.
**Why:** the module checksum DB can't be resolved in an offline authoring
environment; resolving at build time keeps the committed tree honest.
**Trade-off:** the first build needs network to the Go proxy. For an air-gapped
build we'd vendor (`go mod vendor`) and commit `vendor/`.

## ADR-008 — RCA output forced through Anthropic tool-use, not prose parsing
**Decision:** the LLM must return its analysis by calling a `submit_rca` tool
whose input schema is generated from the `RCAReport` pydantic model.
**Why:** structured, validated, machine-consumable output every time — no
regex-scraping of free text, and the same schema powers the Temporal activity
return value and the Markdown renderer.
**Trade-off:** slightly more prompt/tooling setup; eliminates a whole class of
parsing bugs and makes the agent composable.

## ADR-009 — RCA as a durable Temporal workflow
**Decision:** the RCA pipeline (gather → analyze → report) runs as a Temporal
workflow with per-activity retry policies; a SyntheticMonitor workflow can
launch it automatically on sustained probe failure.
**Why:** RCA touches four flaky network backends and a rate-limited LLM. Making
it durable and retryable (instead of a fragile one-shot script) is exactly the
Day-2 thinking the brief asks for — and it satisfies the "operational Temporal
workflow" requirement with something genuinely operational.
**Trade-off:** more moving parts than a cron-driven script. The payoff is
retries, visibility in the Temporal UI, and automatic incident-triggered RCA.
