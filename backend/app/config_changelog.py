"""Human-readable config diff for activity log."""

from __future__ import annotations

from enum import Enum
from typing import Any

from app.models import AppConfig

_SENSITIVE = frozenset({"okx_api_key", "okx_api_secret", "okx_passphrase"})

_LABELS: dict[str, str] = {
    "trade_mode": "거래 모드",
    "strategy_mode": "전략",
    "instrument_type": "상품",
    "auto_invest": "자동 매매",
    "max_positions": "최대 포지션",
    "order_size_usdt": "주문 금액(USDT)",
    "position_size_mode": "주문 크기 방식",
    "order_size_pct": "주문 비율(%)",
    "max_order_size_usdt": "주문 상한(USDT)",
    "min_order_size_usdt": "주문 하한(USDT)",
    "size_split_slots": "잔고÷슬롯",
    "leverage": "레버리지",
    "stop_loss_pct": "손절(%)",
    "take_profit_pct": "익절(%)",
    "trailing_stop": "트레일링",
    "allow_short": "숏 허용",
    "position_side": "진입 방향",
    "min_score": "최소 점수",
    "backtest_auto_settings": "백테스트 자동설정",
    "backtest_interval_minutes": "백테스트 주기(분)",
    "paper_initial_balance": "모의 초기자금",
    "okx_flag": "OKX API 환경",
    "scan_symbols": "스캔 종목",
}


def _fmt_val(key: str, val: Any) -> str:
    if isinstance(val, Enum):
        val = val.value
    if key == "trade_mode":
        return "모의투자" if val == "paper" else "실거래"
    if key == "okx_flag":
        return "데모" if str(val) == "1" else "실거래 API"
    if key == "backtest_auto_settings":
        return "유동(자동)" if val else "수동(고정)"
    if key == "position_size_mode":
        m = {
            "fixed": "고정 USDT",
            "pct_available": "가용 %",
            "pct_equity": "총자산 %",
        }
        return m.get(str(val), str(val))
    if key == "size_split_slots":
        return "켜짐" if val else "꺼짐"
    if key == "strategy_mode":
        m = {"scalp": "단타", "swing": "장타", "both": "단타+장타"}
        return m.get(str(val), str(val))
    if key == "instrument_type":
        m = {"spot": "현물", "swap": "스왑", "futures": "선물"}
        return m.get(str(val), str(val))
    if key == "position_side":
        m = {"auto": "AI 자동", "long": "롱만", "short": "숏만"}
        return m.get(str(val), str(val))
    if isinstance(val, bool):
        return "켜짐" if val else "꺼짐"
    if key == "leverage":
        return f"{val}x"
    if key == "scan_symbols":
        if not val:
            return "(없음)"
        if len(val) <= 3:
            return ", ".join(val)
        return f"{len(val)}개 ({val[0]} …)"
    if isinstance(val, float):
        if val == int(val):
            return str(int(val))
        return f"{val:g}"
    return str(val)


def format_config_changes(old: AppConfig, new: AppConfig) -> list[str]:
    """Return log lines for fields that changed (excludes unchanged)."""
    o = old.model_dump()
    n = new.model_dump()
    lines: list[str] = []

    for key in _LABELS:
        ov, nv = o.get(key), n.get(key)
        if ov == nv:
            continue
        label = _LABELS[key]
        lines.append(f"{label}: {_fmt_val(key, ov)} → {_fmt_val(key, nv)}")

    for key in _SENSITIVE:
        if (o.get(key) or "") != (n.get(key) or ""):
            if any((n.get(k) or "").strip() for k in _SENSITIVE):
                lines.append("API 키: 저장/변경됨")
            break

    return lines
