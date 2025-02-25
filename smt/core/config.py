from pydantic import computed_field, HttpUrl
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
    STEAM_OPENID_URL: HttpUrl

    @computed_field
    @property
    def STEAM_RETURN_URL(self) -> HttpUrl:
        return HttpUrl(f"{self.BASE_URL}api/{self.API_VERSION}/auth/steam/callback")

    @computed_field
    @property
    def DATABASE_URI(self) -> str:
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    model_config = SettingsConfigDict(
        env_file="../.env",
        extra="ignore",
    )


settings = Settings()
