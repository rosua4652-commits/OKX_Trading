/** Strategy mode helpers for UI */

export function scalpEnabled(mode: string): boolean {
  return mode === "scalp" || mode === "both";
}

export function swingEnabled(mode: string): boolean {
  return mode === "swing" || mode === "both";
}

export function strategyModesFromToggle(scalp: boolean, swing: boolean): string | null {
  if (!scalp && !swing) return null;
  if (scalp && swing) return "both";
  if (scalp) return "scalp";
  return "swing";
}

/** Candle/chart interval key for API */
export function chartStrategyKey(mode: string, positionStrategy?: string): string {
  if (positionStrategy && positionStrategy !== "both") return positionStrategy;
  if (mode === "swing") return "swing";
  return "scalp";
}

export function strategyLabel(mode: string): string {
  if (mode === "both") return "단타+장타";
  if (mode === "swing") return "장타";
  return "단타";
}

/** Match backend settings.default_* / swing_* */
export function slTpPctForStrategy(mode: string): { sl: number; tp: number } {
  if (mode === "swing") return { sl: 5, tp: 10 };
  return { sl: 2, tp: 3 };
}
