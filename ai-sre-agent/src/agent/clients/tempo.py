"""Tempo HTTP API client — the traces half of RCA evidence."""
from __future__ import annotations

import logging
import time

import httpx

from agent.models import TraceSample

log = logging.getLogger(__name__)


class TempoClient:
    def __init__(self, base_url: str, timeout: float = 15.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def error_traces(self, service: str, minutes: int, limit: int = 10) -> list[TraceSample]:
        """Search Tempo (TraceQL) for error / slow traces for the service."""
        end = int(time.time())
        start = end - minutes * 60
        traceql = f'{{ resource.service.name="{service}" && status = error }}'
        traces = self._search(traceql, start, end, limit)
        if not traces:
            # No explicit error spans — fall back to slowest recent traces.
            traceql = f'{{ resource.service.name="{service}" }} | select(duration)'
            traces = self._search(traceql, start, end, limit)
        return traces

    def _search(self, traceql: str, start: int, end: int, limit: int) -> list[TraceSample]:
        try:
            r = httpx.get(
                f"{self._base}/api/search",
                params={"q": traceql, "start": start, "end": end, "limit": limit},
                timeout=self._timeout,
            )
            r.raise_for_status()
            payload = r.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("tempo search failed: %s (%s)", traceql, e)
            return []

        out: list[TraceSample] = []
        for t in payload.get("traces", []):
            out.append(
                TraceSample(
                    trace_id=t.get("traceID", ""),
                    root_service=t.get("rootServiceName", ""),
                    root_operation=t.get("rootTraceName", ""),
                    duration_ms=float(t.get("durationMs", 0) or 0),
                    error="error" in traceql,
                )
            )
        return out
