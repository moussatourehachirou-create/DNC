from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BIE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://bie:bie@localhost:5432/bie"
    anthropic_api_key: str | None = None
    llm_model: str = "claude-opus-5-5"
    llm_light_model: str = "claude-haiku-4-5"
    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
