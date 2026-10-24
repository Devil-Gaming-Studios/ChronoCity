from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env", ".env.example"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # infra
    database_url: str = "postgresql://twin:twin@localhost:5432/chronotwin"
    redis_url: str = "redis://localhost:6379/0"
    kafka_bootstrap: str = "localhost:9092"
    bus: Literal["memory", "redpanda"] = "memory"
    # Local durable audit independent of optional telemetry services.
    audit_db_path: str = str(Path(__file__).resolve().parents[1] / "data" / "audit.sqlite3")

    # llm
    llm_mode: Literal["gemini", "claude", "ollama", "scripted"] = "scripted"
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    llm_model: str = "gemini-1.5-flash"
    llm_call_budget: int = 25

    # simulator
    sim_tick_seconds: float = 1.0
    sim_seed: int = 1337

    # map import
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    osm_user_agent: str = "ChronoTwin/0.1 (city digital twin prototype)"

    # api
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"

    # ingest
    window_seconds: float = 2.0
    trust_action_threshold: float = 0.5
    dedupe_window_s: float = 30.0
    ingest_api_key: str = ""
    ingest_rate_limit_per_minute: int = 120
    captcha_required: bool = False
    captcha_demo_token: str = "demo"
    llm_fallback_mode: Literal["scripted", "ollama"] = "scripted"
    llm_fallback_model: str = "small"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
