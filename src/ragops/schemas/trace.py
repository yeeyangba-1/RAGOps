"""MVP schema for one complete RAG request trace."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _new_trace_id() -> str:
    return f"trc_{uuid4().hex}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Trace(BaseModel):
    """A minimal, immutable record of a completed RAG request."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    trace_id: str = Field(default_factory=_new_trace_id, min_length=1)
    query: str = Field(min_length=1)
    retrieval_chunks: list[str] = Field(default_factory=list)
    retrieval_scores: list[float] = Field(default_factory=list)
    prompt_version: str = Field(min_length=1)
    model: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    latency_ms: float = Field(ge=0)
    feedback: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)

    @field_validator("retrieval_chunks")
    @classmethod
    def validate_retrieval_chunks(cls, chunks: list[str]) -> list[str]:
        if any(not chunk.strip() for chunk in chunks):
            raise ValueError("retrieval chunks must not contain blank text")
        return chunks

    @field_validator("retrieval_scores")
    @classmethod
    def validate_retrieval_scores(cls, scores: list[float]) -> list[float]:
        if any(not math.isfinite(score) for score in scores):
            raise ValueError("retrieval scores must be finite numbers")
        return scores

    @field_validator("feedback", mode="before")
    @classmethod
    def normalize_feedback(cls, feedback: object) -> object:
        if isinstance(feedback, str) and not feedback.strip():
            return None
        return feedback

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, created_at: datetime) -> datetime:
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("created_at must include timezone information")
        return created_at.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_retrieval_alignment(self) -> "Trace":
        if len(self.retrieval_chunks) != len(self.retrieval_scores):
            raise ValueError("retrieval chunks and scores must have the same length")
        return self
