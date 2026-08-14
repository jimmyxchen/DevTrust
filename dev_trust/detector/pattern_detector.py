"""Behavioral pattern detector - detects machine-like behavior."""

from __future__ import annotations

import re

from dev_trust.detector.base import BaseSignalDetector
from dev_trust.models import SignalResult, StarEvent


class BehavioralPatternDetector(BaseSignalDetector):
    """Detects machine-like behavior patterns in GitHub accounts.

    Bot accounts exhibit patterns that differ from real human users:
    - High star rates
    - Random-looking usernames
    - Sequential numbering
    - Default avatars
    - No 2FA (not directly observable, but inferable)
    """

    name = "behavioral_pattern"
    description = "Detects machine-like behavioral patterns"
    weight = 0.10

    def get_weight(self) -> float:
        return self.weight

    def detect(self, star_events: list[StarEvent], repo_info: dict) -> SignalResult:
        """Analyze behavioral patterns of stargazers."""
        flagged_users: list[str] = []
        details: dict = {}
        total_score = 0.0

        # Check if this is a burst scenario (all stars close together)
        if len(star_events) >= 10:
            timestamps = sorted([se.starred_at for se in star_events])
            span = (timestamps[-1] - timestamps[0]).total_seconds()
            hours_per_star = span / 3600 / (len(star_events) - 1) if len(star_events) > 1 else 0
        else:
            hours_per_star = 24  # Assume normal if not enough data

        for se in star_events:
            user = se.user
            score, reasons = self._score_behavior(user, hours_per_star)
            total_score += score

            if score > 0.5:
                flagged_users.append(user.login)
                details[user.login] = {
                    "score": round(score, 2),
                    "reasons": reasons,
                    "default_avatar": user.has_default_avatar,
                    "type": user.type,
                }

        avg_score = total_score / len(star_events) if star_events else 0.0
        flagged_ratio = len(flagged_users) / len(star_events) if star_events else 0.0
        # Confidence should reflect actual flagged rate, not just average score.
        confidence = min(1.0, max(avg_score * 0.8, flagged_ratio * 2.0))

        return SignalResult(
            name=self.name,
            suspicious_count=len(flagged_users),
            total_analyzed=len(star_events),
            confidence_score=confidence,
            details=details,
            flagged_users=flagged_users,
        )

    def _score_behavior(self, user: GitHubUser, hours_per_star: float) -> tuple[float, list[str]]:
        """Score a user based on behavioral patterns."""
        score = 0.0
        reasons: list[str] = []

        # Bot accounts often star many repos rapidly
        if hours_per_star < 0.5:  # <30 minutes between stars on average
            score += 0.3
            reasons.append("Rapid starring pattern detected")

        # Default avatar (less suspicious for new accounts, but still a signal)
        if user.has_default_avatar:
            score += 0.1
            reasons.append("Default GitHub avatar")

        # Username patterns
        suspicious_patterns = self._check_username_patterns(user.login)
        if suspicious_patterns:
            score += 0.2
            reasons.extend(suspicious_patterns)

        # Account type
        if user.type != "User":
            score += 0.1
            reasons.append(f"Non-user account type: {user.type}")

        # Site admin check
        if user.site_admin:
            score += 0.05
            reasons.append("Site admin account")

        return min(1.0, score), reasons

    def _check_username_patterns(self, username: str) -> list[str]:
        """Check for suspicious username patterns."""
        patterns_found: list[str] = []

        # Sequential numbering
        match = re.match(r"^(.+?)[-_](\d+)$", username)
        if match:
            prefix = match.group(1)
            num = int(match.group(2))
            if num > 100:
                patterns_found.append("High sequential number in username")

        # Random-looking patterns
        if self._looks_randomly_generated(username):
            patterns_found.append("Randomly generated username pattern")

        # Very short usernames with numbers
        if len(username) <= 4 and any(c.isdigit() for c in username):
            patterns_found.append("Short username with numbers")

        return patterns_found

    def _looks_randomly_generated(self, username: str) -> bool:
        """Check if username appears randomly generated."""
        if len(username) < 6:
            return False

        # Check character distribution
        lower = username.lower()
        letters = sum(1 for c in lower if c.isalpha())
        digits = sum(1 for c in lower if c.isdigit())

        if len(lower) > 0:
            letter_ratio = letters / len(lower)
            digit_ratio = digits / len(lower)
        else:
            return False

        # Mixed letters and digits in a pattern like abc123
        if letter_ratio > 0.4 and digit_ratio > 0.3:
            # Check if it follows word+digits pattern
            import re
            if re.match(r"^[a-z]{3,}[0-9]{3,}$", lower):
                return True

        # All alphanumeric with high entropy
        if letter_ratio + digit_ratio > 0.9:
            unique_chars = len(set(lower))
            if unique_chars >= len(lower) * 0.6:
                return True

        return False
