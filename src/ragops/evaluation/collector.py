"""Local JSONL persistence for evaluation reports."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from ragops.schemas.evaluation import EvaluationReport


class EvaluationReportStorageError(RuntimeError):
    """Raised when persisted evaluation report history cannot be read safely."""


class DuplicateEvaluationReportError(EvaluationReportStorageError):
    """Raised when an evaluation report ID has already been persisted."""


class EvaluationReportCollector:
    """Append and read validated reports from one UTF-8 JSONL file.

    This MVP collector is intended for local, single-process use. It deliberately
    does not provide database transactions, cross-process locking, or indexing.
    """

    def __init__(self, storage_path: str | Path) -> None:
        self.storage_path = Path(storage_path)

    def save(self, report: EvaluationReport) -> EvaluationReport:
        """Append a report and return the persisted value."""
        if self.get_report(report.report_id) is not None:
            raise DuplicateEvaluationReportError(
                f"report_id already exists: {report.report_id}"
            )

        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with self.storage_path.open("a", encoding="utf-8", newline="\n") as file:
            file.write(report.model_dump_json())
            file.write("\n")
        return report

    def list_reports(self) -> list[EvaluationReport]:
        """Return all evaluation reports in append order."""
        if not self.storage_path.exists():
            return []

        reports: list[EvaluationReport] = []
        with self.storage_path.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                payload = line.strip()
                if not payload:
                    continue
                try:
                    reports.append(EvaluationReport.model_validate_json(payload))
                except (ValidationError, ValueError) as error:
                    raise EvaluationReportStorageError(
                        f"invalid evaluation report record at line {line_number}"
                    ) from error
        return reports

    def get_report(self, report_id: str) -> EvaluationReport | None:
        """Return a report by ID, or None when it is not present."""
        for report in self.list_reports():
            if report.report_id == report_id:
                return report
        return None
