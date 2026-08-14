"""Main analysis engine that coordinates all detectors."""

from __future__ import annotations

from typing import Optional

from dev_trust.github.client import GitHubClient
from dev_trust.models import AnalysisReport, Repository, StarEvent
from dev_trust.detector.base import BaseSignalDetector
from dev_trust.detector.scorer import DetectorRegistry, ScoringEngine
from dev_trust.detector.timing_detector import TimingBurstDetector
from dev_trust.detector.account_age_detector import AccountAgeDetector
from dev_trust.detector.activity_detector import UserActivityDetector
from dev_trust.detector.cluster_detector import CreationClusterDetector
from dev_trust.detector.cross_repo_detector import CrossRepoDetector
from dev_trust.detector.network_detector import NetworkDetector
from dev_trust.detector.commit_depth_detector import CommitDepthDetector
from dev_trust.detector.pattern_detector import BehavioralPatternDetector


class DevTrustAnalyzer:
    """Main analysis engine that coordinates all signal detectors."""

    def __init__(
        self,
        github_client: Optional[GitHubClient] = None,
        sample_size: Optional[int] = None,
    ):
        self.github_client = github_client or GitHubClient()
        self.sample_size = sample_size
        self.registry = DetectorRegistry()
        self.scoring_engine = ScoringEngine(self.github_client)

        # Register all detectors
        self._register_detectors()

    def _register_detectors(self) -> None:
        """Register all signal detectors."""
        self.registry.register(TimingBurstDetector())
        self.registry.register(AccountAgeDetector())
        self.registry.register(UserActivityDetector(self.github_client))
        self.registry.register(CreationClusterDetector())
        self.registry.register(CrossRepoDetector(self.github_client))
        self.registry.register(NetworkDetector(self.github_client))
        self.registry.register(CommitDepthDetector(self.github_client))
        self.registry.register(BehavioralPatternDetector())

    def analyze_repo(self, owner: str, repo: str) -> AnalysisReport:
        """Run full analysis on a repository."""
        # Fetch repository info
        repository = self.github_client.get_repository(owner, repo)

        # Fetch stargazers
        print(f"Fetching stargazers for {owner}/{repo}...")
        star_events = self.github_client.get_stargazers(owner, repo, self.sample_size)

        if not star_events:
            print("No stars found for this repository.")
            return AnalysisReport(
                repo=repository,
                trust_score=1.0,
                fake_star_percentage=0.0,
                confidence=0.0,
                risk_level="low",
                total_stars=repository.stars_count,
                analyzed_stars=0,
                recommendations=["No stars to analyze."],
            )

        print(f"Analyzing {len(star_events)} stargazers with {len(self.registry.get_detectors())} signals...")

        # Convert star_events to serializable format for detectors
        repo_info = {
            "full_name": repository.full_name,
            "stars_count": repository.stars_count,
            "created_at": repository.created_at.isoformat(),
            "language": repository.language,
        }

        # Run all detectors
        signals: list[SignalResult] = []
        detectors = self.registry.get_detectors()

        for i, detector in enumerate(detectors):
            try:
                result = detector.detect(star_events, repo_info)
                signals.append(result)
                status = (
                    f"\033[91mCRITICAL\033[0m"
                    if result.confidence_score > 0.7 and result.suspicious_count > 0
                    else (
                        f"\033[93mHIGH\033[0m"
                        if result.confidence_score > 0.5 and result.suspicious_count > 0
                        else (
                            f"\033[92mLOW\033[0m"
                            if result.confidence_score > 0.3 and result.suspicious_count > 0
                            else f"\033[90mNONE\033[0m"
                        )
                    )
                )
                print(
                    f"  [{i+1}/{len(detectors)}] {detector.name:25s} {status} "
                    f"(flagged: {result.suspicious_count}/{result.total_analyzed})"
                )
            except Exception as e:
                print(f"  [{i+1}/{len(detectors)}] {detector.name:25s} \033[90mERROR: {e}\033[0m")
                continue

        # Calculate overall score
        report = self.scoring_engine.calculate_trust_score(signals)
        report.repo = repository
        report.total_stars = repository.stars_count

        return report


# Backward-compatible alias
DevTrustAnalyzer = DevTrustAnalyzer
