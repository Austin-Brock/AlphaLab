from functools import lru_cache
from typing import Annotated

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_WATCHLIST = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "V", "SPY"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="ALPHALAB_", extra="ignore")

    database_url: str = "postgresql+psycopg://alphalab:alphalab@localhost:5432/alphalab"

    # Alpaca market data. Keys come from a free paper-trading account.
    alpaca_api_key: SecretStr | None = None
    alpaca_secret_key: SecretStr | None = None
    alpaca_data_url: str = "https://data.alpaca.markets"
    # "iex" is free; "sip" (all US exchanges) requires a paid subscription.
    alpaca_feed: str = "iex"

    # Securities shown by default. Env format: ALPHALAB_WATCHLIST=AAPL,MSFT,SPY
    watchlist: Annotated[list[str], NoDecode] = DEFAULT_WATCHLIST
    # How long a fetched latest price is served from cache before refetching.
    price_cache_ttl_seconds: int = 60

    @field_validator("watchlist", mode="before")
    @classmethod
    def split_watchlist(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            value = value.split(",")
        return [symbol.strip().upper() for symbol in value if symbol.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
