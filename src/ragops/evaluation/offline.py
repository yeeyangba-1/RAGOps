"""Local orchestration for offline trace evaluation."""

from __future__ import annotations

from ragops.evaluation.collector import EvaluationReportCollector
from ragops.evaluation.rule_based import RuleBasedEvaluator
from ragops.schemas.evaluation import EvaluationReport
from ragops.tracing.collector import TraceCollector


class OfflineEvaluationRunner:
    """Read stored traces, evaluate them, and persist one batch report."""

    def __init__(
        self,
        trace_collector: TraceCollector,
        evaluator: RuleBasedEvaluator,
        report_collector: EvaluationReportCollector,
    ) -> None:
        self._trace_collector = trace_collector
        self._evaluator = evaluator
        self._report_collector = report_collector

    def run(self) -> EvaluationReport:
        """Execute one offline evaluation without retries or fail-open behavior."""
        traces = self._trace_collector.list_traces()
        report = self._evaluator.evaluate_many(traces)
        return self._report_collector.save(report)
