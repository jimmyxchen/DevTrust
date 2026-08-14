"""Cross-repository similarity detector - detects fake star farms."""

from __future__ import annotations

from itertools import combinations

from dev_trust.detector.base import BaseSignalDetector
from dev_trust.models import SignalResult, StarEvent


class CrossRepoDetector(BaseSignalDetector):
    """Detects fake star campaigns via cross-repository similarity.

    Fake star farms target many repos simultaneously. This detector
    finds users who star many repos in the same pattern.
    """

    name = "cross_repo"
    description = "Detects fake star farms via co-starring patterns"
    weight = 0.15

    def __init__(self, github_client):
        self.github_client = github_client

    def get_weight(self) -> float:
        return self.weight

    def detect(self, star_events: list[StarEvent], repo_info: dict) -> SignalResult:
        """Analyze co-starring patterns across repositories."""
        if len(star_events) < 5:
            return SignalResult(
                name=self.name,
                suspicious_count=0,
                total_analyzed=len(star_events),
                confidence_score=0.0,
                details={"reason": "Too few stars for cross-repo analysis"},
            )

        flagged_users: list[str] = []
        details: dict = {}

        # Sample users for analysis (too expensive to check all)
        sample_size = min(50, len(star_events))
        sample_events = star_events[:sample_size]

        co_star_counts: dict[str, list[str]] = {}  # repo -> list of usernames
        user_star_counts: dict[str, int] = {}

        for se in sample_events:
            user = se.user
            starred_repos = self.github_client.get_user_starred_repos(user.login, limit=30)

            user_star_counts[user.login] = len(starred_repos)

            for repo in starred_repos:
                if repo not in co_star_counts:
                    co_star_counts[repo] = []
                co_star_counts[repo].append(user.login)

        # Find repos with suspicious co-starring (many of our users starred them)
        suspicious_repos: dict[str, float] = {}
        for repo, users in co_star_counts.items():
            if len(users) >= 3:
                # What fraction of our sample stars this repo?
                overlap = len(users) / sample_size
                if overlap > 0.3:
                    suspicious_repos[repo] = overlap

        # Score each user
        user_scores: dict[str, float] = {}
        for se in sample_events:
            user = se.user
            score = 0.0
            reasons: list[str] = []

            # High star rate (starred too many repos)
            if user_star_counts.get(user.login, 0) > 100:
                score += 0.3
                reasons.append(f"Starred {user_star_counts[user.login]} repos")

            # Co-stars with suspicious repos
            user_starred_suspicious = 0
            for repo, overlap in suspicious_repos.items():
                if user.login in co_star_counts.get(repo, []):
                    user_starred_suspicious += 1

            if user_starred_suspicious >= 2:
                score += 0.4
                reasons.append(f"Co-starred {user_starred_suspicious} suspicious repos")

            # Identical co-starring pattern
            if len(sample_events) > 10:
                # Check if this user stars the exact same repos as others
                user_repos = set(self.github_client.get_user_starred_repos(user.login, limit=30))
                similar_count = 0
                for other_se in sample_events:
                    if other_se.user.login == user.login:
                        continue
                    other_repos = set(
                        self.github_client.get_user_starred_repos(other_se.user.login, limit=30)
                    )
                    if len(user_repos) > 0 and len(other_repos) > 0:
                        jaccard = len(user_repos & other_repos) / len(user_repos | other_repos)
                        if jaccard > 0.7:
                            similar_count += 1

                if similar_count >= 3:
                    score += 0.2
                    reasons.append(f"Nearly identical starring pattern with {similar_count} users")

            user_scores[user.login] = min(1.0, score)

            if score > 0.5:
                flagged_users.append(user.login)
                details[user.login] = {
                    "score": round(score, 2),
                    "reasons": reasons,
                    "total_starred": user_star_counts.get(user.login, 0),
                }

        avg_score = sum(user_scores.values()) / len(user_scores) if user_scores else 0.0
        confidence = min(1.0, avg_score * 1.5)

        return SignalResult(
            name=self.name,
            suspicious_count=len(flagged_users),
            total_analyzed=sample_size,
            confidence_score=confidence,
            details={
                "suspicious_repos": {k: round(v, 3) for k, v in list(suspicious_repos.items())[:10]},
                "sample_analyzed": sample_size,
                **details,
            },
            flagged_users=flagged_users,
        )
