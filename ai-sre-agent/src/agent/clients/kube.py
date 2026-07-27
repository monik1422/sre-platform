"""Minimal in-cluster Kubernetes reader (pods + warning events).

Uses the mounted ServiceAccount token and CA directly over HTTPS so we avoid a
heavyweight client dependency. All calls are read-only and degrade gracefully
to an empty result when RBAC or the token is unavailable (e.g. running the CLI
from a laptop), so the agent never hard-fails on missing Kube access.
"""
from __future__ import annotations

import logging
import os

import httpx

from agent.models import KubeSignal

log = logging.getLogger(__name__)

_SA = "/var/run/secrets/kubernetes.io/serviceaccount"


class KubeClient:
    def __init__(self, timeout: float = 15.0) -> None:
        self._timeout = timeout
        self._host = os.getenv("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
        self._port = os.getenv("KUBERNETES_SERVICE_PORT", "443")
        self._token = self._read(f"{_SA}/token")
        self._ca = f"{_SA}/ca.crt" if os.path.exists(f"{_SA}/ca.crt") else False

    @staticmethod
    def _read(path: str) -> str:
        try:
            with open(path, encoding="utf-8") as fh:
                return fh.read().strip()
        except OSError:
            return ""

    def _get(self, path: str) -> dict:
        if not self._token:
            return {}
        try:
            r = httpx.get(
                f"https://{self._host}:{self._port}{path}",
                headers={"Authorization": f"Bearer {self._token}"},
                verify=self._ca,
                timeout=self._timeout,
            )
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            log.info("kube api call skipped/failed for %s: %s", path, e)
            return {}

    def signals(self, namespace: str, label_selector: str) -> list[KubeSignal]:
        out: list[KubeSignal] = []

        pods = self._get(
            f"/api/v1/namespaces/{namespace}/pods?labelSelector={label_selector}"
        )
        for pod in pods.get("items", []):
            name = pod.get("metadata", {}).get("name", "?")
            for cs in pod.get("status", {}).get("containerStatuses", []):
                restarts = cs.get("restartCount", 0)
                if restarts:
                    waiting = cs.get("state", {}).get("waiting", {})
                    out.append(
                        KubeSignal(
                            kind="PodRestart",
                            object=name,
                            reason=waiting.get("reason", "")
                            or cs.get("lastState", {}).get("terminated", {}).get("reason", ""),
                            message=waiting.get("message", ""),
                            count=restarts,
                        )
                    )

        events = self._get(
            f"/api/v1/namespaces/{namespace}/events?fieldSelector=type=Warning"
        )
        for ev in events.get("items", [])[-15:]:
            out.append(
                KubeSignal(
                    kind="Event",
                    object=ev.get("involvedObject", {}).get("name", "?"),
                    reason=ev.get("reason", ""),
                    message=ev.get("message", "")[:300],
                    count=ev.get("count", 1),
                )
            )
        return out
