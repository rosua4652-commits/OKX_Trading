export interface Position {
  id: string;
  inst_id: string;
  side: string;
  quantity: number;
  entry_price: number;
  current_price: number;
  stop_loss: number;
  take_profit: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  entry_reason: string;
  entry_score: number;
  strategy_mode: string;
}

export interface CoinCandidate {
  inst_id: string;
  last_price: number;
  change_24h_pct: number;
  volume_24h_usdt: number;
  score: number;
  scalp_ok: boolean;
  swing_ok: boolean;
  outlook: string;
  reasons: string[];
  rsi: number;
  trend: string;
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
  max_positions: number;
  order_size_usdt: number;
  leverage: number;
  stop_loss_pct: number;
  take_profit_pct: number;
  trailing_stop: boolean;
  allow_short: boolean;
  min_score: number;
  okx_api_key: string;
  okx_api_secret: string;
  okx_passphrase: string;
  okx_flag: string;
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
}
