"""Commit depth detector - analyzes genuine code contribution."""

from __future__ import annotations

from dev_trust.detector.base import BaseSignalDetector
from dev_trust.models import SignalResult, StarEvent


class CommitDepthDetector(BaseSignalDetector):
    """Analyzes genuine code contribution depth.

    Real developers have authored commits, contribute to multiple
    repos, and have meaningful code history.
    """

    name = "commit_depth"
    description = "Analyzes genuine code contribution depth"
    weight = 0.10

    def __init__(self, github_client):
        self.github_client = github_client

    def get_weight(self) -> float:
        return self.weight

    def detect(self, star_events: list[StarEvent], repo_info: dict) -> SignalResult:
        """Analyze commit depth of stargazers."""
        flagged_users: list[str] = []
        details: dict = {}
        total_score = 0.0
        analyzed = 0

        # Sample users (expensive check)
        sample_size = min(50, len(star_events))

        for se in star_events[:sample_size]:
            user = se.user
            score, reasons = self._score_commit_depth(user)
            total_score += score
            analyzed += 1

            if score > 0.5:
                flagged_users.append(user.login)
                details[user.login] = {
                    "score": round(score, 2),
                    "reasons": reasons,
                    "public_repos": user.public_repos,
                }

        avg_score = total_score / analyzed if analyzed > 0 else 0.0
        confidence = min(1.0, avg_score * 2.0)

        return SignalResult(
            name=self.name,
            suspicious_count=len(flagged_users),
            total_analyzed=analyzed,
            confidence_score=confidence,
            details=details,
            flagged_users=flagged_users,
        )

    def _score_commit_depth(self, user: GitHubUser) -> tuple[float, list[str]]:
        """Score a user based on commit depth indicators."""
        score = 0.0
        reasons: list[str] = []

        # Account age context: newer accounts naturally have fewer repos
        account_age = user.account_age_days or 365  # default to 1 year if unknown

        # Public repos as a proxy (we can't easily get commit counts without GraphQL)
        if user.public_repos == 0:
            if account_age < 30:
                score += 0.15  # New account, no repos yet — common for beginners
                reasons.append("New account with no public repositories")
            else:
                score += 0.4  # Old account with no repos is more suspicious
                reasons.append("No public repositories for account age > 30 days")
        elif user.public_repos < 3:
            if account_age < 90:
                score += 0.1  # Reasonable for newer developers
                reasons.append(f"Only {user.public_repos} public repos (newer account)")
            else:
                score += 0.25
                reasons.append(f"Only {user.public_repos} public repos for account age > 90 days")
        elif user.public_repos < 10:
            score += 0.05  # Low but not suspicious

        # Followers/following as proxies for engagement
        if user.followers == 0 and user.following == 0 and user.public_repos == 0:
            score += 0.1  # Reduced from 0.2
            reasons.append("Zero social engagement")
        elif user.followers == 0 and user.following > 100:
            score += 0.1  # Reduced from context-free check
            reasons.append("High following count with zero followers")

        # Bio presence (real devs usually have bios)
        if not user.bio and not user.company and not user.location:
            score += 0.1  # Reduced from 0.15
            reasons.append("No profile information")

        # Default avatar
        if user.has_default_avatar:
            score += 0.05  # Reduced from 0.1
            reasons.append("Default avatar")

        return min(1.0, score), reasons
