"""Tests for the immutable evaluation report comparison contract."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from ragops.evaluation import EvaluationIssueCode, EvaluationReport, EvaluationResult
from ragops.schemas import ExperimentComparison


def make_result(
    trace_id: str,
    *,
    passed: bool,
    issues: tuple[EvaluationIssueCode, ...] = (),
) -> EvaluationResult:
    no_retrieval = EvaluationIssueCode.NO_RETRIEVAL in issues
    return EvaluationResult(
        trace_id=trace_id,
        passed=passed,
        issues=issues,
        retrieval_count=0 if no_retrieval else 1,
        max_retrieval_score=None if no_retrieval else 0.1,
        latency_ms=(
            40000.0 if EvaluationIssueCode.HIGH_LATENCY in issues else 842.0
        ),
        min_retrieval_score=0.25,
        max_latency_ms=30000.0,
    )


def make_report(
    specifications: list[
        tuple[str, bool, tuple[EvaluationIssueCode, ...]]
    ],
) -> EvaluationReport:
    return EvaluationReport.from_results(
        make_result(trace_id, passed=passed, issues=issues)
        for trace_id, passed, issues in specifications
    )


def make_mixed_reports() -> tuple[EvaluationReport, EvaluationReport]:
    baseline = make_report(
        [
            ("trc_improved", False, (EvaluationIssueCode.LOW_RETRIEVAL_SCORE,)),
            ("trc_unchanged_passed", True, ()),
            ("trc_unchanged_failed", False, (EvaluationIssueCode.HIGH_LATENCY,)),
            ("trc_regressed", True, ()),
        ]
    )
    candidate = make_report(
        [
            ("trc_regressed", False, (EvaluationIssueCode.HIGH_LATENCY,)),
            ("trc_unchanged_failed", False, (EvaluationIssueCode.HIGH_LATENCY,)),
            ("trc_improved", True, ()),
            ("trc_unchanged_passed", True, ()),
        ]
    )
    return baseline, candidate


def test_empty_reports_produce_legal_empty_comparison() -> None:
    empty = make_report([])

    comparison = ExperimentComparison.from_reports(empty, empty)

    assert comparison.trace_ids == ()
    assert comparison.total_count == 0
    assert comparison.baseline_pass_rate is None
    assert comparison.candidate_pass_rate is None
    assert comparison.pass_rate_delta is None
    assert comparison.improved_trace_ids == ()
    assert comparison.regressed_trace_ids == ()
    assert comparison.unchanged_passed_trace_ids == ()
    assert comparison.unchanged_failed_trace_ids == ()


def test_comparison_generates_identity_and_utc_timestamp() -> None:
    report = make_report([("trc_passed", True, ())])

    comparison = ExperimentComparison.from_reports(report, report)

    assert comparison.comparison_id.startswith("comparison_")
    assert comparison.created_at.tzinfo == timezone.utc
    assert comparison.created_at.utcoffset() == timedelta(0)


def test_all_unchanged_passed_or_failed_are_grouped() -> None:
    passed = make_report([("trc_passed", True, ())])
    failed = make_report(
        [("trc_failed", False, (EvaluationIssueCode.NO_RETRIEVAL,))]
    )

    passed_comparison = ExperimentComparison.from_reports(passed, passed)
    failed_comparison = ExperimentComparison.from_reports(failed, failed)

    assert passed_comparison.unchanged_passed_trace_ids == ("trc_passed",)
    assert failed_comparison.unchanged_failed_trace_ids == ("trc_failed",)


def test_improved_regressed_and_unchanged_groups_use_baseline_order() -> None:
    baseline, candidate = make_mixed_reports()

    comparison = ExperimentComparison.from_reports(baseline, candidate)

    assert comparison.trace_ids == (
        "trc_improved",
        "trc_unchanged_passed",
        "trc_unchanged_failed",
        "trc_regressed",
    )
    assert comparison.improved_trace_ids == ("trc_improved",)
    assert comparison.regressed_trace_ids == ("trc_regressed",)
    assert comparison.unchanged_passed_trace_ids == ("trc_unchanged_passed",)
    assert comparison.unchanged_failed_trace_ids == ("trc_unchanged_failed",)


def test_pass_rate_delta_is_candidate_minus_baseline() -> None:
    baseline = make_report(
        [("trc_a", False, (EvaluationIssueCode.NO_RETRIEVAL,)), ("trc_b", True, ())]
    )
    candidate = make_report([("trc_b", True, ()), ("trc_a", True, ())])

    comparison = ExperimentComparison.from_reports(baseline, candidate)

    assert comparison.baseline_pass_rate == 0.5
    assert comparison.candidate_pass_rate == 1.0
    assert comparison.pass_rate_delta == 0.5


def test_issue_count_deltas_include_decreases_increases_and_zero() -> None:
    baseline, candidate = make_mixed_reports()

    comparison = ExperimentComparison.from_reports(baseline, candidate)

    assert comparison.issue_count_deltas == {
        EvaluationIssueCode.NO_RETRIEVAL: 0,
        EvaluationIssueCode.LOW_RETRIEVAL_SCORE: -1,
        EvaluationIssueCode.HIGH_LATENCY: 1,
    }


def test_four_status_groups_are_disjoint_and_cover_all_traces() -> None:
    baseline, candidate = make_mixed_reports()
    comparison = ExperimentComparison.from_reports(baseline, candidate)
    groups = (
        comparison.improved_trace_ids,
        comparison.regressed_trace_ids,
        comparison.unchanged_passed_trace_ids,
        comparison.unchanged_failed_trace_ids,
    )

    flattened = [trace_id for group in groups for trace_id in group]

    assert len(flattened) == len(set(flattened))
    assert set(flattened) == set(comparison.trace_ids)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("trace_ids", ("trc_wrong",)),
        ("total_count", 99),
        ("baseline_passed_count", 99),
        ("candidate_passed_count", 99),
        ("baseline_pass_rate", 0.25),
        ("candidate_pass_rate", 0.25),
        ("pass_rate_delta", 0.25),
        ("improved_trace_ids", ()),
        ("regressed_trace_ids", ()),
        ("unchanged_passed_trace_ids", ()),
        ("unchanged_failed_trace_ids", ()),
        (
            "issue_count_deltas",
            {
                EvaluationIssueCode.NO_RETRIEVAL: 0,
                EvaluationIssueCode.LOW_RETRIEVAL_SCORE: 0,
                EvaluationIssueCode.HIGH_LATENCY: 0,
            },
        ),
    ],
)
def test_schema_rejects_inconsistent_statistics(
    field_name: str,
    invalid_value: object,
) -> None:
    baseline, candidate = make_mixed_reports()
    comparison = ExperimentComparison.from_reports(baseline, candidate)
    data = comparison.model_dump(mode="python")
    data[field_name] = invalid_value

    with pytest.raises(ValidationError, match=field_name):
        ExperimentComparison.model_validate(data)


def test_comparison_is_frozen_and_issue_deltas_are_immutable() -> None:
    baseline, candidate = make_mixed_reports()
    comparison = ExperimentComparison.from_reports(baseline, candidate)

    with pytest.raises(ValidationError, match="frozen"):
        comparison.total_count = 99
    with pytest.raises(TypeError):
        comparison.issue_count_deltas[EvaluationIssueCode.NO_RETRIEVAL] = 1


def test_comparison_forbids_extra_fields() -> None:
    baseline, candidate = make_mixed_reports()
    comparison = ExperimentComparison.from_reports(baseline, candidate)
    data = comparison.model_dump(mode="python")
    data["unexpected"] = "value"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ExperimentComparison.model_validate(data)


def test_created_at_requires_timezone_and_normalizes_to_utc() -> None:
    baseline, candidate = make_mixed_reports()
    comparison = ExperimentComparison.from_reports(baseline, candidate)
    data = comparison.model_dump(mode="python")
    data["created_at"] = datetime(2026, 7, 29, 12, 0)

    with pytest.raises(ValidationError, match="timezone information"):
        ExperimentComparison.model_validate(data)

    data["created_at"] = datetime(
        2026,
        7,
        29,
        12,
        0,
        tzinfo=timezone(timedelta(hours=8)),
    )
    normalized = ExperimentComparison.model_validate(data)
    assert normalized.created_at == datetime(2026, 7, 29, 4, 0, tzinfo=timezone.utc)
