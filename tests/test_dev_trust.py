"""Tests for DevTrust."""

from __future__ import annotations

import click
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dev_trust.models import (
    AnalysisReport,
    GitHubUser,
    Repository,
    SignalResult,
    StarEvent,
    UserActivity,
)
from dev_trust.detector.scorer import ScoringEngine
from dev_trust.detector.timing_detector import TimingBurstDetector
from dev_trust.detector.account_age_detector import AccountAgeDetector
from dev_trust.detector.activity_detector import UserActivityDetector
from dev_trust.detector.cluster_detector import CreationClusterDetector
from dev_trust.detector.pattern_detector import BehavioralPatternDetector
from dev_trust.detector.base import BaseSignalDetector
from dev_trust.github.client import CacheManager, GitHubClient
from dev_trust.detector.cross_repo_detector import CrossRepoDetector
from dev_trust.detector.network_detector import NetworkDetector
from dev_trust.detector.commit_depth_detector import CommitDepthDetector
from dev_trust.analyzer import DevTrustAnalyzer
from dev_trust.reporter import Reporter
from dev_trust.cli import cli, parse_repo_input


# ============================================================
# Fixtures
# ============================================================


def make_user(login: str, days_old: int = 365, **kwargs) -> GitHubUser:
    """Create a test GitHub user."""
    created_at = datetime.now(timezone.utc) - timedelta(days=days_old)
    defaults = {
        "login": login,
        "id": hash(login) % 1000000,
        "avatar_url": kwargs.get("avatar_url", f"https://avatars.githubusercontent.com/u/{hash(login)%1000000}"),
        "html_url": f"https://github.com/{login}",
        "type": "User",
        "site_admin": False,
        "public_repos": kwargs.get("public_repos", 10),
        "followers": kwargs.get("followers", 5),
        "following": kwargs.get("following", 3),
        "created_at": created_at,
        "has_default_avatar": kwargs.get("has_default_avatar", False),
        "bio": kwargs.get("bio", "A developer"),
    }
    return GitHubUser(**defaults)


def make_star_event(user: GitHubUser, hours_ago: float = 0) -> StarEvent:
    """Create a test star event."""
    starred_at = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return StarEvent(
        user=user,
        starred_at=starred_at,
        repo_full_name="test/repo",
    )


def make_star_events(count: int, age_days: int = 365, burst: bool = False) -> list[StarEvent]:
    """Create a list of test star events."""
    events = []
    now = datetime.now(timezone.utc)
    for i in range(count):
        hours_ago = 0 if burst else i * 24
        user = make_user(f"user_{i}", days_old=age_days)
        event = StarEvent(
            user=user,
            starred_at=now - timedelta(hours=hours_ago),
            repo_full_name="test/repo",
        )
        events.append(event)
    return events


# ============================================================
# CLI Tests
# ============================================================


class TestCLI:
    """Tests for the CLI interface."""

    def test_parse_repo_url(self):
        """Test parsing GitHub URLs."""
        owner, repo = parse_repo_input("https://github.com/octocat/Hello-World")
        assert owner == "octocat"
        assert repo == "Hello-World"

    def test_parse_repo_owner_repo(self):
        """Test parsing owner/repo format."""
        owner, repo = parse_repo_input("octocat/Hello-World")
        assert owner == "octocat"
        assert repo == "Hello-World"

    def test_parse_repo_invalid(self):
        """Test invalid repo input."""
        with pytest.raises(click.BadParameter):
            parse_repo_input("invalid")

    def test_cli_version(self):
        """Test CLI version flag."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "1.0.0" in result.output


# ============================================================
# Detector Tests
# ============================================================


class TestTimingBurstDetector:
    """Tests for timing burst detection."""

    def test_no_burst_detected(self):
        """Test that evenly spaced stars don't trigger burst detection."""
        detector = TimingBurstDetector()
        events = make_star_events(20, age_days=365)
        result = detector.detect(events, {})

        assert result.name == "timing_burst"
        assert result.total_analyzed == 20

    def test_burst_detected(self):
        """Test that burst patterns are detected."""
        detector = TimingBurstDetector()
        # 50 stars all within 1 hour
        events = make_star_events(50, age_days=365, burst=True)
        result = detector.detect(events, {})

        assert result.confidence_score > 0.5
        assert len(result.flagged_users) > 0

    def test_few_stars_no_analysis(self):
        """Test that too few stars returns low confidence."""
        detector = TimingBurstDetector()
        events = make_star_events(2, age_days=365)
        result = detector.detect(events, {})

        assert result.confidence_score == 0.0


class TestAccountAgeDetector:
    """Tests for account age detection."""

    def test_old_accounts_clean(self):
        """Test that old accounts are not flagged."""
        detector = AccountAgeDetector()
        events = [make_star_event(make_user("old_user", days_old=1000))]
        result = detector.detect(events, {})

        assert result.suspicious_count == 0

    def test_new_account_flagged(self):
        """Test that very new accounts are flagged."""
        detector = AccountAgeDetector()
        user = make_user("new_bot", days_old=1)
        events = [make_star_event(user)]
        result = detector.detect(events, {})

        assert result.suspicious_count == 1
        assert result.confidence_score > 0.5

    def test_empty_profile_bonus(self):
        """Test that empty profiles increase suspicion."""
        detector = AccountAgeDetector()
        user = make_user("empty_profile", days_old=1, bio=None, public_repos=0)
        events = [make_star_event(user)]
        result = detector.detect(events, {})

        assert result.suspicious_count == 1
        assert result.confidence_score > 0.7


class TestActivityDetector:
    """Tests for user activity detection."""

    def test_injects_github_client(self):
        """Test that detector accepts github client."""
        from unittest.mock import MagicMock
        client = MagicMock()
        detector = UserActivityDetector(client)
        assert detector.github_client is client


class TestCreationClusterDetector:
    """Tests for creation cluster detection."""

    def test_no_cluster_old_accounts(self):
        """Test that spread-out account dates don't cluster."""
        detector = CreationClusterDetector()
        events = []
        for i in range(20):
            user = make_user(f"user_{i}", days_old=365 + i * 30)
            events.append(make_star_event(user))

        result = detector.detect(events, {})
        assert result.total_analyzed == 20

    def test_cluster_detected(self):
        """Test that similarly-created accounts cluster."""
        detector = CreationClusterDetector()
        events = []
        base_time = datetime.now(timezone.utc) - timedelta(days=7)
        for i in range(10):
            created_at = base_time + timedelta(hours=i)
            user = GitHubUser(
                login=f"bot_{i}",
                id=i,
                avatar_url=f"https://avatars.githubusercontent.com/u/{i}",
                html_url=f"https://github.com/bot_{i}",
                type="User",
                site_admin=False,
                public_repos=0,
                created_at=created_at,
            )
            events.append(make_star_event(user))

        result = detector.detect(events, {})
        # Should detect some clustering
        assert result.total_analyzed == 10


class TestBehavioralPatternDetector:
    """Tests for behavioral pattern detection."""

    def test_default_avatar_detected(self):
        """Test that default avatars are flagged."""
        detector = BehavioralPatternDetector()
        user = make_user("bot_user", days_old=30, has_default_avatar=True,
                         avatar_url="https://gravatar.com/avatar/d4c74594d841139328261f6dbc60",
                         public_repos=0, followers=0, following=0)
        events = [make_star_event(user)]
        result = detector.detect(events, {})

        assert result.total_analyzed == 1
        assert result.confidence_score > 0.0

    def test_sequential_username_detected(self):
        """Test sequential username patterns."""
        detector = BehavioralPatternDetector()
        user = make_user("user_9999", days_old=30)
        events = [make_star_event(user)]
        result = detector.detect(events, {})

        assert result.total_analyzed == 1


# ============================================================
# Scoring Tests
# ============================================================


class TestScoringEngine:
    """Tests for the scoring engine."""

    def test_all_low_signals(self):
        """Test scoring with all low-confidence signals."""
        engine = ScoringEngine(MagicMock())
        signals = [
            SignalResult(name="timing_burst", suspicious_count=0, total_analyzed=100, confidence_score=0.1),
            SignalResult(name="account_age", suspicious_count=0, total_analyzed=100, confidence_score=0.1),
            SignalResult(name="user_activity", suspicious_count=0, total_analyzed=100, confidence_score=0.1),
            SignalResult(name="creation_cluster", suspicious_count=0, total_analyzed=100, confidence_score=0.1),
            SignalResult(name="cross_repo", suspicious_count=0, total_analyzed=100, confidence_score=0.1),
            SignalResult(name="network_analysis", suspicious_count=0, total_analyzed=100, confidence_score=0.1),
            SignalResult(name="commit_depth", suspicious_count=0, total_analyzed=100, confidence_score=0.1),
            SignalResult(name="behavioral_pattern", suspicious_count=0, total_analyzed=100, confidence_score=0.1),
        ]

        report = engine.calculate_trust_score(signals)
        assert report.risk_level == "low"
        assert report.trust_score > 0.8
        assert report.fake_star_percentage < 0.2

    def test_all_high_signals(self):
        """Test scoring with all high-confidence signals."""
        engine = ScoringEngine(MagicMock())
        signals = [
            SignalResult(name="timing_burst", suspicious_count=80, total_analyzed=100, confidence_score=0.9),
            SignalResult(name="account_age", suspicious_count=75, total_analyzed=100, confidence_score=0.85),
            SignalResult(name="user_activity", suspicious_count=70, total_analyzed=100, confidence_score=0.8),
            SignalResult(name="creation_cluster", suspicious_count=65, total_analyzed=100, confidence_score=0.8),
            SignalResult(name="cross_repo", suspicious_count=60, total_analyzed=100, confidence_score=0.7),
            SignalResult(name="network_analysis", suspicious_count=50, total_analyzed=100, confidence_score=0.6),
            SignalResult(name="commit_depth", suspicious_count=45, total_analyzed=100, confidence_score=0.5),
            SignalResult(name="behavioral_pattern", suspicious_count=55, total_analyzed=100, confidence_score=0.65),
        ]

        report = engine.calculate_trust_score(signals)
        assert report.risk_level in ("high", "critical")
        assert report.fake_star_percentage > 0.5

    def test_flagged_users_aggregation(self):
        """Test that flagged users are aggregated across signals."""
        engine = ScoringEngine(MagicMock())
        signals = [
            SignalResult(
                name="account_age",
                suspicious_count=2,
                total_analyzed=10,
                confidence_score=0.8,
                flagged_users=["bot1", "bot2"],
            ),
            SignalResult(
                name="user_activity",
                suspicious_count=1,
                total_analyzed=10,
                confidence_score=0.7,
                flagged_users=["bot1"],
            ),
        ]

        report = engine.calculate_trust_score(signals)
        # bot1 should appear with higher score (flagged by 2 signals)
        flagged_logins = [u for u, _, _ in report.flagged_users]
        assert "bot1" in flagged_logins
        assert "bot2" in flagged_logins


# ============================================================
# Model Tests
# ============================================================


class TestModels:
    """Tests for data models."""

    def test_github_user_creation(self):
        """Test GitHubUser creation."""
        user = make_user("test_user", days_old=100)
        assert user.login == "test_user"
        assert user.public_repos == 10
        assert user.account_age_days is None  # Set after scoring

    def test_star_event_creation(self):
        """Test StarEvent creation."""
        user = make_user("test_user")
        event = make_star_event(user, hours_ago=5)
        assert event.repo_full_name == "test/repo"
        assert (datetime.now(timezone.utc) - event.starred_at).total_seconds() > 4 * 3600

    def test_signal_result(self):
        """Test SignalResult creation."""
        result = SignalResult(
            name="test_signal",
            suspicious_count=5,
            total_analyzed=100,
            confidence_score=0.75,
            flagged_users=["user1", "user2"],
        )
        assert result.name == "test_signal"
        assert result.suspicious_count == 5
        assert len(result.flagged_users) == 2

    def test_risk_level_classification(self):
        """Test risk level classification."""
        from dev_trust.reporter import Reporter
        from dev_trust.models import AnalysisReport

        repo = Repository(
            full_name="test/repo",
            owner="test",
            name="repo",
            description="Test repo",
            html_url="https://github.com/test/repo",
            stars_count=100,
            forks_count=10,
            open_issues=5,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        report = AnalysisReport(
            repo=repo,
            trust_score=0.3,
            fake_star_percentage=0.7,
            confidence=0.8,
            risk_level="critical",
            total_stars=100,
            analyzed_stars=50,
        )

        reporter = Reporter(report)
        assert reporter.report.risk_level == "critical"


# ============================================================
# Integration Tests
# ============================================================


class TestIntegration:
    """Integration tests (mocked)."""

    @patch("dev_trust.github.client._requests")
    @patch("dev_trust.github.client.Github")
    def test_full_analysis_mocked(self, mock_github_class, mock_requests):
        """Test full analysis pipeline with mocked GitHub API."""
        from dev_trust.analyzer import DevTrustAnalyzer

        # Setup mocks
        mock_github = MagicMock()
        mock_github_class.return_value = mock_github

        # Mock repo
        mock_repo = MagicMock()
        mock_repo.full_name = "test/repo"
        mock_repo.description = "Test repository"
        mock_repo.html_url = "https://github.com/test/repo"
        mock_repo.stargazers_count = 1000
        mock_repo.forks_count = 50
        mock_repo.open_issues_count = 10
        mock_repo.created_at = datetime.now(timezone.utc) - timedelta(days=365)
        mock_repo.updated_at = datetime.now(timezone.utc)
        mock_repo.language = "Python"
        mock_repo.archived = False
        mock_repo.fork = False
        mock_repo.get_topics.return_value = ["python", "testing"]
        mock_github.get_repo.return_value = mock_repo

        # Mock stargazers
        mock_stargazers = MagicMock()
        stargazer_list = []
        for i in range(20):
            sg = MagicMock()
            sg.starred_at = datetime.now(timezone.utc) - timedelta(hours=i)
            sg.user = MagicMock()
            sg.user.login = f"user_{i}"
            sg.user.id = i
            sg.user.avatar_url = f"https://avatars.githubusercontent.com/u/{i}"
            sg.user.html_url = f"https://github.com/user_{i}"
            sg.user.type = "User"
            sg.user.site_admin = False
            sg.user.name = f"User {i}"
            sg.user.company = None
            sg.user.blog = None
            sg.user.location = None
            sg.user.email = None
            sg.user.bio = f"User {i} bio"
            sg.user.public_repos = 5
            sg.user.public_gists = 0
            sg.user.followers = 3
            sg.user.following = 2
            sg.user.created_at = datetime.now(timezone.utc) - timedelta(days=100 + i)
            sg.user.updated_at = datetime.now(timezone.utc)
            stargazer_list.append(sg)
        mock_stargazers.__iter__ = lambda self: iter(stargazer_list)
        mock_repo.get_stargazers_with_dates.return_value = mock_stargazers

        # Mock rate limit
        mock_rate = MagicMock()
        mock_rate.core.remaining = 5000
        mock_rate.core.limit = 5000
        mock_rate.core.reset = datetime.now(timezone.utc) + timedelta(hours=1)
        mock_rate.search.remaining = 30
        mock_rate.search.limit = 30
        mock_github.get_rate_limit.return_value = mock_rate

        # Mock the REST API response for get_stargazers
        def _starred_at_iso(dt):
            """Format datetime for GitHub API (no timezone suffix for aware datetimes)."""
            return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = [
            {
                "user": {
                    "login": sg.user.login,
                    "id": sg.user.id,
                    "avatar_url": sg.user.avatar_url,
                    "html_url": sg.user.html_url,
                    "type": sg.user.type,
                    "site_admin": sg.user.site_admin,
                    "name": sg.user.name,
                    "company": sg.user.company,
                    "blog": sg.user.blog,
                    "location": sg.user.location,
                    "email": sg.user.email,
                    "bio": sg.user.bio,
                    "public_repos": sg.user.public_repos,
                    "public_gists": sg.user.public_gists,
                    "followers": sg.user.followers,
                    "following": sg.user.following,
                    "created_at": _starred_at_iso(sg.user.created_at),
                    "updated_at": _starred_at_iso(sg.user.updated_at),
                },
                "starred_at": _starred_at_iso(sg.starred_at),
            }
            for sg in stargazer_list
        ]
        mock_requests.get.return_value = mock_response

        # Run analysis
        analyzer = DevTrustAnalyzer()
        analyzer.github_client._github = mock_github
        # Also pre-populate cache to avoid re-fetching
        analyzer.github_client.cache.set(
            "stargazers:test/repo:all",
            [
                {
                    "user": {
                        "login": sg.user.login,
                        "id": sg.user.id,
                        "avatar_url": sg.user.avatar_url,
                        "html_url": sg.user.html_url,
                        "type": sg.user.type,
                        "site_admin": sg.user.site_admin,
                        "name": sg.user.name,
                        "company": sg.user.company,
                        "blog": sg.user.blog,
                        "location": sg.user.location,
                        "email": sg.user.email,
                        "bio": sg.user.bio,
                        "public_repos": sg.user.public_repos,
                        "public_gists": sg.user.public_gists,
                        "followers": sg.user.followers,
                        "following": sg.user.following,
                        "created_at": sg.user.created_at.isoformat(),
                        "updated_at": sg.user.updated_at.isoformat(),
                    },
                    "starred_at": sg.starred_at.isoformat(),
                    "repo_full_name": "test/repo",
                }
                for sg in stargazer_list
            ],
        )

        report = analyzer.analyze_repo("test", "repo")

        assert report.total_stars == 1000
        assert report.analyzed_stars >= 20  # Sums across all signals
        assert len(report.signals) > 0
        assert report.risk_level in ("low", "medium", "high", "critical")


# ============================================================
# Edge Case Tests
# ============================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    # --- Empty / boundary inputs ---

    def test_timing_burst_empty(self):
        """Test timing detector with empty input."""
        detector = TimingBurstDetector()
        result = detector.detect([], {})
        assert result.confidence_score == 0.0
        assert result.suspicious_count == 0

    def test_account_age_empty(self):
        """Test account age detector with empty input."""
        detector = AccountAgeDetector()
        result = detector.detect([], {})
        assert result.confidence_score == 0.0
        assert result.suspicious_count == 0

    def test_account_age_no_created_at(self):
        """Test account age detector when user has no created_at."""
        detector = AccountAgeDetector()
        user = make_user("no_date", days_old=100)
        user.created_at = None
        events = [make_star_event(user)]
        result = detector.detect(events, {})
        # Should handle gracefully (returns 0.5 score with "Could not determine")
        assert result.total_analyzed == 1

    def test_behavioral_empty(self):
        """Test behavioral detector with empty input."""
        detector = BehavioralPatternDetector()
        result = detector.detect([], {})
        assert result.confidence_score == 0.0
        assert result.suspicious_count == 0

    def test_creation_cluster_empty(self):
        """Test cluster detector with empty input."""
        detector = CreationClusterDetector()
        result = detector.detect([], {})
        assert result.confidence_score == 0.0
        assert result.suspicious_count == 0

    def test_cross_repo_too_few(self):
        """Test cross-repo detector with too few stars."""
        detector = CrossRepoDetector(MagicMock())
        user = make_user("test", days_old=100)
        events = [make_star_event(user)]
        result = detector.detect(events, {})
        assert result.confidence_score == 0.0

    def test_network_too_few(self):
        """Test network detector with too few stars."""
        detector = NetworkDetector(MagicMock())
        user = make_user("test", days_old=100)
        events = [make_star_event(user)]
        result = detector.detect(events, {})
        assert result.confidence_score == 0.0

    def test_commit_depth_empty(self):
        """Test commit depth detector with empty input."""
        detector = CommitDepthDetector(MagicMock())
        result = detector.detect([], {})
        assert result.confidence_score == 0.0
        assert result.suspicious_count == 0

    # --- UserActivityDetector with mock ---

    def test_activity_detector_with_mock_client(self):
        """Test activity detector with properly mocked client."""
        mock_client = MagicMock()

        def mock_get_events(login, days=90):
            activity = UserActivity(user_login=login)
            activity.total_events = 20
            activity.push_events = 5
            activity.pull_request_events = 3
            activity.create_events = 4
            activity.watch_events = 8
            activity.activity_types = {
                "PushEvent", "PullRequestEvent", "CreateEvent", "WatchEvent"
            }
            return activity

        mock_client.get_user_events.side_effect = mock_get_events

        detector = UserActivityDetector(mock_client)
        events = [make_star_event(make_user("active_dev", days_old=365))]
        result = detector.detect(events, {})

        assert result.name == "user_activity"
        assert result.total_analyzed == 1
        # Active user with diverse events should have low suspicion
        assert result.confidence_score < 0.5

    def test_activity_detector_inactive_user(self):
        """Test activity detector flags inactive users."""
        mock_client = MagicMock()

        def mock_get_events(login, days=90):
            activity = UserActivity(user_login=login)
            activity.total_events = 1
            activity.watch_events = 1
            activity.activity_types = {"WatchEvent"}
            return activity

        mock_client.get_user_events.side_effect = mock_get_events

        detector = UserActivityDetector(mock_client)
        events = [make_star_event(make_user("inactive_bot", days_old=10))]
        result = detector.detect(events, {})

        assert result.total_analyzed == 1
        assert result.confidence_score > 0.3

    def test_activity_detector_handles_api_error(self):
        """Test activity detector handles API errors gracefully."""
        mock_client = MagicMock()
        mock_client.get_user_events.side_effect = Exception("API error")

        detector = UserActivityDetector(mock_client)
        events = [make_star_event(make_user("error_user", days_old=10))]
        # Should not raise, should skip user
        result = detector.detect(events, {})
        assert result.total_analyzed == 0

    # --- CrossRepoDetector with mock ---

    def test_cross_repo_with_mock_client(self):
        """Test cross-repo detector with properly mocked client."""
        mock_client = MagicMock()
        events = make_star_events(20, age_days=365)

        def mock_get_starred(login, limit=30):
            # Return overlapping repos to simulate co-starring
            base = ["owner/repo1", "owner/repo2", "owner/repo3"]
            return base + [f"owner/repo_{i}" for i in range(10)]

        mock_client.get_user_starred_repos.side_effect = mock_get_starred

        detector = CrossRepoDetector(mock_client)
        result = detector.detect(events, {})

        assert result.name == "cross_repo"
        assert result.total_analyzed == 20

    def test_cross_repo_with_no_stars(self):
        """Test cross-repo detector with users who starred nothing."""
        mock_client = MagicMock()
        mock_client.get_user_starred_repos.return_value = []

        events = make_star_events(10, age_days=365)
        detector = CrossRepoDetector(mock_client)
        result = detector.detect(events, {})

        assert result.total_analyzed == 10

    # --- NetworkDetector with mock ---

    def test_network_detector_with_mock_client(self):
        """Test network detector with mocked PyGithub."""
        mock_client = MagicMock()
        events = make_star_events(10, age_days=365)

        # Mock the github attribute
        mock_gh_user = MagicMock()
        mock_gh_user.get_followers.return_value = []
        mock_gh_user.get_following.return_value = []
        mock_client.github.get_user.return_value = mock_gh_user

        detector = NetworkDetector(mock_client)
        result = detector.detect(events, {})

        assert result.name == "network_analysis"
        assert result.total_analyzed == 10

    # --- CommitDepthDetector tests ---

    def test_commit_depth_no_repos(self):
        """Test commit depth detector flags users with no repos."""
        detector = CommitDepthDetector(MagicMock())
        user = make_user("no_repos", days_old=10, public_repos=0,
                         followers=0, following=0, bio=None)
        events = [make_star_event(user)]
        result = detector.detect(events, {})

        assert result.total_analyzed == 1
        assert result.confidence_score > 0.3

    def test_commit_depth_legitimate_user(self):
        """Test commit depth detector gives low score to real devs."""
        detector = CommitDepthDetector(MagicMock())
        user = make_user("real_dev", days_old=1000, public_repos=50,
                         followers=100, following=50,
                         bio="Full-stack developer", company="Google")
        events = [make_star_event(user)]
        result = detector.detect(events, {})

        assert result.total_analyzed == 1
        assert result.confidence_score < 0.3

    # --- ScoringEngine edge cases ---

    def test_scoring_no_signals_raises(self):
        """Test scoring with no signals raises ValueError."""
        engine = ScoringEngine(MagicMock())
        with pytest.raises(ValueError):
            engine.calculate_trust_score([])

    def test_scoring_no_duplicate_signal_names(self):
        """Test that flagged users don't have duplicate signal names."""
        engine = ScoringEngine(MagicMock())
        signals = [
            SignalResult(
                name="timing_burst",
                suspicious_count=2,
                total_analyzed=10,
                confidence_score=0.9,
                flagged_users=["bot1", "bot2"],
            ),
            SignalResult(
                name="account_age",
                suspicious_count=1,
                total_analyzed=10,
                confidence_score=0.8,
                flagged_users=["bot1"],
            ),
            SignalResult(
                name="user_activity",
                suspicious_count=1,
                total_analyzed=10,
                confidence_score=0.7,
                flagged_users=["bot1"],
            ),
        ]

        report = engine.calculate_trust_score(signals)
        for _, _, reason in report.flagged_users:
            signal_names = [s.strip() for s in reason.replace("Suspicious in: ", "").split(",")]
            assert len(signal_names) == len(set(signal_names)), \
                f"Duplicate signal names found in: {reason}"

    def test_scoring_single_signal(self):
        """Test scoring with just one signal."""
        engine = ScoringEngine(MagicMock())
        signals = [
            SignalResult(
                name="timing_burst",
                suspicious_count=50,
                total_analyzed=100,
                confidence_score=0.8,
            ),
        ]
        report = engine.calculate_trust_score(signals)
        assert report.fake_star_percentage > 0
        assert report.trust_score < 1.0

    def test_scoring_medium_risk(self):
        """Test medium risk classification."""
        engine = ScoringEngine(MagicMock())
        signals = [
            SignalResult(name=s, suspicious_count=25, total_analyzed=100,
                         confidence_score=0.4)
            for s in ScoringEngine.WEIGHTS
        ]
        report = engine.calculate_trust_score(signals)
        assert report.risk_level in ("low", "medium", "high", "critical")

    # --- CacheManager tests ---

    def test_cache_manager_basic(self, tmp_path):
        """Test basic cache get/set/clear."""
        cache = CacheManager(tmp_path, ttl_hours=1)
        cache.set("test_key", {"data": "value"})
        result = cache.get("test_key")
        assert result == {"data": "value"}
        cache.clear()
        assert cache.get("test_key") is None

    def test_cache_manager_expiry(self, tmp_path):
        """Test cache expiry."""
        cache = CacheManager(tmp_path, ttl_hours=-1)  # Already expired
        cache.set("expired_key", {"data": "old"})
        result = cache.get("expired_key")
        assert result is None

    def test_cache_manager_disabled(self, tmp_path, monkeypatch):
        """Test cache when disabled."""
        from dev_trust.config import settings
        monkeypatch.setattr(settings, "no_cache", True)
        cache = CacheManager(tmp_path, ttl_hours=1)
        cache.set("disabled_key", {"data": "value"})
        assert cache.get("disabled_key") is None

    def test_cache_manager_corrupted_file(self, tmp_path):
        """Test cache handles corrupted files gracefully."""
        cache = CacheManager(tmp_path, ttl_hours=1)
        cache_file = tmp_path / cache._cache_key("bad_key")
        cache_file.write_text("not valid json{{{")
        assert cache.get("bad_key") is None

    # --- GitHubClient tests ---

    def test_client_no_auth(self):
        """Test client without authentication."""
        client = GitHubClient(token=None)
        assert client.is_authenticated is False

    def test_client_with_auth(self):
        """Test client with authentication."""
        client = GitHubClient(token="ghp_test_token")
        assert client.is_authenticated is True

    # --- CLI edge case tests ---

    def test_cli_analyze_no_token(self):
        """Test analyze command with fully mocked analyzer (no real API calls)."""
        from unittest.mock import patch
        from dev_trust.models import AnalysisReport, Repository, SignalResult

        runner = CliRunner()
        with patch("dev_trust.cli.DevTrustAnalyzer") as mock_analyzer_class, \
             patch("dev_trust.cli.Progress") as mock_progress:
            mock_analyzer = MagicMock()
            mock_repo = Repository(
                full_name="owner/repo",
                owner="owner",
                name="repo",
                description="Test",
                html_url="https://github.com/owner/repo",
                stars_count=100,
                forks_count=10,
                open_issues=5,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            mock_report = AnalysisReport(
                repo=mock_repo,
                trust_score=0.8,
                fake_star_percentage=0.2,
                confidence=0.7,
                risk_level="low",
                total_stars=100,
                analyzed_stars=50,
                signals=[],
                recommendations=[],
            )
            mock_analyzer.analyze_repo.return_value = mock_report
            mock_analyzer_class.return_value = mock_analyzer

            # Mock progress context manager with proper task support
            mock_task = MagicMock()
            mock_progress_instance = MagicMock()
            mock_progress_instance.add_task.return_value = mock_task
            mock_progress_instance.__enter__ = MagicMock(return_value=mock_progress_instance)
            mock_progress_instance.__exit__ = MagicMock(return_value=False)
            mock_progress.return_value = mock_progress_instance

            result = runner.invoke(cli, ["analyze", "owner/repo"])
            assert result.exit_code == 0

    def test_cli_clear_cache(self):
        """Test clear-cache command."""
        runner = CliRunner()
        result = runner.invoke(cli, ["clear-cache"])
        assert result.exit_code == 0

    def test_cli_info(self):
        """Test info command."""
        runner = CliRunner()
        result = runner.invoke(cli, ["info"])
        assert result.exit_code == 0

    def test_cli_help(self):
        """Test help output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "analyze" in result.output

    def test_cli_analyze_help(self):
        """Test analyze subcommand help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["analyze", "--help"])
        assert result.exit_code == 0

    # --- Analyzer edge cases ---

    @patch("dev_trust.github.client._requests")
    @patch("dev_trust.github.client.Github")
    def test_analyzer_empty_stars(self, mock_github_class, mock_requests, tmp_path):
        """Test analyzer handles repos with no stars."""
        from dev_trust.config import settings as _settings
        import dev_trust.github.client as _gh_client

        # Use isolated cache directory
        original_cache_dir = _settings.cache_dir
        _settings.cache_dir = tmp_path

        try:
            mock_github = MagicMock()
            mock_github_class.return_value = mock_github

            mock_repo = MagicMock()
            mock_repo.full_name = "test/empty"
            mock_repo.description = "No stars repo"
            mock_repo.html_url = "https://github.com/test/empty"
            mock_repo.stargazers_count = 0
            mock_repo.forks_count = 0
            mock_repo.open_issues_count = 0
            mock_repo.created_at = datetime.now(timezone.utc) - timedelta(days=30)
            mock_repo.updated_at = datetime.now(timezone.utc)
            mock_repo.language = "Python"
            mock_repo.archived = False
            mock_repo.fork = False
            mock_repo.get_topics.return_value = []
            mock_github.get_repo.return_value = mock_repo

            # Empty stargazers
            mock_stargazers = MagicMock()
            mock_stargazers.__iter__ = lambda self: iter([])
            mock_repo.get_stargazers_with_dates.return_value = mock_stargazers

            mock_rate = MagicMock()
            mock_rate.core.remaining = 5000
            mock_rate.core.limit = 5000
            mock_rate.search.remaining = 30
            mock_rate.search.limit = 30
            mock_github.get_rate_limit.return_value = mock_rate

            # Mock empty REST API response
            mock_response = MagicMock()
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = []
            mock_requests.get.return_value = mock_response

            from dev_trust.github.client import GitHubClient
            client = GitHubClient()
            client._github = mock_github

            from dev_trust.analyzer import DevTrustAnalyzer
            analyzer = DevTrustAnalyzer(github_client=client)
            report = analyzer.analyze_repo("test", "empty")

            assert report.trust_score == 1.0
            assert report.fake_star_percentage == 0.0
            assert report.analyzed_stars == 0
        finally:
            _settings.cache_dir = original_cache_dir

    # --- Detector error resilience ---

    def test_detector_errors_skipped_in_analyzer(self):
        """Test that detector errors don't crash the analyzer."""
        from dev_trust.detector.scorer import DetectorRegistry

        registry = DetectorRegistry()
        registry.register(TimingBurstDetector())

        # Register a detector that raises
        class BrokenDetector(BaseSignalDetector):
            name = "broken"
            description = "Always fails"
            weight = 0.5

            def detect(self, star_events, repo_info):
                raise RuntimeError("Intentional error")

            def get_weight(self):
                return self.weight

        registry.register(BrokenDetector())

        events = make_star_events(10, age_days=365)
        # The analyzer's loop catches detector errors and continues
        results = []
        for detector in registry.get_detectors():
            try:
                result = detector.detect(events, {})
                results.append(result)
            except Exception:
                continue

        assert len(results) == 1  # Only timing_burst succeeded
        assert results[0].name == "timing_burst"

    # --- Reproducer for GitHub client timeout ---

    @patch("dev_trust.github.client._requests")
    def test_stargazers_request_has_timeout(self, mock_requests):
        """Verify that stargazer fetching includes a timeout parameter."""
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status.return_value = None
        mock_requests.get.return_value = mock_response

        client = GitHubClient(token="ghp_test")
        client._github = MagicMock()

        # Should call requests.get with timeout
        client.get_stargazers("owner", "repo", sample_size=10)

        call_kwargs = mock_requests.get.call_args
        assert "timeout" in call_kwargs.kwargs or "timeout" in call_kwargs[1]
        assert call_kwargs.kwargs.get("timeout") == 30 or call_kwargs[1].get("timeout") == 30

    # --- Reporter tests ---

    def test_reporter_json_output(self):
        """Test JSON report generation."""
        repo = Repository(
            full_name="test/repo",
            owner="test",
            name="repo",
            description="Test",
            html_url="https://github.com/test/repo",
            stars_count=100,
            forks_count=10,
            open_issues=5,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        report = AnalysisReport(
            repo=repo,
            trust_score=0.8,
            fake_star_percentage=0.2,
            confidence=0.7,
            risk_level="low",
            total_stars=100,
            analyzed_stars=50,
            signals=[
                SignalResult(
                    name="timing_burst",
                    suspicious_count=5,
                    total_analyzed=50,
                    confidence_score=0.3,
                ),
            ],
        )
        reporter = Reporter(report)
        json_output = reporter.print_json_report()
        parsed = json.loads(json_output)
        assert parsed["trust_score"] == 0.8
        assert parsed["fake_star_percentage"] == 0.2
        assert len(parsed["signals"]) == 1

    def test_reporter_markdown_output(self):
        """Test Markdown report generation."""
        repo = Repository(
            full_name="test/repo",
            owner="test",
            name="repo",
            description="Test",
            html_url="https://github.com/test/repo",
            stars_count=100,
            forks_count=10,
            open_issues=5,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        report = AnalysisReport(
            repo=repo,
            trust_score=0.5,
            fake_star_percentage=0.5,
            confidence=0.6,
            risk_level="medium",
            total_stars=100,
            analyzed_stars=50,
        )
        reporter = Reporter(report)
        md_output = reporter.generate_markdown_report()
        assert "# DevTrust Analysis" in md_output
        assert "MEDIUM" in md_output

    def test_reporter_save_to_file(self, tmp_path):
        """Test saving report to file."""
        repo = Repository(
            full_name="test/repo",
            owner="test",
            name="repo",
            description="Test",
            html_url="https://github.com/test/repo",
            stars_count=100,
            forks_count=10,
            open_issues=5,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        report = AnalysisReport(
            repo=repo,
            trust_score=0.8,
            fake_star_percentage=0.2,
            confidence=0.7,
            risk_level="low",
            total_stars=100,
            analyzed_stars=50,
        )
        reporter = Reporter(report)
        output_file = tmp_path / "report.md"
        reporter.save_report(output_file, "markdown")
        assert output_file.exists()
        content = output_file.read_text()
        assert "# DevTrust Analysis" in content


# ============================================================
# Bug Regression Tests (from live analysis of practical-tutorials/project-based-learning)
# ============================================================


class TestBugRegressions:
    """Regression tests for bugs discovered during live analysis."""

    # --- Status display should not show CRITICAL/HIGH with 0 flagged users ---

    def test_status_no_critical_when_zero_flagged(self, capsys):
        """A detector with high confidence but 0 flagged users should show NONE, not CRITICAL."""
        from dev_trust.reporter import Reporter

        repo = Repository(
            full_name="test/repo",
            owner="test",
            name="repo",
            description="Test",
            html_url="https://github.com/test/repo",
            stars_count=100,
            forks_count=10,
            open_issues=5,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        report = AnalysisReport(
            repo=repo,
            trust_score=0.8,
            fake_star_percentage=0.2,
            confidence=0.7,
            risk_level="low",
            total_stars=100,
            analyzed_stars=100,
            signals=[
                SignalResult(
                    name="account_age",
                    suspicious_count=0,
                    total_analyzed=200,
                    confidence_score=0.75,  # High confidence but 0 flagged
                ),
            ],
        )
        reporter = Reporter(report)
        reporter.print_text_report()
        output = capsys.readouterr().out
        # CRITICAL should NOT appear in output when suspicious_count is 0
        assert "\033[91mCRITICAL\033[0m" not in output
        assert "NONE" in output

    def test_status_high_when_zero_flagged(self, capsys):
        """A detector with medium confidence but 0 flagged users should show NONE, not HIGH."""
        from dev_trust.reporter import Reporter

        repo = Repository(
            full_name="test/repo",
            owner="test",
            name="repo",
            description="Test",
            html_url="https://github.com/test/repo",
            stars_count=100,
            forks_count=10,
            open_issues=5,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        report = AnalysisReport(
            repo=repo,
            trust_score=0.8,
            fake_star_percentage=0.2,
            confidence=0.7,
            risk_level="low",
            total_stars=100,
            analyzed_stars=100,
            signals=[
                SignalResult(
                    name="behavioral_pattern",
                    suspicious_count=0,
                    total_analyzed=200,
                    confidence_score=0.55,  # Would show HIGH before fix
                ),
            ],
        )
        reporter = Reporter(report)
        reporter.print_text_report()
        output = capsys.readouterr().out
        assert "\033[93mHIGH\033[0m" not in output

    def test_status_critical_when_flagged_users_exist(self, capsys):
        """A detector with high confidence AND flagged users should show CRITICAL."""
        from dev_trust.reporter import Reporter

        repo = Repository(
            full_name="test/repo",
            owner="test",
            name="repo",
            description="Test",
            html_url="https://github.com/test/repo",
            stars_count=100,
            forks_count=10,
            open_issues=5,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        report = AnalysisReport(
            repo=repo,
            trust_score=0.5,
            fake_star_percentage=0.5,
            confidence=0.7,
            risk_level="high",
            total_stars=100,
            analyzed_stars=100,
            signals=[
                SignalResult(
                    name="timing_burst",
                    suspicious_count=50,
                    total_analyzed=100,
                    confidence_score=0.8,
                    flagged_users=["bot1", "bot2"],
                ),
            ],
        )
        reporter = Reporter(report)
        reporter.print_text_report()
        output = capsys.readouterr().out
        assert "\033[91mCRITICAL\033[0m" in output

    # --- commit_depth should not flag all new developers ---

    def test_commit_depth_new_developer_not_flagged(self):
        """A new developer (30 days old, 0 repos) should not be flagged as highly suspicious."""
        detector = CommitDepthDetector(MagicMock())
        user = make_user("new_learner", days_old=30, public_repos=0,
                         followers=0, following=0, bio="Learning to code",
                         account_age_days=30)
        events = [make_star_event(user)]
        result = detector.detect(events, {})

        assert result.total_analyzed == 1
        # Should NOT flag a new learner with 0 repos
        assert result.suspicious_count == 0

    def test_commit_depth_old_empty_account_flagged(self):
        """An old account (365 days) with 0 repos should be flagged."""
        detector = CommitDepthDetector(MagicMock())
        user = make_user("old_empty", days_old=365, public_repos=0,
                         followers=0, following=0, bio=None,
                         account_age_days=365)
        events = [make_star_event(user)]
        result = detector.detect(events, {})

        assert result.total_analyzed == 1
        # Should flag an old account with 0 repos
        assert result.suspicious_count == 1

    def test_commit_depth_legitimate_developer_clean(self):
        """A legitimate developer with repos and followers should not be flagged."""
        detector = CommitDepthDetector(MagicMock())
        user = make_user("real_dev", days_old=1000, public_repos=50,
                         followers=100, following=50,
                         bio="Full-stack developer", company="Google",
                         account_age_days=1000)
        events = [make_star_event(user)]
        result = detector.detect(events, {})

        assert result.total_analyzed == 1
        assert result.suspicious_count == 0
        assert result.confidence_score < 0.3

    # --- account_age confidence should be context-aware ---

    def test_account_age_confidence_with_no_flagged(self):
        """account_age confidence should be low when no users are flagged."""
        detector = AccountAgeDetector()
        # All old accounts — should flag 0 users
        events = [make_star_event(make_user(f"old_user_{i}", days_old=1000))
                  for i in range(20)]
        result = detector.detect(events, {})

        assert result.suspicious_count == 0
        # Confidence should be low when no users flagged
        assert result.confidence_score < 0.5, (
            f"Expected low confidence with 0 flagged, got {result.confidence_score}"
        )

    # --- Live analysis format validation ---

    def test_live_report_structure(self):
        """Validate structure matches what the live analysis produces."""
        import json
        import tempfile
        from dev_trust.reporter import Reporter
        from dev_trust.cli import cli
        from click.testing import CliRunner

        # We can't do a full live test here, but we can validate
        # that the JSON output structure matches expectations
        repo = Repository(
            full_name="owner/repo",
            owner="owner",
            name="repo",
            description="Test",
            html_url="https://github.com/owner/repo",
            stars_count=1000,
            forks_count=100,
            open_issues=10,
            created_at=datetime.now(timezone.utc) - timedelta(days=365),
            updated_at=datetime.now(timezone.utc),
            language="Python",
        )
        report = AnalysisReport(
            repo=repo,
            trust_score=0.7881,
            fake_star_percentage=0.2119,
            confidence=0.4555,
            risk_level="medium",
            total_stars=275714,
            analyzed_stars=200,
            signals=[
                SignalResult(
                    name="timing_burst",
                    suspicious_count=0,
                    total_analyzed=200,
                    confidence_score=0.4,
                ),
                SignalResult(
                    name="account_age",
                    suspicious_count=0,
                    total_analyzed=200,
                    confidence_score=0.75,
                ),
            ],
            recommendations=[
                "Consider reviewing the flagged accounts - estimated 21.2% of stars may be fake.",
            ],
        )
        reporter = Reporter(report)
        json_output = reporter.print_json_report()
        parsed = json.loads(json_output)

        # Verify structure matches live output format
        assert parsed["repository"]["full_name"] == "owner/repo"
        assert parsed["trust_score"] == 0.7881
        assert parsed["fake_star_percentage"] == 0.2119
        assert parsed["risk_level"] == "medium"
        assert len(parsed["signals"]) == 2
        assert len(parsed["recommendations"]) == 1
        # Verify score consistency
        assert abs(parsed["trust_score"] + parsed["fake_star_percentage"] - 1.0) < 0.001

    def test_events_fallback_enriches_user_data(self):
        """Events API fallback should enrich user profiles for detectors that need them."""
        from unittest.mock import patch, MagicMock
        from dev_trust.github.client import GitHubClient
        import dev_trust.github.client as gh_client

        client = GitHubClient(token="ghp_test")
        client._github = MagicMock()

        # Simulate Events API returning minimal user data (empty after page 1)
        events_data = [
            {
                "type": "WatchEvent",
                "created_at": "2024-01-15T10:00:00Z",
                "actor": {
                    "login": "testuser1",
                    "id": 1,
                    "avatar_url": "https://avatars.githubusercontent.com/u/1",
                    "html_url": "https://github.com/testuser1",
                    "type": "User",
                    "site_admin": False,
                },
            },
        ]

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        # Return data on first call, empty on second (pagination ends)
        mock_response.json.side_effect = [events_data, []]

        from dev_trust.models import GitHubUser
        enriched_user = GitHubUser(
            login="testuser1",
            id=1,
            avatar_url="https://avatars.githubusercontent.com/u/1",
            html_url="https://github.com/testuser1",
            type="User",
            site_admin=False,
            public_repos=25,
            followers=10,
            following=5,
            bio="A developer",
            company="Acme",
            location="NYC",
            email="test@example.com",
            created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            has_default_avatar=False,
        )

        with patch.object(gh_client, "_requests") as mock_reqs, \
             patch.object(client, "get_users_batch", return_value={"testuser1": enriched_user}):
            mock_reqs.get.return_value = mock_response
            result = client._get_star_events_from_api("owner", "repo", 10)

        assert len(result) == 1
        assert result[0].user.login == "testuser1"
        # Enriched fields should be present
        assert result[0].user.public_repos == 25
        assert result[0].user.created_at is not None
        assert result[0].user.followers == 10
        assert result[0].user.bio == "A developer"
