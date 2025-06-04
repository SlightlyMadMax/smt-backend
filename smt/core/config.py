from functools import lru_cache

from pydantic import HttpUrl, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Steam Market Trader"
    BASE_URL: HttpUrl
    DEBUG: bool
    SESSION_SECRET_KEY: str
    API_VERSION: str
    PORT: int = 8000

    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str
    DB_HOST: str
    DB_PORT: int = 5432

    STEAM_API_KEY: str
    STEAM_USERNAME: str
    STEAM_PASSWORD: str
    STEAMID: str
    STEAM_SHARED_SECRET: str
    STEAM_IDENTITY_SECRET: str

    REDIS_PORT: str

    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str

    @computed_field
    @property
    def DATABASE_URI(self) -> str:
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    model_config = SettingsConfigDict(
        env_file="../.env",
        extra="ignore",
        frozen=True,
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()
