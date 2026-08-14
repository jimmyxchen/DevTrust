"""Network analysis detector - analyzes stargazer social networks."""

from __future__ import annotations

from collections import defaultdict

from dev_trust.detector.base import BaseSignalDetector
from dev_trust.models import SignalResult, StarEvent


class NetworkDetector(BaseSignalDetector):
    """Analyzes stargazer social networks for suspicious patterns.

    Real users have diverse social connections. Bot accounts often
    exist in isolated clusters or have no real network presence.
    """

    name = "network_analysis"
    description = "Analyzes stargazer social networks for bot clusters"
    weight = 0.10

    def __init__(self, github_client):
        self.github_client = github_client

    def get_weight(self) -> float:
        return self.weight

    def detect(self, star_events: list[StarEvent], repo_info: dict) -> SignalResult:
        """Analyze network patterns of stargazers."""
        if len(star_events) < 5:
            return SignalResult(
                name=self.name,
                suspicious_count=0,
                total_analyzed=len(star_events),
                confidence_score=0.0,
                details={"reason": "Too few stars for network analysis"},
            )

        # Sample users for network analysis (expensive API calls)
        sample_size = min(30, len(star_events))
        sample_logins = [se.user.login for se in star_events[:sample_size]]

        flagged_users: list[str] = []
        details: dict = {}

        # Build follower graph
        user_followers: dict[str, set[str]] = defaultdict(set)
        user_following: dict[str, set[str]] = defaultdict(set)

        for login in sample_logins:
            try:
                gh_user = self.github_client.github.get_user(login)
                # Get followers
                for follower in gh_user.get_followers()[:20]:
                    follower_login = follower.login
                    user_followers[login].add(follower_login)
                    user_following[follower_login].add(login)

                # Get following
                for following in gh_user.get_following()[:20]:
                    following_login = following.login
                    user_following[login].add(following_login)
                    user_followers[following_login].add(login)
            except Exception:
                continue

        # Find mutual following clusters (sock puppets)
        mutual_pairs: list[tuple[str, str]] = []
        for login in sample_logins:
            if login not in user_following:
                continue
            for other in sample_logins:
                if other != login and other in user_following[login] and login in user_following.get(other, set()):
                    if (other, login) not in mutual_pairs and (login, other) not in mutual_pairs:
                        mutual_pairs.append((login, other))

        # Score each user
        user_scores: dict[str, float] = {}
        for login in sample_logins:
            score = 0.0
            reasons: list[str] = []

            followers = user_followers.get(login, set())
            following = user_following.get(login, set())

            # Isolated nodes: 0 followers, only follows target repo accounts
            external_connections = followers - set(sample_logins)
            if len(followers) == 0 and len(following) <= 5:
                score += 0.3
                reasons.append("No followers and minimal following")

            # In mutual-only clusters (sock puppets)
            in_mutual_cluster = any(login == pair[0] or login == pair[1] for pair in mutual_pairs)
            if in_mutual_cluster:
                score += 0.2
                reasons.append("Part of mutual-following cluster")

            # High following count with low followers (bot pattern)
            if len(following) > 50 and len(followers) < 5:
                score += 0.2
                reasons.append("Following many but has few followers")

            # No external connections
            if len(external_connections) == 0 and len(followers) > 0:
                score += 0.1
                reasons.append("Followers only from sample group (isolated)")

            user_scores[login] = min(1.0, score)

            if score > 0.4:
                flagged_users.append(login)
                details[login] = {
                    "score": round(score, 2),
                    "reasons": reasons,
                    "followers": len(followers),
                    "following": len(following),
                    "external_connections": len(external_connections),
                }

        avg_score = sum(user_scores.values()) / len(user_scores) if user_scores else 0.0
        confidence = min(1.0, avg_score * 2.0)

        return SignalResult(
            name=self.name,
            suspicious_count=len(flagged_users),
            total_analyzed=sample_size,
            confidence_score=confidence,
            details={
                "mutual_clusters": len(mutual_pairs),
                "sample_analyzed": sample_size,
                **details,
            },
            flagged_users=flagged_users,
        )
