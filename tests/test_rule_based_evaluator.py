"""Tests for deterministic Trace evaluation rules."""

from __future__ import annotations

import pytest

from ragops.evaluation import EvaluationIssueCode, RuleBasedEvaluator
from ragops.schemas import Trace


def make_trace(**overrides: object) -> Trace:
    data: dict[str, object] = {
        "trace_id": "trc_rule_test",
        "query": "退款多久到账？",
        "retrieval_chunks": ["退款通常在三个工作日内到账。"],
        "retrieval_scores": [0.91],
        "prompt_version": "qa_v1",
        "model": "example-model",
        "answer": "通常三个工作日内到账。",
        "latency_ms": 842.0,
        "feedback": None,
    }
    data.update(overrides)
    return Trace.model_validate(data)


def test_normal_trace_passes() -> None:
    result = RuleBasedEvaluator().evaluate(make_trace())

    assert result.passed is True
    assert result.issues == ()
    assert result.retrieval_count == 1
    assert result.max_retrieval_score == 0.91


def test_trace_without_retrieval_reports_only_no_retrieval() -> None:
    trace = make_trace(retrieval_chunks=[], retrieval_scores=[])

    result = RuleBasedEvaluator().evaluate(trace)

    assert result.passed is False
    assert result.issues == (EvaluationIssueCode.NO_RETRIEVAL,)
    assert result.retrieval_count == 0
    assert result.max_retrieval_score is None


def test_low_retrieval_score_fails() -> None:
    trace = make_trace(retrieval_scores=[0.24])

    result = RuleBasedEvaluator().evaluate(trace)

    assert result.issues == (EvaluationIssueCode.LOW_RETRIEVAL_SCORE,)


def test_high_latency_fails() -> None:
    trace = make_trace(latency_ms=30000.1)

    result = RuleBasedEvaluator().evaluate(trace)

    assert result.issues == (EvaluationIssueCode.HIGH_LATENCY,)


def test_low_score_and_high_latency_have_stable_issue_order() -> None:
    trace = make_trace(retrieval_scores=[0.1], latency_ms=40000.0)

    result = RuleBasedEvaluator().evaluate(trace)

    assert result.issues == (
        EvaluationIssueCode.LOW_RETRIEVAL_SCORE,
        EvaluationIssueCode.HIGH_LATENCY,
    )


def test_retrieval_score_equal_to_threshold_passes_rule() -> None:
    result = RuleBasedEvaluator().evaluate(make_trace(retrieval_scores=[0.25]))

    assert result.passed is True


def test_latency_equal_to_threshold_passes_rule() -> None:
    result = RuleBasedEvaluator().evaluate(make_trace(latency_ms=30000.0))

    assert result.passed is True


def test_custom_thresholds_are_applied_and_recorded() -> None:
    evaluator = RuleBasedEvaluator(
        min_retrieval_score=0.8,
        max_latency_ms=500.0,
    )
    trace = make_trace(retrieval_scores=[0.7, 0.75], retrieval_chunks=["a", "b"])

    result = evaluator.evaluate(trace)

    assert result.issues == (
        EvaluationIssueCode.LOW_RETRIEVAL_SCORE,
        EvaluationIssueCode.HIGH_LATENCY,
    )
    assert result.max_retrieval_score == 0.75
    assert result.min_retrieval_score == 0.8
    assert result.max_latency_ms == 500.0


@pytest.mark.parametrize(
    "value",
    [True, False, "0.25", float("nan"), float("inf"), float("-inf")],
)
def test_min_retrieval_score_rejects_invalid_values(value: object) -> None:
    with pytest.raises((TypeError, ValueError), match="finite number"):
        RuleBasedEvaluator(min_retrieval_score=value)


@pytest.mark.parametrize(
    "value",
    [True, False, "30000", float("nan"), float("inf"), float("-inf")],
)
def test_max_latency_rejects_non_finite_or_non_numeric_values(value: object) -> None:
    with pytest.raises((TypeError, ValueError), match="finite number"):
        RuleBasedEvaluator(max_latency_ms=value)


def test_max_latency_rejects_negative_value() -> None:
    with pytest.raises(ValueError, match="greater than or equal to zero"):
        RuleBasedEvaluator(max_latency_ms=-0.1)


def test_evaluation_does_not_modify_trace() -> None:
    trace = make_trace(retrieval_scores=[0.8, 0.7], retrieval_chunks=["a", "b"])
    before = trace.model_dump(mode="json")

    result = RuleBasedEvaluator().evaluate(trace)

    assert trace.model_dump(mode="json") == before
    assert result.trace_id == trace.trace_id
    assert result.latency_ms == trace.latency_ms
