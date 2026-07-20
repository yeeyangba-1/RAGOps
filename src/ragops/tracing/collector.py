"""Local JSONL persistence for MVP RAG traces."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from ragops.schemas.trace import Trace


class TraceStorageError(RuntimeError):
    """Raised when persisted trace history cannot be read safely."""


class DuplicateTraceError(TraceStorageError):
    """Raised when a trace ID has already been persisted."""


class TraceCollector:
    """Append and read validated traces from one UTF-8 JSONL file.

    This MVP collector is intended for local, single-process use. It deliberately
    does not provide database transactions, cross-process locking, or indexing.
    """

    def __init__(self, storage_path: str | Path) -> None:
        self.storage_path = Path(storage_path)

    def save(self, trace: Trace) -> Trace:
        """Append a trace and return the persisted value."""
        if self.get_trace(trace.trace_id) is not None:
            raise DuplicateTraceError(f"trace_id already exists: {trace.trace_id}")

        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with self.storage_path.open("a", encoding="utf-8", newline="\n") as file:
            file.write(trace.model_dump_json())
            file.write("\n")
        return trace

    def list_traces(self) -> list[Trace]:
        """Return all traces in append order."""
        if not self.storage_path.exists():
            return []

        traces: list[Trace] = []
        with self.storage_path.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                payload = line.strip()
                if not payload:
                    continue
                try:
                    traces.append(Trace.model_validate_json(payload))
                except (ValidationError, ValueError) as error:
                    raise TraceStorageError(
                        f"invalid trace record at line {line_number}"
                    ) from error
        return traces

    def get_trace(self, trace_id: str) -> Trace | None:
        """Return a trace by ID, or None when it is not present."""
        for trace in self.list_traces():
            if trace.trace_id == trace_id:
                return trace
        return None
