"""Deterministic release gate for existing experiment comparisons."""

from __future__ import annotations

from ragops.schemas.experiment import ExperimentComparison
from ragops.schemas.release import ReleaseDecision, ReleasePolicy


class ReleaseGate:
    """Create a release recommendation without rerunning evaluation."""

    def decide(
        self,
        comparison: ExperimentComparison,
        policy: ReleasePolicy | None = None,
    ) -> ReleaseDecision:
        """Apply a policy to an existing comparison."""
        active_policy = policy if policy is not None else ReleasePolicy()
        return ReleaseDecision.from_comparison(comparison, active_policy)
