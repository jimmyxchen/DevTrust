"""Account creation clustering detector - detects coordinated bot campaigns."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import numpy as np
from sklearn.cluster import DBSCAN

from dev_trust.detector.base import BaseSignalDetector
from dev_trust.models import SignalResult, StarEvent, GitHubUser


class CreationClusterDetector(BaseSignalDetector):
    """Detects coordinated bot campaigns via account creation clustering.

    Bot campaigns often register many accounts in a short time window.
    This detector finds such clusters using density-based clustering.
    """

    name = "creation_cluster"
    description = "Detects coordinated bot campaigns via creation date clustering"
    weight = 0.15

    def get_weight(self) -> float:
        return self.weight

    def detect(self, star_events: list[StarEvent], repo_info: dict) -> SignalResult:
        """Analyze account creation dates for clustering patterns."""
        if len(star_events) < 5:
            return SignalResult(
                name=self.name,
                suspicious_count=0,
                total_analyzed=len(star_events),
                confidence_score=0.0,
                details={"reason": "Too few stars to analyze clustering"},
            )

        # Collect creation dates and usernames
        users_with_dates: list[tuple[str, float, str]] = []  # (login, timestamp, raw_date)
        users_without_dates: list[str] = []

        for se in star_events:
            user = se.user
            if user.created_at:
                ts = user.created_at.timestamp()
                users_with_dates.append((user.login, ts, user.created_at.isoformat()))
            else:
                users_without_dates.append(user.login)

        if len(users_with_dates) < 5:
            return SignalResult(
                name=self.name,
                suspicious_count=0,
                total_analyzed=len(star_events),
                confidence_score=0.0,
                details={"reason": "Could not determine creation dates for enough users"},
            )

        # Cluster creation timestamps using DBSCAN
        timestamps = np.array([[u[1]] for u in users_with_dates])

        # eps = 7 days in seconds, min_samples = 3
        eps_seconds = 7 * 24 * 3600
        clustering = DBSCAN(eps=eps_seconds, min_samples=3).fit(timestamps)

        labels = clustering.labels_
        n_clusters = len(set(labels)) - (1 if -1 in labels else 0)

        # Identify which users are in clusters
        cluster_users: list[str] = []
        cluster_sizes: dict[int, int] = {}
        for i, (login, _, _) in enumerate(users_with_dates):
            label = labels[i]
            if label != -1:  # In a cluster
                cluster_users.append(login)
                cluster_sizes[label] = cluster_sizes.get(label, 0) + 1

        # Score based on clustering
        score = 0.0
        cluster_info: dict = {}

        cluster_pct = len(cluster_users) / len(star_events)
        if cluster_pct > 0.2:
            score += 0.3
            cluster_info["cluster_percentage"] = round(cluster_pct, 3)

        if n_clusters >= 2:
            score += 0.1
            cluster_info["n_clusters"] = n_clusters

        # Check for large clusters (strong indicator)
        large_clusters = {k: v for k, v in cluster_sizes.items() if v >= 5}
        if large_clusters:
            score += 0.2
            cluster_info["large_cluster_sizes"] = list(large_clusters.values())

        # Username entropy analysis
        entropy_score, high_entropy_users = self._analyze_username_entropy(
            [se.user for se in star_events]
        )
        score += entropy_score * 0.3

        # Sequential username patterns
        sequential = self._detect_sequential_usernames([se.user.login for se in star_events])
        if sequential:
            score += 0.2
            cluster_info["sequential_patterns"] = sequential

        score = min(1.0, score)

        return SignalResult(
            name=self.name,
            suspicious_count=len(cluster_users),
            total_analyzed=len(star_events),
            confidence_score=score,
            details=cluster_info,
            flagged_users=cluster_users,
        )

    def _analyze_username_entropy(self, users: list[GitHubUser]) -> tuple[float, list[str]]:
        """Detect high-entropy usernames that look randomly generated."""
        import re
        import string

        flagged: list[str] = []
        high_entropy_count = 0

        for user in users:
            login = user.login.lower()
            # Calculate Shannon entropy of username
            if len(login) < 4:
                continue

            char_counts: dict[str, int] = {}
            for c in login:
                char_counts[c] = char_counts.get(c, 0) + 1

            entropy = 0.0
            length = len(login)
            for count in char_counts.values():
                p = count / length
                entropy -= p * math.log2(p)

            # Normalize entropy (max for uniform distribution over all chars)
            max_entropy = math.log2(min(length, len(string.ascii_lowercase + string.digits)))

            if max_entropy > 0 and entropy / max_entropy > 0.85:
                # Also check for random-looking patterns
                if self._looks_random(login):
                    high_entropy_count += 1
                    flagged.append(user.login)

        if len(users) == 0:
            return 0.0, []

        entropy_score = (high_entropy_count / len(users)) * 0.5
        return entropy_score, flagged

    def _looks_random(self, username: str) -> bool:
        """Check if username looks randomly generated."""
        import re

        # Patterns common in bot usernames
        patterns = [
            r"[a-z]+_[a-z0-9]{4,}",     # word_randomchars
            r"[a-z]+\d{4,}",             # word1234
            r"\d{3,}[a-z]+",             # 123abc
            r"[a-z0-9]{16,}",            # long random string
        ]

        for pattern in patterns:
            if re.match(pattern, username):
                return True

        # Check for low character variety relative to length
        if len(username) > 8 and len(set(username)) <= 4:
            return True

        return False

    def _detect_sequential_usernames(self, usernames: list[str]) -> list[str]:
        """Detect sequential username patterns like user_1, user_2, etc."""
        import re

        # Group by prefix
        prefix_groups: dict[str, list[str]] = {}
        for name in usernames:
            match = re.match(r"^(.+?)[-_](\d+)$", name)
            if match:
                prefix = match.group(1)
                num = int(match.group(2))
                if prefix not in prefix_groups:
                    prefix_groups[prefix] = []
                prefix_groups[prefix].append((num, name))

        sequential: list[str] = []
        for prefix, entries in prefix_groups.items():
            if len(entries) >= 3:
                nums = sorted([e[0] for e in entries])
                # Check if mostly sequential
                if nums[-1] - nums[0] <= len(nums) * 2:
                    sequential.extend([e[1] for e in entries])

        return sequential
