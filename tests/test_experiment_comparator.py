"""Tests for deterministic comparison of existing evaluation reports."""

from __future__ import annotations

import pytest

from ragops.evaluation import EvaluationIssueCode, EvaluationReport, EvaluationResult
from ragops.experiments import (
    DuplicateEvaluationTraceError,
    ExperimentComparator,
    IncomparableEvaluationReportsError,
)
from ragops.schemas import ExperimentComparison
from ragops.evaluation import RuleBasedEvaluator


def make_result(
    trace_id: str,
    *,
    passed: bool,
    issues: tuple[EvaluationIssueCode, ...] = (),
) -> EvaluationResult:
    return EvaluationResult(
        trace_id=trace_id,
        passed=passed,
        issues=issues,
        retrieval_count=1,
        max_retrieval_score=0.1,
        latency_ms=842.0,
        min_retrieval_score=0.25,
        max_latency_ms=30000.0,
    )


def make_report(results: list[EvaluationResult]) -> EvaluationReport:
    return EvaluationReport.from_results(results)


def test_comparator_handles_reordered_candidate_and_baseline_output_order() -> None:
    baseline = make_report(
        [
            make_result(
                "trc_a",
                passed=False,
                issues=(EvaluationIssueCode.LOW_RETRIEVAL_SCORE,),
            ),
            make_result("trc_b", passed=True),
        ]
    )
    candidate = make_report(
        [make_result("trc_b", passed=True), make_result("trc_a", passed=True)]
    )

    comparison = ExperimentComparator().compare(baseline, candidate)

    assert comparison.trace_ids == ("trc_a", "trc_b")
    assert comparison.improved_trace_ids == ("trc_a",)
    assert comparison.unchanged_passed_trace_ids == ("trc_b",)


def test_candidate_missing_baseline_trace_is_rejected() -> None:
    baseline = make_report(
        [make_result("trc_a", passed=True), make_result("trc_b", passed=True)]
    )
    candidate = make_report([make_result("trc_a", passed=True)])

    with pytest.raises(IncomparableEvaluationReportsError, match="same trace_ids"):
        ExperimentComparator().compare(baseline, candidate)


def test_candidate_extra_trace_is_rejected() -> None:
    baseline = make_report([make_result("trc_a", passed=True)])
    candidate = make_report(
        [make_result("trc_a", passed=True), make_result("trc_b", passed=True)]
    )

    with pytest.raises(IncomparableEvaluationReportsError, match="same trace_ids"):
        ExperimentComparator().compare(baseline, candidate)


def test_duplicate_baseline_trace_id_is_rejected() -> None:
    duplicate = make_report(
        [make_result("trc_duplicate", passed=True), make_result("trc_duplicate", passed=True)]
    )
    candidate = make_report([make_result("trc_duplicate", passed=True)])

    with pytest.raises(DuplicateEvaluationTraceError, match="baseline"):
        ExperimentComparator().compare(duplicate, candidate)


def test_duplicate_candidate_trace_id_is_rejected() -> None:
    baseline = make_report([make_result("trc_duplicate", passed=True)])
    duplicate = make_report(
        [make_result("trc_duplicate", passed=True), make_result("trc_duplicate", passed=True)]
    )

    with pytest.raises(DuplicateEvaluationTraceError, match="candidate"):
        ExperimentComparator().compare(baseline, duplicate)


def test_comparator_does_not_modify_input_reports() -> None:
    baseline = make_report(
        [
            make_result(
                "trc_a",
                passed=False,
                issues=(EvaluationIssueCode.LOW_RETRIEVAL_SCORE,),
            )
        ]
    )
    candidate = make_report([make_result("trc_a", passed=True)])
    baseline_before = baseline.model_dump(mode="json")
    candidate_before = candidate.model_dump(mode="json")

    ExperimentComparator().compare(baseline, candidate)

    assert baseline.model_dump(mode="json") == baseline_before
    assert candidate.model_dump(mode="json") == candidate_before


def test_comparator_does_not_execute_rule_based_evaluator(monkeypatch) -> None:
    report = make_report([make_result("trc_existing", passed=True)])

    def unexpected_call(*args, **kwargs):
        raise AssertionError("comparison must not execute evaluation rules")

    monkeypatch.setattr(RuleBasedEvaluator, "evaluate", unexpected_call)
    monkeypatch.setattr(RuleBasedEvaluator, "evaluate_many", unexpected_call)

    comparison = ExperimentComparator().compare(report, report)

    assert isinstance(comparison, ExperimentComparison)


def test_same_report_produces_only_unchanged_results() -> None:
    report = make_report(
        [
            make_result("trc_passed", passed=True),
            make_result(
                "trc_failed",
                passed=False,
                issues=(EvaluationIssueCode.HIGH_LATENCY,),
            ),
        ]
    )

    comparison = ExperimentComparator().compare(report, report)

    assert comparison.improved_trace_ids == ()
    assert comparison.regressed_trace_ids == ()
    assert comparison.unchanged_passed_trace_ids == ("trc_passed",)
    assert comparison.unchanged_failed_trace_ids == ("trc_failed",)
    assert all(delta == 0 for delta in comparison.issue_count_deltas.values())
