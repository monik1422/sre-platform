# Transcript 02 — Deployment & Live Debugging

> Curated, chronological log of bringing the platform up on a real cluster and
> fixing every failure encountered. This is the operational half of the work:
> real error signatures, real root causes, real fixes — each of which became a
> commit. Environment: Windows + WSL2 (Ubuntu 26.04), Docker Desktop, later
> k3d. Tool used: Anthropic Claude, fed live cluster output at each step.

## Environment starting point

- Tooling verified: Docker 29.6.2, kubectl v1.36.3, GNU Make 4.4.1, git 2.53.
- Target: `make up` → k3s + Argo CD + GitOps root app, then a fully green Argo
  application tree, then `make demo`.

---

## Defect 1 — bootstrap crashes reading the kubeconfig

**Symptom**
```
./bootstrap/bootstrap.sh: line 48: /etc/rancher/k3s/k3s.yaml: Permission denied
make: *** [Makefile:23: up] Error 1
```
k3s installed and started, but the script died immediately after.

**Root cause**
k3s writes its kubeconfig to `/etc/rancher/k3s/k3s.yaml` owned by root, mode
`0600`. The bootstrap then ran `kubectl` as the non-root user, which cannot read
that file.

**Fix**
```bash
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown "$(id -u):$(id -g)" ~/.kube/config
export KUBECONFIG=~/.kube/config
```
Confirmed `kubectl` could reach the API. Commit:
`fix(bootstrap): make kubeconfig readable by the non-root user`.

---

## Defect 2 — k3s crash-loops on WSL2 (the big one)

**Symptom**
API server unreachable (`connect: connection refused` on `127.0.0.1:6443`);
`systemctl status k3s` showed `activating` then `Failed`. Journal, filtered to
the fatal line:
```
kubelet.go:1547 "Failed to start ContainerManager"
  err="system validation failed - wrong number of fields (expected 6, got 7)"
```

**Root cause**
A known kubelet-on-WSL2 incompatibility. The kubelet parses
`/proc/<pid>/mountinfo` expecting 6 fields before the separator; WSL2's kernel
emits a 7th on some mount lines, so ContainerManager refuses to start, the
kubelet exits non-zero, and systemd restarts it forever. Not a cgroup or
networking issue — the host mount-table format. No `.wslconfig`/iptables tweak
fixes it.

**Fix — pivot to k3d (run the identical k3s inside Docker)**
```bash
sudo systemctl stop k3s && sudo systemctl disable k3s
k3d cluster create sre --servers 1 --wait
kubectl config use-context k3d-sre
kubectl get nodes            # k3d-sre-server-0  Ready  v1.35.5+k3s1
```
Inside a container the mount table is clean, so the kubelet parser is happy.
Then built and side-loaded the two local images and installed Argo CD:
```bash
docker build -t sample-api:local ./apps/sample-api
docker build -t ai-sre-agent:local ./ai-sre-agent
k3d image import sample-api:local ai-sre-agent:local -c sre
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/v2.11.3/manifests/install.yaml
```
Recorded as **ADR-010** (validated on k3d; production target remains EKS). This
is the same k3s and the same manifests — only the host wrapper changed.

---

## Defect 3 — Argo root application stuck `Unknown`

**Symptom**
```
InvalidSpecError: application destination server '...kubernetes.default.svc'
and namespace 'argocd' do not match any of the allowed destinations
in project 'platform'
```
Sync/health `Unknown`; repoURL blank. (Not a Git-fetch problem — the repo-server
logs showed nothing.)

**Root cause**
The root Application object lives in the `argocd` namespace, but the `platform`
AppProject's `destinations` only whitelisted the workload namespaces. Argo
refuses to reconcile a destination the project doesn't allow.

**Fix**
Added the `argocd` namespace to the `platform` project and, to unblock the whole
tree on a single local cluster, widened both projects to
`- server: https://kubernetes.default.svc` / `namespace: '*'`. Re-applied and
hard-refreshed; `root` went `Synced/Healthy` and spawned all children. Commit:
`fix(gitops): allow argocd namespace + widen project destinations for local run`.

---

## Defect 4 — `namespaces` app also `Unknown`, then `tempo` SyncError

Once the root synced, the child apps cascaded. Two needed attention.

**4a. `namespaces` `Unknown`** — same project-destination class as Defect 3;
cleared by the `namespace: '*'` widening above. Because `namespaces` is
sync-wave -1, everything else was blocked behind it until it synced.

**4b. `tempo` — `SyncError`**
```
Failed sync attempt: one or more synchronization tasks are not valid
(retried 5 times).
syncResult ... group: monitoring.coreos.com  kind: ServiceMonitor
```
The failing task was the **ServiceMonitor** (a `monitoring.coreos.com` CRD).
The four core objects (ConfigMap/Service/ServiceAccount/StatefulSet) were fine;
the whole batch failed because that one CRD-backed object couldn't be
dry-run-validated — a classic app-of-apps CRD ordering race (Tempo rendering its
ServiceMonitor before the CRD from kube-prometheus-stack was registerable for
dry-run).

**Fix**
Added the sync option `SkipDryRunOnMissingResource=true` (with
`ServerSideApply=true`) to the tempo Application so Argo stops failing the batch
on the not-yet-dry-runnable CRD kind. Commit:
`fix(observability): skip dry-run on tempo ServiceMonitor to avoid CRD race`.

---

## Defect 5 — Temporal `ImagePullBackOff`

**Symptom**
```
Failed to pull image "temporalio/temporal:1.1.2":
docker.io/temporalio/temporal:1.1.2: not found
```
And the agent then crash-looped with `Connection refused` — pure collateral,
because nothing was listening on Temporal's `7233`.

**Root cause**
The pinned tag `temporalio/temporal:1.1.2` does not exist on Docker Hub.

**Fix (staged — see Defect 6)**
First attempt swapped to `temporalio/server:1.25.1` and `temporalio/auto-setup:
1.25.1`, both of which *do* pull — but those are the wrong images for the
`server start-dev` command (see next). Commit trail:
`fix(temporal): correct image tag (1.1.2 does not exist on Docker Hub)`.

---

## Defect 6 — Temporal crash-loops after the image fix

**Symptom (evolved across attempts)**
```
# with temporalio/server:1.25.1 + readOnlyRootFilesystem:
unable to create open /etc/temporal/config/docker.yaml: read-only file system
# after mounting an emptyDir over /etc/temporal/config:
unable to stat /etc/temporal/config/config_template.yaml: no such file or directory
```

**Root cause**
`temporalio/server` and `temporalio/auto-setup` use a **config-templating
entrypoint** that (a) writes generated config into `/etc/temporal/config`
(blocked by `readOnlyRootFilesystem: true`) and (b) ships a `config_template.yaml`
in that same directory (which an empty mount then masked). Critically, those
images do **not** run `server start-dev` — that subcommand belongs to the
standalone Temporal CLI. So the manifest's args were never even the process that
ran.

**Fix**
Switched to the **`temporalio/temporal`** CLI image (whose native command *is*
`server start-dev`, writes only to `--db-filename` on the writable `/data`
mount, and never touches `/etc/temporal/config`). Verified the tag pulls,
imported it into k3d, removed the config-volume hacks, and removed a duplicate
`--namespace` flag (the dev-server takes a single custom namespace). Result:
`temporal` → `1/1 Running`, and the agent connected on the next restart.
Commits:
`fix(temporal): use temporalio/temporal CLI image for start-dev` and
`fix(temporal): single sre namespace, drop server-image config hacks`.

**Verification**
```
kubectl get applications -n argocd
temporal       Synced   Healthy
ai-sre-agent   Synced   Healthy
```
The agent's `Connection refused` cleared the moment Temporal answered on 7233,
confirming it was downstream of Defect 6 all along.

---

## Defect 7 — `make status`/`make up` fail while `kubectl` works

**Symptom**
`make status` errored with `127.0.0.1:6443 connection refused`, even though a
plain `kubectl get applications` in the same shell listed the green tree.

**Root cause**
The Makefile had `export KUBECONFIG` with no value, which re-exports whatever the
calling shell holds. A stale `export KUBECONFIG=/etc/rancher/k3s/k3s.yaml` (from
the abandoned native-k3s attempts) was being passed to every `make`-invoked
`kubectl`, pointing at the dead k3s API server. Interactive `kubectl` used the
default k3d kubeconfig, so the two disagreed.

**Fix**
Pinned the Makefile to the correct kubeconfig:
```makefile
export KUBECONFIG := $(HOME)/.kube/config
```
and cleared the stale value from the shell/`.bashrc`. `make status` then listed
the apps correctly. Commit:
`fix(makefile): pin KUBECONFIG to default path so targets work on k3d`.

---

## Defect 8 — demo fault injection fails on a port-forward race

**Symptom**
```
==> 1/5 Injecting fault ...
curl: (7) Failed to connect to localhost port 18080 ... Could not connect to server
```

**Root cause**
`chaos/run-scenario.sh` started a `kubectl port-forward` and immediately `curl`ed
it; the forward hadn't established yet (and once KUBECONFIG had drifted, it
couldn't connect at all). The fault never got injected, invalidating the rest of
the run.

**Fix**
Documented and ran the demo with a persistent port-forward in a separate
terminal, and hardened the script to wait for the forward before injecting.
Manual sequence that works reliably:
```bash
kubectl -n sample-api port-forward svc/sample-api 18080:80   # leave running
curl -sS -X POST http://localhost:18080/fault -d '{"latency_ms":800,"error_pct":30}'
for i in $(seq 1 400); do curl -s -o /dev/null http://localhost:18080/api/work; sleep 0.2; done
kubectl create job -n ai-sre rca-demo --from=cronjob/ai-sre-agent-rca
kubectl -n ai-sre wait --for=condition=complete job/rca-demo --timeout=200s
kubectl -n ai-sre logs job/rca-demo        # the structured RCA report
curl -sS -X POST http://localhost:18080/fault -d '{"latency_ms":0,"error_pct":0}'
```
Commit: `fix(chaos): wait for port-forward before injecting fault`.

---

## Defect 9 — `kube-prometheus-stack` stuck `Unknown` (but `Healthy`)

**Symptom**
```
ComparisonError: Failed to compare desired state to live state: failed to
calculate diff: error calculating structured merge diff: ...
.status.terminatingReplicas: field not declared in schema
```
The repo-server logs showed all four Helm charts rendering successfully, so this
was a *diff* failure, not a fetch/render failure. The workloads were `Healthy`
and running.

**Root cause**
Version skew between the tooling and the cluster: Kubernetes v1.35 added
`.status.terminatingReplicas` to Deployment/ReplicaSet/StatefulSet, but Argo CD
v2.11.3 (mid-2024) ships an older API schema that doesn't declare that field, so
its structured-merge diff aborts with `ComparisonError` on the Prometheus-stack
workloads (the ones now carrying that status field).

**Fix (two options; documented both)**
- Root-cause: upgrade Argo CD to a release that knows the v1.35 schema:
  ```bash
  kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/v2.14.5/manifests/install.yaml
  ```
- Lightweight: `ignoreDifferences` on `.status.terminatingReplicas` for the
  affected kinds in `argocd/apps/10-kube-prometheus-stack.yaml`.

Documented as a known cosmetic issue in the README (Health is `Healthy`; only the
sync *diff* is affected). Commit: `fix(argocd): k8s 1.35 schema compatibility for
kube-prometheus-stack`.

---

## Final state

```
NAME                    SYNC STATUS   HEALTH STATUS
ai-sre-agent            Synced        Healthy
kube-prometheus-stack   Synced        Healthy   # after Argo upgrade / ignoreDifferences
loki                    Synced        Healthy
namespaces              Synced        Healthy
otel-collector          Synced        Healthy
platform-config         Synced        Healthy
root                    Synced        Healthy
sample-api              Synced        Healthy
tempo                   Synced        Healthy
temporal                Synced        Healthy
```

Full incident demo validated end-to-end: fault injection → SLO burn-rate alert →
AI SRE agent RCA (in-cluster Job) → structured report → fault cleared → RED
dashboard recovers.

## Lessons captured as ADRs / README notes

- **ADR-010** — k3d over host k3s on WSL2 (kubelet mountinfo bug).
- **README "Notes for reviewers"** — the Argo/k8s-1.35 schema skew, the k3d
  reproduction path, and the dry-run vs. live-LLM agent modes.
- Reinforced **ADR-006** (Temporal dev-server via the CLI image; production uses
  the HA chart) with the concrete image-compatibility findings from Defect 6.
