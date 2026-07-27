"""Prometheus HTTP API client — the metrics half of RCA evidence."""
from __future__ import annotations

import logging

import httpx

from agent.models import MetricPoint

log = logging.getLogger(__name__)


class PrometheusClient:
    def __init__(self, base_url: str, timeout: float = 15.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def instant(self, expr: str) -> float | None:
        """Evaluate an instant PromQL query, returning a single scalar or None."""
        try:
            r = httpx.get(
                f"{self._base}/api/v1/query",
                params={"query": expr},
                timeout=self._timeout,
            )
            r.raise_for_status()
            result = r.json()["data"]["result"]
            if not result:
                return None
            return float(result[0]["value"][1])
        except (httpx.HTTPError, KeyError, ValueError, IndexError) as e:
            log.warning("prometheus query failed: %s (%s)", expr, e)
            return None

    def red_snapshot(self, service: str) -> list[MetricPoint]:
        """RED + SLO snapshot for a service, using the pre-computed SLI rules
        where available (falling back to raw expressions)."""
        exprs: dict[str, tuple[str, str]] = {
            "request_rate_1m": (
                f'sum(rate(http_requests_total{{service="{service}"}}[1m]))',
                "req/s",
            ),
            "error_ratio_5m": (
                "job:sample_api_request_errors:ratio_rate5m",
                "ratio",
            ),
            "error_ratio_1h": (
                "job:sample_api_request_errors:ratio_rate1h",
                "ratio",
            ),
            "latency_p95_5m": (
                "job:sample_api_latency_p95_seconds:5m",
                "s",
            ),
            "targets_up": (
                f'sum(up{{service="{service}"}})',
                "count",
            ),
        }
        points: list[MetricPoint] = []
        for name, (expr, unit) in exprs.items():
            val = self.instant(expr)
            if val is not None:
                points.append(MetricPoint(name=name, value=round(val, 6), unit=unit))
        # Derived burn rate for narrative convenience (budget = 0.5%).
        er1h = next((p.value for p in points if p.name == "error_ratio_1h"), None)
        if er1h is not None:
            points.append(
                MetricPoint(name="error_budget_burn_rate_1h", value=round(er1h / 0.005, 2), unit="x")
            )
        return points
