"""Konfiguration aus Umgebungsvariablen.

Bewusst ohne pydantic-settings, damit die Abhängigkeitsliste klein bleibt: eine schlanke
Klasse mit typisierten Feldern, die aus ``os.environ`` liest. ``settings()`` liefert eine
gecachte Instanz; ``reload()`` verwirft den Cache (für Tests).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

TIER_STANDARD = "standard"
TIER_SOVEREIGN = "sovereign"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_list(name: str) -> list[str]:
    raw = _env(name)
    return [x.strip() for x in raw.split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    """Alle vom Worker gelesenen Umgebungsvariablen (siehe ``.env.example`` im Monorepo-Root)."""

    app_env: str = "development"
    app_version: str = "0.1.0"

    database_url: str = ""
    redis_url: str = ""

    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    task_queue_cpu: str = "chopstr-cpu"
    task_queue_gpu: str = "chopstr-gpu"

    s3_endpoint: str = ""
    s3_region: str = "eu-central-1"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket_sources: str = "chopstr-sources"
    s3_bucket_derived: str = "chopstr-derived"
    s3_force_path_style: bool = True
    local_storage_dir: str = ""

    llm_provider: str = "bedrock-eu"
    aws_region: str = "eu-central-1"
    bedrock_model_id: str = ""
    mistral_base_url: str = "https://api.mistral.ai"
    mistral_api_key: str = ""
    mistral_model: str = ""
    selfhost_llm_base_url: str = ""
    selfhost_llm_model: str = ""
    selfhost_llm_api_key: str = ""

    asr_model_de: str = ""
    asr_model_ch: str = ""
    asr_device: str = "auto"
    asr_compute: str = "int8"
    asr_window_s: float = 600.0
    asr_overlap_s: float = 20.0
    hf_token: str = ""
    diarizer_model: str = ""
    gladia_api_key: str = ""
    gladia_base_url: str = ""

    languagetool_url: str = ""
    egress_allowlist: list[str] = field(default_factory=list)

    work_dir: str = ""

    # Render (Phase 3): x264-Preset (Tests setzen ultrafast), Font-Verzeichnis, YuNet-Modell
    render_x264_preset: str = "medium"
    render_fonts_dir: str = ""
    yunet_model_path: str = ""

    # Kostenmodell (EUR); alle Werte per ENV überschreibbar, siehe costlog.py
    gpu_eur_per_hour: float = 1.20
    cpu_eur_per_hour: float = 0.05
    storage_eur_per_gb_month: float = 0.02
    llm_eur_per_1m_input: float = 3.0
    llm_eur_per_1m_output: float = 15.0
    gladia_eur_per_hour: float = 0.60

    @property
    def is_local_storage(self) -> bool:
        return not self.s3_endpoint

    def asr_model_for(self, variant: str) -> str:
        """Modell-ID für ASR-Variante ('de' | 'de-CH'). Leer, wenn nicht konfiguriert."""
        return self.asr_model_ch if variant == "de-CH" else self.asr_model_de


def load_settings() -> Settings:
    """Liest alle Werte frisch aus der Umgebung."""
    return Settings(
        app_env=_env("APP_ENV", "development"),
        app_version=_env("APP_VERSION", "0.1.0"),
        database_url=_env("DATABASE_URL"),
        redis_url=_env("REDIS_URL"),
        temporal_address=_env("TEMPORAL_ADDRESS", "localhost:7233"),
        temporal_namespace=_env("TEMPORAL_NAMESPACE", "default"),
        task_queue_cpu=_env("TEMPORAL_TASK_QUEUE_CPU", "chopstr-cpu"),
        task_queue_gpu=_env("TEMPORAL_TASK_QUEUE_GPU", "chopstr-gpu"),
        s3_endpoint=_env("S3_ENDPOINT"),
        s3_region=_env("S3_REGION", "eu-central-1"),
        s3_access_key=_env("S3_ACCESS_KEY"),
        s3_secret_key=_env("S3_SECRET_KEY"),
        s3_bucket_sources=_env("S3_BUCKET_SOURCES", "chopstr-sources"),
        s3_bucket_derived=_env("S3_BUCKET_DERIVED", "chopstr-derived"),
        s3_force_path_style=_env_bool("S3_FORCE_PATH_STYLE", True),
        local_storage_dir=_env("LOCAL_STORAGE_DIR"),
        llm_provider=_env("LLM_PROVIDER", "bedrock-eu"),
        aws_region=_env("AWS_REGION", "eu-central-1"),
        bedrock_model_id=_env("BEDROCK_MODEL_ID"),
        mistral_base_url=_env("MISTRAL_BASE_URL", "https://api.mistral.ai"),
        mistral_api_key=_env("MISTRAL_API_KEY"),
        mistral_model=_env("MISTRAL_MODEL"),
        selfhost_llm_base_url=_env("SELFHOST_LLM_BASE_URL"),
        selfhost_llm_model=_env("SELFHOST_LLM_MODEL"),
        selfhost_llm_api_key=_env("SELFHOST_LLM_API_KEY"),
        asr_model_de=_env("ASR_MODEL_DE"),
        asr_model_ch=_env("ASR_MODEL_CH"),
        asr_device=_env("ASR_DEVICE", "auto"),
        asr_compute=_env("ASR_COMPUTE", "int8"),
        asr_window_s=_env_float("ASR_WINDOW_S", 600.0),
        asr_overlap_s=_env_float("ASR_OVERLAP_S", 20.0),
        hf_token=_env("HF_TOKEN"),
        diarizer_model=_env("DIARIZER_MODEL"),
        gladia_api_key=_env("GLADIA_API_KEY"),
        gladia_base_url=_env("GLADIA_BASE_URL"),
        languagetool_url=_env("LANGUAGETOOL_URL"),
        egress_allowlist=_env_list("EGRESS_ALLOWLIST"),
        work_dir=_env("WORKER_WORK_DIR"),
        render_x264_preset=_env("RENDER_X264_PRESET", "medium"),
        render_fonts_dir=_env("RENDER_FONTS_DIR"),
        yunet_model_path=_env("YUNET_MODEL_PATH"),
        gpu_eur_per_hour=_env_float("GPU_EUR_PER_HOUR", 1.20),
        cpu_eur_per_hour=_env_float("CPU_EUR_PER_HOUR", 0.05),
        storage_eur_per_gb_month=_env_float("STORAGE_EUR_PER_GB_MONTH", 0.02),
        llm_eur_per_1m_input=_env_float("LLM_EUR_PER_1M_INPUT", 3.0),
        llm_eur_per_1m_output=_env_float("LLM_EUR_PER_1M_OUTPUT", 15.0),
        gladia_eur_per_hour=_env_float("GLADIA_EUR_PER_HOUR", 0.60),
    )


@lru_cache(maxsize=1)
def settings() -> Settings:
    """Gecachte Instanz. Nach Änderungen an ``os.environ`` ``reload()`` aufrufen."""
    return load_settings()


def reload() -> Settings:
    settings.cache_clear()
    return settings()


__all__ = ["Settings", "TIER_SOVEREIGN", "TIER_STANDARD", "load_settings", "reload", "settings"]
