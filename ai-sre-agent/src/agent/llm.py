"""Turn a SignalBundle into a structured RCAReport via Claude.

We use Anthropic tool-use with a forced tool_choice so the model MUST return
JSON matching the RCAReport schema — no fragile prose parsing.
"""
from __future__ import annotations

import logging

from anthropic import Anthropic

from agent.config import Config
from agent.models import RCAReport, SignalBundle

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a Staff Site Reliability Engineer performing incident root-cause \
analysis. You are given structured evidence gathered from Prometheus (metrics \
and SLOs), Loki (logs), Tempo (traces), Alertmanager (firing alerts), and \
Kubernetes (pod restarts and warning events) for a single service over a short \
window.

Reason like an on-call SRE:
1. Start from what is firing and what the SLI/error-budget numbers actually say.
2. Correlate across signals — a spike in error_ratio with matching 5xx log \
lines and error traces is strong evidence; an alert with no supporting metric \
movement is weak.
3. Name the single most probable root cause. Do not hedge across five \
possibilities — commit to the most likely one and set confidence accordingly.
4. Ground every claim in a specific value, log line, trace id, or alert from \
the evidence. Never invent numbers that are not present.
5. Give remediation that is concrete and ordered: what to do now to stop the \
bleeding, then what to fix properly.

If the evidence is thin or contradictory, say so and set confidence to low.
Return your analysis ONLY by calling the submit_rca tool."""


def analyze(bundle: SignalBundle, cfg: Config) -> RCAReport:
    client = Anthropic(api_key=cfg.anthropic_api_key)
    tool = RCAReport.anthropic_tool_schema()

    user_content = (
        "Here is the gathered evidence as JSON. Produce the RCA.\n\n"
        f"```json\n{bundle.model_dump_json(indent=2)}\n```"
    )

    resp = client.messages.create(
        model=cfg.model,
        max_tokens=cfg.max_tokens,
        system=SYSTEM_PROMPT,
        tools=[tool],
        tool_choice={"type": "tool", "name": "submit_rca"},
        messages=[{"role": "user", "content": user_content}],
    )

    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "submit_rca":
            log.info("received structured RCA from model %s", cfg.model)
            return RCAReport.model_validate(block.input)

    raise RuntimeError("model did not return a submit_rca tool call")
