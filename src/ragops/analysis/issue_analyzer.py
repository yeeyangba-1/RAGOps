"""Join failed evaluations to source traces and group their issues."""

from __future__ import annotations

from collections.abc import Iterable

from ragops.schemas.analysis import BadCase, IssueAnalysisReport
from ragops.schemas.evaluation import EvaluationReport
from ragops.schemas.trace import Trace


class IssueAnalysisError(RuntimeError):
    """Base error for failed-trace issue analysis."""


class MissingTraceForEvaluationError(IssueAnalysisError):
    """Raised when a failed evaluation has no matching source Trace."""


class DuplicateTraceForAnalysisError(IssueAnalysisError):
    """Raised when input traces contain the same trace ID more than once."""


class IssueAnalyzer:
    """Analyze report failures using only existing evaluation issues."""

    def analyze(
        self,
        report: EvaluationReport,
        traces: Iterable[Trace],
    ) -> IssueAnalysisReport:
        """Join failed results to traces and preserve report result order."""
        trace_index: dict[str, Trace] = {}
        for trace in traces:
            if trace.trace_id in trace_index:
                raise DuplicateTraceForAnalysisError(
                    f"duplicate trace_id for analysis: {trace.trace_id}"
                )
            trace_index[trace.trace_id] = trace

        bad_cases: list[BadCase] = []
        for evaluation in report.results:
            if evaluation.passed:
                continue
            trace = trace_index.get(evaluation.trace_id)
            if trace is None:
                raise MissingTraceForEvaluationError(
                    f"missing trace for failed evaluation: {evaluation.trace_id}"
                )
            bad_cases.append(BadCase(trace=trace, evaluation=evaluation))

        return IssueAnalysisReport.from_bad_cases(report.report_id, bad_cases)
