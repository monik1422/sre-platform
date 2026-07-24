# SRE Platform — developer & operator entrypoints.
# Every target is idempotent and safe to re-run.

SHELL      := /usr/bin/env bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := help

KUBECONFIG ?= $(HOME)/.kube/config-sre-platform
export KUBECONFIG

ARGOCD_NS  := argocd
AGENT_NS   := ai-sre

.PHONY: help
help: ## Show this help
	@awk 'BEGIN{FS":.*##"}/^[a-zA-Z0-9_.-]+:.*##/{printf "  \033[36m%-22s\033[0m %s\n",$$1,$$2}' $(MAKEFILE_LIST)

## ---------------------------------------------------------------------------
## Cluster lifecycle
## ---------------------------------------------------------------------------
.PHONY: up
up: ## Bootstrap everything: k3s + Argo CD + GitOps root app
	./bootstrap/bootstrap.sh

.PHONY: down
down: ## Tear down the k3s cluster and all state
	./bootstrap/teardown.sh

.PHONY: status
status: ## Show Argo CD application sync/health status
	kubectl get applications -n $(ARGOCD_NS)

.PHONY: argocd-password
argocd-password: ## Print the initial Argo CD admin password
	@kubectl -n $(ARGOCD_NS) get secret argocd-initial-admin-secret \
		-o jsonpath='{.data.password}' | base64 -d; echo

.PHONY: argocd-ui
argocd-ui: ## Port-forward the Argo CD UI to https://localhost:8080
	kubectl port-forward -n $(ARGOCD_NS) svc/argocd-server 8080:443

.PHONY: grafana
grafana: ## Port-forward Grafana to http://localhost:3000 (admin / see secret)
	kubectl port-forward -n observability svc/kube-prometheus-stack-grafana 3000:80

.PHONY: temporal-ui
temporal-ui: ## Port-forward the Temporal Web UI to http://localhost:8088
	kubectl port-forward -n temporal svc/temporal-web 8088:8080

## ---------------------------------------------------------------------------
## Quality gates (run in CI and locally before commit)
## ---------------------------------------------------------------------------
.PHONY: lint
lint: lint-yaml lint-py ## Run all linters

.PHONY: lint-yaml
lint-yaml: ## Lint all Kubernetes/Argo manifests
	yamllint -c .yamllint.yaml argocd platform apps ai-sre-agent

.PHONY: lint-py
lint-py: ## Lint & type-check the AI SRE agent
	cd ai-sre-agent && ruff check src temporal && python -m pytest -q

.PHONY: build-app
build-app: ## Build the sample-api container image into the k3s image store
	cd apps/sample-api && docker build -t sample-api:local . \
		&& docker save sample-api:local | sudo k3s ctr images import -

.PHONY: build-agent
build-agent: ## Build the AI SRE agent image into the k3s image store
	cd ai-sre-agent && docker build -t ai-sre-agent:local . \
		&& docker save ai-sre-agent:local | sudo k3s ctr images import -

## ---------------------------------------------------------------------------
## Chaos / demo
## ---------------------------------------------------------------------------
.PHONY: chaos-latency
chaos-latency: ## Inject 800ms latency + 30% errors into sample-api
	./chaos/inject-latency.sh on

.PHONY: chaos-clear
chaos-clear: ## Clear all injected faults
	./chaos/inject-latency.sh off

.PHONY: chaos-kill
chaos-kill: ## Kill a random sample-api pod
	./chaos/kill-pod.sh

.PHONY: rca
rca: ## Run the AI SRE agent RCA against the current cluster state
	kubectl create job -n $(AGENT_NS) rca-$$(date +%s) \
		--from=cronjob/ai-sre-agent-rca || \
	kubectl apply -f ai-sre-agent/deploy/agent-job.yaml

.PHONY: demo
demo: ## Full guided demo: inject fault, wait, run RCA, print report
	./chaos/run-scenario.sh
