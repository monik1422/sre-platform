#!/usr/bin/env bash
# inject-latency.sh {on|off} — toggle deterministic fault injection on sample-api.
#
# "on"  : +800ms latency and 30% 5xx errors on /api/work
# "off" : clears all injected faults
#
# Uses a short-lived port-forward so it works against the default-deny
# NetworkPolicies without needing a throwaway in-cluster pod.
set -euo pipefail

NS="sample-api"
SVC="sample-api"
LOCAL_PORT="18080"
MODE="${1:-on}"

if [[ "$MODE" == "on" ]]; then
  PAYLOAD='{"latency_ms":800,"error_pct":30}'
  echo "[chaos] injecting latency=800ms error_pct=30 into ${SVC}"
elif [[ "$MODE" == "off" ]]; then
  PAYLOAD='{"latency_ms":0,"error_pct":0}'
  echo "[chaos] clearing injected faults on ${SVC}"
else
  echo "usage: $0 {on|off}" >&2
  exit 1
fi

kubectl port-forward -n "$NS" "svc/${SVC}" "${LOCAL_PORT}:80" >/dev/null 2>&1 &
PF_PID=$!
trap 'kill "$PF_PID" 2>/dev/null || true' EXIT
sleep 2

curl -fsS -X POST "http://localhost:${LOCAL_PORT}/fault" -d "$PAYLOAD" && echo
echo "[chaos] done"
