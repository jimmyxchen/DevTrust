"""Data models for DevTrust."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class GitHubUser:
    """Represents a GitHub user."""

    login: str
    id: int
    avatar_url: str
    html_url: str
    type: str
    site_admin: bool
    name: Optional[str] = None
    company: Optional[str] = None
    blog: Optional[str] = None
    location: Optional[str] = None
    email: Optional[str] = None
    bio: Optional[str] = None
    public_repos: int = 0
    public_gists: int = 0
    followers: int = 0
    following: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Computed fields
    account_age_days: Optional[int] = None
    has_default_avatar: bool = False
    profile_completeness: float = 0.0


@dataclass
class StarEvent:
    """Represents a star event on a repository."""

    user: GitHubUser
    starred_at: datetime
    repo_full_name: str


@dataclass
class Repository:
    """Represents a GitHub repository."""

    full_name: str
    owner: str
    name: str
    description: Optional[str]
    html_url: str
    stars_count: int
    forks_count: int
    open_issues: int
    created_at: datetime
    updated_at: datetime
    language: Optional[str] = None
    topics: list[str] = field(default_factory=list)
    is_archived: bool = False
    is_fork: bool = False


@dataclass
class UserActivity:
    """Represents a user's activity summary."""

    user_login: str
    total_events: int = 0
    push_events: int = 0
    pull_request_events: int = 0
    issue_events: int = 0
    issue_comment_events: int = 0
    create_events: int = 0
    watch_events: int = 0  # stars
    fork_events: int = 0
    other_events: int = 0
    activity_types: set[str] = field(default_factory=set)
    first_event_date: Optional[datetime] = None
    last_event_date: Optional[datetime] = None
    starred_repos_sample: list[str] = field(default_factory=list)


@dataclass
class SignalResult:
    """Result from a single signal detector."""

    name: str
    suspicious_count: int
    total_analyzed: int
    confidence_score: float  # 0.0 to 1.0
    details: dict = field(default_factory=dict)
    flagged_users: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class AnalysisReport:
    """Complete analysis report for a repository."""

    repo: Optional[Repository] = None
    trust_score: float = 1.0  # 0.0 = completely untrusted, 1.0 = fully trusted
    fake_star_percentage: float = 0.0  # Estimated % of fake stars
    confidence: float = 0.0  # Confidence in this estimate
    risk_level: str = "low"  # low, medium, high, critical
    total_stars: int = 0
    analyzed_stars: int = 0
    signals: list[SignalResult] = field(default_factory=list)
    flagged_users: list[tuple[str, float, str]] = field(default_factory=list)  # (login, score, reason)
    recommendations: list[str] = field(default_factory=list)
    analyzed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def get_risk_color(self) -> str:
        """Get ANSI color code for risk level."""
        colors = {
            "low": "\033[92m",      # green
            "medium": "\033[93m",   # yellow
            "high": "\033[91m",     # red
            "critical": "\033[95m", # magenta
        }
        return colors.get(self.risk_level, "\033[0m")
