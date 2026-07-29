"""Local JSONL persistence for release decisions."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from ragops.schemas.release import ReleaseDecision


class ReleaseDecisionStorageError(RuntimeError):
    """Raised when persisted release decision history cannot be read safely."""


class DuplicateReleaseDecisionError(ReleaseDecisionStorageError):
    """Raised when a release decision ID has already been persisted."""


class ReleaseDecisionCollector:
    """Append and read validated decisions from one UTF-8 JSONL file.

    This MVP collector is intended for local, single-process use. It deliberately
    does not provide database transactions, cross-process locking, or indexing.
    """

    def __init__(self, storage_path: str | Path) -> None:
        self.storage_path = Path(storage_path)

    def save(self, decision: ReleaseDecision) -> ReleaseDecision:
        """Append a decision and return the persisted value."""
        if self.get_decision(decision.decision_id) is not None:
            raise DuplicateReleaseDecisionError(
                f"decision_id already exists: {decision.decision_id}"
            )

        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with self.storage_path.open("a", encoding="utf-8", newline="\n") as file:
            file.write(decision.model_dump_json())
            file.write("\n")
        return decision

    def list_decisions(self) -> list[ReleaseDecision]:
        """Return all release decisions in append order."""
        if not self.storage_path.exists():
            return []

        decisions: list[ReleaseDecision] = []
        with self.storage_path.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                payload = line.strip()
                if not payload:
                    continue
                try:
                    decisions.append(ReleaseDecision.model_validate_json(payload))
                except (ValidationError, ValueError) as error:
                    raise ReleaseDecisionStorageError(
                        f"invalid release decision record at line {line_number}"
                    ) from error
        return decisions

    def get_decision(self, decision_id: str) -> ReleaseDecision | None:
        """Return a decision by ID, or None when it is not present."""
        for decision in self.list_decisions():
            if decision.decision_id == decision_id:
                return decision
        return None
