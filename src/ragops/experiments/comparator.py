"""Compare existing evaluation reports without executing evaluation rules."""

from __future__ import annotations

from ragops.schemas.evaluation import EvaluationReport
from ragops.schemas.experiment import ExperimentComparison


class ExperimentComparisonError(RuntimeError):
    """Base error for evaluation report comparison."""


class IncomparableEvaluationReportsError(ExperimentComparisonError):
    """Raised when reports do not cover exactly the same trace IDs."""


class DuplicateEvaluationTraceError(ExperimentComparisonError):
    """Raised when one report contains a trace ID more than once."""


def _unique_trace_ids(report: EvaluationReport, report_name: str) -> set[str]:
    trace_ids: set[str] = set()
    for result in report.results:
        if result.trace_id in trace_ids:
            raise DuplicateEvaluationTraceError(
                f"duplicate trace_id in {report_name} report: {result.trace_id}"
            )
        trace_ids.add(result.trace_id)
    return trace_ids


class ExperimentComparator:
    """Compare passed states and issue counts from two existing reports."""

    def compare(
        self,
        baseline_report: EvaluationReport,
        candidate_report: EvaluationReport,
    ) -> ExperimentComparison:
        """Validate report comparability and return a derived comparison."""
        baseline_trace_ids = _unique_trace_ids(baseline_report, "baseline")
        candidate_trace_ids = _unique_trace_ids(candidate_report, "candidate")
        if baseline_trace_ids != candidate_trace_ids:
            raise IncomparableEvaluationReportsError(
                "baseline and candidate reports must cover the same trace_ids"
            )
        return ExperimentComparison.from_reports(baseline_report, candidate_report)
