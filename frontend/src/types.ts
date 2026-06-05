export interface Position {
  id: string;
  inst_id: string;
  side: string;
  quantity: number;
  entry_price: number;
  current_price: number;
  stop_loss: number;
  take_profit: number;
  sl_pct?: number;
  tp_pct?: number;
  sl_usdt?: number;
  tp_usdt?: number;
  sl_tp_note?: string;
  sl_tp_manual?: boolean;
  auto_sl_tp_disabled?: boolean;
  auto_sl_disabled?: boolean;
  auto_tp_disabled?: boolean;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  entry_reason: string;
  entry_score: number;
  strategy_mode: string;
  instrument_type?: string;
  opened_at?: string;
  leverage?: number;
  notional_usdt?: number;
  liquidation_price?: number;
  scale_in_count?: number;
  last_scale_price?: number;
}

export interface CoinCandidate {
  inst_id: string;
  last_price: number;
  change_24h_pct: number;
  volume_24h_usdt: number;
  score: number;
  scalp_ok: boolean;
  swing_ok: boolean;
  short_scalp_ok?: boolean;
  short_swing_ok?: boolean;
  outlook: string;
  reasons: string[];
  rsi: number;
  trend: string;
  sparkline?: number[];
  ohlc_bars?: { o: number; h: number; l: number; c: number }[];
}

export interface Portfolio {
  balance: number;
  equity: number;
  available: number;
  unrealized_pnl: number;
  realized_pnl: number;
  positions: Position[];
  trade_count: number;
  win_rate: number;
}

export interface AppConfig {
  trade_mode: string;
  strategy_mode: string;
  instrument_type: string;
  auto_invest: boolean;
  position_side?: string;
  max_positions: number;
  order_size_usdt: number;
  position_size_mode?: string;
  order_size_pct?: number;
  max_order_size_usdt?: number;
  min_order_size_usdt?: number;
  size_split_slots?: boolean;
  order_size_basis?: string;
  leverage: number;
  margin_mode?: string;
  stop_loss_pct: number;
  take_profit_pct: number;
  trailing_stop: boolean;
  allow_short: boolean;
  min_score: number;
  backtest_auto_settings?: boolean;
  backtest_auto_sl_tp?: boolean;
  trend_scale_in?: boolean;
  max_scale_ins?: number;
  scale_in_size_pct?: number;
  scale_in_min_pnl_pct?: number;
  trend_exit_confirm_bars?: number;
  backtest_interval_minutes?: number;
  backtest_candle_limit?: number;
  scan_symbols?: string[];
  paper_initial_balance: number;
  okx_api_key: string;
  okx_api_secret: string;
  okx_passphrase: string;
  okx_flag: string;
  api_keys_configured?: boolean;
}

export interface TradeRecord {
  id: string;
  inst_id: string;
  side: string;
  quantity: number;
  price: number;
  pnl: number;
  pnl_pct: number;
  reason: string;
  close_type?: string;
  position_side?: string;
  entry_price?: number;
  exit_price?: number;
  notional_usdt?: number;
  strategy_mode?: string;
  mode?: string;
  ts: string;
}

export interface PendingOrder {
  inst_id: string;
  ord_id: string;
  side: string;
  pos_side: string;
  order_type: string;
  price: number;
  size: number;
  filled_size: number;
  state: string;
  ts: string;
}

export interface BacktestTrial {
  min_score: number;
  total_pnl: number;
  win_rate: number;
  trades: number;
  long_entries: number;
  short_entries: number;
}

export interface BacktestDirectionTrial {
  mode: string;
  window_ratio: number;
  min_score: number;
  total_pnl: number;
  win_rate: number;
  trades: number;
  long_trades?: number;
  short_trades?: number;
}

export interface BacktestSlTpTrial {
  stop_loss_pct: number;
  take_profit_pct: number;
  total_pnl: number;
  win_rate: number;
  trades: number;
  tp_hits?: number;
  sl_hits?: number;
}

export interface BacktestRecommendation {
  min_score: number;
  reason: string;
  trials: BacktestTrial[];
  direction?: string;
  direction_reason?: string;
  direction_trials?: BacktestDirectionTrial[];
  window_ratio?: number;
  stop_loss_pct?: number;
  take_profit_pct?: number;
  sl_tp_reason?: string;
  sl_tp_trials?: BacktestSlTpTrial[];
}

export interface BacktestMetrics {
  total_pnl: number;
  total_pnl_pct: number;
  win_rate: number;
  trade_count: number;
  long_trades: number;
  short_trades: number;
  avg_score_entries: number;
  max_drawdown_pct: number;
  bars_evaluated: number;
  start_equity?: number;
  end_equity?: number;
  order_notional_usdt?: number;
  total_fees_usdt?: number;
}

export interface BacktestTrade {
  inst_id: string;
  side: string;
  strategy: string;
  entry_bar: number;
  exit_bar: number;
  entry_price: number;
  exit_price: number;
  score: number;
  sl_pct: number;
  tp_pct: number;
  notional_usdt?: number;
  margin_usdt?: number;
  fee_usdt?: number;
  pnl_usdt: number;
  pnl_pct: number;
  exit_reason: string;
}

export interface BacktestLogEntry {
  ts: string;
  level: string;
  message: string;
}

export interface SymbolCandleChart {
  bars: { o: number; h: number; l: number; c: number }[];
  total_bars: number;
  display_offset: number;
  trade_markers?: { entry: number; exit: number }[];
}

export interface SymbolSlTpProfile {
  inst_id: string;
  stop_loss_pct: number;
  take_profit_pct: number;
  win_rate: number;
  trades: number;
  tp_hits?: number;
  sl_hits?: number;
  avg_win_tp_pct?: number;
  updated_at?: string;
  run_id?: string;
}

export interface BacktestResult {
  id: string;
  status: string;
  started_at: string;
  finished_at?: string;
  strategy_mode: string;
  symbols: string[];
  candle_interval?: string;
  symbol_charts?: Record<string, SymbolCandleChart>;
  params_snapshot?: Record<string, unknown>;
  metrics?: BacktestMetrics;
  recommendation?: BacktestRecommendation;
  trades?: BacktestTrade[];
  logs?: BacktestLogEntry[];
  error?: string;
  symbol_profiles?: Record<string, SymbolSlTpProfile>;
}

export interface BacktestStatus {
  running: boolean;
  progress_pct: number;
  phase: string;
  message: string;
  result_id?: string;
}

export interface BacktestHistoryEntry {
  id: string;
  finished_at: string;
  status: string;
  strategy_mode: string;
  symbols: string[];
  metrics?: BacktestMetrics;
  recommendation?: {
    min_score: number;
    reason?: string;
    direction?: string;
    window_ratio?: number;
    stop_loss_pct?: number;
    take_profit_pct?: number;
  };
  direction?: string;
  window_ratio?: number;
  trade_count: number;
  applied_sl_pct?: number;
  applied_tp_pct?: number;
  exit_stats?: { sl: number; tp: number; end_close: number; trailing: number; other: number };
  error?: string;
}

export interface BacktestBundle {
  status: BacktestStatus;
  result: BacktestResult | null;
  history?: BacktestHistoryEntry[];
  symbol_profiles?: SymbolSlTpProfile[];
  auto_run?: boolean;
  interval_sec?: number;
  interval_minutes?: number;
}

export interface StatusData {
  build: string;
  config: AppConfig;
  bot: {
    status: { running: boolean; phase: string; scan_count: number; message: string };
    activity_log: { ts: string; phase: string; message: string; level: string }[];
  };
  portfolio: Portfolio;
  candidates: CoinCandidate[];
  linked: boolean;
  link_message: string;
  portfolio_source?: "paper" | "okx";
  portfolio_sync_message?: string;
  next_order_size_usdt?: number;
  next_order_size_detail?: {
    notional_usdt: number;
    margin_usdt: number;
    leverage: number;
    summary: string;
    steps: string[];
    slots_remaining: number;
    order_size_basis: string;
  };
  pending_orders?: PendingOrder[];
  trades?: TradeRecord[];
  backtest?: BacktestBundle;
}
