"""Tests for deterministic issue analysis schemas."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from ragops.evaluation import EvaluationIssueCode, EvaluationResult
from ragops.schemas import BadCase, IssueAnalysisReport, Trace


def make_trace(trace_id: str = "trc_bad_case") -> Trace:
    return Trace(
        trace_id=trace_id,
        query="退款多久到账？",
        retrieval_chunks=["退款通常在三个工作日内到账。"],
        retrieval_scores=[0.1],
        prompt_version="qa_v1",
        model="example-model",
        answer="通常三个工作日内到账。",
        latency_ms=40000.0,
    )


def make_evaluation(
    trace_id: str = "trc_bad_case",
    *,
    passed: bool = False,
    issues: tuple[EvaluationIssueCode, ...] = (
        EvaluationIssueCode.LOW_RETRIEVAL_SCORE,
    ),
) -> EvaluationResult:
    return EvaluationResult(
        trace_id=trace_id,
        passed=passed,
        issues=issues,
        retrieval_count=1,
        max_retrieval_score=0.1,
        latency_ms=40000.0,
        min_retrieval_score=0.25,
        max_latency_ms=30000.0,
    )


def make_bad_case(
    trace_id: str = "trc_bad_case",
    *,
    issues: tuple[EvaluationIssueCode, ...] = (
        EvaluationIssueCode.LOW_RETRIEVAL_SCORE,
    ),
) -> BadCase:
    return BadCase(
        trace=make_trace(trace_id),
        evaluation=make_evaluation(trace_id, issues=issues),
    )


def test_bad_case_contains_complete_trace_and_failed_evaluation() -> None:
    trace = make_trace()
    evaluation = make_evaluation()

    bad_case = BadCase(trace=trace, evaluation=evaluation)

    assert bad_case.trace is trace
    assert bad_case.evaluation is evaluation


def test_bad_case_rejects_passed_evaluation() -> None:
    with pytest.raises(ValidationError, match="failed evaluation"):
        BadCase(
            trace=make_trace(),
            evaluation=make_evaluation(passed=True, issues=()),
        )


def test_bad_case_rejects_mismatched_trace_id() -> None:
    with pytest.raises(ValidationError, match="trace_id must match"):
        BadCase(
            trace=make_trace("trc_source"),
            evaluation=make_evaluation("trc_evaluation"),
        )


def test_issue_analysis_report_generates_identity_and_utc_timestamp() -> None:
    report = IssueAnalysisReport.from_bad_cases("report_source", [make_bad_case()])

    assert report.analysis_id.startswith("analysis_")
    assert report.created_at.tzinfo == timezone.utc
    assert report.created_at.utcoffset() == timedelta(0)


def test_created_at_requires_timezone_and_is_normalized_to_utc() -> None:
    report = IssueAnalysisReport.from_bad_cases("report_source", [])
    data = report.model_dump(mode="python")
    data["created_at"] = datetime(2026, 7, 29, 12, 0)

    with pytest.raises(ValidationError, match="timezone information"):
        IssueAnalysisReport.model_validate(data)

    data["created_at"] = datetime(
        2026,
        7,
        29,
        12,
        0,
        tzinfo=timezone(timedelta(hours=8)),
    )
    normalized = IssueAnalysisReport.model_validate(data)
    assert normalized.created_at == datetime(2026, 7, 29, 4, 0, tzinfo=timezone.utc)


def test_empty_bad_case_report_contains_all_empty_issue_groups() -> None:
    report = IssueAnalysisReport.from_bad_cases("report_empty", [])

    assert report.bad_cases == ()
    assert report.total_bad_cases == 0
    assert report.issue_groups == {
        EvaluationIssueCode.NO_RETRIEVAL: (),
        EvaluationIssueCode.LOW_RETRIEVAL_SCORE: (),
        EvaluationIssueCode.HIGH_LATENCY: (),
    }


def test_one_bad_case_can_enter_multiple_issue_groups() -> None:
    bad_case = make_bad_case(
        issues=(
            EvaluationIssueCode.LOW_RETRIEVAL_SCORE,
            EvaluationIssueCode.HIGH_LATENCY,
        )
    )

    report = IssueAnalysisReport.from_bad_cases("report_multi", [bad_case])

    assert report.issue_groups[EvaluationIssueCode.LOW_RETRIEVAL_SCORE] == (
        "trc_bad_case",
    )
    assert report.issue_groups[EvaluationIssueCode.HIGH_LATENCY] == (
        "trc_bad_case",
    )


def test_issue_group_order_follows_bad_case_order() -> None:
    bad_cases = [
        make_bad_case("trc_second"),
        make_bad_case("trc_first"),
    ]

    report = IssueAnalysisReport.from_bad_cases("report_order", bad_cases)

    assert report.issue_groups[EvaluationIssueCode.LOW_RETRIEVAL_SCORE] == (
        "trc_second",
        "trc_first",
    )


def test_duplicate_issue_is_grouped_once_for_same_trace() -> None:
    bad_case = make_bad_case(
        issues=(
            EvaluationIssueCode.HIGH_LATENCY,
            EvaluationIssueCode.HIGH_LATENCY,
        )
    )

    report = IssueAnalysisReport.from_bad_cases("report_duplicate", [bad_case])

    assert report.issue_groups[EvaluationIssueCode.HIGH_LATENCY] == (
        "trc_bad_case",
    )


def test_report_rejects_incorrect_total_bad_cases() -> None:
    report = IssueAnalysisReport.from_bad_cases("report_source", [make_bad_case()])
    data = report.model_dump(mode="python")
    data["total_bad_cases"] = 2

    with pytest.raises(ValidationError, match="total_bad_cases"):
        IssueAnalysisReport.model_validate(data)


def test_report_rejects_incorrect_issue_groups() -> None:
    report = IssueAnalysisReport.from_bad_cases("report_source", [make_bad_case()])
    data = report.model_dump(mode="python")
    data["issue_groups"] = {
        EvaluationIssueCode.NO_RETRIEVAL: (),
        EvaluationIssueCode.LOW_RETRIEVAL_SCORE: (),
        EvaluationIssueCode.HIGH_LATENCY: (),
    }

    with pytest.raises(ValidationError, match="issue_groups"):
        IssueAnalysisReport.model_validate(data)


def test_analysis_schemas_are_frozen() -> None:
    bad_case = make_bad_case()
    report = IssueAnalysisReport.from_bad_cases("report_source", [bad_case])

    with pytest.raises(ValidationError, match="frozen"):
        bad_case.trace = make_trace("trc_other")
    with pytest.raises(ValidationError, match="frozen"):
        report.total_bad_cases = 2
    with pytest.raises(TypeError):
        report.issue_groups[EvaluationIssueCode.NO_RETRIEVAL] = ("trc_other",)


def test_analysis_schemas_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        BadCase.model_validate(
            {
                "trace": make_trace(),
                "evaluation": make_evaluation(),
                "unexpected": "value",
            }
        )

    report = IssueAnalysisReport.from_bad_cases("report_source", [])
    data = report.model_dump(mode="python")
    data["unexpected"] = "value"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        IssueAnalysisReport.model_validate(data)
