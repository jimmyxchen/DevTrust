"""Base detector framework for signal detection."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from dev_trust.models import SignalResult

if TYPE_CHECKING:
    from dev_trust.models import StarEvent


class BaseSignalDetector(ABC):
    """Abstract base class for all signal detectors."""

    name: str = "base"
    description: str = "Base detector"

    @abstractmethod
    def detect(self, star_events: list[StarEvent], repo_info: dict) -> SignalResult:
        """
        Analyze star events and return a signal result.

        Args:
            star_events: List of star events to analyze
            repo_info: Repository metadata dict

        Returns:
            SignalResult with detection findings
        """
        ...

    @abstractmethod
    def get_weight(self) -> float:
        """Return the weight of this signal in the overall scoring (0.0-1.0)."""
        ...
