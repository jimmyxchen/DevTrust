"""Detector registry and scoring engine."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev_trust.models import AnalysisReport, SignalResult
from dev_trust.github.client import GitHubClient

if TYPE_CHECKING:
    from dev_trust.detector.base import BaseSignalDetector
    from dev_trust.models import StarEvent, Repository


class DetectorRegistry:
    """Registry that manages all signal detectors."""

    def __init__(self):
        self._detectors: list[BaseSignalDetector] = []
        self._total_weight: float = 0.0

    def register(self, detector: BaseSignalDetector) -> None:
        """Register a detector."""
        self._detectors.append(detector)
        self._total_weight += detector.get_weight()

    def get_detectors(self) -> list[BaseSignalDetector]:
        """Get all registered detectors."""
        return list(self._detectors)

    def get_total_weight(self) -> float:
        """Get total weight of all detectors."""
        return self._total_weight


class ScoringEngine:
    """Combines multiple signal results into an overall trust score."""

    # Signal weights (must sum to 1.0)
    WEIGHTS = {
        "timing_burst": 0.15,
        "account_age": 0.20,
        "user_activity": 0.20,
        "creation_cluster": 0.15,
        "cross_repo": 0.15,
        "network_analysis": 0.10,
        "commit_depth": 0.10,
        "behavioral_pattern": 0.10,
    }

    def __init__(self, github_client: GitHubClient):
        self.github_client = github_client

    def calculate_trust_score(self, signals: list[SignalResult]) -> AnalysisReport:
        """
        Calculate overall trust score from all signal results.

        Trust Score = 1.0 - (weighted average of suspicious percentages)
        """
        if not signals:
            raise ValueError("No signals to score")

        # Calculate weighted fake star percentage
        total_fake_weighted = 0.0
        total_weight = 0.0

        for signal in signals:
            weight = self.WEIGHTS.get(signal.name, 0.1)
            if signal.total_analyzed > 0:
                fake_ratio = signal.suspicious_count / signal.total_analyzed
            else:
                fake_ratio = 0.0

            # Weight by both the signal weight and its confidence
            effective_weight = weight * signal.confidence_score
            total_fake_weighted += fake_ratio * effective_weight
            total_weight += effective_weight

        if total_weight > 0:
            fake_star_percentage = total_fake_weighted / total_weight
        else:
            fake_star_percentage = 0.0

        fake_star_percentage = min(1.0, max(0.0, fake_star_percentage))
        trust_score = 1.0 - fake_star_percentage

        # Calculate overall confidence
        avg_confidence = sum(s.confidence_score for s in signals) / len(signals)

        # Determine risk level
        if fake_star_percentage < 0.2:
            risk_level = "low"
        elif fake_star_percentage < 0.5:
            risk_level = "medium"
        elif fake_star_percentage < 0.8:
            risk_level = "high"
        else:
            risk_level = "critical"

        # Collect flagged users across all signals
        flagged: dict[str, tuple[float, set[str]]] = {}
        for signal in signals:
            for user in signal.flagged_users:
                if user not in flagged:
                    flagged[user] = (0.0, set())
                flagged[user] = (flagged[user][0] + signal.confidence_score, flagged[user][1] | {signal.name})

        flagged_list = [
            (user, score / len(reasons), f"Suspicious in: {', '.join(sorted(reasons))}")
            for user, (score, reasons) in sorted(
                flagged.items(), key=lambda x: x[1][0], reverse=True
            )
        ]

        # Generate recommendations
        recommendations = self._generate_recommendations(signals, fake_star_percentage, risk_level)

        return AnalysisReport(
            trust_score=trust_score,
            fake_star_percentage=fake_star_percentage,
            confidence=avg_confidence,
            risk_level=risk_level,
            total_stars=0,
            analyzed_stars=sum(s.total_analyzed for s in signals),
            signals=signals,
            flagged_users=flagged_list,
            recommendations=recommendations,
        )

    def _generate_recommendations(
        self, signals: list[SignalResult], fake_pct: float, risk_level: str
    ) -> list[str]:
        """Generate actionable recommendations based on findings."""
        recs: list[str] = []

        if risk_level == "low":
            recs.append("The star count appears legitimate with minimal fake star indicators.")
        else:
            recs.append(
                f"Consider reviewing the flagged accounts - "
                f"estimated {fake_pct*100:.1f}% of stars may be fake."
            )

        # Signal-specific recommendations
        signal_names = {s.name: s for s in signals}

        if "timing_burst" in signal_names and signal_names["timing_burst"].confidence_score > 0.7:
            recs.append(
                "A timing burst was detected - stars came in an unnaturally short window. "
                "This is a strong indicator of a purchased star campaign."
            )

        if "account_age" in signal_names and signal_names["account_age"].confidence_score > 0.7:
            recs.append(
                "Many stargazers have very new accounts. "
                "Consider reviewing these accounts - they may be throwaway bot accounts."
            )

        if "user_activity" in signal_names and signal_names["user_activity"].confidence_score > 0.7:
            recs.append(
                "Many stargazers show no real GitHub activity beyond starring. "
                "These accounts have no meaningful contribution to the ecosystem."
            )

        if "creation_cluster" in signal_names and signal_names["creation_cluster"].confidence_score > 0.7:
            recs.append(
                "A coordinated campaign is likely - many accounts were created in the same time window. "
                "This pattern strongly suggests automated bot registration."
            )

        if "cross_repo" in signal_names and signal_names["cross_repo"].confidence_score > 0.7:
            recs.append(
                "Suspicious stargazers co-starred many identical repos. "
                "This is typical of fake star farm services that target multiple repos."
            )

        if risk_level in ("high", "critical"):
            recs.append(
                "Consider using GitHub's built-in star removal features "
                "if fake stars are confirmed."
            )

        return recs
