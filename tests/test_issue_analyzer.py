"""Tests for joining failed evaluations to source traces."""

from __future__ import annotations

import pytest

from ragops.analysis import (
    DuplicateTraceForAnalysisError,
    IssueAnalyzer,
    MissingTraceForEvaluationError,
)
from ragops.evaluation import EvaluationIssueCode, EvaluationReport, RuleBasedEvaluator
from ragops.schemas import Trace


def make_trace(trace_id: str, **overrides: object) -> Trace:
    data: dict[str, object] = {
        "trace_id": trace_id,
        "query": f"问题 {trace_id}",
        "retrieval_chunks": [f"证据 {trace_id}"],
        "retrieval_scores": [0.91],
        "prompt_version": "qa_v1",
        "model": "example-model",
        "answer": f"回答 {trace_id}",
        "latency_ms": 842.0,
    }
    data.update(overrides)
    return Trace.model_validate(data)


def make_report(traces: list[Trace]) -> EvaluationReport:
    return RuleBasedEvaluator().evaluate_many(traces)


def test_analyze_ignores_passed_results_and_joins_failed_trace() -> None:
    passed = make_trace("trc_passed")
    failed = make_trace("trc_failed", retrieval_scores=[0.1])
    report = make_report([passed, failed])

    analysis = IssueAnalyzer().analyze(report, [passed, failed])

    assert analysis.source_report_id == report.report_id
    assert analysis.total_bad_cases == 1
    assert analysis.bad_cases[0].trace is failed
    assert analysis.bad_cases[0].evaluation is report.results[1]
    assert analysis.issue_groups[EvaluationIssueCode.LOW_RETRIEVAL_SCORE] == (
        "trc_failed",
    )


def test_analyze_supports_generator_input() -> None:
    failed = make_trace("trc_generator", latency_ms=40000.0)
    report = make_report([failed])

    analysis = IssueAnalyzer().analyze(report, (trace for trace in [failed]))

    assert analysis.bad_cases[0].trace.trace_id == "trc_generator"


def test_duplicate_input_trace_id_is_rejected() -> None:
    first = make_trace("trc_duplicate")
    second = make_trace("trc_duplicate", answer="不同回答")
    report = make_report([])

    with pytest.raises(DuplicateTraceForAnalysisError, match="trc_duplicate"):
        IssueAnalyzer().analyze(report, [first, second])


def test_missing_failed_trace_is_rejected() -> None:
    failed = make_trace("trc_missing", retrieval_chunks=[], retrieval_scores=[])
    report = make_report([failed])

    with pytest.raises(MissingTraceForEvaluationError, match="trc_missing"):
        IssueAnalyzer().analyze(report, [])


def test_unreferenced_extra_trace_is_ignored() -> None:
    failed = make_trace("trc_failed", latency_ms=40000.0)
    extra = make_trace("trc_extra")
    report = make_report([failed])

    analysis = IssueAnalyzer().analyze(report, [extra, failed])

    assert analysis.total_bad_cases == 1
    assert analysis.bad_cases[0].trace.trace_id == "trc_failed"


def test_analyze_preserves_report_order_for_failures() -> None:
    traces = [
        make_trace("trc_second", retrieval_scores=[0.1]),
        make_trace("trc_passed"),
        make_trace("trc_first", latency_ms=40000.0),
    ]
    report = make_report(traces)

    analysis = IssueAnalyzer().analyze(report, reversed(traces))

    assert tuple(case.trace.trace_id for case in analysis.bad_cases) == (
        "trc_second",
        "trc_first",
    )


def test_analyze_does_not_modify_report_or_traces() -> None:
    traces = [
        make_trace("trc_passed"),
        make_trace("trc_failed", retrieval_scores=[0.1]),
    ]
    report = make_report(traces)
    report_before = report.model_dump(mode="json")
    traces_before = [trace.model_dump(mode="json") for trace in traces]

    IssueAnalyzer().analyze(report, traces)

    assert report.model_dump(mode="json") == report_before
    assert [trace.model_dump(mode="json") for trace in traces] == traces_before


def test_analyzer_does_not_run_rule_based_evaluation(tmp_path, monkeypatch) -> None:
    failed = make_trace("trc_existing_failure", retrieval_scores=[0.1])
    report = make_report([failed])

    def unexpected_call(*args, **kwargs):
        raise AssertionError("IssueAnalyzer must not execute evaluation rules")

    monkeypatch.setattr(RuleBasedEvaluator, "evaluate", unexpected_call)
    monkeypatch.setattr(RuleBasedEvaluator, "evaluate_many", unexpected_call)

    analysis = IssueAnalyzer().analyze(report, [failed])

    assert analysis.total_bad_cases == 1
