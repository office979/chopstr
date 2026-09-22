"""Kostensenke: schreibt ``job_costs``-Zeilen und schätzt EUR pro Job.

Preistabelle per ENV überschreibbar (siehe ``config.Settings``):
GPU_EUR_PER_HOUR, CPU_EUR_PER_HOUR, STORAGE_EUR_PER_GB_MONTH, LLM_EUR_PER_1M_INPUT,
LLM_EUR_PER_1M_OUTPUT, GLADIA_EUR_PER_HOUR. Die Defaults sind grobe Platzhalter, keine
Anbieterpreise. TODO: pro Provider/Modell differenzieren, sobald Verträge feststehen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import config, db

JOB_TYPES = (
    "ingest", "asr", "diarize", "nlp", "heatmap", "llm_propose", "llm_score", "llm_candidates", "llm_copy", "render",
)  # fmt: skip


@dataclass
class Cost:
    workspace_id: str
    job_type: str
    source_id: str | None = None
    clip_id: str | None = None
    provider: str | None = None
    model_id: str | None = None
    source_minutes: float = 0.0
    gpu_seconds: float = 0.0
    cpu_seconds: float = 0.0
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    storage_bytes: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def estimate_eur(c: Cost, s: config.Settings | None = None) -> float:
    """Schätzung in EUR aus Preistabelle; Speicher wird als ein Monat Vorhaltung gerechnet."""
    s = s or config.settings()
    eur = 0.0
    eur += c.gpu_seconds / 3600.0 * s.gpu_eur_per_hour
    eur += c.cpu_seconds / 3600.0 * s.cpu_eur_per_hour
    eur += c.llm_input_tokens / 1_000_000 * s.llm_eur_per_1m_input
    eur += c.llm_output_tokens / 1_000_000 * s.llm_eur_per_1m_output
    eur += c.storage_bytes / (1024**3) * s.storage_eur_per_gb_month
    if c.provider == "gladia-eu":
        eur += c.source_minutes / 60.0 * s.gladia_eur_per_hour
    return round(eur, 4)


def record(conn: db.Connection, c: Cost, s: config.Settings | None = None) -> float:
    """Schreibt eine Zeile in ``job_costs`` und gibt die Schätzung zurück."""
    eur = estimate_eur(c, s)
    db.insert(
        conn,
        "job_costs",
        workspace_id=c.workspace_id,
        source_id=c.source_id,
        clip_id=c.clip_id,
        job_type=c.job_type,
        provider=c.provider,
        model_id=c.model_id,
        source_minutes=round(c.source_minutes, 3),
        gpu_seconds=round(c.gpu_seconds, 3),
        cpu_seconds=round(c.cpu_seconds, 3),
        llm_input_tokens=int(c.llm_input_tokens),
        llm_output_tokens=int(c.llm_output_tokens),
        storage_bytes=int(c.storage_bytes),
        estimated_eur=eur,
    )
    return eur


def make_sink(conn: db.Connection, workspace_id: str, source_id: str | None = None, clip_id: str | None = None):
    """Callable für ``providers_llm.LLM(cost_sink=...)``: erwartet ``{"provider","model","in","out","job_type"?}``."""

    def _sink(usage: dict[str, Any]) -> None:
        record(
            conn,
            Cost(
                workspace_id=workspace_id,
                source_id=source_id,
                clip_id=clip_id,
                job_type=usage.get("job_type", "llm_score"),
                provider=usage.get("provider"),
                model_id=usage.get("model"),
                llm_input_tokens=int(usage.get("in", 0)),
                llm_output_tokens=int(usage.get("out", 0)),
            ),
        )

    return _sink


__all__ = ["JOB_TYPES", "Cost", "estimate_eur", "make_sink", "record"]
