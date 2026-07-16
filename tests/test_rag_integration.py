"""Tests for the generic RAG-to-Trace integration layer."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from src.tracing import RagTracePayload, TraceCollector, TracedRagRunner


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


def test_failed_rag_request_does_not_persist_incomplete_trace(tmp_path) -> None:
    collector = TraceCollector(tmp_path / "traces.jsonl")
    runner = TracedRagRunner[object](
        collector,
        result_mapper=lambda result: RagTracePayload([], [], str(result)),
        prompt_version="support_qa_v1",
        model="deepseek-chat",
    )

    def failing_pipeline(query: str) -> object:
        raise RuntimeError(f"pipeline failed for: {query}")

    with pytest.raises(RuntimeError, match="pipeline failed"):
        runner.run("会失败的问题", failing_pipeline)

    assert collector.list_traces() == []
