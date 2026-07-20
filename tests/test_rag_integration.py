"""Tests for the generic RAG-to-Trace integration layer."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from ragops.tracing import RagTracePayload, TraceCollector, TraceStorageError, TracedRagRunner


def clock_from(values: list[float]) -> Iterator[float]:
    return iter(values)


def test_rag_request_returns_queryable_trace_id(tmp_path) -> None:
    collector = TraceCollector(tmp_path / "traces.jsonl")
    raw_result = {
        "response": "通常3到5个工作日原路返回。",
        "documents": [
            {
                "text": "退款审核通过后通常在3到5个工作日内原路返回。",
                "relevance": 0.91,
            }
        ],
    }
    received_queries: list[str] = []

    def pipeline(query: str) -> dict[str, object]:
        received_queries.append(query)
        return raw_result

    def map_result(result: dict[str, object]) -> RagTracePayload:
        documents = result["documents"]
        assert isinstance(documents, list)
        return RagTracePayload(
            retrieval_chunks=[document["text"] for document in documents],
            retrieval_scores=[document["relevance"] for document in documents],
            answer=str(result["response"]),
        )

    ticks = clock_from([10.0, 10.842])
    runner = TracedRagRunner[dict[str, object]](
        collector,
        result_mapper=map_result,
        prompt_version="support_qa_v1",
        model="deepseek-chat",
        clock=lambda: next(ticks),
    )

    run = runner.run("退款审核通过后多久到账？", pipeline, feedback="有帮助")

    assert received_queries == ["退款审核通过后多久到账？"]
    assert run.result is raw_result
    assert run.trace_id is not None
    assert run.trace_id.startswith("trc_")

    stored_trace = collector.get_trace(run.trace_id)
    assert stored_trace is not None
    assert stored_trace.trace_id == run.trace_id
    assert stored_trace.query == "退款审核通过后多久到账？"
    assert stored_trace.retrieval_chunks == [
        "退款审核通过后通常在3到5个工作日内原路返回。"
    ]
    assert stored_trace.retrieval_scores == [0.91]
    assert stored_trace.prompt_version == "support_qa_v1"
    assert stored_trace.model == "deepseek-chat"
    assert stored_trace.answer == "通常3到5个工作日原路返回。"
    assert stored_trace.latency_ms == pytest.approx(842)
    assert stored_trace.feedback == "有帮助"


def test_fail_open_returns_original_result_when_trace_save_fails(
    tmp_path, monkeypatch, caplog
) -> None:
    collector = TraceCollector(tmp_path / "traces.jsonl")
    raw_result = {"answer": "pipeline succeeded"}
    pipeline_calls = 0

    def pipeline(query: str) -> dict[str, str]:
        nonlocal pipeline_calls
        pipeline_calls += 1
        return raw_result

    def fail_save(trace) -> None:
        raise TraceStorageError("storage unavailable")

    monkeypatch.setattr(collector, "save", fail_save)
    runner = TracedRagRunner[dict[str, str]](
        collector,
        result_mapper=lambda result: RagTracePayload([], [], result["answer"]),
        prompt_version="support_qa_v1",
        model="deepseek-chat",
    )

    with caplog.at_level(logging.ERROR):
        run = runner.run("question", pipeline)

    assert run.result is raw_result
    assert run.trace_id is None
    assert pipeline_calls == 1
    assert any(
        "Failed to create or persist RAG trace" in record.getMessage()
        and record.name == "ragops.tracing.rag_integration"
        and record.exc_info is not None
        for record in caplog.records
    )


def test_fail_open_handles_result_mapper_failure(tmp_path, caplog) -> None:
    collector = TraceCollector(tmp_path / "traces.jsonl")
    raw_result = object()
    pipeline_calls = 0

    def pipeline(query: str) -> object:
        nonlocal pipeline_calls
        pipeline_calls += 1
        return raw_result

    def failing_mapper(result: object) -> RagTracePayload:
        raise ValueError("mapping failed")

    runner = TracedRagRunner[object](
        collector,
        result_mapper=failing_mapper,
        prompt_version="support_qa_v1",
        model="deepseek-chat",
    )

    with caplog.at_level(logging.ERROR):
        run = runner.run("question", pipeline)

    assert run.result is raw_result
    assert run.trace_id is None
    assert pipeline_calls == 1
    assert collector.list_traces() == []
    assert any(record.exc_info is not None for record in caplog.records)


def test_fail_open_handles_trace_validation_failure(tmp_path, caplog) -> None:
    collector = TraceCollector(tmp_path / "traces.jsonl")
    raw_result = object()
    pipeline_calls = 0

    def pipeline(query: str) -> object:
        nonlocal pipeline_calls
        pipeline_calls += 1
        return raw_result

    runner = TracedRagRunner[object](
        collector,
        result_mapper=lambda result: RagTracePayload(["chunk"], [], "answer"),
        prompt_version="support_qa_v1",
        model="deepseek-chat",
    )

    with caplog.at_level(logging.ERROR):
        run = runner.run("question", pipeline)

    assert run.result is raw_result
    assert run.trace_id is None
    assert pipeline_calls == 1
    assert collector.list_traces() == []
    assert any(record.exc_info is not None for record in caplog.records)


def test_fail_closed_raises_trace_error_without_repeating_pipeline(
    tmp_path, monkeypatch
) -> None:
    collector = TraceCollector(tmp_path / "traces.jsonl")
    pipeline_calls = 0

    def pipeline(query: str) -> str:
        nonlocal pipeline_calls
        pipeline_calls += 1
        return "answer"

    def fail_save(trace) -> None:
        raise TraceStorageError("storage unavailable")

    monkeypatch.setattr(collector, "save", fail_save)
    runner = TracedRagRunner[str](
        collector,
        result_mapper=lambda result: RagTracePayload([], [], result),
        prompt_version="support_qa_v1",
        model="deepseek-chat",
        fail_open=False,
    )

    with pytest.raises(TraceStorageError, match="storage unavailable"):
        runner.run("question", pipeline)

    assert pipeline_calls == 1


@pytest.mark.parametrize("fail_open", [True, False])
def test_failed_rag_request_does_not_persist_incomplete_trace(
    tmp_path, caplog, fail_open: bool
) -> None:
    collector = TraceCollector(tmp_path / "traces.jsonl")
    pipeline_calls = 0
    runner = TracedRagRunner[object](
        collector,
        result_mapper=lambda result: RagTracePayload([], [], str(result)),
        prompt_version="support_qa_v1",
        model="deepseek-chat",
        fail_open=fail_open,
    )

    def failing_pipeline(query: str) -> object:
        nonlocal pipeline_calls
        pipeline_calls += 1
        raise RuntimeError(f"pipeline failed for: {query}")

    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError, match="pipeline failed"):
            runner.run("会失败的问题", failing_pipeline)

    assert pipeline_calls == 1
    assert collector.list_traces() == []
    assert caplog.records == []
