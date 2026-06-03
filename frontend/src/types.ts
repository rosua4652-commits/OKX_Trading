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
  sl_tp_note?: string;
  sl_tp_manual?: boolean;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  entry_reason: string;
  entry_score: number;
  strategy_mode: string;
  instrument_type?: string;
  opened_at?: string;
  leverage?: number;
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
  leverage: number;
  stop_loss_pct: number;
  take_profit_pct: number;
  trailing_stop: boolean;
  allow_short: boolean;
  min_score: number;
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
  notional_usdt?: number;
  strategy_mode?: string;
  mode?: string;
  ts: string;
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
  trades?: TradeRecord[];
}
