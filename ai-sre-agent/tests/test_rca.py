"""Tests for the schema and the offline heuristic RCA path."""
from agent.models import Alert, MetricPoint, RCAReport, Severity, SignalBundle
from agent.rca import _heuristic_rca
from agent.report import render_markdown


def _bundle(**metrics: float) -> SignalBundle:
    return SignalBundle(
        service="sample-api",
        namespace="sample-api",
        window_minutes=15,
        metrics=[MetricPoint(name=k, value=v) for k, v in metrics.items()],
    )


def test_tool_schema_is_wellformed():
    schema = RCAReport.anthropic_tool_schema()
    assert schema["name"] == "submit_rca"
    assert "properties" in schema["input_schema"]
    assert "root_cause" in schema["input_schema"]["properties"]


def test_heuristic_flags_total_outage():
    rca = _heuristic_rca(_bundle(targets_up=0.0))
    assert rca.severity == Severity.sev1
    assert "down" in rca.root_cause.lower()


def test_heuristic_flags_error_spike():
    b = _bundle(error_ratio_5m=0.4, error_budget_burn_rate_1h=80.0, targets_up=2.0)
    b.alerts.append(Alert(name="SampleApiErrorBudgetFastBurn", severity="page"))
    rca = _heuristic_rca(b)
    assert rca.severity == Severity.sev1
    assert rca.evidence  # evidence is populated


def test_heuristic_flags_latency():
    rca = _heuristic_rca(_bundle(error_ratio_5m=0.0, latency_p95_5m=0.6, targets_up=2.0))
    assert rca.severity == Severity.sev2
    assert "latency" in rca.root_cause.lower()


def test_report_renders_markdown():
    rca = _heuristic_rca(_bundle(error_ratio_5m=0.4, error_budget_burn_rate_1h=80.0, targets_up=2.0))
    md = render_markdown(_bundle(error_ratio_5m=0.4), rca)
    assert md.startswith("# RCA")
    assert "## Remediation" in md
