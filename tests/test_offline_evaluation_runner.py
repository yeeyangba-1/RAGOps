"""Tests for the local offline evaluation workflow."""

from __future__ import annotations

import pytest

from ragops.evaluation import (
    EvaluationReportCollector,
    EvaluationReportStorageError,
    OfflineEvaluationRunner,
    RuleBasedEvaluator,
)
from ragops.schemas import EvaluationIssueCode, EvaluationReport, Trace
from ragops.tracing import TraceCollector, TraceStorageError


def make_trace(trace_id: str, **overrides: object) -> Trace:
    data: dict[str, object] = {
        "trace_id": trace_id,
        "query": "退款多久到账？",
        "retrieval_chunks": ["退款通常在三个工作日内到账。"],
        "retrieval_scores": [0.91],
        "prompt_version": "qa_v1",
        "model": "example-model",
        "answer": "通常三个工作日内到账。",
        "latency_ms": 842.0,
    }
    data.update(overrides)
    return Trace.model_validate(data)


def make_runner(tmp_path, traces: list[Trace] | None = None):
    trace_collector = TraceCollector(tmp_path / "traces.jsonl")
    for trace in traces or []:
        trace_collector.save(trace)
    report_collector = EvaluationReportCollector(tmp_path / "reports.jsonl")
    runner = OfflineEvaluationRunner(
        trace_collector,
        RuleBasedEvaluator(),
        report_collector,
    )
    return runner, trace_collector, report_collector


def test_runner_reads_evaluates_and_persists_multiple_traces(tmp_path) -> None:
    traces = [make_trace("trc_first"), make_trace("trc_second")]
    runner, _, report_collector = make_runner(tmp_path, traces)

    report = runner.run()

    assert isinstance(report, EvaluationReport)
    assert report.total_count == 2
    assert tuple(result.trace_id for result in report.results) == (
        "trc_first",
        "trc_second",
    )
    assert report_collector.get_report(report.report_id) == report


def test_empty_trace_history_generates_and_persists_empty_report(tmp_path) -> None:
    runner, _, report_collector = make_runner(tmp_path)

    report = runner.run()

    assert report.total_count == 0
    assert report.pass_rate is None
    assert report_collector.list_reports() == [report]


def test_mixed_trace_statistics_are_correct(tmp_path) -> None:
    traces = [
        make_trace("trc_passed"),
        make_trace("trc_no_retrieval", retrieval_chunks=[], retrieval_scores=[]),
        make_trace("trc_slow", latency_ms=40000.0),
    ]
    runner, _, _ = make_runner(tmp_path, traces)

    report = runner.run()

    assert report.passed_count == 1
    assert report.failed_count == 2
    assert report.pass_rate == pytest.approx(1 / 3)
    assert report.issue_counts[EvaluationIssueCode.NO_RETRIEVAL] == 1
    assert report.issue_counts[EvaluationIssueCode.HIGH_LATENCY] == 1
    assert report.failed_trace_ids == ("trc_no_retrieval", "trc_slow")


def test_runner_preserves_trace_and_result_order(tmp_path) -> None:
    traces = [make_trace("trc_3"), make_trace("trc_1"), make_trace("trc_2")]
    runner, _, _ = make_runner(tmp_path, traces)

    report = runner.run()

    assert tuple(result.trace_id for result in report.results) == (
        "trc_3",
        "trc_1",
        "trc_2",
    )


def test_repeated_runs_create_distinct_appended_reports(tmp_path) -> None:
    runner, _, report_collector = make_runner(tmp_path, [make_trace("trc_repeat")])

    first = runner.run()
    second = runner.run()

    assert first.report_id != second.report_id
    assert report_collector.list_reports() == [first, second]


def test_trace_read_error_propagates_unchanged(tmp_path) -> None:
    trace_path = tmp_path / "traces.jsonl"
    trace_path.write_text("not-json\n", encoding="utf-8")
    runner = OfflineEvaluationRunner(
        TraceCollector(trace_path),
        RuleBasedEvaluator(),
        EvaluationReportCollector(tmp_path / "reports.jsonl"),
    )

    with pytest.raises(TraceStorageError, match="line 1"):
        runner.run()


def test_report_save_error_propagates_unchanged(tmp_path, monkeypatch) -> None:
    runner, _, report_collector = make_runner(tmp_path, [make_trace("trc_save")])

    def fail_save(report: EvaluationReport) -> EvaluationReport:
        raise EvaluationReportStorageError("storage unavailable")

    monkeypatch.setattr(report_collector, "save", fail_save)

    with pytest.raises(EvaluationReportStorageError, match="storage unavailable"):
        runner.run()


def test_runner_does_not_modify_original_traces(tmp_path) -> None:
    traces = [
        make_trace("trc_original_1"),
        make_trace("trc_original_2", retrieval_scores=[0.1]),
    ]
    before = [trace.model_dump(mode="json") for trace in traces]
    runner, _, _ = make_runner(tmp_path, traces)

    runner.run()

    assert [trace.model_dump(mode="json") for trace in traces] == before


def test_runner_delegates_batch_rules_to_evaluate_many(tmp_path, monkeypatch) -> None:
    evaluator = RuleBasedEvaluator()
    trace_collector = TraceCollector(tmp_path / "traces.jsonl")
    trace_collector.save(make_trace("trc_delegate"))
    report_collector = EvaluationReportCollector(tmp_path / "reports.jsonl")
    original_evaluate_many = RuleBasedEvaluator.evaluate_many
    received_trace_ids: list[tuple[str, ...]] = []

    def spy_evaluate_many(self, traces):
        trace_tuple = tuple(traces)
        received_trace_ids.append(tuple(trace.trace_id for trace in trace_tuple))
        return original_evaluate_many(self, trace_tuple)

    monkeypatch.setattr(RuleBasedEvaluator, "evaluate_many", spy_evaluate_many)
    runner = OfflineEvaluationRunner(trace_collector, evaluator, report_collector)

    runner.run()

    assert received_trace_ids == [("trc_delegate",)]
