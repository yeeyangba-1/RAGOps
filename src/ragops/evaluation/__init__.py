"""Public API for trace evaluation."""

from ragops.evaluation.collector import (
    DuplicateEvaluationReportError,
    EvaluationReportCollector,
    EvaluationReportStorageError,
)
from ragops.evaluation.offline import OfflineEvaluationRunner
from ragops.evaluation.rule_based import RuleBasedEvaluator
from ragops.schemas.evaluation import (
    EvaluationIssueCode,
    EvaluationReport,
    EvaluationResult,
)

__all__ = [
    "DuplicateEvaluationReportError",
    "EvaluationIssueCode",
    "EvaluationReport",
    "EvaluationReportCollector",
    "EvaluationReportStorageError",
    "EvaluationResult",
    "OfflineEvaluationRunner",
    "RuleBasedEvaluator",
]
