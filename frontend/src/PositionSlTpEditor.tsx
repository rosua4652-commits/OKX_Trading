import { useEffect, useMemo, useState } from "react";
import {
  resetPositionSlTpAuto,
  setPositionAutoSlTpDisabled,
  setPositionSlTp,
} from "./api";
import { fmtNum, fmtPnlUsdt, fmtPrice, slTpFromPrices } from "./format";
import type { Position } from "./types";

function crossedLevel(p: Position) {
  const isShort = p.side === "short";
  const hitTp =
    p.take_profit > 0 &&
    (isShort ? p.current_price <= p.take_profit : p.current_price >= p.take_profit);
  const hitSl =
    p.stop_loss > 0 &&
    (isShort ? p.current_price >= p.stop_loss : p.current_price <= p.stop_loss);
  return { hitTp, hitSl };
}

function positionNotional(p: Position) {
  if (p.notional_usdt && p.notional_usdt > 0) return p.notional_usdt;
  return p.quantity * (p.entry_price || p.current_price || 0);
}

function pnlBaseUsdt(p: Position) {
  const notional = positionNotional(p);
  if (p.instrument_type === "spot") return notional;
  const lev = p.leverage && p.leverage > 0 ? p.leverage : 1;
  return notional / lev;
}

function pctToUsdt(pct: number, base: number) {
  return Math.abs((base * pct) / 100);
}

function usdtToPct(usdt: number, base: number) {
  return base > 0 ? (Math.abs(usdt) / base) * 100 : 0;
}

function strategyLabel(strategy?: string) {
  if (strategy === "swing") return "장타";
  if (strategy === "both") return "복합";
  return "단타";
}

function amountInputValue(amount: number) {
  if (!Number.isFinite(amount) || amount <= 0) return "";
  const digits = amount < 0.01 ? 5 : amount < 0.1 ? 4 : 3;
  return amount.toFixed(digits).replace(/0+$/, "").replace(/\.$/, "");
}

export function PositionSlTpEditor({
  position: p,
  onSaved,
}: {
  position: Position;
  onSaved: () => void;
}) {
  const lev = p.leverage && p.leverage > 0 ? p.leverage : 1;
  const instType = p.instrument_type || "swap";
  const base = pnlBaseUsdt(p);
  const fromPrices = slTpFromPrices(
    p.entry_price,
    p.stop_loss,
    p.take_profit,
    p.side,
    lev,
    instType,
  );
  const initSlPct = p.sl_pct && p.sl_pct > 0 ? p.sl_pct : Math.abs(fromPrices.slPct);
  const initTpPct = p.tp_pct && p.tp_pct > 0 ? p.tp_pct : Math.abs(fromPrices.tpPct);
  const initialSlUsdt = p.sl_usdt && p.sl_usdt > 0 ? p.sl_usdt : pctToUsdt(initSlPct, base);
  const initialTpUsdt = p.tp_usdt && p.tp_usdt > 0 ? p.tp_usdt : pctToUsdt(initTpPct, base);

  const [slUsdt, setSlUsdt] = useState(amountInputValue(initialSlUsdt));
  const [tpUsdt, setTpUsdt] = useState(amountInputValue(initialTpUsdt));
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    const b = pnlBaseUsdt(p);
    const fp = slTpFromPrices(
      p.entry_price,
      p.stop_loss,
      p.take_profit,
      p.side,
      p.leverage && p.leverage > 0 ? p.leverage : 1,
      p.instrument_type || "swap",
    );
    const s = p.sl_pct && p.sl_pct > 0 ? p.sl_pct : Math.abs(fp.slPct);
    const t = p.tp_pct && p.tp_pct > 0 ? p.tp_pct : Math.abs(fp.tpPct);
    setSlUsdt(amountInputValue(p.sl_usdt && p.sl_usdt > 0 ? p.sl_usdt : pctToUsdt(s, b)));
    setTpUsdt(amountInputValue(p.tp_usdt && p.tp_usdt > 0 ? p.tp_usdt : pctToUsdt(t, b)));
  }, [
    p.inst_id,
    p.sl_pct,
    p.tp_pct,
    p.stop_loss,
    p.take_profit,
    p.entry_price,
    p.side,
    p.leverage,
    p.instrument_type,
    p.notional_usdt,
    p.quantity,
    p.sl_usdt,
    p.tp_usdt,
  ]);

  const slAmount = p.sl_usdt && p.sl_usdt > 0 ? p.sl_usdt : pctToUsdt(initSlPct, base);
  const tpAmount = p.tp_usdt && p.tp_usdt > 0 ? p.tp_usdt : pctToUsdt(initTpPct, base);
  const crossed = useMemo(() => crossedLevel(p), [p]);
  const slDisabled = !!p.auto_sl_disabled || !!p.auto_sl_tp_disabled;
  const tpDisabled = !!p.auto_tp_disabled || !!p.auto_sl_tp_disabled;

  const save = async () => {
    const sl = Number(slUsdt);
    const tp = Number(tpUsdt);
    if (!Number.isFinite(sl) || !Number.isFinite(tp) || sl <= 0 || tp <= 0) {
      setErr("손절/익절 USDT 금액을 0보다 크게 입력하세요");
      return;
    }
    const slPctToSave = usdtToPct(sl, base);
    const tpPctToSave = usdtToPct(tp, base);
    if (slPctToSave <= 0 || tpPctToSave <= 0) {
      setErr("증거금 기준 금액을 계산할 수 없습니다");
      return;
    }
    setSaving(true);
    setErr("");
    try {
      const res = await setPositionSlTp(p.inst_id, slPctToSave, tpPctToSave);
      if (!res.ok) {
        setErr(res.message || "저장 실패");
        return;
      }
      onSaved();
    } catch {
      setErr("저장 실패");
    } finally {
      setSaving(false);
    }
  };

  const resetAuto = async () => {
    setSaving(true);
    setErr("");
    try {
      const res = await resetPositionSlTpAuto(p.inst_id);
      if (!res.ok) {
        setErr(res.message || "자동 복구 실패");
        return;
      }
      onSaved();
    } catch {
      setErr("자동 복구 실패");
    } finally {
      setSaving(false);
    }
  };

  const setDisabled = async (patch: { sl_disabled?: boolean; tp_disabled?: boolean }) => {
    setSaving(true);
    setErr("");
    try {
      const res = await setPositionAutoSlTpDisabled(p.inst_id, patch);
      if (!res.ok) {
        setErr(res.message || "설정 실패");
        return;
      }
      onSaved();
    } catch {
      setErr("설정 실패");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="sl-tp-editor" onClick={(e) => e.stopPropagation()}>
      <div className="sl-tp-summary">
        {p.sl_tp_manual && <span className="badge manual-sl-tp">수동</span>}
        {slDisabled && <span className="badge disabled-sl-tp">손절 OFF</span>}
        {tpDisabled && <span className="badge disabled-sl-tp">익절 OFF</span>}
        <span className="sl-tp-pct-line">
          [{strategyLabel(p.strategy_mode)}] SL -{fmtPnlUsdt(slAmount)} / TP +{fmtPnlUsdt(tpAmount)}
        </span>
      </div>
      <div className="sl-tp-prices muted">
        SL ${fmtPrice(p.stop_loss)} · TP ${fmtPrice(p.take_profit)} · ROI {fmtNum(initSlPct, 1)}/{fmtNum(initTpPct, 1)}%
      </div>
      {(slDisabled || tpDisabled) && (crossed.hitTp || crossed.hitSl) && (
        <div className="sl-tp-warn">
          꺼둔 항목은 가격선을 넘어도 자동 청산하지 않습니다.
        </div>
      )}
      <div className="sl-tp-inputs">
        <label>
          손절 USDT
          <input
            type="number"
            min={0.00001}
            step={0.0001}
            value={slUsdt}
            onChange={(e) => setSlUsdt(e.target.value)}
          />
        </label>
        <label>
          익절 USDT
          <input
            type="number"
            min={0.00001}
            step={0.0001}
            value={tpUsdt}
            onChange={(e) => setTpUsdt(e.target.value)}
          />
        </label>
        <button type="button" className="sl-tp-save" disabled={saving} onClick={save}>
          {saving ? "저장중" : "적용"}
        </button>
        {(p.sl_tp_manual || slDisabled || tpDisabled) && (
          <button type="button" className="sl-tp-auto" disabled={saving} onClick={resetAuto}>
            자동
          </button>
        )}
      </div>
      <div className="sl-tp-toggle-row">
        <label className="sl-tp-disable-toggle">
          <input
            type="checkbox"
            checked={slDisabled}
            disabled={saving}
            onChange={(e) => setDisabled({ sl_disabled: e.target.checked })}
          />
          손절 사용 안 함
        </label>
        <label className="sl-tp-disable-toggle">
          <input
            type="checkbox"
            checked={tpDisabled}
            disabled={saving}
            onChange={(e) => setDisabled({ tp_disabled: e.target.checked })}
          />
          익절 사용 안 함
        </label>
      </div>
      <div className="sl-tp-hint">
        입력 금액은 실제 PnL(USDT) 기준입니다. 저장 시 이 포지션 증거금 기준 ROI%로 자동 환산됩니다.
      </div>
      {err && <div className="sl-tp-err">{err}</div>}
    </div>
  );
}
