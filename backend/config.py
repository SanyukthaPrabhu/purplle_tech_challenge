import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./retail_analytics.db"
    SECRET_KEY: str = "supersecretkeyretailiq123"
    PROJECT_NAME: str = "RetailIQ Analytics API"
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
