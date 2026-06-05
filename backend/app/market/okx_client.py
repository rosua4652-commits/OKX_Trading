"""OKX REST API client wrapper."""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger("oat.okx")


def _is_pos_side_error(result: Any) -> bool:
    text = str(result).lower()
    return "posside" in text or "pos side" in text or "parameter posside error" in text


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
        self.last_error = ""

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

    def get_instrument(self, inst_id: str, inst_type: str = "SWAP") -> Optional[dict[str, Any]]:
        for inst in self.get_instruments(inst_type=inst_type):
            if inst.get("instId") == inst_id:
                return inst
        return None

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

    def get_fills_history(
        self,
        inst_type: str = "SWAP",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self._ensure_imports()
        if not self._trade:
            return []
        try:
            result = self._trade.get_fills_history(instType=inst_type, limit=str(limit))
            if self._ok(result):
                return result.get("data", [])
            logger.error("get_fills_history failed: %s", result)
        except Exception as e:
            logger.error("get_fills_history error: %s", e)
        return []

    def get_pending_orders(
        self,
        inst_type: str = "SWAP",
    ) -> list[dict[str, Any]]:
        self._ensure_imports()
        if not self._trade:
            return []
        try:
            result = self._trade.get_order_list(instType=inst_type)
            if self._ok(result):
                return result.get("data", [])
            logger.error("get_order_list failed: %s", result)
        except Exception as e:
            logger.error("get_order_list error: %s", e)
        return []

    def set_leverage(
        self,
        inst_id: str,
        lever: int,
        mgn_mode: str = "cross",
        pos_side: str = "",
    ) -> bool:
        self._ensure_imports()
        if not self._account:
            return False
        try:
            params: dict[str, Any] = {
                "instId": inst_id,
                "lever": str(lever),
                "mgnMode": mgn_mode,
            }
            if mgn_mode == "isolated" and pos_side:
                params["posSide"] = pos_side
            result = self._account.set_leverage(**params)
            if self._ok(result):
                return True
            if pos_side and _is_pos_side_error(result):
                params.pop("posSide", None)
                result = self._account.set_leverage(**params)
                return self._ok(result)
            logger.error("set_leverage failed: %s", result)
            return False
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
            self.last_error = "trade api unavailable"
            return None
        try:
            self.last_error = ""
            params: dict[str, Any] = {
                "instId": inst_id,
                "tdMode": td_mode,
                "side": side,
                "ordType": ord_type,
                "sz": sz,
            }
            if params.get("tdMode") == "cash" and side == "buy":
                params["tgtCcy"] = "quote_ccy"
            if pos_side and ("-SWAP" in inst_id or "-FUTURES" in inst_id.upper()):
                params["posSide"] = pos_side
            if ord_type == "limit" and px:
                params["px"] = px
            result = self._trade.place_order(**params)
            if self._ok(result) and result.get("data"):
                return result["data"][0]
            if params.get("posSide") and _is_pos_side_error(result):
                retry = dict(params)
                retry.pop("posSide", None)
                result = self._trade.place_order(**retry)
                if self._ok(result) and result.get("data"):
                    return result["data"][0]
            self.last_error = str(result)
            logger.error("place_order failed: %s", result)
        except Exception as e:
            self.last_error = str(e)
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

    def _balance_check(self) -> tuple[bool, str]:
        if not self._account:
            return False, "계정 API 초기화 실패"
        result = self._account.get_account_balance()
        if self._ok(result):
            env = "데모" if self.flag == "1" else "실거래"
            return True, f"OKX 연결 성공 ({env})"
        return False, str(result.get("msg", "unknown"))

    def test_connection(self) -> tuple[bool, str]:
        if not self.has_credentials:
            return False, "API 키가 설정되지 않았습니다"
        self._ensure_imports()
        try:
            ok, msg = self._balance_check()
            if ok:
                return True, msg
            lower = msg.lower()
            if "environment" not in lower and "does not match" not in lower:
                return False, f"연결 실패: {msg}"

            alt_flag = "0" if self.flag == "1" else "1"
            alt = OKXClient(
                self.api_key, self.api_secret, self.passphrase, alt_flag
            )
            alt._ensure_imports()
            ok2, msg2 = alt._balance_check()
            if ok2:
                env = "데모" if alt_flag == "1" else "실거래"
                return True, f"{msg2}|AUTO_FLAG:{alt_flag}|환경 자동 맞춤 ({env})"

            return (
                False,
                "API 키 환경 불일치: OKX에서 데모(시뮬레이션) 키면 설정→데모 모드, "
                "실거래 키면 설정→실거래 모드로 맞추세요.",
            )
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
