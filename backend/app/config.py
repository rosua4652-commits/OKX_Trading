from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    port: int = 8080
    initial_balance: float = 10_000.0
    scan_interval_sec: int = 30
    max_positions: int = 5
    min_quote_volume_usdt: float = 500_000.0
    scalp_min_quote_volume_usdt: float = 1_000_000.0
    scalp_min_abs_change_24h_pct: float = 1.0
    min_candles: int = 100
    default_stop_loss_pct: float = 2.0
    default_take_profit_pct: float = 3.0
    swing_stop_loss_pct: float = 5.0
    swing_take_profit_pct: float = 10.0
    trailing_activate_pct: float = 1.5
    trailing_distance_pct: float = 0.8
    trading_fee_pct: float = 0.05
    backtest_auto_run: bool = True
    backtest_interval_sec: int = 3600
    backtest_start_delay_sec: int = 5
    backtest_candle_limit: int = 500
    backtest_optimize: bool = True
    okx_api_key: str = ""
    okx_api_secret: str = ""
    okx_passphrase: str = ""
    okx_flag: str = "1"

    class Config:
        env_prefix = "OAT_"
        env_file = ".env"
        extra = "ignore"


settings = Settings()
