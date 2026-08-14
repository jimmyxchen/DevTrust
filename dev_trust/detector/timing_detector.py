"""Timing burst detector - detects coordinated star-burst campaigns."""

from __future__ import annotations

import numpy as np

from dev_trust.detector.base import BaseSignalDetector
from dev_trust.models import SignalResult, StarEvent


class TimingBurstDetector(BaseSignalDetector):
    """Detects fake star campaigns via timing burst analysis.

    Fake star campaigns typically happen in short, coordinated bursts
    where many stars are created in a very short time window.
    """

    name = "timing_burst"
    description = "Detects coordinated star-burst campaigns via timing analysis"
    weight = 0.15

    def get_weight(self) -> float:
        return self.weight

    def detect(self, star_events: list[StarEvent], repo_info: dict) -> SignalResult:
        """Analyze timing distribution of stars for burst patterns."""
        if len(star_events) < 3:
            return SignalResult(
                name=self.name,
                suspicious_count=0,
                total_analyzed=len(star_events),
                confidence_score=0.0,
                details={"reason": "Too few stars to analyze timing"},
            )

        # Extract timestamps
        timestamps = sorted([se.starred_at for se in star_events])
        now = max(timestamps)

        # Calculate time differences in hours between consecutive stars
        diffs_hours = []
        for i in range(1, len(timestamps)):
            diff = (timestamps[i] - timestamps[i - 1]).total_seconds() / 3600
            diffs_hours.append(diff)

        # Recent burst analysis: stars in the last 7 days
        recent_threshold = now - __import__("datetime").timedelta(days=7)
        recent_stars = [se for se in star_events if se.starred_at >= recent_threshold]

        # Check if >60% of stars happened within 24 hours
        one_day_windows = self._find_burst_windows(timestamps, hours=24, threshold=0.6)
        one_hour_windows = self._find_burst_windows(timestamps, hours=1, threshold=0.3)

        # Coefficient of variation of time differences
        if len(diffs_hours) > 1:
            mean_diff = np.mean(diffs_hours)
            std_diff = np.std(diffs_hours)
            cv = std_diff / mean_diff if mean_diff > 0 else 0
        else:
            cv = 0

        # Burstiness metric: fraction of stars in the densest 10% of the time range
        total_span = (timestamps[-1] - timestamps[0]).total_seconds()
        if total_span > 0:
            dense_window = total_span * 0.1
            dense_count = 0
            dense_start = timestamps[-1] - __import__("datetime").timedelta(seconds=dense_window)
            for ts in timestamps:
                if ts >= dense_start:
                    dense_count += 1
            burstiness = dense_count / len(timestamps)
        else:
            burstiness = 1.0  # All stars at same time = extreme burst

        # Score calculation
        score = 0.0
        flagged_users: list[str] = []

        # 24-hour burst
        if one_day_windows:
            score += 0.3
            burst_start, burst_end, pct = one_day_windows[0]
            flagged_users = [
                se.user.login
                for se in star_events
                if burst_start <= se.starred_at <= burst_end
            ]

        # 1-hour burst (stronger signal)
        if one_hour_windows:
            score += 0.3

        # High burstiness
        if burstiness > 0.5:
            score += 0.2

        # Low coefficient of variation (unnaturally regular)
        if cv < 0.5 and len(diffs_hours) > 5:
            score += 0.1

        # Many recent stars (campaign still active)
        if len(recent_stars) > len(star_events) * 0.3:
            score += 0.1

        score = min(1.0, score)

        return SignalResult(
            name=self.name,
            suspicious_count=len(flagged_users) if score > 0.5 else 0,
            total_analyzed=len(star_events),
            confidence_score=score,
            details={
                "burstiness": round(burstiness, 3),
                "coefficient_of_variation": round(cv, 3),
                "one_day_windows": one_day_windows,
                "one_hour_windows": one_hour_windows,
                "recent_stars_7d": len(recent_stars),
                "mean_gap_hours": round(float(np.mean(diffs_hours)), 2) if diffs_hours else 0,
            },
            flagged_users=flagged_users,
        )

    def _find_burst_windows(
        self, timestamps: list, hours: int, threshold: float
    ) -> list[tuple]:
        """Find time windows where >threshold% of stars occurred."""
        from datetime import timedelta

        window = timedelta(hours=hours)
        results = []
        n = len(timestamps)
        required = int(n * threshold)

        if required < 2:
            return results

        # Sliding window approach (simplified - check key windows)
        # Check the densest windows
        left = 0
        for right in range(n):
            while (timestamps[right] - timestamps[left]).total_seconds() > window.total_seconds():
                left += 1

            count = right - left + 1
            if count >= required:
                pct = count / n
                results.append((timestamps[left], timestamps[right], round(pct, 3)))

        return sorted(results, key=lambda x: x[2], reverse=True)[:3]
