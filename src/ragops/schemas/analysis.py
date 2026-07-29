"""Schemas for deterministic failed-trace issue analysis."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Self
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from ragops.schemas.evaluation import EvaluationIssueCode, EvaluationResult
from ragops.schemas.trace import Trace


def _new_analysis_id() -> str:
    return f"analysis_{uuid4().hex}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BadCase(BaseModel):
    """A failed evaluation joined with its complete source Trace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trace: Trace
    evaluation: EvaluationResult

    @model_validator(mode="after")
    def validate_failed_trace(self) -> "BadCase":
        if self.evaluation.passed:
            raise ValueError("bad cases must contain a failed evaluation")
        if self.trace.trace_id != self.evaluation.trace_id:
            raise ValueError("trace_id must match evaluation.trace_id")
        return self


def _build_issue_groups(
    bad_cases: Iterable[BadCase],
) -> dict[EvaluationIssueCode, tuple[str, ...]]:
    grouped_ids: dict[EvaluationIssueCode, list[str]] = {
        issue: [] for issue in EvaluationIssueCode
    }
    seen_ids: dict[EvaluationIssueCode, set[str]] = {
        issue: set() for issue in EvaluationIssueCode
    }

    for bad_case in bad_cases:
        trace_id = bad_case.trace.trace_id
        for issue in dict.fromkeys(bad_case.evaluation.issues):
            if trace_id not in seen_ids[issue]:
                grouped_ids[issue].append(trace_id)
                seen_ids[issue].add(trace_id)

    return {issue: tuple(trace_ids) for issue, trace_ids in grouped_ids.items()}


class IssueAnalysisReport(BaseModel):
    """An immutable grouping of failed traces by evaluation issue."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    analysis_id: str = Field(
        default_factory=_new_analysis_id,
        min_length=10,
        pattern=r"^analysis_",
    )
    source_report_id: str = Field(min_length=1)
    bad_cases: tuple[BadCase, ...] = Field(default_factory=tuple)
    total_bad_cases: int = Field(ge=0, strict=True)
    issue_groups: Mapping[EvaluationIssueCode, tuple[str, ...]]
    created_at: datetime = Field(default_factory=_utc_now)

    @field_validator("issue_groups")
    @classmethod
    def freeze_issue_groups(
        cls,
        issue_groups: Mapping[EvaluationIssueCode, tuple[str, ...]],
    ) -> Mapping[EvaluationIssueCode, tuple[str, ...]]:
        return MappingProxyType(dict(issue_groups))

    @field_serializer("issue_groups")
    def serialize_issue_groups(
        self,
        issue_groups: Mapping[EvaluationIssueCode, tuple[str, ...]],
    ) -> dict[EvaluationIssueCode, tuple[str, ...]]:
        return dict(issue_groups)

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, created_at: datetime) -> datetime:
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("created_at must include timezone information")
        return created_at.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_statistics(self) -> "IssueAnalysisReport":
        if self.total_bad_cases != len(self.bad_cases):
            raise ValueError("total_bad_cases must equal the number of bad_cases")

        expected_groups = _build_issue_groups(self.bad_cases)
        if dict(self.issue_groups) != expected_groups:
            raise ValueError("issue_groups must match the actual bad case issues")
        return self

    @classmethod
    def from_bad_cases(
        cls,
        source_report_id: str,
        bad_cases: Iterable[BadCase],
    ) -> Self:
        """Build an analysis report with all statistics derived from bad cases."""
        bad_case_tuple = tuple(bad_cases)
        return cls(
            source_report_id=source_report_id,
            bad_cases=bad_case_tuple,
            total_bad_cases=len(bad_case_tuple),
            issue_groups=_build_issue_groups(bad_case_tuple),
        )
