"""Schemas for deterministic evaluation report comparison."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Annotated, Self
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from ragops.schemas.evaluation import (
    EvaluationIssueCode,
    EvaluationReport,
    EvaluationResult,
)


def _new_comparison_id() -> str:
    return f"comparison_{uuid4().hex}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _index_results(
    report: EvaluationReport,
    report_name: str,
) -> dict[str, EvaluationResult]:
    index: dict[str, EvaluationResult] = {}
    for result in report.results:
        if result.trace_id in index:
            raise ValueError(
                f"{report_name} report contains duplicate trace_id: {result.trace_id}"
            )
        index[result.trace_id] = result
    return index


def _derive_comparison(
    baseline_report: EvaluationReport,
    candidate_report: EvaluationReport,
) -> dict[str, object]:
    baseline_index = _index_results(baseline_report, "baseline")
    candidate_index = _index_results(candidate_report, "candidate")
    if set(baseline_index) != set(candidate_index):
        raise ValueError("baseline and candidate reports must cover the same trace_ids")

    trace_ids = tuple(result.trace_id for result in baseline_report.results)
    improved: list[str] = []
    regressed: list[str] = []
    unchanged_passed: list[str] = []
    unchanged_failed: list[str] = []

    for trace_id in trace_ids:
        baseline_passed = baseline_index[trace_id].passed
        candidate_passed = candidate_index[trace_id].passed
        if not baseline_passed and candidate_passed:
            improved.append(trace_id)
        elif baseline_passed and not candidate_passed:
            regressed.append(trace_id)
        elif baseline_passed:
            unchanged_passed.append(trace_id)
        else:
            unchanged_failed.append(trace_id)

    pass_rate_delta = (
        None
        if baseline_report.pass_rate is None
        else candidate_report.pass_rate - baseline_report.pass_rate
    )
    issue_count_deltas = {
        issue: candidate_report.issue_counts[issue]
        - baseline_report.issue_counts[issue]
        for issue in EvaluationIssueCode
    }

    return {
        "trace_ids": trace_ids,
        "total_count": len(trace_ids),
        "baseline_passed_count": baseline_report.passed_count,
        "candidate_passed_count": candidate_report.passed_count,
        "baseline_pass_rate": baseline_report.pass_rate,
        "candidate_pass_rate": candidate_report.pass_rate,
        "pass_rate_delta": pass_rate_delta,
        "improved_trace_ids": tuple(improved),
        "regressed_trace_ids": tuple(regressed),
        "unchanged_passed_trace_ids": tuple(unchanged_passed),
        "unchanged_failed_trace_ids": tuple(unchanged_failed),
        "issue_count_deltas": issue_count_deltas,
    }


IssueCountDelta = Annotated[int, Field(strict=True)]


class ExperimentComparison(BaseModel):
    """An immutable comparison of two reports covering the same traces."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    comparison_id: str = Field(
        default_factory=_new_comparison_id,
        min_length=12,
        pattern=r"^comparison_",
    )
    baseline_report: EvaluationReport
    candidate_report: EvaluationReport
    trace_ids: tuple[str, ...]
    total_count: int = Field(ge=0, strict=True)
    baseline_passed_count: int = Field(ge=0, strict=True)
    candidate_passed_count: int = Field(ge=0, strict=True)
    baseline_pass_rate: float | None = Field(default=None, ge=0, le=1, strict=True)
    candidate_pass_rate: float | None = Field(default=None, ge=0, le=1, strict=True)
    pass_rate_delta: float | None = Field(default=None, ge=-1, le=1, strict=True)
    improved_trace_ids: tuple[str, ...]
    regressed_trace_ids: tuple[str, ...]
    unchanged_passed_trace_ids: tuple[str, ...]
    unchanged_failed_trace_ids: tuple[str, ...]
    issue_count_deltas: Mapping[EvaluationIssueCode, IssueCountDelta]
    created_at: datetime = Field(default_factory=_utc_now)

    @field_validator("issue_count_deltas")
    @classmethod
    def freeze_issue_count_deltas(
        cls,
        issue_count_deltas: Mapping[EvaluationIssueCode, int],
    ) -> Mapping[EvaluationIssueCode, int]:
        return MappingProxyType(dict(issue_count_deltas))

    @field_serializer("issue_count_deltas")
    def serialize_issue_count_deltas(
        self,
        issue_count_deltas: Mapping[EvaluationIssueCode, int],
    ) -> dict[EvaluationIssueCode, int]:
        return dict(issue_count_deltas)

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, created_at: datetime) -> datetime:
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("created_at must include timezone information")
        return created_at.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_statistics(self) -> "ExperimentComparison":
        expected = _derive_comparison(self.baseline_report, self.candidate_report)
        fields = (
            "trace_ids",
            "total_count",
            "baseline_passed_count",
            "candidate_passed_count",
            "baseline_pass_rate",
            "candidate_pass_rate",
            "pass_rate_delta",
            "improved_trace_ids",
            "regressed_trace_ids",
            "unchanged_passed_trace_ids",
            "unchanged_failed_trace_ids",
        )
        for field_name in fields:
            if getattr(self, field_name) != expected[field_name]:
                raise ValueError(
                    f"{field_name} must match the actual report comparison"
                )
        if dict(self.issue_count_deltas) != expected["issue_count_deltas"]:
            raise ValueError(
                "issue_count_deltas must match the actual report issue counts"
            )
        return self

    @classmethod
    def from_reports(
        cls,
        baseline_report: EvaluationReport,
        candidate_report: EvaluationReport,
    ) -> Self:
        """Build a comparison with all fields derived from two reports."""
        statistics = _derive_comparison(baseline_report, candidate_report)
        return cls(
            baseline_report=baseline_report,
            candidate_report=candidate_report,
            **statistics,
        )
