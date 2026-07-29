"""Tests for local JSONL evaluation report persistence."""

from __future__ import annotations

import json

import pytest

from ragops.evaluation import (
    DuplicateEvaluationReportError,
    EvaluationReportCollector,
    EvaluationReportStorageError,
    RuleBasedEvaluator,
)
from ragops.schemas import EvaluationReport, Trace


def make_trace(trace_id: str = "trc_report") -> Trace:
    return Trace(
        trace_id=trace_id,
        query="退款多久到账？",
        retrieval_chunks=["退款通常在三个工作日内到账。"],
        retrieval_scores=[0.91],
        prompt_version="qa_v1",
        model="example-model",
        answer="通常三个工作日内到账。",
        latency_ms=842.0,
    )


def make_report(
    *,
    report_id: str | None = None,
    trace_id: str = "trc_report",
) -> EvaluationReport:
    report = RuleBasedEvaluator().evaluate_many([make_trace(trace_id)])
    if report_id is None:
        return report
    return report.model_copy(update={"report_id": report_id})


def test_missing_file_returns_empty_list(tmp_path) -> None:
    collector = EvaluationReportCollector(tmp_path / "missing" / "reports.jsonl")

    assert collector.list_reports() == []


def test_save_creates_parent_and_report_can_be_reloaded(tmp_path) -> None:
    storage_path = tmp_path / "history" / "reports.jsonl"
    collector = EvaluationReportCollector(storage_path)
    report = make_report()

    assert collector.save(report) == report
    assert storage_path.exists()
    assert EvaluationReportCollector(storage_path).list_reports() == [report]


def test_multiple_reports_keep_append_order(tmp_path) -> None:
    collector = EvaluationReportCollector(tmp_path / "reports.jsonl")
    first = make_report(report_id="report_first", trace_id="trc_first")
    second = make_report(report_id="report_second", trace_id="trc_second")

    collector.save(first)
    collector.save(second)

    assert collector.list_reports() == [first, second]


def test_get_report_returns_match_or_none(tmp_path) -> None:
    collector = EvaluationReportCollector(tmp_path / "reports.jsonl")
    report = make_report(report_id="report_lookup")
    collector.save(report)

    assert collector.get_report("report_lookup") == report
    assert collector.get_report("report_missing") is None


def test_duplicate_report_id_is_rejected(tmp_path) -> None:
    collector = EvaluationReportCollector(tmp_path / "reports.jsonl")
    report = make_report(report_id="report_duplicate")
    collector.save(report)

    with pytest.raises(DuplicateEvaluationReportError, match="report_duplicate"):
        collector.save(report)


def test_blank_lines_are_ignored(tmp_path) -> None:
    storage_path = tmp_path / "reports.jsonl"
    report = make_report()
    storage_path.write_text(
        f"\n{report.model_dump_json()}\n   \n",
        encoding="utf-8",
    )

    assert EvaluationReportCollector(storage_path).list_reports() == [report]


def test_invalid_json_reports_physical_line_number(tmp_path) -> None:
    storage_path = tmp_path / "reports.jsonl"
    storage_path.write_text("\nnot-json\n", encoding="utf-8")

    with pytest.raises(EvaluationReportStorageError, match="line 2"):
        EvaluationReportCollector(storage_path).list_reports()


def test_schema_invalid_json_reports_physical_line_number(tmp_path) -> None:
    storage_path = tmp_path / "reports.jsonl"
    storage_path.write_text(
        '\n{"report_id":"report_incomplete"}\n',
        encoding="utf-8",
    )

    with pytest.raises(EvaluationReportStorageError, match="line 2"):
        EvaluationReportCollector(storage_path).list_reports()


def test_utf8_content_round_trips(tmp_path) -> None:
    storage_path = tmp_path / "reports.jsonl"
    collector = EvaluationReportCollector(storage_path)
    report = make_report(trace_id="trc_退款问答")

    collector.save(report)

    raw_record = json.loads(storage_path.read_text(encoding="utf-8"))
    assert raw_record["results"][0]["trace_id"] == "trc_退款问答"
    assert collector.list_reports() == [report]
