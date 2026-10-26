from decimal import Decimal
from functools import lru_cache
from typing import Annotated

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# About 50 large, heavily traded US companies across sectors, plus SPY.
DEFAULT_WATCHLIST = [
    # The original ten
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "V", "SPY",
    # Technology
    "AVGO", "ORCL", "CRM", "ADBE", "AMD", "CSCO", "QCOM",
    # Consumer
    "HD", "MCD", "NKE", "COST", "WMT", "PG", "KO", "PEP",
    # Financials
    "MA", "BAC", "GS", "WFC",
    # Health care
    "UNH", "JNJ", "LLY", "PFE", "MRK", "ABBV", "TMO",
    # Energy
    "XOM", "CVX", "COP",
    # Industrials
    "CAT", "BA", "GE", "HON", "UPS",
    # Communication
    "NFLX", "DIS", "T", "VZ",
    # Utilities and materials
    "NEE", "LIN",
]  # fmt: skip


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="ALPHALAB_", extra="ignore")

    # Hosted Postgres providers (e.g. Neon on Vercel) set DATABASE_URL, so accept that too.
    database_url: str = Field(
        default="postgresql+psycopg://alphalab:alphalab@localhost:5432/alphalab",
        validation_alias=AliasChoices("ALPHALAB_DATABASE_URL", "DATABASE_URL"),
    )

    # Owner key for every change (orders, pause/resume, agent runs). Reads stay public.
    # Unset means all changes are refused. Generate with: openssl rand -hex 32
    admin_key: SecretStr | None = None

    # Alpaca market data. Keys come from a free paper-trading account.
    alpaca_api_key: SecretStr | None = None
    alpaca_secret_key: SecretStr | None = None
    alpaca_data_url: str = "https://data.alpaca.markets"
    # Used only for the market clock (open/closed); no orders are ever sent to Alpaca.
    alpaca_trading_url: str = "https://paper-api.alpaca.markets"
    # "iex" is free; "sip" (all US exchanges) requires a paid subscription.
    alpaca_feed: str = "iex"

    # Securities shown by default. Env format: ALPHALAB_WATCHLIST=AAPL,MSFT,SPY
    watchlist: Annotated[list[str], NoDecode] = DEFAULT_WATCHLIST
    # What the dashboard's value chart compares each portfolio against.
    benchmark_symbol: str = "SPY"
    # How long a fetched latest price is served from cache before refetching.
    price_cache_ttl_seconds: int = 60

    # Trading engine.
    # Reject orders while the US market is closed. Set false to test trades after hours.
    enforce_market_hours: bool = True
    # Reject orders when the price was fetched longer ago than this.
    max_price_age_seconds: int = 300
    # Simulated slippage: buys fill this many basis points above market, sells below.
    slippage_bps: Decimal = Decimal("5")
    # Flat commission charged per filled order.
    commission_per_order: Decimal = Decimal("0")

    # AI trading agent (AWS Bedrock).
    # The AWS profile must use the restricted AlphaLabBedrock role; the app refuses any other.
    # Empty means "use credentials from the environment" (the GitHub Actions daily run).
    aws_profile: str | None = "alphalab"
    aws_region: str = "us-east-1"
    aws_expected_role: str = "AlphaLabBedrock"
    # Any Bedrock model that supports tool use via the Converse API.
    bedrock_model_id: str = "openai.gpt-oss-120b-1:0"
    agent_max_proposals: int = 5
    # Upper bound on model round-trips per run, to cap cost if the model loops.
    agent_max_turns: int = 30
    agent_max_tokens: int = 4096
    # The scheduled daily run waits until this time, US Eastern, so the opening
    # volatility has settled. Format HH:MM.
    daily_run_after: str = "10:00"

    @field_validator("admin_key")
    @classmethod
    def admin_key_is_long(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < 32:
            raise ValueError("admin_key must be at least 32 characters")
        return value

    @field_validator("aws_profile")
    @classmethod
    def blank_profile_means_environment(cls, value: str | None) -> str | None:
        return value or None

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, value: str) -> str:
        # Providers hand out postgres:// or postgresql:// URLs; SQLAlchemy would pick psycopg2.
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value.removeprefix(prefix)
        return value

    @field_validator("watchlist", mode="before")
    @classmethod
    def split_watchlist(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            value = value.split(",")
        return [symbol.strip().upper() for symbol in value if symbol.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
