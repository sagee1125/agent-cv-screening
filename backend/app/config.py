from typing import List

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Zhipu AI SDK credentials
    zai_api_key: str = Field(validation_alias=AliasChoices("ZAI_API_KEY", "OPENAI_API_KEY"))
    llm_base_url: str
    llm_model: str = "gpt-4o-mini"
    llm_vision_model: str = "glm-4v-flash"
    llm_vision_max_pages: int = 6
    llm_vision_render_scale: float = 2.6
    llm_vision_image_format: str = "PNG"
    llm_vision_jpeg_quality: int = 90
    llm_vision_retry_attempts: int = 2
    llm_vision_focus_pass_enabled: bool = True
    llm_text_fallback_enabled: bool = True
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
    cors_origins: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
    ]

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()