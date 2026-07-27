"""Top-level RCA orchestration: gather -> analyze -> report."""
from __future__ import annotations

import logging

from agent.config import Config
from agent.models import (
    Confidence,
    RCAReport,
    RemediationStep,
    Severity,
    SignalBundle,
)
from agent.signals import gather

log = logging.getLogger(__name__)


def run(cfg: Config) -> tuple[SignalBundle, RCAReport]:
    bundle = gather(cfg)
    if cfg.dry_run:
        log.warning("DRY_RUN (no ANTHROPIC_API_KEY): emitting heuristic RCA skeleton")
        return bundle, _heuristic_rca(bundle)

    # Imported lazily so the CLI still works without the anthropic package
    # installed in dry-run environments.
    from agent.llm import analyze

    return bundle, analyze(bundle, cfg)


def _heuristic_rca(b: SignalBundle) -> RCAReport:
    """A deterministic, non-LLM RCA so the pipeline is demonstrable offline.

    It applies a few obvious correlation rules — enough to prove the plumbing
    end-to-end; the LLM path is what makes it genuinely actionable.
    """
    metrics = {m.name: m.value for m in b.metrics}
    burn = metrics.get("error_budget_burn_rate_1h", 0.0)
    p95 = metrics.get("latency_p95_5m", 0.0)
    err5m = metrics.get("error_ratio_5m", 0.0)
    up = metrics.get("targets_up", 1.0)

    evidence = [f"{m.name} = {m.value}{(' ' + m.unit) if m.unit else ''}" for m in b.metrics]
    evidence += [f"firing alert: {a.name} ({a.severity})" for a in b.alerts]
    evidence += [f"kube: {k.kind} {k.object} x{k.count} {k.reason}".strip() for k in b.kube]
    if b.logs:
        evidence.append(f"sample error log: {b.logs[0].line[:160]}")
    if b.traces:
        t = b.traces[0]
        evidence.append(f"trace {t.trace_id} {t.root_operation} {t.duration_ms}ms error={t.error}")

    if up == 0:
        cause = "All service targets are down — no replica is being scraped."
        sev, conf = Severity.sev1, Confidence.high
        title = f"{b.service}: total outage (targets down)"
    elif err5m and err5m > 0.05:
        cause = ("Elevated 5xx error rate. Error logs and error spans correlate "
                 "with the metric spike, indicating application-level failures "
                 "(consistent with an injected/failing dependency).")
        sev = Severity.sev1 if burn > 14.4 else Severity.sev2
        conf = Confidence.medium
        title = f"{b.service}: elevated error rate (burn {burn}x)"
    elif p95 and p95 > 0.3:
        cause = ("Latency SLO breach with normal error rate — added per-request "
                 "latency, most consistent with a slow downstream dependency.")
        sev, conf = Severity.sev2, Confidence.medium
        title = f"{b.service}: p95 latency {round(p95 * 1000)}ms over objective"
    else:
        cause = "No strong anomaly across signals in the window."
        sev, conf = Severity.sev3, Confidence.low
        title = f"{b.service}: no clear anomaly"

    return RCAReport(
        title=title,
        severity=sev,
        confidence=conf,
        summary=cause,
        affected_service=b.service,
        symptom=(f"error_ratio_5m={err5m}, p95={p95}s, burn_rate_1h={burn}x, "
                 f"targets_up={up}"),
        root_cause=cause,
        evidence=evidence or ["no signals gathered — check backend connectivity"],
        contributing_factors=[],
        remediation=[
            RemediationStep(
                action="Confirm the anomaly in Grafana (sample-api RED dashboard) "
                       "and identify the first affected timestamp.",
                rationale="Anchor the investigation to a concrete onset time.",
                urgency="immediate",
            ),
            RemediationStep(
                action="If fault injection is active, clear it: `make chaos-clear`. "
                       "Otherwise roll back the most recent sample-api deploy.",
                rationale="Fastest path to restore the SLI while root cause is confirmed.",
                urgency="immediate",
            ),
        ],
        prevention=[
            (
                "Add a canary/synthetic check (Temporal SyntheticMonitor) to detect "
                "this class of failure before users do."
            ),
        ],
    )
