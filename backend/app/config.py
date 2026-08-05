from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    # OpenAI
    openai_api_key: str
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0
    llm_seed: int = 42

    # Database
    database_url: str

    # Storage
    upload_dir: str = "./data/uploads"
    report_dir: str = "./data/reports"
    cache_dir: str = "./data/cache"

    # App
    debug: bool = True
    secret_key: str
    app_version: str = "1.0.0"
    cors_origins: List[str] = ["http://localhost:3000", "http://localhost:8000"]

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()