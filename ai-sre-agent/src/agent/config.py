"""Runtime configuration, sourced entirely from the environment (12-factor)."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    # Observability endpoints (in-cluster service DNS by default).
    prometheus_url: str = os.getenv(
        "PROMETHEUS_URL", "http://kube-prometheus-stack-prometheus.observability.svc:9090"
    )
    loki_url: str = os.getenv("LOKI_URL", "http://loki.observability.svc:3100")
    tempo_url: str = os.getenv("TEMPO_URL", "http://tempo.observability.svc:3100")
    alertmanager_url: str = os.getenv(
        "ALERTMANAGER_URL",
        "http://kube-prometheus-stack-alertmanager.observability.svc:9093",
    )

    # Target under investigation.
    target_service: str = os.getenv("TARGET_SERVICE", "sample-api")
    target_namespace: str = os.getenv("TARGET_NAMESPACE", "sample-api")

    # LLM.
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    model: str = os.getenv("AI_SRE_MODEL", "claude-sonnet-5")
    max_tokens: int = int(os.getenv("AI_SRE_MAX_TOKENS", "2000"))

    # Temporal.
    temporal_target: str = os.getenv("TEMPORAL_TARGET", "temporal.temporal.svc:7233")
    temporal_namespace: str = os.getenv("TEMPORAL_NAMESPACE", "sre")
    temporal_task_queue: str = os.getenv("TEMPORAL_TASK_QUEUE", "ai-sre")

    # Behaviour. DRY_RUN skips the LLM call (gather + skeleton report only) so
    # the pipeline is demonstrable without a key or network egress.
    dry_run: bool = os.getenv("ANTHROPIC_API_KEY", "") == ""
    lookback_minutes: int = int(os.getenv("LOOKBACK_MINUTES", "15"))
    http_timeout: float = float(os.getenv("HTTP_TIMEOUT", "15"))


def load() -> Config:
    return Config()
