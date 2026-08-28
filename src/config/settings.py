"""Project settings loaded from .env."""

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


def find_project_root() -> Path:
    """Resolve the project root from this file location."""
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = find_project_root()
ENV_PATH = PROJECT_ROOT / ".env"

load_dotenv(ENV_PATH)


def get_env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def get_env_int(name: str, default: int) -> int:
    value = os.getenv(name)

    if value is None or not value.strip():
        return default

    try:
        return int(value)
    except ValueError:
        return default


def get_env_float(name: str, default: float) -> float:
    value = os.getenv(name)

    if value is None or not value.strip():
        return default

    try:
        return float(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    project_root: Path

    # NCBI / PubMed
    ncbi_email: str
    ncbi_api_key: str

    # ILAAS / OpenAI-compatible LLM endpoint
    ilaas_api_key: str
    ilaas_base_url: str
    ilaas_model: str
    ilaas_max_tokens: int
    ilaas_temperature: float

    # Runtime
    max_retries: int
    retry_sleep_seconds: int

    # Paperclip
    paperclip_binary: str
    paperclip_full_text_path_template: str


def load_settings() -> Settings:
    return Settings(
        project_root=PROJECT_ROOT,

        ncbi_email=get_env_str("NCBI_EMAIL"),
        ncbi_api_key=get_env_str("NCBI_API_KEY"),

        ilaas_api_key=get_env_str("ILAAS_API_KEY"),
        ilaas_base_url=get_env_str(
            "ILAAS_BASE_URL",
            "https://llm.ilaas.fr/v1",
        ).rstrip("/"),
        ilaas_model=get_env_str("ILAAS_MODEL", "mistral-medium-latest"),
        ilaas_max_tokens=get_env_int("ILAAS_MAX_TOKENS", 6144),
        ilaas_temperature=get_env_float("ILAAS_TEMPERATURE", 0.0),

        max_retries=get_env_int("MAX_RETRIES", 3),
        retry_sleep_seconds=get_env_int("RETRY_SLEEP_SECONDS", 3),

        paperclip_binary=get_env_str("PAPERCLIP_BINARY", "paperclip"),
        paperclip_full_text_path_template=get_env_str(
            "PAPERCLIP_FULL_TEXT_PATH_TEMPLATE",
            "/papers/{pmc_id}/content.lines",
        ),
    )


settings = load_settings()
