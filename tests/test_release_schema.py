"""Tests for release policy and decision schemas."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from ragops.evaluation import EvaluationIssueCode, EvaluationReport, EvaluationResult
from ragops.schemas import (
    ExperimentComparison,
    ReleaseDecision,
    ReleaseDecisionReason,
    ReleasePolicy,
)


def make_result(
    trace_id: str,
    issues: tuple[EvaluationIssueCode, ...] = (),
) -> EvaluationResult:
    no_retrieval = EvaluationIssueCode.NO_RETRIEVAL in issues
    return EvaluationResult(
        trace_id=trace_id,
        passed=not issues,
        issues=issues,
        retrieval_count=0 if no_retrieval else 1,
        max_retrieval_score=None if no_retrieval else 0.9,
        latency_ms=40001.0 if EvaluationIssueCode.HIGH_LATENCY in issues else 100.0,
        min_retrieval_score=0.25,
        max_latency_ms=30000.0,
    )


def make_report(
    specifications: list[tuple[str, tuple[EvaluationIssueCode, ...]]],
) -> EvaluationReport:
    return EvaluationReport.from_results(
        make_result(trace_id, issues) for trace_id, issues in specifications
    )


def make_comparison() -> ExperimentComparison:
    report = make_report([("trc_passed", ())])
    return ExperimentComparison.from_reports(report, report)


def test_default_policy_values_and_frozen_contract() -> None:
    policy = ReleasePolicy()

    assert policy.min_candidate_pass_rate == 0.8
    assert policy.min_pass_rate_delta == 0.0
    assert policy.max_regressed_trace_count == 0
    assert policy.max_total_issue_increase == 0
    with pytest.raises(ValidationError, match="frozen"):
        policy.min_candidate_pass_rate = 0.9


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("min_candidate_pass_rate", True),
        ("min_candidate_pass_rate", float("nan")),
        ("min_candidate_pass_rate", float("inf")),
        ("min_candidate_pass_rate", -0.1),
        ("min_candidate_pass_rate", 1.1),
        ("min_pass_rate_delta", False),
        ("min_pass_rate_delta", float("-inf")),
        ("min_pass_rate_delta", -1.1),
        ("min_pass_rate_delta", 1.1),
        ("max_regressed_trace_count", True),
        ("max_regressed_trace_count", -1),
        ("max_regressed_trace_count", 1.5),
        ("max_total_issue_increase", False),
        ("max_total_issue_increase", -1),
        ("max_total_issue_increase", 1.5),
    ],
)
def test_policy_rejects_invalid_thresholds(
    field_name: str,
    invalid_value: object,
) -> None:
    with pytest.raises(ValidationError):
        ReleasePolicy(**{field_name: invalid_value})


def test_policy_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ReleasePolicy(unexpected=True)


def test_decision_identity_source_ids_and_utc_timestamp() -> None:
    comparison = make_comparison()

    decision = ReleaseDecision.from_comparison(comparison, ReleasePolicy())

    assert decision.decision_id.startswith("decision_")
    assert decision.comparison_id == comparison.comparison_id
    assert decision.baseline_report_id == comparison.baseline_report.report_id
    assert decision.candidate_report_id == comparison.candidate_report.report_id
    assert decision.created_at.tzinfo == timezone.utc


def test_empty_comparison_is_rejected_for_only_empty_reason() -> None:
    empty = make_report([])
    comparison = ExperimentComparison.from_reports(empty, empty)

    decision = ReleaseDecision.from_comparison(comparison, ReleasePolicy())

    assert decision.approved is False
    assert decision.reasons == (ReleaseDecisionReason.EMPTY_EVALUATION,)
    assert decision.candidate_pass_rate is None
    assert decision.pass_rate_delta is None
    assert decision.regressed_trace_count == 0
    assert decision.total_issue_increase == 0


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("approved", False),
        ("reasons", (ReleaseDecisionReason.TOO_MANY_REGRESSIONS,)),
        ("candidate_pass_rate", 0.0),
        ("pass_rate_delta", None),
        ("regressed_trace_count", 1),
        ("total_issue_increase", 1),
    ],
)
def test_decision_rejects_inconsistent_external_statistics(
    field_name: str,
    invalid_value: object,
) -> None:
    decision = ReleaseDecision.from_comparison(make_comparison(), ReleasePolicy())
    data = decision.model_dump(mode="python")
    data[field_name] = invalid_value

    with pytest.raises(ValidationError):
        ReleaseDecision.model_validate(data)


def test_empty_decision_rejects_nonzero_derived_counts() -> None:
    empty = make_report([])
    comparison = ExperimentComparison.from_reports(empty, empty)
    decision = ReleaseDecision.from_comparison(comparison, ReleasePolicy())
    data = decision.model_dump(mode="python")
    data["regressed_trace_count"] = 1

    with pytest.raises(ValidationError, match="zero derived counts"):
        ReleaseDecision.model_validate(data)


def test_decision_is_frozen_and_forbids_extra_fields() -> None:
    decision = ReleaseDecision.from_comparison(make_comparison(), ReleasePolicy())

    with pytest.raises(ValidationError, match="frozen"):
        decision.approved = False

    data = decision.model_dump(mode="python")
    data["unexpected"] = "value"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ReleaseDecision.model_validate(data)


def test_decision_created_at_requires_timezone_and_normalizes_to_utc() -> None:
    decision = ReleaseDecision.from_comparison(make_comparison(), ReleasePolicy())
    data = decision.model_dump(mode="python")
    data["created_at"] = datetime(2026, 7, 29, 12, 0)

    with pytest.raises(ValidationError, match="timezone information"):
        ReleaseDecision.model_validate(data)

    data["created_at"] = datetime(
        2026,
        7,
        29,
        12,
        0,
        tzinfo=timezone(timedelta(hours=8)),
    )
    normalized = ReleaseDecision.model_validate(data)
    assert normalized.created_at == datetime(2026, 7, 29, 4, 0, tzinfo=timezone.utc)


def test_decision_json_uses_stable_reason_value() -> None:
    empty = make_report([])
    decision = ReleaseDecision.from_comparison(
        ExperimentComparison.from_reports(empty, empty),
        ReleasePolicy(),
    )

    assert '"empty_evaluation"' in decision.model_dump_json()
