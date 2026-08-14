"""Account age and throwaway account detector."""

from __future__ import annotations

from datetime import datetime, timedelta

from dev_trust.detector.base import BaseSignalDetector
from dev_trust.models import SignalResult, StarEvent, GitHubUser


class AccountAgeDetector(BaseSignalDetector):
    """Detects suspicious accounts based on age and profile completeness.

    Fake star accounts are often newly created throwaway accounts
    with minimal profile information.
    """

    name = "account_age"
    description = "Detects throwaway accounts and suspicious profiles"
    weight = 0.20

    def get_weight(self) -> float:
        return self.weight

    def detect(self, star_events: list[StarEvent], repo_info: dict) -> SignalResult:
        """Analyze account ages and profile completeness."""
        flagged_users: list[str] = []
        details: dict = {}
        total_score = 0.0

        for se in star_events:
            user = se.user
            user_score, reasons = self._score_user(user, se.starred_at)
            total_score += user_score

            if user_score > 0.5:
                flagged_users.append(user.login)
                details[user.login] = {
                    "score": round(user_score, 2),
                    "reasons": reasons,
                    "account_age_days": user.account_age_days,
                    "public_repos": user.public_repos,
                    "followers": user.followers,
                    "following": user.following,
                }

        avg_score = total_score / len(star_events) if star_events else 0.0
        flagged_ratio = len(flagged_users) / len(star_events) if star_events else 0.0
        # Confidence reflects both average suspiciousness AND actual flagged rate.
        # A detector that scores moderately but flags 0 users should not show high confidence.
        confidence = min(1.0, max(avg_score * 0.8, flagged_ratio * 1.5))

        return SignalResult(
            name=self.name,
            suspicious_count=len(flagged_users),
            total_analyzed=len(star_events),
            confidence_score=confidence,
            details=details,
            flagged_users=flagged_users,
        )

    def _score_user(self, user: GitHubUser, starred_at: datetime) -> tuple[float, list[str]]:
        """Score a single user for suspiciousness. Returns (score, reasons)."""
        score = 0.0
        reasons: list[str] = []

        if not user.created_at:
            return 0.5, ["Could not determine account age"]

        account_age_days = (starred_at - user.created_at).days
        user.account_age_days = account_age_days

        # Account age scoring
        if account_age_days < 1:
            score += 0.95
            reasons.append("Account created <1 day before starring")
        elif account_age_days < 7:
            score += 0.80
            reasons.append("Account created <7 days before starring")
        elif account_age_days < 30:
            score += 0.50
            reasons.append("Account created <30 days before starring")
        elif account_age_days < 90:
            score += 0.20
            reasons.append("Account created <90 days before starring")
        else:
            score += 0.0

        # Profile completeness scoring
        profile_score = self._profile_completeness(user)
        score += profile_score * 0.3

        if profile_score > 0.5:
            reasons.append("Incomplete profile")

        # Follower/following analysis
        if user.followers == 0 and user.following == 0 and user.public_repos == 0:
            score += 0.2
            reasons.append("Zero activity (0 followers, 0 following, 0 repos)")
        elif user.followers == 0 and user.following > 100:
            score += 0.15
            reasons.append("High following count with zero followers (suspicious)")

        # Default avatar
        if user.has_default_avatar:
            score += 0.1
            reasons.append("Using default GitHub avatar")

        return min(1.0, score), reasons

    def _profile_completeness(self, user: GitHubUser) -> float:
        """Calculate profile completeness score (0.0 = complete, 1.0 = empty)."""
        fields_to_check = [user.name, user.bio, user.location, user.email, user.blog]
        filled = sum(1 for f in fields_to_check if f)
        completeness = filled / len(fields_to_check)
        return 1.0 - completeness
