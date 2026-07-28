"""Temporal worker: registers the RCA + synthetic-monitor workflows and their
activities, then polls the task queue forever.

On startup it also ensures the target Temporal namespace exists and (optionally)
kicks off the SyntheticMonitor workflow so the platform is self-monitoring the
moment the worker is healthy.
"""
from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.service import RPCError
from temporalio.worker import Worker

from agent import config
from temporal import activities
from temporal.workflows import RCAWorkflow, SyntheticMonitorWorkflow

logging.basicConfig(
    level=logging.INFO,
    format='{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
log = logging.getLogger("worker")


async def _start_synthetic_monitor(client: Client, cfg: config.Config) -> None:
    svc = cfg.target_service
    url = f"http://{svc}.{cfg.target_namespace}.svc/healthz"
    try:
        await client.start_workflow(
            SyntheticMonitorWorkflow.run,
            {"url": url, "interval_seconds": 30, "fail_threshold": 3,
             "target_service": svc, "target_namespace": cfg.target_namespace},
            id="synthetic-monitor-sample-api",
            task_queue=cfg.temporal_task_queue,
        )
        log.info("started SyntheticMonitor for %s", url)
    except RPCError as e:
        # WorkflowExecutionAlreadyStarted is expected on restart — idempotent.
        log.info("synthetic monitor already running or not started: %s", e)


async def main() -> None:
    cfg = config.load()
    log.info("connecting to Temporal at %s (ns=%s)", cfg.temporal_target, cfg.temporal_namespace)
    client = await Client.connect(cfg.temporal_target, namespace=cfg.temporal_namespace)

    await _start_synthetic_monitor(client, cfg)

    worker = Worker(
        client,
        task_queue=cfg.temporal_task_queue,
        workflows=[RCAWorkflow, SyntheticMonitorWorkflow],
        activities=[
            activities.gather_signals,
            activities.produce_rca,
            activities.render_report,
            activities.probe_service,
        ],
    )
    log.info("worker polling task queue %s", cfg.temporal_task_queue)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
