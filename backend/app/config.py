from decimal import Decimal
from functools import lru_cache
from typing import Annotated

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_WATCHLIST = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "V", "SPY"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="ALPHALAB_", extra="ignore")

    # Hosted Postgres providers (e.g. Neon on Vercel) set DATABASE_URL, so accept that too.
    database_url: str = Field(
        default="postgresql+psycopg://alphalab:alphalab@localhost:5432/alphalab",
        validation_alias=AliasChoices("ALPHALAB_DATABASE_URL", "DATABASE_URL"),
    )

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
    aws_profile: str = "alphalab"
    aws_region: str = "us-east-1"
    aws_expected_role: str = "AlphaLabBedrock"
    # Any Bedrock model that supports tool use via the Converse API.
    bedrock_model_id: str = "openai.gpt-oss-120b-1:0"
    agent_max_proposals: int = 5
    # Upper bound on model round-trips per run, to cap cost if the model loops.
    agent_max_turns: int = 20
    agent_max_tokens: int = 4096

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
