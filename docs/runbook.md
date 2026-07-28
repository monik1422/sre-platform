# Runbook — sample-api

Every alert's `runbook_url` points here. Keep steps copy-pasteable.

## Quick reference
```bash
make grafana        # RED + SLO dashboard
make argocd-ui      # sync/health of every component
kubectl get pods -A | grep -Ev 'Running|Completed'
make rca            # ask the AI SRE agent for a structured RCA
```

## SampleApiErrorBudgetFastBurn
**Meaning:** 5xx error ratio > 14.4× the 0.5% budget on both 5m and 1h windows —
the 30-day budget is being consumed in ~2 days. This pages.

1. Confirm on the RED dashboard (`make grafana`) — is `error_ratio_5m` spiking?
2. Is fault injection active from a demo? Clear it: `make chaos-clear`.
3. Otherwise check the most recent `sample-api` rollout:
   `kubectl -n sample-api rollout history deploy/sample-api`.
   Roll back if a bad deploy correlates with onset:
   `kubectl -n sample-api rollout undo deploy/sample-api`.
4. Pull correlated evidence fast: `make rca` (agent) or open a spiking log line
   in Grafana → click the `trace_id` derived field to jump to the failing trace.

## SampleApiErrorBudgetSlowBurn
Chronic, low-grade errors. Not a page — investigate within the day.
1. Run `make rca` for a correlation summary.
2. Look for a partially-failing dependency or a specific route/status in
   `sum by (route,code) (rate(http_requests_total{service="sample-api"}[10m]))`.

## SampleApiLatencyHigh
p95 > 300ms for 5m with normal error rate — usually a slow dependency.
1. In Tempo, sort `sample-api` traces by duration; inspect the slow span
   (`downstream.db-query` in this demo).
2. Check `fault.injected_latency_ms` span attribute — is this an injected fault?

## SampleApiTargetDown
Prometheus can't scrape any replica.
1. `kubectl -n sample-api get pods -l app.kubernetes.io/name=sample-api`
2. `kubectl -n sample-api describe pod <pod>` — image pull? OOMKill? probe fail?
3. If pods are healthy but unscraped, check the ServiceMonitor and that the
   `http` port is exposed.
