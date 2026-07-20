"""Generic adapter for collecting traces from an existing RAG pipeline."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import Generic, TypeVar

from ragops.schemas.trace import Trace
from ragops.tracing.collector import TraceCollector


logger = logging.getLogger(__name__)


PipelineResult = TypeVar("PipelineResult")


@dataclass(frozen=True, slots=True)
class RagTracePayload:
    """Pipeline-independent values needed to build the MVP Trace."""

    retrieval_chunks: Sequence[str]
    retrieval_scores: Sequence[float]
    answer: str


@dataclass(frozen=True, slots=True)
class TracedRagResult(Generic[PipelineResult]):
    """The untouched pipeline result and its trace ID when persistence succeeds."""

    result: PipelineResult
    trace_id: str | None


class TracedRagRunner(Generic[PipelineResult]):
    """Run an existing RAG callable and persist an MVP Trace.

    The result mapper keeps this integration independent from any RAG framework
    or application-specific response shape.
    """

    def __init__(
        self,
        collector: TraceCollector,
        *,
        result_mapper: Callable[[PipelineResult], RagTracePayload],
        prompt_version: str,
        model: str,
        fail_open: bool = True,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        if not prompt_version.strip():
            raise ValueError("prompt_version must not be blank")
        if not model.strip():
            raise ValueError("model must not be blank")

        self._collector = collector
        self._result_mapper = result_mapper
        self._prompt_version = prompt_version.strip()
        self._model = model.strip()
        self._fail_open = fail_open
        self._clock = clock

    def run(
        self,
        query: str,
        pipeline: Callable[[str], PipelineResult],
        *,
        feedback: str | None = None,
    ) -> TracedRagResult[PipelineResult]:
        """Run the pipeline, persist its successful result, and return trace_id."""
        started_at = self._clock()
        result = pipeline(query)
        latency_ms = (self._clock() - started_at) * 1000
        try:
            payload = self._result_mapper(result)
            trace = Trace(
                query=query,
                retrieval_chunks=list(payload.retrieval_chunks),
                retrieval_scores=list(payload.retrieval_scores),
                prompt_version=self._prompt_version,
                model=self._model,
                answer=payload.answer,
                latency_ms=latency_ms,
                feedback=feedback,
            )
            persisted = self._collector.save(trace)
        except Exception:
            if not self._fail_open:
                raise
            logger.exception(
                "Failed to create or persist RAG trace; returning pipeline result "
                "without trace_id"
            )
            return TracedRagResult(result=result, trace_id=None)

        return TracedRagResult(result=result, trace_id=persisted.trace_id)
