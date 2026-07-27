"""Gather evidence from every observability backend into one SignalBundle."""
from __future__ import annotations

import logging

from agent.clients.alertmanager import AlertmanagerClient
from agent.clients.kube import KubeClient
from agent.clients.loki import LokiClient
from agent.clients.prometheus import PrometheusClient
from agent.clients.tempo import TempoClient
from agent.config import Config
from agent.models import SignalBundle

log = logging.getLogger(__name__)


def gather(cfg: Config) -> SignalBundle:
    """Query all four signal sources for the target service.

    Each client degrades to empty on failure, so partial observability still
    yields a usable (if lower-confidence) bundle — exactly how a human on-call
    proceeds when one backend is flaky.
    """
    svc = cfg.target_service
    window = cfg.lookback_minutes

    prom = PrometheusClient(cfg.prometheus_url, cfg.http_timeout)
    loki = LokiClient(cfg.loki_url, cfg.http_timeout)
    tempo = TempoClient(cfg.tempo_url, cfg.http_timeout)
    am = AlertmanagerClient(cfg.alertmanager_url, cfg.http_timeout)
    kube = KubeClient(cfg.http_timeout)

    bundle = SignalBundle(
        service=svc,
        namespace=cfg.target_namespace,
        window_minutes=window,
        alerts=am.firing(service=svc),
        metrics=prom.red_snapshot(svc),
        logs=loki.error_logs(svc, window),
        traces=tempo.error_traces(svc, window),
        kube=kube.signals(cfg.target_namespace, f"app.kubernetes.io/name={svc}"),
    )
    log.info(
        "gathered signals: %d alerts, %d metrics, %d logs, %d traces, %d kube",
        len(bundle.alerts), len(bundle.metrics), len(bundle.logs),
        len(bundle.traces), len(bundle.kube),
    )
    return bundle
