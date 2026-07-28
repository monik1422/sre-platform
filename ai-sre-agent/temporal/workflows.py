"""Temporal workflows.

RCAWorkflow          durable, retryable RCA pipeline (gather -> analyze -> report).
SyntheticMonitor     operational workflow: periodically probes the service and
                     auto-launches an RCA when it detects sustained failure.

Workflow code is deterministic — all IO is delegated to activities, all waiting
uses workflow.sleep, and unbounded loops use continue_as_new to keep history
bounded (production hygiene).
"""
from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from temporal.activities import (
        gather_signals,
        probe_service,
        produce_rca,
        render_report,
    )

_FAST_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=4,
)
# The LLM call is slower and rate-limit-prone: fewer, more patient retries.
_LLM_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_attempts=3,
)


@workflow.defn
class RCAWorkflow:
    @workflow.run
    async def run(self, params: dict) -> dict:
        bundle = await workflow.execute_activity(
            gather_signals, params,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=_FAST_RETRY,
        )
        rca = await workflow.execute_activity(
            produce_rca, bundle,
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=_LLM_RETRY,
        )
        report_md = await workflow.execute_activity(
            render_report, args=[bundle, rca],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_FAST_RETRY,
        )
        return {"rca": rca, "report_md": report_md}


@workflow.defn
class SyntheticMonitorWorkflow:
    """Probes a URL on an interval; N consecutive failures triggers an RCA."""

    @workflow.run
    async def run(self, params: dict) -> None:
        url: str = params["url"]
        interval_s: int = params.get("interval_seconds", 30)
        fail_threshold: int = params.get("fail_threshold", 3)
        iterations: int = params.get("iterations", 120)  # ~1h at 30s, then CAN
        consecutive_failures: int = params.get("_consecutive_failures", 0)

        for _ in range(iterations):
            healthy = await workflow.execute_activity(
                probe_service, url,
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            if healthy:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                workflow.logger.warning(
                    "probe failed (%d/%d)", consecutive_failures, fail_threshold
                )
                if consecutive_failures >= fail_threshold:
                    # Fire-and-forget child RCA so monitoring keeps running.
                    await workflow.start_child_workflow(
                        RCAWorkflow.run,
                        {"target_service": params.get("target_service", "sample-api"),
                         "target_namespace": params.get("target_namespace", "sample-api"),
                         "lookback_minutes": 15},
                        id=f"rca-auto-{workflow.now().strftime('%Y%m%d-%H%M%S')}",
                        parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                    )
                    consecutive_failures = 0
            await workflow.sleep(timedelta(seconds=interval_s))

        # Keep history bounded across long-running monitoring.
        params["_consecutive_failures"] = consecutive_failures
        workflow.continue_as_new(params)
