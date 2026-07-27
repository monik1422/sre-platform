"""Typed contracts for signals gathered and the RCA the LLM must produce.

The RCAReport schema is also emitted as the Anthropic tool-use input schema
(see llm.py) so the model is *forced* to return well-formed, parseable output
rather than free prose we have to scrape.
"""
from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Signals (input to the LLM)
# --------------------------------------------------------------------------- #
class Alert(BaseModel):
    name: str
    severity: str = ""
    state: str = ""
    summary: str = ""
    description: str = ""
    labels: dict[str, str] = Field(default_factory=dict)


class MetricPoint(BaseModel):
    name: str
    value: float
    unit: str = ""


class LogSample(BaseModel):
    timestamp: str
    line: str
    trace_id: str = ""


class TraceSample(BaseModel):
    trace_id: str
    root_service: str = ""
    root_operation: str = ""
    duration_ms: float = 0.0
    error: bool = False


class KubeSignal(BaseModel):
    kind: str            # e.g. "PodRestart", "Event"
    object: str
    reason: str = ""
    message: str = ""
    count: int = 1


class SignalBundle(BaseModel):
    """Everything the agent gathered — the evidence base for the RCA."""
    collected_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    service: str = ""
    namespace: str = ""
    window_minutes: int = 15
    alerts: list[Alert] = Field(default_factory=list)
    metrics: list[MetricPoint] = Field(default_factory=list)
    logs: list[LogSample] = Field(default_factory=list)
    traces: list[TraceSample] = Field(default_factory=list)
    kube: list[KubeSignal] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# RCA (output from the LLM)
# --------------------------------------------------------------------------- #
class Confidence(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class Severity(str, Enum):
    sev1 = "SEV1"
    sev2 = "SEV2"
    sev3 = "SEV3"


class RemediationStep(BaseModel):
    action: str = Field(description="Concrete, executable remediation step.")
    rationale: str = Field(description="Why this step addresses the root cause.")
    urgency: str = Field(description="One of: immediate, short-term, follow-up.")


class RCAReport(BaseModel):
    title: str = Field(description="One-line incident title.")
    severity: Severity
    confidence: Confidence
    summary: str = Field(description="2-3 sentence executive summary for an incident channel.")
    affected_service: str
    symptom: str = Field(description="What users/monitoring observed.")
    root_cause: str = Field(description="The single most probable root cause, stated plainly.")
    evidence: list[str] = Field(
        description="Bullet list of specific signals (metric values, log lines, "
        "trace ids, alerts) that support the root cause."
    )
    contributing_factors: list[str] = Field(default_factory=list)
    remediation: list[RemediationStep] = Field(description="Ordered remediation steps.")
    prevention: list[str] = Field(
        default_factory=list,
        description="Day-2 follow-ups: alerts, tests, or guardrails to prevent recurrence.",
    )

    @staticmethod
    def anthropic_tool_schema() -> dict:
        """JSON schema for the submit_rca tool the LLM is required to call."""
        schema = RCAReport.model_json_schema()
        # Anthropic tool input_schema wants a plain object schema.
        schema.pop("$defs", None)
        return {
            "name": "submit_rca",
            "description": "Submit the structured root-cause analysis report.",
            "input_schema": RCAReport.model_json_schema(),
        }
