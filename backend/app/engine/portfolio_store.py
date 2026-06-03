"""Portfolio store — paper and live separation."""

from __future__ import annotations

from app.engine.portfolio import PortfolioManager
from app.models import TradeMode


class PortfolioStore:
    def __init__(self) -> None:
        self.paper = PortfolioManager(TradeMode.PAPER)
        self.live = PortfolioManager(TradeMode.LIVE)
        self.paper.load()
        self.live.load()

    def get(self, mode: TradeMode) -> PortfolioManager:
        return self.live if mode == TradeMode.LIVE else self.paper


store = PortfolioStore()
