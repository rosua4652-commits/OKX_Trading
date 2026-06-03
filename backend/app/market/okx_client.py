"""OKX REST API client wrapper."""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger("oat.okx")


class OKXClient:
    """Unified OKX API access for market data and trading."""

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        passphrase: str = "",
        flag: str = "1",
    ) -> None:
        self.api_key = api_key or settings.okx_api_key
        self.api_secret = api_secret or settings.okx_api_secret
        self.passphrase = passphrase or settings.okx_passphrase
        self.flag = flag or settings.okx_flag
        self._market = None
        self._trade = None
        self._account = None
        self._public = None

    def _ensure_imports(self) -> None:
        if self._market is not None:
            return
        try:
            import okx.MarketData as MarketData
            import okx.Trade as Trade
            import okx.Account as Account
            import okx.PublicData as PublicData

            self._market = MarketData.MarketAPI(flag=self.flag)
            self._public = PublicData.PublicAPI(flag=self.flag)
            if self.api_key:
                self._trade = Trade.TradeAPI(
                    self.api_key,
                    self.api_secret,
                    self.passphrase,
                    False,
                    self.flag,
                )
                self._account = Account.AccountAPI(
                    self.api_key,
                    self.api_secret,
                    self.passphrase,
                    False,
                    self.flag,
                )
        except ImportError as e:
            logger.warning("python-okx not installed: %s", e)

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key and self.api_secret and self.passphrase)

    def _ok(self, result: dict) -> bool:
        return isinstance(result, dict) and result.get("code") == "0"

    def get_tickers(self, inst_type: str = "SWAP") -> list[dict[str, Any]]:
        self._ensure_imports()
        if not self._market:
            return []
        try:
            result = self._market.get_tickers(instType=inst_type)
            if self._ok(result):
                return result.get("data", [])
        except Exception as e:
            logger.error("get_tickers error: %s", e)
        return []

    def get_ticker(self, inst_id: str) -> Optional[dict[str, Any]]:
        self._ensure_imports()
        if not self._market:
            return None
        try:
            result = self._market.get_ticker(instId=inst_id)
            if self._ok(result) and result.get("data"):
                return result["data"][0]
        except Exception as e:
            logger.error("get_ticker error: %s", e)
        return None

    def get_candles(
        self,
        inst_id: str,
        bar: str = "5m",
        limit: int = 120,
    ) -> list[list[str]]:
        self._ensure_imports()
        if not self._market:
            return []
        try:
            result = self._market.get_candlesticks(instId=inst_id, bar=bar, limit=str(limit))
            if self._ok(result):
                return result.get("data", [])
        except Exception as e:
            logger.error("get_candles error: %s", e)
        return []

    def get_instruments(self, inst_type: str = "SWAP") -> list[dict[str, Any]]:
        self._ensure_imports()
        if not self._public:
            return []
        try:
            result = self._public.get_instruments(instType=inst_type)
            if self._ok(result):
                return result.get("data", [])
        except Exception as e:
            logger.error("get_instruments error: %s", e)
        return []

    def get_balance(self) -> list[dict[str, Any]]:
        self._ensure_imports()
        if not self._account:
            return []
        try:
            result = self._account.get_account_balance()
            if self._ok(result):
                return result.get("data", [])
        except Exception as e:
            logger.error("get_balance error: %s", e)
        return []

    def get_positions(self, inst_type: str = "SWAP") -> list[dict[str, Any]]:
        self._ensure_imports()
        if not self._account:
            return []
        try:
            result = self._account.get_positions(instType=inst_type)
            if self._ok(result):
                return result.get("data", [])
        except Exception as e:
            logger.error("get_positions error: %s", e)
        return []

    def set_leverage(self, inst_id: str, lever: int, mgn_mode: str = "cross") -> bool:
        self._ensure_imports()
        if not self._account:
            return False
        try:
            result = self._account.set_leverage(
                instId=inst_id,
                lever=str(lever),
                mgnMode=mgn_mode,
            )
            return self._ok(result)
        except Exception as e:
            logger.error("set_leverage error: %s", e)
            return False

    def place_order(
        self,
        inst_id: str,
        side: str,
        sz: str,
        ord_type: str = "market",
        td_mode: str = "cross",
        pos_side: str = "long",
        px: str = "",
    ) -> Optional[dict[str, Any]]:
        self._ensure_imports()
        if not self._trade:
            return None
        try:
            params: dict[str, Any] = {
                "instId": inst_id,
                "tdMode": td_mode,
                "side": side,
                "ordType": ord_type,
                "sz": sz,
            }
            if "-SWAP" in inst_id or "-FUTURES" in inst_id.upper():
                params["posSide"] = pos_side
            if ord_type == "limit" and px:
                params["px"] = px
            result = self._trade.place_order(**params)
            if self._ok(result) and result.get("data"):
                return result["data"][0]
            logger.error("place_order failed: %s", result)
        except Exception as e:
            logger.error("place_order error: %s", e)
        return None

    def close_position(
        self,
        inst_id: str,
        pos_side: str,
        sz: str,
        td_mode: str = "cross",
    ) -> Optional[dict[str, Any]]:
        side = "sell" if pos_side == "long" else "buy"
        return self.place_order(
            inst_id=inst_id,
            side=side,
            sz=sz,
            td_mode=td_mode,
            pos_side=pos_side,
        )

    def test_connection(self) -> tuple[bool, str]:
        if not self.has_credentials:
            return False, "API 키가 설정되지 않았습니다"
        self._ensure_imports()
        try:
            result = self._account.get_account_balance()
            if self._ok(result):
                return True, "OKX 연결 성공"
            return False, f"연결 실패: {result.get('msg', 'unknown')}"
        except Exception as e:
            return False, f"연결 오류: {e}"


_client: Optional[OKXClient] = None


def get_okx_client(
    api_key: str = "",
    api_secret: str = "",
    passphrase: str = "",
    flag: str = "1",
) -> OKXClient:
    global _client
    if api_key:
        return OKXClient(api_key, api_secret, passphrase, flag)
    if _client is None:
        _client = OKXClient()
    return _client
