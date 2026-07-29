"""Tests for local JSONL release decision persistence."""

from __future__ import annotations

import json

import pytest

from ragops.evaluation import EvaluationReport
from ragops.experiments import ExperimentComparator
from ragops.release import (
    DuplicateReleaseDecisionError,
    ReleaseDecisionCollector,
    ReleaseDecisionStorageError,
    ReleaseGate,
)


def make_decision(*, comparison_id: str | None = None):
    empty = EvaluationReport.from_results([])
    comparison = ExperimentComparator().compare(empty, empty)
    if comparison_id is not None:
        data = comparison.model_dump(mode="python")
        data["comparison_id"] = comparison_id
        comparison = type(comparison).model_validate(data)
    return ReleaseGate().decide(comparison)


def test_missing_file_returns_empty_list(tmp_path) -> None:
    collector = ReleaseDecisionCollector(tmp_path / "missing" / "decisions.jsonl")

    assert collector.list_decisions() == []


def test_save_creates_parent_and_decision_can_be_reloaded(tmp_path) -> None:
    storage_path = tmp_path / "history" / "decisions.jsonl"
    collector = ReleaseDecisionCollector(storage_path)
    decision = make_decision()

    assert collector.save(decision) == decision
    assert storage_path.exists()
    reloaded = ReleaseDecisionCollector(storage_path).list_decisions()
    assert reloaded == [decision]
    assert reloaded[0].comparison == decision.comparison


def test_multiple_decisions_keep_append_order(tmp_path) -> None:
    collector = ReleaseDecisionCollector(tmp_path / "decisions.jsonl")
    first = make_decision()
    second = make_decision()

    collector.save(first)
    collector.save(second)

    assert collector.list_decisions() == [first, second]


def test_get_decision_returns_match_or_none(tmp_path) -> None:
    collector = ReleaseDecisionCollector(tmp_path / "decisions.jsonl")
    decision = make_decision()
    collector.save(decision)

    assert collector.get_decision(decision.decision_id) == decision
    assert collector.get_decision("decision_missing") is None


def test_duplicate_decision_id_is_rejected(tmp_path) -> None:
    collector = ReleaseDecisionCollector(tmp_path / "decisions.jsonl")
    decision = make_decision()
    collector.save(decision)

    with pytest.raises(DuplicateReleaseDecisionError, match=decision.decision_id):
        collector.save(decision)


def test_blank_lines_are_ignored(tmp_path) -> None:
    storage_path = tmp_path / "decisions.jsonl"
    decision = make_decision()
    storage_path.write_text(
        f"\n{decision.model_dump_json()}\n   \n",
        encoding="utf-8",
    )

    assert ReleaseDecisionCollector(storage_path).list_decisions() == [decision]


def test_invalid_json_reports_physical_line_number(tmp_path) -> None:
    storage_path = tmp_path / "decisions.jsonl"
    storage_path.write_text("\nnot-json\n", encoding="utf-8")

    with pytest.raises(ReleaseDecisionStorageError, match="line 2"):
        ReleaseDecisionCollector(storage_path).list_decisions()


def test_schema_invalid_json_reports_physical_line_number(tmp_path) -> None:
    storage_path = tmp_path / "decisions.jsonl"
    storage_path.write_text(
        '\n{"decision_id":"decision_incomplete"}\n',
        encoding="utf-8",
    )

    with pytest.raises(ReleaseDecisionStorageError, match="line 2"):
        ReleaseDecisionCollector(storage_path).list_decisions()


def test_tampered_decision_statistics_are_rejected_on_reload(tmp_path) -> None:
    storage_path = tmp_path / "decisions.jsonl"
    payload = json.loads(make_decision().model_dump_json())
    payload["candidate_pass_rate"] = 0.9
    storage_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ReleaseDecisionStorageError, match="line 1"):
        ReleaseDecisionCollector(storage_path).list_decisions()


def test_utf8_content_round_trips(tmp_path) -> None:
    storage_path = tmp_path / "decisions.jsonl"
    collector = ReleaseDecisionCollector(storage_path)
    decision = make_decision(comparison_id="comparison_退款问答")

    collector.save(decision)

    raw_record = json.loads(storage_path.read_text(encoding="utf-8"))
    assert raw_record["comparison_id"] == "comparison_退款问答"
    assert collector.list_decisions() == [decision]
