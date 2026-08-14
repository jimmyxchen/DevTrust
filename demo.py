"""Demo script showing DevTrust analysis with synthetic data.

Run: python demo.py
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

# Seed for reproducibility
random.seed(42)

from dev_trust.models import GitHubUser, Repository, StarEvent, SignalResult, UserActivity
from dev_trust.analyzer import DevTrustAnalyzer
from dev_trust.detector.scorer import ScoringEngine
from dev_trust.detector.timing_detector import TimingBurstDetector
from dev_trust.detector.account_age_detector import AccountAgeDetector
from dev_trust.detector.activity_detector import UserActivityDetector
from dev_trust.detector.cluster_detector import CreationClusterDetector
from dev_trust.detector.cross_repo_detector import CrossRepoDetector
from dev_trust.detector.network_detector import NetworkDetector
from dev_trust.detector.commit_depth_detector import CommitDepthDetector
from dev_trust.detector.pattern_detector import BehavioralPatternDetector


def make_fake_star_burst(n: int = 50) -> list[StarEvent]:
    """Simulate a fake star burst campaign."""
    events = []
    now = datetime.now(timezone.utc)
    burst_time = now - timedelta(hours=2)  # All stars in 2-hour window

    for i in range(n):
        # Bots: created 1-5 days ago
        account_age = random.randint(0, 5)
        user = GitHubUser(
            login=f"bot_account_{random.randint(1000, 9999)}",
            id=10_000 + i,
            avatar_url=f"https://avatars.githubusercontent.com/u/{10_000 + i}?v=4",
            html_url=f"https://github.com/bot_account_{i}",
            type="User",
            site_admin=False,
            name=None,
            company=None,
            blog=None,
            location=None,
            email=None,
            bio=None,
            public_repos=random.randint(0, 2),
            public_gists=0,
            followers=0,
            following=random.randint(0, 5),
            created_at=burst_time - timedelta(days=account_age),
            updated_at=burst_time,
            has_default_avatar=True,
        )
        # Stars clustered in a 2-hour window
        starred_at = burst_time + timedelta(minutes=random.randint(0, 120))
        events.append(StarEvent(
            user=user,
            starred_at=starred_at,
            repo_full_name="practical-tutorials/project-based-learning",
        ))

    return sorted(events, key=lambda e: e.starred_at)


def make_legitimate_stars(n: int = 30) -> list[StarEvent]:
    """Simulate legitimate organic stars spread over months."""
    events = []
    now = datetime.now(timezone.utc)

    for i in range(n):
        account_age = random.randint(200, 3000)  # Old accounts
        user = GitHubUser(
            login=f"real_dev_{i}",
            id=1_000_000 + i,
            avatar_url=f"https://avatars.githubusercontent.com/u/{1_000_000 + i}?v=4",
            html_url=f"https://github.com/real_dev_{i}",
            type="User",
            site_admin=False,
            name=f"Real Developer {i}",
            company="Acme Corp",
            blog=f"https://realdev{i}.blog.dev",
            location="San Francisco, CA",
            email=f"dev{i}@example.com",
            bio="Full-stack developer | Open source enthusiast",
            public_repos=random.randint(10, 150),
            public_gists=random.randint(0, 20),
            followers=random.randint(5, 500),
            following=random.randint(10, 200),
            created_at=now - timedelta(days=account_age),
            updated_at=now - timedelta(days=random.randint(0, 30)),
            has_default_avatar=False,
        )
        # Stars spread over the last 3 months
        starred_at = now - timedelta(days=random.randint(0, 90))
        events.append(StarEvent(
            user=user,
            starred_at=starred_at,
            repo_full_name="practical-tutorials/project-based-learning",
        ))

    return sorted(events, key=lambda e: e.starred_at)


def run_demo():
    """Run the full DevTrust demo."""
    print()
    print("=" * 70)
    print("  DevTrust Demo — Fake Star Detection")
    print("  Repo: practical-tutorials/project-based-learning")
    print("=" * 70)
    print()

    now = datetime.now(timezone.utc)
    repo = Repository(
        full_name="practical-tutorials/project-based-learning",
        owner="practical-tutorials",
        name="project-based-learning",
        description="Curated list of project-based tutorials",
        html_url="https://github.com/practical-tutorials/project-based-learning",
        stars_count=175_000,
        forks_count=23_000,
        open_issues=312,
        created_at=datetime(2019, 1, 1, tzinfo=timezone.utc),
        updated_at=now,
        language="HTML",
        topics=["tutorial", "projects", "learning"],
    )

    # Mix: 60 fake stars + 40 legitimate = 100 total
    fake_stars = make_fake_star_burst(60)
    legitimate_stars = make_legitimate_stars(40)
    all_events = sorted(fake_stars + legitimate_stars, key=lambda e: e.starred_at)

    print(f"  Repository:  {repo.full_name}")
    print(f"  Stars:       {repo.stars_count:,}")
    print(f"  Analyzed:    {len(all_events)} (50 fake + 50 legitimate simulated)")
    print()

    repo_info = {
        "full_name": repo.full_name,
        "stars_count": repo.stars_count,
        "created_at": repo.created_at.isoformat(),
        "language": repo.language,
    }

    # Create a mock GitHub client to avoid real API calls in demo
    mock_github_client = MagicMock()

    def mock_get_user_events(login, days=90):
        """Return mock user activity with some events to simulate real users."""
        activity = UserActivity(user_login=login)
        activity.total_events = 15
        activity.push_events = 3
        activity.pull_request_events = 2
        activity.issue_events = 1
        activity.create_events = 2
        activity.watch_events = 5
        activity.fork_events = 2
        activity.other_events = 0
        activity.activity_types = {"PushEvent", "PullRequestEvent", "WatchEvent", "CreateEvent", "IssuesEvent"}
        activity.first_event_date = datetime.now(timezone.utc) - timedelta(days=60)
        activity.last_event_date = datetime.now(timezone.utc) - timedelta(days=1)
        activity.starred_repos_sample = ["octocat/Hello-World", "torvalds/linux"]
        return activity

    def mock_get_user_starred_repos(login, limit=30):
        """Return mock starred repos."""
        return [f"user_{i}/repo_{j}" for i in range(5) for j in range(3)]

    mock_github_client.get_user_events.side_effect = mock_get_user_events
    mock_github_client.get_user_starred_repos.side_effect = mock_get_user_starred_repos

    # Create analyzer with the mock client so detectors use it
    analyzer = DevTrustAnalyzer(github_client=mock_github_client)
    detectors = analyzer.registry.get_detectors()

    signals = []
    for i, detector in enumerate(detectors):
        try:
            result = detector.detect(all_events, repo_info)
            signals.append(result)
            status = (
                "\033[91mCRITICAL\033[0m" if result.confidence_score > 0.7 and result.suspicious_count > 0
                else ("\033[93mHIGH\033[0m" if result.confidence_score > 0.5 and result.suspicious_count > 0
                else ("\033[92mLOW\033[0m" if result.confidence_score > 0.3 and result.suspicious_count > 0
                else "\033[90mNONE\033[0m"))
            )
            print(
                f"  [{i+1}/{len(detectors)}] {detector.name:25s} {status} "
                f"(flagged: {result.suspicious_count}/{result.total_analyzed})"
            )
        except Exception as e:
            print(f"  [{i+1}/{len(detectors)}] {detector.name:25s} \033[90mERROR: {e}\033[0m")

    print()

    # Score
    scoring = ScoringEngine(MagicMock())
    report = scoring.calculate_trust_score(signals)
    report.repo = repo
    report.total_stars = repo.stars_count
    report.analyzed_stars = len(all_events)

    # Print report
    from dev_trust.reporter import Reporter
    Reporter(report).print_text_report()


if __name__ == "__main__":
    run_demo()
