"""Alertmanager v2 API client — what is actually firing right now."""
from __future__ import annotations

import logging

import httpx

from agent.models import Alert

log = logging.getLogger(__name__)


class AlertmanagerClient:
    def __init__(self, base_url: str, timeout: float = 15.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def firing(self, service: str | None = None) -> list[Alert]:
        try:
            r = httpx.get(
                f"{self._base}/api/v2/alerts",
                params={"active": "true", "silenced": "false", "inhibited": "false"},
                timeout=self._timeout,
            )
            r.raise_for_status()
            raw = r.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("alertmanager query failed: %s", e)
            return []

        alerts: list[Alert] = []
        for a in raw:
            labels = a.get("labels", {})
            if service and labels.get("service") not in (None, service):
                continue
            ann = a.get("annotations", {})
            alerts.append(
                Alert(
                    name=labels.get("alertname", "unknown"),
                    severity=labels.get("severity", ""),
                    state=a.get("status", {}).get("state", ""),
                    summary=ann.get("summary", ""),
                    description=ann.get("description", ""),
                    labels=labels,
                )
            )
        return alerts
