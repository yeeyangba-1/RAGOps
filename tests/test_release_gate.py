"""Tests for deterministic release gate rules."""

from __future__ import annotations

from collections.abc import Iterable

from ragops.evaluation import EvaluationIssueCode, EvaluationReport, EvaluationResult
from ragops.evaluation.rule_based import RuleBasedEvaluator
from ragops.experiments import ExperimentComparator
from ragops.release import ReleaseGate
from ragops.schemas import (
    ExperimentComparison,
    ReleaseDecisionReason,
    ReleasePolicy,
)


IssueTuple = tuple[EvaluationIssueCode, ...]
Specification = tuple[str, IssueTuple]


def make_result(trace_id: str, issues: IssueTuple = ()) -> EvaluationResult:
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


def make_report(specifications: Iterable[Specification]) -> EvaluationReport:
    return EvaluationReport.from_results(
        make_result(trace_id, issues) for trace_id, issues in specifications
    )


def compare(
    baseline: list[Specification],
    candidate: list[Specification],
) -> ExperimentComparison:
    return ExperimentComparator().compare(
        make_report(baseline),
        make_report(candidate),
    )


def test_default_policy_approves_when_all_conditions_pass() -> None:
    comparison = compare([("trc_a", ())], [("trc_a", ())])

    decision = ReleaseGate().decide(comparison)

    assert decision.approved is True
    assert decision.reasons == ()


def test_policy_threshold_boundaries_are_inclusive() -> None:
    low = (EvaluationIssueCode.LOW_RETRIEVAL_SCORE,)
    baseline = [(f"trc_{index}", low if index == 0 else ()) for index in range(5)]
    comparison = compare(baseline, baseline)

    decision = ReleaseGate().decide(comparison)

    assert decision.candidate_pass_rate == 0.8
    assert decision.pass_rate_delta == 0.0
    assert decision.approved is True


def test_empty_comparison_has_only_empty_reason() -> None:
    comparison = compare([], [])

    decision = ReleaseGate().decide(comparison)

    assert decision.approved is False
    assert decision.reasons == (ReleaseDecisionReason.EMPTY_EVALUATION,)


def test_candidate_pass_rate_below_minimum_blocks_release() -> None:
    low = (EvaluationIssueCode.LOW_RETRIEVAL_SCORE,)
    baseline = [(f"trc_{index}", ()) for index in range(5)]
    candidate = [(f"trc_{index}", low if index < 2 else ()) for index in range(5)]
    policy = ReleasePolicy(
        min_candidate_pass_rate=0.8,
        min_pass_rate_delta=-1,
        max_regressed_trace_count=2,
        max_total_issue_increase=2,
    )

    decision = ReleaseGate().decide(compare(baseline, candidate), policy)

    assert decision.reasons == (
        ReleaseDecisionReason.CANDIDATE_PASS_RATE_BELOW_MINIMUM,
    )


def test_pass_rate_delta_below_minimum_blocks_release() -> None:
    low = (EvaluationIssueCode.LOW_RETRIEVAL_SCORE,)
    baseline = [(f"trc_{index}", ()) for index in range(5)]
    candidate = [(f"trc_{index}", low if index == 0 else ()) for index in range(5)]
    policy = ReleasePolicy(
        min_candidate_pass_rate=0.8,
        min_pass_rate_delta=0,
        max_regressed_trace_count=1,
        max_total_issue_increase=1,
    )

    decision = ReleaseGate().decide(compare(baseline, candidate), policy)

    assert decision.reasons == (
        ReleaseDecisionReason.PASS_RATE_DELTA_BELOW_MINIMUM,
    )


def test_regression_count_above_maximum_blocks_release() -> None:
    low = (EvaluationIssueCode.LOW_RETRIEVAL_SCORE,)
    comparison = compare(
        [("trc_a", ()), ("trc_b", low)],
        [("trc_a", low), ("trc_b", ())],
    )
    policy = ReleasePolicy(
        min_candidate_pass_rate=0.5,
        min_pass_rate_delta=0,
        max_regressed_trace_count=0,
        max_total_issue_increase=0,
    )

    decision = ReleaseGate().decide(comparison, policy)

    assert decision.reasons == (ReleaseDecisionReason.TOO_MANY_REGRESSIONS,)


def test_total_issue_increase_above_maximum_blocks_release() -> None:
    no_retrieval = (EvaluationIssueCode.NO_RETRIEVAL,)
    high_latency = (EvaluationIssueCode.HIGH_LATENCY,)
    comparison = compare(
        [("trc_a", no_retrieval), ("trc_b", ())],
        [("trc_a", high_latency), ("trc_b", ())],
    )
    policy = ReleasePolicy(min_candidate_pass_rate=0.5)

    decision = ReleaseGate().decide(comparison, policy)

    assert decision.total_issue_increase == 1
    assert decision.reasons == (
        ReleaseDecisionReason.TOTAL_ISSUE_INCREASE_EXCEEDED,
    )


def test_issue_decreases_do_not_offset_a_new_issue() -> None:
    baseline_issues = (
        EvaluationIssueCode.NO_RETRIEVAL,
        EvaluationIssueCode.LOW_RETRIEVAL_SCORE,
    )
    candidate_issues = (EvaluationIssueCode.HIGH_LATENCY,)
    comparison = compare(
        [("trc_a", baseline_issues)],
        [("trc_a", candidate_issues)],
    )

    decision = ReleaseGate().decide(
        comparison,
        ReleasePolicy(min_candidate_pass_rate=0),
    )

    assert sum(comparison.issue_count_deltas.values()) == -1
    assert decision.total_issue_increase == 1
    assert decision.reasons == (
        ReleaseDecisionReason.TOTAL_ISSUE_INCREASE_EXCEEDED,
    )


def test_multiple_reasons_use_stable_check_order() -> None:
    low = (EvaluationIssueCode.LOW_RETRIEVAL_SCORE,)
    comparison = compare(
        [("trc_a", ()), ("trc_b", ())],
        [("trc_a", low), ("trc_b", low)],
    )

    decision = ReleaseGate().decide(comparison)

    assert decision.reasons == (
        ReleaseDecisionReason.CANDIDATE_PASS_RATE_BELOW_MINIMUM,
        ReleaseDecisionReason.PASS_RATE_DELTA_BELOW_MINIMUM,
        ReleaseDecisionReason.TOO_MANY_REGRESSIONS,
        ReleaseDecisionReason.TOTAL_ISSUE_INCREASE_EXCEEDED,
    )


def test_custom_policy_can_approve_the_same_candidate() -> None:
    low = (EvaluationIssueCode.LOW_RETRIEVAL_SCORE,)
    comparison = compare(
        [("trc_a", ()), ("trc_b", ())],
        [("trc_a", low), ("trc_b", ())],
    )
    policy = ReleasePolicy(
        min_candidate_pass_rate=0.5,
        min_pass_rate_delta=-0.5,
        max_regressed_trace_count=1,
        max_total_issue_increase=1,
    )

    decision = ReleaseGate().decide(comparison, policy)

    assert decision.policy == policy
    assert decision.approved is True


def test_gate_does_not_rerun_evaluation_or_comparison(monkeypatch) -> None:
    comparison = compare([("trc_a", ())], [("trc_a", ())])

    def fail(*args, **kwargs):
        raise AssertionError("upstream processing must not run")

    monkeypatch.setattr(RuleBasedEvaluator, "evaluate_many", fail)
    monkeypatch.setattr(ExperimentComparator, "compare", fail)

    assert ReleaseGate().decide(comparison).approved is True


def test_gate_does_not_modify_comparison_or_policy() -> None:
    comparison = compare([("trc_a", ())], [("trc_a", ())])
    policy = ReleasePolicy()
    comparison_before = comparison.model_dump(mode="json")
    policy_before = policy.model_dump(mode="json")

    ReleaseGate().decide(comparison, policy)

    assert comparison.model_dump(mode="json") == comparison_before
    assert policy.model_dump(mode="json") == policy_before
