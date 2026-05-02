"""Strategy Family Member - declaration-only interface for strategy family membership."""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.policy.strategy_family_policy import StrategyFamily


class StrategyFamilyMember(ABC):
    """Declaration-only interface for strategy family membership.

    No execution logic. No on_bar(). No on_fill().
    Exists for: audit, enabling/disabling, future attachment.
    """

    @property
    @abstractmethod
    def family(self) -> StrategyFamily:
        ...

    @property
    @abstractmethod
    def timeframe(self) -> str:
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...
