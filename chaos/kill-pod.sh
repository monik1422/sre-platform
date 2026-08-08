#!/usr/bin/env bash
# kill-pod.sh — delete a random sample-api pod to exercise self-healing and
# generate a Kube "PodRestart"/scheduling signal for the AI SRE agent.
set -euo pipefail

NS="sample-api"
SELECTOR="app.kubernetes.io/name=sample-api"

POD="$(kubectl get pods -n "$NS" -l "$SELECTOR" \
  -o jsonpath='{.items[0].metadata.name}')"

if [[ -z "$POD" ]]; then
  echo "[chaos] no sample-api pods found" >&2
  exit 1
fi

echo "[chaos] deleting pod ${POD} (Deployment will reschedule it)"
kubectl delete pod -n "$NS" "$POD"
echo "[chaos] current pods:"
kubectl get pods -n "$NS" -l "$SELECTOR"
