"""Tests for the EvaluationResult contract."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from ragops.evaluation import EvaluationIssueCode, EvaluationReport, EvaluationResult


def make_result(**overrides: object) -> EvaluationResult:
    data: dict[str, object] = {
        "trace_id": "trc_example",
        "passed": True,
        "issues": [],
        "retrieval_count": 1,
        "max_retrieval_score": 0.91,
        "latency_ms": 842.0,
        "min_retrieval_score": 0.25,
        "max_latency_ms": 30000.0,
    }
    data.update(overrides)
    return EvaluationResult.model_validate(data)


def make_report(**overrides: object) -> EvaluationReport:
    results = (
        make_result(trace_id="trc_passed"),
        make_result(
            trace_id="trc_failed",
            passed=False,
            issues=[EvaluationIssueCode.HIGH_LATENCY],
        ),
    )
    data: dict[str, object] = {
        "results": results,
        "total_count": 2,
        "passed_count": 1,
        "failed_count": 1,
        "pass_rate": 0.5,
        "issue_counts": {
            EvaluationIssueCode.NO_RETRIEVAL: 0,
            EvaluationIssueCode.LOW_RETRIEVAL_SCORE: 0,
            EvaluationIssueCode.HIGH_LATENCY: 1,
        },
        "failed_trace_ids": ["trc_failed"],
    }
    data.update(overrides)
    return EvaluationReport.model_validate(data)


def test_evaluation_result_generates_identity_and_utc_timestamp() -> None:
    result = make_result()

    assert result.evaluation_id.startswith("eval_")
    assert result.created_at.tzinfo == timezone.utc
    assert result.created_at.utcoffset() == timedelta(0)
    assert result.evaluator == "rule_based_v1"


def test_issue_codes_serialize_as_stable_strings() -> None:
    result = make_result(
        passed=False,
        issues=[EvaluationIssueCode.LOW_RETRIEVAL_SCORE],
    )

    encoded = json.loads(result.model_dump_json())

    assert encoded["issues"] == ["low_retrieval_score"]


@pytest.mark.parametrize(
    ("passed", "issues", "message"),
    [
        (True, [EvaluationIssueCode.HIGH_LATENCY], "must not contain issues"),
        (False, [], "must contain at least one issue"),
    ],
)
def test_passed_and_issues_must_be_consistent(
    passed: bool,
    issues: list[EvaluationIssueCode],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        make_result(passed=passed, issues=issues)


@pytest.mark.parametrize(
    ("retrieval_count", "max_score", "message"),
    [
        (0, 0.1, "must be None"),
        (1, None, "is required"),
    ],
)
def test_retrieval_count_and_max_score_must_be_consistent(
    retrieval_count: int,
    max_score: float | None,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        make_result(
            retrieval_count=retrieval_count,
            max_retrieval_score=max_score,
        )


@pytest.mark.parametrize("non_finite", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize(
    "field_name",
    ["max_retrieval_score", "latency_ms", "min_retrieval_score", "max_latency_ms"],
)
def test_non_finite_numbers_are_rejected(field_name: str, non_finite: float) -> None:
    with pytest.raises(ValidationError, match="finite number"):
        make_result(**{field_name: non_finite})


def test_created_at_requires_timezone_and_is_normalized_to_utc() -> None:
    with pytest.raises(ValidationError, match="timezone information"):
        make_result(created_at=datetime(2026, 7, 28, 12, 0))

    offset = timezone(timedelta(hours=8))
    result = make_result(created_at=datetime(2026, 7, 28, 12, 0, tzinfo=offset))

    assert result.created_at == datetime(2026, 7, 28, 4, 0, tzinfo=timezone.utc)
    assert result.created_at.tzinfo == timezone.utc


def test_evaluation_result_is_frozen() -> None:
    result = make_result()

    with pytest.raises(ValidationError, match="frozen"):
        result.passed = False

    with pytest.raises(AttributeError):
        result.issues.append(EvaluationIssueCode.HIGH_LATENCY)


def test_evaluation_result_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        make_result(unexpected="value")


def test_evaluation_report_generates_identity_and_utc_timestamp() -> None:
    report = make_report()

    assert report.report_id.startswith("report_")
    assert report.created_at.tzinfo == timezone.utc
    assert report.evaluator == "rule_based_v1"


def test_evaluation_report_is_frozen() -> None:
    report = make_report()

    with pytest.raises(ValidationError, match="frozen"):
        report.total_count = 3

    with pytest.raises(TypeError):
        report.issue_counts[EvaluationIssueCode.HIGH_LATENCY] = 2


def test_evaluation_report_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        make_report(unexpected="value")


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"total_count": 3}, "total_count"),
        ({"passed_count": 2}, "passed_count"),
        ({"failed_count": 0}, "failed_count"),
        ({"pass_rate": 0.75}, "pass_rate"),
        (
            {
                "issue_counts": {
                    EvaluationIssueCode.NO_RETRIEVAL: 0,
                    EvaluationIssueCode.LOW_RETRIEVAL_SCORE: 1,
                    EvaluationIssueCode.HIGH_LATENCY: 1,
                }
            },
            "issue_counts",
        ),
        ({"failed_trace_ids": ["trc_wrong"]}, "failed_trace_ids"),
    ],
)
def test_evaluation_report_rejects_inconsistent_statistics(
    override: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        make_report(**override)


def test_evaluation_report_rejects_negative_issue_count() -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        make_report(
            issue_counts={
                EvaluationIssueCode.NO_RETRIEVAL: 0,
                EvaluationIssueCode.LOW_RETRIEVAL_SCORE: 0,
                EvaluationIssueCode.HIGH_LATENCY: -1,
            }
        )


def test_report_counts_duplicate_issue_only_once_per_result() -> None:
    result = make_result(
        passed=False,
        issues=[
            EvaluationIssueCode.HIGH_LATENCY,
            EvaluationIssueCode.HIGH_LATENCY,
        ],
    )

    report = EvaluationReport.from_results([result])

    assert report.issue_counts[EvaluationIssueCode.HIGH_LATENCY] == 1
