"""Schemas for deterministic evaluation results."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from enum import Enum
from numbers import Real
from types import MappingProxyType
from typing import Annotated, Literal, Self
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)


def _new_evaluation_id() -> str:
    return f"eval_{uuid4().hex}"


def _new_report_id() -> str:
    return f"report_{uuid4().hex}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _finite_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field_name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be a finite number")
    return number


class EvaluationIssueCode(str, Enum):
    """Stable codes emitted by the rule-based evaluator."""

    NO_RETRIEVAL = "no_retrieval"
    LOW_RETRIEVAL_SCORE = "low_retrieval_score"
    HIGH_LATENCY = "high_latency"


class EvaluationResult(BaseModel):
    """An immutable result produced by one evaluation of a Trace."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    evaluation_id: str = Field(
        default_factory=_new_evaluation_id,
        min_length=6,
        pattern=r"^eval_",
    )
    trace_id: str = Field(min_length=1)
    evaluator: Literal["rule_based_v1"] = "rule_based_v1"
    passed: bool
    issues: tuple[EvaluationIssueCode, ...] = Field(default_factory=tuple)
    retrieval_count: int = Field(ge=0, strict=True)
    max_retrieval_score: float | None
    latency_ms: float = Field(ge=0)
    min_retrieval_score: float
    max_latency_ms: float = Field(ge=0)
    created_at: datetime = Field(default_factory=_utc_now)

    @field_validator(
        "latency_ms",
        "min_retrieval_score",
        "max_latency_ms",
        mode="before",
    )
    @classmethod
    def require_finite_number(cls, value: object, info) -> float:
        return _finite_number(value, info.field_name)

    @field_validator("max_retrieval_score", mode="before")
    @classmethod
    def require_finite_max_score(cls, value: object) -> float | None:
        if value is None:
            return None
        return _finite_number(value, "max_retrieval_score")

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, created_at: datetime) -> datetime:
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("created_at must include timezone information")
        return created_at.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_consistency(self) -> "EvaluationResult":
        if self.passed and self.issues:
            raise ValueError("passed evaluations must not contain issues")
        if not self.passed and not self.issues:
            raise ValueError("failed evaluations must contain at least one issue")
        if self.retrieval_count == 0 and self.max_retrieval_score is not None:
            raise ValueError(
                "max_retrieval_score must be None when retrieval_count is zero"
            )
        if self.retrieval_count > 0 and self.max_retrieval_score is None:
            raise ValueError(
                "max_retrieval_score is required when retrieval_count is positive"
            )
        return self


IssueCount = Annotated[int, Field(ge=0, strict=True)]


class EvaluationReport(BaseModel):
    """An immutable aggregate of evaluation results for one batch."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    report_id: str = Field(
        default_factory=_new_report_id,
        min_length=8,
        pattern=r"^report_",
    )
    evaluator: Literal["rule_based_v1"] = "rule_based_v1"
    results: tuple[EvaluationResult, ...] = Field(default_factory=tuple)
    total_count: int = Field(ge=0, strict=True)
    passed_count: int = Field(ge=0, strict=True)
    failed_count: int = Field(ge=0, strict=True)
    pass_rate: float | None = Field(default=None, ge=0, le=1)
    issue_counts: Mapping[EvaluationIssueCode, IssueCount]
    failed_trace_ids: tuple[str, ...] = Field(default_factory=tuple)
    created_at: datetime = Field(default_factory=_utc_now)

    @field_validator("pass_rate", mode="before")
    @classmethod
    def require_finite_pass_rate(cls, value: object) -> float | None:
        if value is None:
            return None
        return _finite_number(value, "pass_rate")

    @field_validator("issue_counts")
    @classmethod
    def freeze_issue_counts(
        cls,
        issue_counts: Mapping[EvaluationIssueCode, int],
    ) -> Mapping[EvaluationIssueCode, int]:
        return MappingProxyType(dict(issue_counts))

    @field_serializer("issue_counts")
    def serialize_issue_counts(
        self,
        issue_counts: Mapping[EvaluationIssueCode, int],
    ) -> dict[EvaluationIssueCode, int]:
        return dict(issue_counts)

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, created_at: datetime) -> datetime:
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("created_at must include timezone information")
        return created_at.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_statistics(self) -> "EvaluationReport":
        expected_total = len(self.results)
        expected_passed = sum(result.passed for result in self.results)
        expected_failed = expected_total - expected_passed
        expected_pass_rate = (
            expected_passed / expected_total if expected_total else None
        )
        expected_issue_counts = {
            issue: sum(issue in set(result.issues) for result in self.results)
            for issue in EvaluationIssueCode
        }
        expected_failed_trace_ids = tuple(
            result.trace_id for result in self.results if not result.passed
        )

        if self.total_count != expected_total:
            raise ValueError("total_count must equal the number of results")
        if self.passed_count != expected_passed:
            raise ValueError("passed_count must equal the number of passed results")
        if self.failed_count != expected_failed:
            raise ValueError("failed_count must equal the number of failed results")
        if self.passed_count + self.failed_count != self.total_count:
            raise ValueError("passed_count and failed_count must sum to total_count")
        if self.pass_rate != expected_pass_rate:
            raise ValueError("pass_rate must match the actual result statistics")
        if dict(self.issue_counts) != expected_issue_counts:
            raise ValueError("issue_counts must match the actual result issues")
        if self.failed_trace_ids != expected_failed_trace_ids:
            raise ValueError("failed_trace_ids must match failed results in order")
        return self

    @classmethod
    def from_results(cls, results: Iterable[EvaluationResult]) -> Self:
        """Build a report with all statistics derived from its results."""
        result_tuple = tuple(results)
        passed_count = sum(result.passed for result in result_tuple)
        total_count = len(result_tuple)
        issue_counts = {
            issue: sum(issue in set(result.issues) for result in result_tuple)
            for issue in EvaluationIssueCode
        }

        return cls(
            results=result_tuple,
            total_count=total_count,
            passed_count=passed_count,
            failed_count=total_count - passed_count,
            pass_rate=passed_count / total_count if total_count else None,
            issue_counts=issue_counts,
            failed_trace_ids=tuple(
                result.trace_id for result in result_tuple if not result.passed
            ),
        )
