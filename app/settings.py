from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WORKBENCH_", env_file=".env", extra="ignore")

    env: str = "development"
    database_url: str = "sqlite:///./workbench.dev.db"
    redis_url: str = "redis://localhost:6379/0"
    object_storage_url: str = "http://localhost:9000"
    log_level: str = "INFO"
    auth_secret: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
