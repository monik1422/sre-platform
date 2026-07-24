#!/usr/bin/env bash
# teardown.sh — completely remove the k3s cluster and all platform state.
set -euo pipefail

log() { printf '\033[1;34m[teardown]\033[0m %s\n' "$*"; }

if command -v k3s-uninstall.sh >/dev/null 2>&1; then
  log "uninstalling k3s (this removes ALL cluster state)"
  sudo /usr/local/bin/k3s-uninstall.sh
else
  log "k3s-uninstall.sh not found — is k3s installed?"
fi

rm -f "${KUBECONFIG:-$HOME/.kube/config-sre-platform}"
log "done"
