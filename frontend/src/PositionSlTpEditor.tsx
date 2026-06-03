import { useEffect, useState } from "react";
import { resetPositionSlTpAuto, setPositionSlTp } from "./api";
import { fmtNum, fmtPrice, fmtSlTpCell, slTpFromPrices } from "./format";
import type { Position } from "./types";

export function PositionSlTpEditor({
  position: p,
  onSaved,
}: {
  position: Position;
  onSaved: () => void;
}) {
  const fromPrices = slTpFromPrices(p.entry_price, p.stop_loss, p.take_profit, p.side);
  const initSl = p.sl_pct && p.sl_pct > 0 ? p.sl_pct : Math.abs(fromPrices.slPct);
  const initTp = p.tp_pct && p.tp_pct > 0 ? p.tp_pct : Math.abs(fromPrices.tpPct);

  const [slPct, setSlPct] = useState(String(Number(initSl.toFixed(2))));
  const [tpPct, setTpPct] = useState(String(Number(initTp.toFixed(2))));
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    const fp = slTpFromPrices(p.entry_price, p.stop_loss, p.take_profit, p.side);
    const s = p.sl_pct && p.sl_pct > 0 ? p.sl_pct : Math.abs(fp.slPct);
    const t = p.tp_pct && p.tp_pct > 0 ? p.tp_pct : Math.abs(fp.tpPct);
    setSlPct(String(Number(s.toFixed(2))));
    setTpPct(String(Number(t.toFixed(2))));
  }, [p.inst_id, p.sl_pct, p.tp_pct, p.stop_loss, p.take_profit, p.entry_price, p.side]);

  const t = fmtSlTpCell(
    p.entry_price,
    p.stop_loss,
    p.take_profit,
    p.side,
    p.strategy_mode,
    p.sl_pct,
    p.tp_pct,
    p.sl_tp_note,
  );

  const save = async () => {
    const sl = Number(slPct);
    const tp = Number(tpPct);
    if (!Number.isFinite(sl) || !Number.isFinite(tp)) {
      setErr("숫자를 입력하세요");
      return;
    }
    setSaving(true);
    setErr("");
    try {
      const res = await setPositionSlTp(p.inst_id, sl, tp);
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
        setErr(res.message || "복귀 실패");
        return;
      }
      onSaved();
    } catch {
      setErr("복귀 실패");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="sl-tp-editor" onClick={(e) => e.stopPropagation()}>
      <div className="sl-tp-summary">
        {p.sl_tp_manual && <span className="badge manual-sl-tp">수동</span>}
        <span className="sl-tp-pct-line">{t.text}</span>
      </div>
      <div className="sl-tp-prices muted">
        SL ${fmtPrice(p.stop_loss)} · TP ${fmtPrice(p.take_profit)}
      </div>
      <div className="sl-tp-inputs">
        <label>
          손절 %
          <input
            type="number"
            min={0.1}
            max={80}
            step={0.1}
            value={slPct}
            onChange={(e) => setSlPct(e.target.value)}
          />
        </label>
        <label>
          익절 %
          <input
            type="number"
            min={0.1}
            max={200}
            step={0.1}
            value={tpPct}
            onChange={(e) => setTpPct(e.target.value)}
          />
        </label>
        <button type="button" className="sl-tp-save" disabled={saving} onClick={save}>
          {saving ? "…" : "적용"}
        </button>
        {p.sl_tp_manual && (
          <button type="button" className="sl-tp-auto" disabled={saving} onClick={resetAuto}>
            AI자동
          </button>
        )}
      </div>
      <div className="sl-tp-hint">가격 도달 시 봇이 자동 손절·익절</div>
      {err && <div className="sl-tp-err">{err}</div>}
    </div>
  );
}
