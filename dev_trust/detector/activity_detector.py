"""User activity detector - detects inactive/fake accounts."""

from __future__ import annotations

from dev_trust.detector.base import BaseSignalDetector
from dev_trust.models import SignalResult, StarEvent


class UserActivityDetector(BaseSignalDetector):
    """Detects fake accounts by analyzing genuine GitHub activity.

    Real GitHub users have diverse activity beyond just starring repos.
    This detector checks for genuine engagement patterns.
    """

    name = "user_activity"
    description = "Detects inactive/fake accounts via activity analysis"
    weight = 0.20

    def __init__(self, github_client):
        self.github_client = github_client

    def get_weight(self) -> float:
        return self.weight

    def detect(self, star_events: list[StarEvent], repo_info: dict) -> SignalResult:
        """Analyze user activity patterns."""
        flagged_users: list[str] = []
        details: dict = {}
        total_score = 0.0
        analyzed = 0

        for se in star_events:
            user = se.user
            if user.account_age_days is None:
                if user.created_at:
                    user.account_age_days = (se.starred_at - user.created_at).days
                else:
                    continue

            # Fetch user events for activity analysis
            try:
                activity = self.github_client.get_user_events(user.login)
                score, reasons = self._score_activity(user, activity)
            except Exception:
                continue
            total_score += score
            analyzed += 1

            if score > 0.5:
                flagged_users.append(user.login)
                details[user.login] = {
                    "score": round(score, 2),
                    "reasons": reasons,
                    "total_events": activity.total_events,
                    "activity_types": list(activity.activity_types),
                    "non_star_events": activity.total_events - activity.watch_events,
                    "public_repos": user.public_repos,
                }

        avg_score = total_score / analyzed if analyzed > 0 else 0.0
        confidence = min(1.0, avg_score * 1.5)

        return SignalResult(
            name=self.name,
            suspicious_count=len(flagged_users),
            total_analyzed=analyzed,
            confidence_score=confidence,
            details=details,
            flagged_users=flagged_users,
        )

    def _score_activity(self, user: GitHubUser, activity) -> tuple[float, list[str]]:
        """Score a user based on their activity pattern."""
        score = 0.0
        reasons: list[str] = []

        # Total events in last 90 days
        if activity.total_events == 0:
            score += 0.4
            reasons.append("No events in last 90 days")

        # Non-star activity
        non_star = activity.total_events - activity.watch_events
        if activity.total_events > 0:
            star_ratio = activity.watch_events / activity.total_events
        else:
            star_ratio = 0.0

        if non_star < 3 and activity.total_events > 0:
            score += 0.3
            reasons.append("Only star-related activity")

        if star_ratio > 0.9 and activity.total_events > 5:
            score += 0.2
            reasons.append(">90% of activity is starring")

        # Activity diversity
        meaningful_types = {"PushEvent", "PullRequestEvent", "IssuesEvent", "IssueCommentEvent", "CreateEvent"}
        meaningful_count = len(activity.activity_types & meaningful_types)

        if meaningful_count == 0 and activity.total_events > 0:
            score += 0.3
            reasons.append("No meaningful code-related activity")

        # Public repos as a proxy for real engagement
        if user.public_repos == 0 and activity.total_events < 5:
            score += 0.2
            reasons.append("No repos and minimal activity")

        return min(1.0, score), reasons
