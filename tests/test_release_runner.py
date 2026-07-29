"""Tests for release gate orchestration."""

from __future__ import annotations

import pytest

from ragops.evaluation import EvaluationReport
from ragops.experiments import ExperimentComparator
from ragops.release import ReleaseDecisionCollector, ReleaseGate, ReleaseGateRunner
from ragops.schemas import ReleasePolicy


def make_comparison():
    empty = EvaluationReport.from_results([])
    return ExperimentComparator().compare(empty, empty)


def test_runner_decides_persists_and_returns_decision(tmp_path) -> None:
    comparison = make_comparison()
    collector = ReleaseDecisionCollector(tmp_path / "decisions.jsonl")
    runner = ReleaseGateRunner(ReleaseGate(), collector)

    decision = runner.run(comparison)

    assert collector.list_decisions() == [decision]
    assert decision.comparison_id == comparison.comparison_id
    assert decision.comparison == comparison


def test_runner_uses_custom_policy(tmp_path) -> None:
    policy = ReleasePolicy(max_regressed_trace_count=3)
    runner = ReleaseGateRunner(
        ReleaseGate(),
        ReleaseDecisionCollector(tmp_path / "decisions.jsonl"),
    )

    decision = runner.run(make_comparison(), policy)

    assert decision.policy == policy


def test_multiple_runs_generate_and_append_distinct_decisions(tmp_path) -> None:
    collector = ReleaseDecisionCollector(tmp_path / "decisions.jsonl")
    runner = ReleaseGateRunner(ReleaseGate(), collector)
    comparison = make_comparison()

    first = runner.run(comparison)
    second = runner.run(comparison)

    assert first.decision_id != second.decision_id
    assert collector.list_decisions() == [first, second]


def test_gate_exception_propagates_unchanged(tmp_path) -> None:
    error = RuntimeError("gate failed")

    class FailingGate:
        def decide(self, comparison, policy=None):
            raise error

    runner = ReleaseGateRunner(
        FailingGate(),
        ReleaseDecisionCollector(tmp_path / "decisions.jsonl"),
    )

    with pytest.raises(RuntimeError) as caught:
        runner.run(make_comparison())
    assert caught.value is error


def test_collector_exception_propagates_unchanged() -> None:
    error = RuntimeError("save failed")

    class FailingCollector:
        def save(self, decision):
            raise error

    runner = ReleaseGateRunner(ReleaseGate(), FailingCollector())

    with pytest.raises(RuntimeError) as caught:
        runner.run(make_comparison())
    assert caught.value is error


def test_runner_does_not_modify_comparison_or_policy(tmp_path) -> None:
    comparison = make_comparison()
    policy = ReleasePolicy()
    comparison_before = comparison.model_dump(mode="json")
    policy_before = policy.model_dump(mode="json")
    runner = ReleaseGateRunner(
        ReleaseGate(),
        ReleaseDecisionCollector(tmp_path / "decisions.jsonl"),
    )

    runner.run(comparison, policy)

    assert comparison.model_dump(mode="json") == comparison_before
    assert policy.model_dump(mode="json") == policy_before
