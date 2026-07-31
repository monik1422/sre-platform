# AI Interaction Log

This platform was built and validated AI-first. This document is the **index**
to the full session transcripts; the raw, unedited chat exports live alongside
it in [`docs/transcripts/`](./transcripts/).

## How AI was used

I used AI (Anthropic's Claude) as an engineering partner across three distinct
phases, and the transcripts are split to match:

1. **Design & architecture** — framing the component set, arguing trade-offs
   (per-signal observability paths, app-of-apps vs. a monolith, RCA-as-workflow),
   and settling the SLO/alerting model. The output of this phase is the ADR set
   in [`design-decisions.md`](./design-decisions.md).
2. **Implementation** — generating the GitOps manifests, the instrumented Go
   service, and the Python AI SRE agent + Temporal workflows, then reviewing and
   correcting the generated code (OTel imports, Loki label names, schema-forced
   LLM output).
3. **Live deployment & debugging** — bringing the whole stack up on a real
   cluster. This was the most valuable phase: AI was used to root-cause and fix
   a series of real, non-obvious failures (WSL2 kernel incompatibility, Argo CD
   project scoping, a Helm/CRD ordering race, a wrong container image, and an
   Argo-vs-Kubernetes schema-version skew). Every fix in this phase became a
   real commit in the git history.

AI was an accelerator, not an autopilot: I reviewed all generated code, made the
architectural calls, and drove the debugging by feeding real cluster output back
in and deciding which fix to apply. The transcripts include the dead ends and
corrections, not just the clean path — that is the honest record of how the work
actually happened.

## Transcripts

| File | Phase | Covers |
|---|---|---|
| [`transcripts/01-build-session.md`](./transcripts/01-build-session.md) | Design + implementation | Architecture decisions, repo scaffolding, GitOps topology, observability stack, SLO/alerting, sample-api, AI SRE agent, Temporal workflows, and the packaging/git-history discussion. |
| [`transcripts/02-deployment-debugging.md`](./transcripts/02-deployment-debugging.md) | Live deployment | Every defect hit while standing the platform up on k3d/WSL2 and its fix — chronological, with the exact error signatures and resolutions. |

## Major defects found and fixed (summary)

A condensed defect log; the full detail is in
[`transcripts/02-deployment-debugging.md`](./transcripts/02-deployment-debugging.md).

| # | Defect | Root cause | Fix | Commit |
|---|---|---|---|---|
| 1 | `bootstrap.sh` crashed reading kubeconfig | k3s writes `/etc/rancher/k3s/k3s.yaml` root-only (0600); script read it as non-root | Copy kubeconfig to `~/.kube/config` with user ownership | `fix(bootstrap): readable kubeconfig for non-root` |
| 2 | k3s crash-looped on WSL2 | kubelet `system validation failed - wrong number of fields (expected 6, got 7)` — WSL2 `/proc/mountinfo` format vs. kubelet parser | Ran the identical k3s inside Docker via **k3d**, which uses the container's clean mount table | `docs: validated on k3d (WSL2)` / ADR-010 |
| 3 | Argo root app stuck `Unknown` | `platform` AppProject `destinations` did not allow the `argocd` namespace where the root Application lives | Added `argocd` (and widened to `namespace: '*'`) in both projects | `fix(gitops): allow argocd + widen project destinations` |
| 4 | `tempo` app `SyncError` — "tasks not valid" | ServiceMonitor (a `monitoring.coreos.com` CRD) rendered before/against a CRD the API server couldn't dry-run-validate (app-of-apps CRD race) | Added `SkipDryRunOnMissingResource=true` sync option | `fix(observability): skip dry-run on tempo ServiceMonitor (CRD race)` |
| 5 | `temporal` pod `ImagePullBackOff` | Referenced image tag `temporalio/temporal:1.1.2` does not exist on Docker Hub | Corrected to the Temporal CLI image tag that provides `server start-dev` | `fix(temporal): correct image` |
| 6 | `temporal` pod crash-loop after image fix | Used `temporalio/server`/`auto-setup` images whose config-templating entrypoint writes to `/etc/temporal/config` and is incompatible with `readOnlyRootFilesystem`; also does not accept `start-dev` args | Switched to the `temporalio/temporal` CLI image (native `start-dev`); removed the duplicate `--namespace` flag | `fix(temporal): use temporal CLI image for start-dev` |
| 7 | `make status`/`make up` failed with `127.0.0.1:6443 refused` while `kubectl` worked | Makefile `export KUBECONFIG` inherited a stale k3s path from the shell | Pinned `export KUBECONFIG := $(HOME)/.kube/config` in the Makefile | `fix(makefile): pin kubeconfig for k3d` |
| 8 | `chaos/run-scenario.sh` failed to inject fault | Port-forward not ready before the script `curl`ed it (timing race) | Wait/readiness before injecting; documented manual demo steps | `fix(chaos): wait for port-forward before injecting fault` |
| 9 | `kube-prometheus-stack` stuck `Unknown` (Healthy) | Argo CD v2.11 schema predates k8s v1.35's new `.status.terminatingReplicas` field → structured-merge diff fails with `ComparisonError` | Upgrade Argo CD (v2.14) **or** `ignoreDifferences` on that field | `fix(argocd): k8s 1.35 schema compatibility` |

> Every one of these was found by running the platform on a real cluster and
> feeding the actual error output back through AI to root-cause it — which is
> exactly the day-2 operational loop the AI SRE agent itself automates.
