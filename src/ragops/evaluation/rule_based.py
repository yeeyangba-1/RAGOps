"""Deterministic, local evaluation rules for RAG traces."""

from __future__ import annotations

import math
from numbers import Real

from ragops.schemas.evaluation import EvaluationIssueCode, EvaluationResult
from ragops.schemas.trace import Trace


def _validate_threshold(value: object, name: str, *, non_negative: bool) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a finite number")

    threshold = float(value)
    if not math.isfinite(threshold):
        raise ValueError(f"{name} must be a finite number")
    if non_negative and threshold < 0:
        raise ValueError(f"{name} must be greater than or equal to zero")
    return threshold


class RuleBasedEvaluator:
    """Evaluate retrieval presence, retrieval score, and request latency."""

    __slots__ = ("min_retrieval_score", "max_latency_ms")

    def __init__(
        self,
        *,
        min_retrieval_score: float = 0.25,
        max_latency_ms: float = 30000.0,
    ) -> None:
        self.min_retrieval_score = _validate_threshold(
            min_retrieval_score,
            "min_retrieval_score",
            non_negative=False,
        )
        self.max_latency_ms = _validate_threshold(
            max_latency_ms,
            "max_latency_ms",
            non_negative=True,
        )

    def evaluate(self, trace: Trace) -> EvaluationResult:
        """Evaluate a completed Trace without changing it."""
        retrieval_count = len(trace.retrieval_chunks)
        issues: list[EvaluationIssueCode] = []

        if retrieval_count == 0:
            max_retrieval_score = None
            issues.append(EvaluationIssueCode.NO_RETRIEVAL)
        else:
            max_retrieval_score = max(trace.retrieval_scores)
            if max_retrieval_score < self.min_retrieval_score:
                issues.append(EvaluationIssueCode.LOW_RETRIEVAL_SCORE)

        if trace.latency_ms > self.max_latency_ms:
            issues.append(EvaluationIssueCode.HIGH_LATENCY)

        return EvaluationResult(
            trace_id=trace.trace_id,
            passed=not issues,
            issues=tuple(issues),
            retrieval_count=retrieval_count,
            max_retrieval_score=max_retrieval_score,
            latency_ms=trace.latency_ms,
            min_retrieval_score=self.min_retrieval_score,
            max_latency_ms=self.max_latency_ms,
        )
