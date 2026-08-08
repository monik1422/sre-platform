#!/usr/bin/env bash
# run-scenario.sh — end-to-end AI SRE demo:
#   1. inject a fault into sample-api
#   2. drive some traffic so the SLI actually moves
#   3. wait for metrics/alerts to reflect the degradation
#   4. run the AI SRE agent RCA in-cluster and print the structured report
#   5. clear the fault
set -euo pipefail

SVC_NS="sample-api"
AGENT_NS="ai-sre"
LOCAL_PORT="18080"
DRIVE_SECONDS="${DRIVE_SECONDS:-120}"

section() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

section "1/5  Injecting fault (latency 800ms, 30%% errors)"
./chaos/inject-latency.sh on

section "2/5  Driving traffic for ${DRIVE_SECONDS}s so the SLI moves"
kubectl port-forward -n "$SVC_NS" svc/sample-api "${LOCAL_PORT}:80" >/dev/null 2>&1 &
PF_PID=$!
trap 'kill "$PF_PID" 2>/dev/null || true' EXIT
sleep 2
END=$(( $(date +%s) + DRIVE_SECONDS ))
while [[ $(date +%s) -lt $END ]]; do
  curl -s -o /dev/null "http://localhost:${LOCAL_PORT}/api/work" || true
  sleep 0.2
done
kill "$PF_PID" 2>/dev/null || true
trap - EXIT

section "3/5  Letting Prometheus evaluate rules (60s)"
sleep 60

section "4/5  Running AI SRE agent RCA in-cluster"
JOB="rca-demo-$(date +%s)"
kubectl create job -n "$AGENT_NS" "$JOB" --from=cronjob/ai-sre-agent-rca
kubectl wait -n "$AGENT_NS" --for=condition=complete "job/${JOB}" --timeout=200s || \
  echo "(job still running or failed — showing logs anyway)"
echo "----------------------------- RCA REPORT -----------------------------"
kubectl logs -n "$AGENT_NS" "job/${JOB}" || true
echo "----------------------------------------------------------------------"

section "5/5  Clearing fault"
./chaos/inject-latency.sh off
echo "Demo complete. Open Grafana (make grafana) to see the RED dashboard recover."
