"""Schemas for deterministic evaluation results."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import Enum
from numbers import Real
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _new_evaluation_id() -> str:
    return f"eval_{uuid4().hex}"


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
