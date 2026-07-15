"""Tests for the MVP Trace schema and JSONL collector."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.schemas.trace import Trace
from src.tracing.collector import DuplicateTraceError, TraceCollector, TraceStorageError


def make_trace(**overrides: object) -> Trace:
    data: dict[str, object] = {
        "query": "退款审核通过后多久到账？",
        "retrieval_chunks": [
            "退款审核通过后通常在3到5个工作日内原路返回。",
            "对公付款退款可能需要人工处理。",
        ],
        "retrieval_scores": [0.91, 0.82],
        "prompt_version": "prompt_qa_v1",
        "model": "deepseek-chat",
        "answer": "通常3到5个工作日原路返回，对公付款可能需要人工处理。",
        "latency_ms": 842,
        "feedback": "回答清楚。",
    }
    data.update(overrides)
    return Trace.model_validate(data)


def test_trace_contains_required_mvp_fields() -> None:
    trace = make_trace()

    assert trace.trace_id.startswith("trc_")
    assert trace.query == "退款审核通过后多久到账？"
    assert trace.retrieval_chunks[0].startswith("退款审核通过后")
    assert trace.retrieval_scores == [0.91, 0.82]
    assert trace.prompt_version == "prompt_qa_v1"
    assert trace.model == "deepseek-chat"
    assert trace.answer
    assert trace.latency_ms == 842
    assert trace.feedback == "回答清楚。"
    assert trace.created_at.tzinfo == timezone.utc


def test_trace_rejects_misaligned_chunks_and_scores() -> None:
    with pytest.raises(ValidationError, match="must have the same length"):
        make_trace(retrieval_scores=[0.91])


@pytest.mark.parametrize("score", [float("nan"), float("inf"), float("-inf")])
def test_trace_rejects_non_finite_scores(score: float) -> None:
    with pytest.raises(ValidationError, match="finite numbers"):
        make_trace(retrieval_chunks=["证据"], retrieval_scores=[score])


def test_trace_requires_timezone_aware_created_at() -> None:
    with pytest.raises(ValidationError, match="timezone information"):
        make_trace(created_at=datetime(2026, 7, 15, 10, 30))


def test_collector_saves_and_reads_trace_history(tmp_path) -> None:
    storage_path = tmp_path / "history" / "traces.jsonl"
    collector = TraceCollector(storage_path)
    first = make_trace(trace_id="trc_first")
    second = make_trace(trace_id="trc_second", feedback=None, latency_ms=910)

    assert collector.list_traces() == []
    assert collector.save(first) == first
    assert collector.save(second) == second

    reloaded = TraceCollector(storage_path)
    assert reloaded.list_traces() == [first, second]
    assert reloaded.get_trace("trc_first") == first
    assert reloaded.get_trace("trc_missing") is None

    raw_records = [json.loads(line) for line in storage_path.read_text(encoding="utf-8").splitlines()]
    assert [record["trace_id"] for record in raw_records] == ["trc_first", "trc_second"]


def test_collector_rejects_duplicate_trace_id(tmp_path) -> None:
    collector = TraceCollector(tmp_path / "traces.jsonl")
    trace = make_trace(trace_id="trc_duplicate")
    collector.save(trace)

    with pytest.raises(DuplicateTraceError, match="trc_duplicate"):
        collector.save(trace)


def test_collector_reports_corrupt_history_line(tmp_path) -> None:
    storage_path = tmp_path / "traces.jsonl"
    storage_path.write_text('{"trace_id":"broken"}\n', encoding="utf-8")

    with pytest.raises(TraceStorageError, match="line 1"):
        TraceCollector(storage_path).list_traces()
