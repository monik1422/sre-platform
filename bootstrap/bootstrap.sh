#!/usr/bin/env bash
#
# bootstrap.sh — one-shot, idempotent bootstrap of the entire SRE platform.
#
# Flow:
#   1. Install k3s (single node, traefik disabled — we bring our own ingress path)
#   2. Wait for the node to be Ready
#   3. Install Argo CD via its stable manifest
#   4. Seed the ONE secret that cannot live in Git: the Anthropic API key for
#      the AI SRE agent. In production this is delivered by External Secrets
#      Operator / Sealed Secrets (see docs/design-decisions.md, ADR-005).
#   5. Build & import local images (sample-api, ai-sre-agent) into k3s containerd
#   6. Apply the Argo CD AppProjects + the app-of-apps root Application.
#
# After this runs, Argo CD owns everything. Nothing else is ever kubectl-applied.
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KUBECONFIG_PATH="${KUBECONFIG:-$HOME/.kube/config-sre-platform}"
K3S_VERSION="${K3S_VERSION:-v1.30.2+k3s2}"
ARGOCD_VERSION="${ARGOCD_VERSION:-v2.11.3}"
GITOPS_REPO_URL="${GITOPS_REPO_URL:-}"   # set to your fork; defaults to local path note below

log()  { printf '\033[1;34m[bootstrap]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[bootstrap]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[bootstrap] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

require() { command -v "$1" >/dev/null 2>&1 || die "missing required tool: $1"; }

# --- pre-flight ------------------------------------------------------------
require curl
require kubectl
require docker
[[ -n "$GITOPS_REPO_URL" ]] || warn "GITOPS_REPO_URL not set — Argo CD apps point at the placeholder in argocd/*.yaml. Fork this repo, push, and export GITOPS_REPO_URL=https://github.com/<you>/sre-platform.git before running, OR edit argocd/root-app.yaml."

# --- 1. k3s ----------------------------------------------------------------
if ! sudo k3s kubectl get nodes >/dev/null 2>&1; then
  log "installing k3s ${K3S_VERSION}"
  curl -sfL https://get.k3s.io | \
    INSTALL_K3S_VERSION="${K3S_VERSION}" \
    INSTALL_K3S_EXEC="--disable=traefik --write-kubeconfig-mode=0644" sh -
else
  log "k3s already installed — skipping"
fi

mkdir -p "$(dirname "$KUBECONFIG_PATH")"
sudo cat /etc/rancher/k3s/k3s.yaml > "$KUBECONFIG_PATH"
chmod 600 "$KUBECONFIG_PATH"
export KUBECONFIG="$KUBECONFIG_PATH"

# --- 2. wait for node ------------------------------------------------------
log "waiting for node to become Ready"
kubectl wait --for=condition=Ready node --all --timeout=180s

# --- 3. Argo CD ------------------------------------------------------------
log "installing Argo CD ${ARGOCD_VERSION}"
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n argocd \
  -f "https://raw.githubusercontent.com/argoproj/argo-cd/${ARGOCD_VERSION}/manifests/install.yaml"
log "waiting for Argo CD to be available"
kubectl -n argocd rollout status deploy/argocd-server --timeout=300s
kubectl -n argocd rollout status deploy/argocd-repo-server --timeout=300s

# --- 4. seed the AI SRE agent secret --------------------------------------
kubectl create namespace ai-sre --dry-run=client -o yaml | kubectl apply -f -
if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  log "seeding ai-sre/anthropic-credentials from ANTHROPIC_API_KEY env var"
  kubectl -n ai-sre create secret generic anthropic-credentials \
    --from-literal=api-key="${ANTHROPIC_API_KEY}" \
    --dry-run=client -o yaml | kubectl apply -f -
else
  warn "ANTHROPIC_API_KEY not set. The AI SRE agent will start but stay in DRY_RUN mode"
  warn "(it will gather signals and emit a report skeleton without the LLM call)."
  kubectl -n ai-sre create secret generic anthropic-credentials \
    --from-literal=api-key="" \
    --dry-run=client -o yaml | kubectl apply -f -
fi

# --- 5. build & import local images ---------------------------------------
log "building sample-api image"
docker build -q -t sample-api:local "${REPO_ROOT}/apps/sample-api" >/dev/null
log "building ai-sre-agent image"
docker build -q -t ai-sre-agent:local "${REPO_ROOT}/ai-sre-agent" >/dev/null
log "importing images into k3s containerd"
docker save sample-api:local  | sudo k3s ctr images import -
docker save ai-sre-agent:local | sudo k3s ctr images import -

# --- 6. hand control to Argo CD (app-of-apps) ------------------------------
log "applying Argo CD projects + root application (GitOps takes over from here)"
kubectl apply -f "${REPO_ROOT}/argocd/projects.yaml"
kubectl apply -f "${REPO_ROOT}/argocd/root-app.yaml"

cat <<EOF

$(log 'bootstrap complete ✅')

Next:
  export KUBECONFIG=${KUBECONFIG_PATH}
  make status              # watch the app-of-apps converge
  make argocd-password     # initial admin password
  make argocd-ui           # https://localhost:8080  (user: admin)
  make grafana             # http://localhost:3000
  make demo                # inject a fault and run the AI SRE agent

Argo CD is now the single source of truth. Do not 'kubectl apply' workloads
by hand — commit to Git and let it sync.
EOF
