"""Loki HTTP API client — the logs half of RCA evidence."""
from __future__ import annotations

import logging
import re
import time

import httpx

from agent.models import LogSample

log = logging.getLogger(__name__)

_TRACE_RE = re.compile(r'"?trace_id"?\s*[:=]\s*"?([0-9a-f]{16,32})"?')


class LokiClient:
    def __init__(self, base_url: str, timeout: float = 15.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def error_logs(self, service: str, minutes: int, limit: int = 25) -> list[LogSample]:
        """Recent error-ish log lines for the service, newest first.

        Logs arrive via OTLP so `service_name` is the resource label. We filter
        for error signal in the line and best-effort extract a trace id to link
        each log back to its Tempo trace.
        """
        end = int(time.time() * 1e9)
        start = end - int(minutes * 60 * 1e9)
        logql = f'{{service_name="{service}"}} |~ `(?i)error|fault|panic|exception`'
        try:
            r = httpx.get(
                f"{self._base}/loki/api/v1/query_range",
                params={"query": logql, "start": start, "end": end,
                        "limit": limit, "direction": "backward"},
                timeout=self._timeout,
            )
            r.raise_for_status()
            streams = r.json()["data"]["result"]
        except (httpx.HTTPError, KeyError, ValueError) as e:
            log.warning("loki query failed: %s (%s)", logql, e)
            return []

        samples: list[LogSample] = []
        for stream in streams:
            for ts, line in stream.get("values", []):
                m = _TRACE_RE.search(line)
                samples.append(
                    LogSample(timestamp=ts, line=line[:1000], trace_id=m.group(1) if m else "")
                )
        return samples[:limit]
