"""Schemas for deterministic release recommendations."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import Enum
from numbers import Real
from typing import Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ragops.schemas.experiment import ExperimentComparison


def _new_decision_id() -> str:
    return f"decision_{uuid4().hex}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _finite_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field_name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be a finite number")
    return number


class ReleasePolicy(BaseModel):
    """Immutable thresholds used by the deterministic release gate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    min_candidate_pass_rate: float = Field(default=0.8, ge=0, le=1)
    min_pass_rate_delta: float = Field(default=0.0, ge=-1, le=1)
    max_regressed_trace_count: int = Field(default=0, ge=0, strict=True)
    max_total_issue_increase: int = Field(default=0, ge=0, strict=True)

    @field_validator(
        "min_candidate_pass_rate",
        "min_pass_rate_delta",
        mode="before",
    )
    @classmethod
    def require_finite_threshold(cls, value: object, info) -> float:
        return _finite_number(value, info.field_name)


class ReleaseDecisionReason(str, Enum):
    """Stable reason codes that can block a candidate release."""

    EMPTY_EVALUATION = "empty_evaluation"
    CANDIDATE_PASS_RATE_BELOW_MINIMUM = (
        "candidate_pass_rate_below_minimum"
    )
    PASS_RATE_DELTA_BELOW_MINIMUM = "pass_rate_delta_below_minimum"
    TOO_MANY_REGRESSIONS = "too_many_regressions"
    TOTAL_ISSUE_INCREASE_EXCEEDED = "total_issue_increase_exceeded"


def _derive_reasons(
    policy: ReleasePolicy,
    candidate_pass_rate: float | None,
    pass_rate_delta: float | None,
    regressed_trace_count: int,
    total_issue_increase: int,
) -> tuple[ReleaseDecisionReason, ...]:
    if candidate_pass_rate is None and pass_rate_delta is None:
        return (ReleaseDecisionReason.EMPTY_EVALUATION,)

    reasons: list[ReleaseDecisionReason] = []
    if candidate_pass_rate < policy.min_candidate_pass_rate:
        reasons.append(
            ReleaseDecisionReason.CANDIDATE_PASS_RATE_BELOW_MINIMUM
        )
    if pass_rate_delta < policy.min_pass_rate_delta:
        reasons.append(ReleaseDecisionReason.PASS_RATE_DELTA_BELOW_MINIMUM)
    if regressed_trace_count > policy.max_regressed_trace_count:
        reasons.append(ReleaseDecisionReason.TOO_MANY_REGRESSIONS)
    if total_issue_increase > policy.max_total_issue_increase:
        reasons.append(ReleaseDecisionReason.TOTAL_ISSUE_INCREASE_EXCEEDED)
    return tuple(reasons)


class ReleaseDecision(BaseModel):
    """Immutable release recommendation derived from one comparison."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_id: str = Field(
        default_factory=_new_decision_id,
        min_length=10,
        pattern=r"^decision_",
    )
    comparison_id: str = Field(min_length=12, pattern=r"^comparison_")
    baseline_report_id: str = Field(min_length=8, pattern=r"^report_")
    candidate_report_id: str = Field(min_length=8, pattern=r"^report_")
    policy: ReleasePolicy
    approved: bool
    reasons: tuple[ReleaseDecisionReason, ...] = Field(default_factory=tuple)
    candidate_pass_rate: float | None
    pass_rate_delta: float | None
    regressed_trace_count: int = Field(ge=0, strict=True)
    total_issue_increase: int = Field(ge=0, strict=True)
    created_at: datetime = Field(default_factory=_utc_now)

    @field_validator("candidate_pass_rate", mode="before")
    @classmethod
    def require_candidate_pass_rate(
        cls,
        value: object,
    ) -> float | None:
        if value is None:
            return None
        number = _finite_number(value, "candidate_pass_rate")
        if not 0 <= number <= 1:
            raise ValueError("candidate_pass_rate must be between 0 and 1")
        return number

    @field_validator("pass_rate_delta", mode="before")
    @classmethod
    def require_pass_rate_delta(cls, value: object) -> float | None:
        if value is None:
            return None
        number = _finite_number(value, "pass_rate_delta")
        if not -1 <= number <= 1:
            raise ValueError("pass_rate_delta must be between -1 and 1")
        return number

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, created_at: datetime) -> datetime:
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("created_at must include timezone information")
        return created_at.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_decision(self) -> "ReleaseDecision":
        is_empty = (
            self.candidate_pass_rate is None and self.pass_rate_delta is None
        )
        if (self.candidate_pass_rate is None) != (self.pass_rate_delta is None):
            raise ValueError(
                "candidate_pass_rate and pass_rate_delta must both be present "
                "or both be None"
            )
        if is_empty and (
            self.regressed_trace_count != 0 or self.total_issue_increase != 0
        ):
            raise ValueError("empty evaluations must have zero derived counts")

        expected_reasons = _derive_reasons(
            self.policy,
            self.candidate_pass_rate,
            self.pass_rate_delta,
            self.regressed_trace_count,
            self.total_issue_increase,
        )
        if self.reasons != expected_reasons:
            raise ValueError("reasons must match the derived release checks")
        if self.approved != (not expected_reasons):
            raise ValueError("approved must match the derived release reasons")
        return self

    @classmethod
    def from_comparison(
        cls,
        comparison: ExperimentComparison,
        policy: ReleasePolicy,
    ) -> Self:
        """Derive a release decision from an existing comparison."""
        total_issue_increase = sum(
            max(delta, 0) for delta in comparison.issue_count_deltas.values()
        )
        reasons = _derive_reasons(
            policy,
            comparison.candidate_pass_rate,
            comparison.pass_rate_delta,
            len(comparison.regressed_trace_ids),
            total_issue_increase,
        )
        return cls(
            comparison_id=comparison.comparison_id,
            baseline_report_id=comparison.baseline_report.report_id,
            candidate_report_id=comparison.candidate_report.report_id,
            policy=policy,
            approved=not reasons,
            reasons=reasons,
            candidate_pass_rate=comparison.candidate_pass_rate,
            pass_rate_delta=comparison.pass_rate_delta,
            regressed_trace_count=len(comparison.regressed_trace_ids),
            total_issue_increase=total_issue_increase,
        )
