# Application settings loaded from environment variables.
from pathlib import Path
from typing import List

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# Returns the repo root from this file's location so .env loads from any cwd.
def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


# Loads process settings from environment variables and .env.
class Settings(BaseSettings):
    # Zhipu AI SDK credentials
    zai_api_key: str = Field(validation_alias=AliasChoices("ZAI_API_KEY", "OPENAI_API_KEY"))
    llm_base_url: str
    llm_model: str = "glm-4-flash"
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
    # Local CV privacy pipeline settings.
    cv_ocr_enabled: bool = True
    cv_ocr_max_pages: int = 6
    cv_ocr_render_scale: float = 2.6
    cv_ocr_min_page_chars: int = 24
    cv_ocr_confidence_threshold: float = 0.55
    cv_local_ner_enabled: bool = True
    cv_local_ner_model: str = "urchade/gliner_multi_pii-v1"
    cv_local_ner_threshold: float = 0.55
    cv_local_ner_max_chars: int = 6000

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
    matching_enabled: bool = True
    matching_schema_version: str = "1.0.0"
    matching_algorithm_version: str = "candidate-matching-v1"
    matching_taxonomy_version: str = "skill-taxonomy-v1"
    matching_recalc_timeout_seconds: int = 900
    matching_recalc_debounce_seconds: int = 5
    cors_origins: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
    ]


    # JD parser mode: rule (default, deterministic) | hybrid (rule + LLM refine) | qwen (rule + local Qwen model)
    jd_parser_mode: str = "rule"
    # Optional model override for the LLM skill refiner (defaults to llm_model).
    jd_parser_llm_model: str | None = None
    # Local Qwen3-0.6B fine-tuned extractor settings (used when mode == "qwen").
    jd_qwen_model_id: str = "Rithankoushik/job-parser-model-qwen"
    jd_qwen_max_new_tokens: int = 512
    jd_qwen_device: str = "auto"
    # PolyU public jobs board used by the one-click sync button.
    polyu_jobs_base_url: str = "https://jobs.polyu.edu.hk"
    polyu_jobs_list_url: str = "https://jobs.polyu.edu.hk/general.php"

    # Ignore unrelated .env keys so loading never fails on extra input
    # (pydantic-settings defaults to extra="forbid", which breaks when the
    # .env contains aliased keys such as OPENAI_API_KEY).
    # The path is absolute so a CLI started from any directory still finds .env.
    model_config = SettingsConfigDict(env_file=str(_repo_root() / ".env"), extra="ignore")


# Instantiates process-wide settings from environment variables and .env.
settings = Settings()
