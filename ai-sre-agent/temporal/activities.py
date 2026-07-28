"""Temporal activities — the side-effecting steps of the RCA pipeline.

Activities are where all IO lives (querying backends, calling the LLM, probing
the service). Blocking client calls are pushed to a thread so the async
activity worker stays responsive. Each returns plain JSON-serialisable data.
"""
from __future__ import annotations

import asyncio
import dataclasses

import httpx
from temporalio import activity

from agent import config
from agent.models import RCAReport, SignalBundle
from agent.rca import _heuristic_rca
from agent.report import render_markdown
from agent.signals import gather


def _cfg(params: dict) -> config.Config:
    cfg = config.load()
    overrides = {k: params[k] for k in ("target_service", "target_namespace", "lookback_minutes")
                 if params.get(k) is not None}
    return dataclasses.replace(cfg, **overrides) if overrides else cfg


@activity.defn
async def gather_signals(params: dict) -> dict:
    cfg = _cfg(params)
    bundle = await asyncio.to_thread(gather, cfg)
    activity.logger.info("gathered %d alerts / %d logs / %d traces",
                         len(bundle.alerts), len(bundle.logs), len(bundle.traces))
    return bundle.model_dump()


@activity.defn
async def produce_rca(bundle_dict: dict) -> dict:
    cfg = config.load()
    bundle = SignalBundle.model_validate(bundle_dict)
    if cfg.dry_run:
        rca = _heuristic_rca(bundle)
    else:
        from agent.llm import analyze
        rca = await asyncio.to_thread(analyze, bundle, cfg)
    return rca.model_dump()


@activity.defn
async def render_report(bundle_dict: dict, rca_dict: dict) -> str:
    bundle = SignalBundle.model_validate(bundle_dict)
    rca = RCAReport.model_validate(rca_dict)
    md = render_markdown(bundle, rca)
    # In production this would post to Slack/PagerDuty and persist to object
    # storage; here we log it so it is visible in `kubectl logs` and the UI.
    activity.logger.info("RCA report generated (%d chars)", len(md))
    return md


@activity.defn
async def probe_service(url: str) -> bool:
    """Synthetic health probe used by the SyntheticMonitor workflow."""
    try:
        r = await asyncio.to_thread(httpx.get, url, timeout=5.0)
        return r.status_code < 500
    except httpx.HTTPError:
        return False
