"""Local orchestration for release recommendations."""

from __future__ import annotations

from ragops.release.collector import ReleaseDecisionCollector
from ragops.release.gate import ReleaseGate
from ragops.schemas.experiment import ExperimentComparison
from ragops.schemas.release import ReleaseDecision, ReleasePolicy


class ReleaseGateRunner:
    """Decide and persist one release recommendation."""

    def __init__(
        self,
        gate: ReleaseGate,
        collector: ReleaseDecisionCollector,
    ) -> None:
        self._gate = gate
        self._collector = collector

    def run(
        self,
        comparison: ExperimentComparison,
        policy: ReleasePolicy | None = None,
    ) -> ReleaseDecision:
        """Execute one gate decision without retries or fail-open behavior."""
        decision = self._gate.decide(comparison, policy)
        return self._collector.save(decision)
