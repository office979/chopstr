"""Kostensenke: schreibt ``job_costs``-Zeilen und schätzt EUR pro Job.

Preistabelle per ENV überschreibbar (siehe ``config.Settings``):
GPU_EUR_PER_HOUR, CPU_EUR_PER_HOUR, STORAGE_EUR_PER_GB_MONTH, LLM_EUR_PER_1M_INPUT,
LLM_EUR_PER_1M_OUTPUT, GLADIA_EUR_PER_HOUR. Die Defaults sind grobe Platzhalter, keine
Anbieterpreise.

Kostenbuch je Lauf (T2): ``llm_call_eur`` rechnet je Aufruf mit der Preistabelle je Modell
(``CHOPSTR_PRICE_TABLE``, JSON ``{"<modell-präfix>": {"in", "cached_in", "cache_write", "out"}}`` in EUR je
1 Mio. Token, längster passender Präfix gewinnt; ohne Eintrag gelten LLM_EUR_PER_1M_INPUT/OUTPUT). Batch-
Aufrufe kosten ``CHOPSTR_BATCH_DISCOUNT`` (Standard 0,5) des Listenpreises, ``dev_subscription`` (claude-cli)
kostet 0 €. ``RunLedger`` sammelt die Aufrufe eines Laufs, setzt das Budget (``CHOPSTR_RUN_BUDGET_EUR``,
``CHOPSTR_RUN_BUDGET_TOKENS``) durch und rechnet € und Tokens je Quellstunde.
"""

from __future__ import annotations

import json
import threading
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


# Platzhalter in EUR je 1 Mio. Token, angelehnt an die Listenpreise der Anbieter (vor dem Produktivbetrieb
# gegen die aktuelle Preisliste prüfen und per CHOPSTR_PRICE_TABLE setzen). cached_in: Lesen aus dem
# Prompt-Cache (0,1 x Eingabe), cache_write: Schreiben in den Cache (1,25 x Eingabe). Die Aliase der
# Claude-CLI (haiku, sonnet) laufen über ein Abo und kosten hier nichts.
DEFAULT_PRICE_TABLE: dict[str, dict[str, float]] = {
    "claude-haiku": {"in": 1.0, "cached_in": 0.10, "cache_write": 1.25, "out": 5.0},
    "claude-sonnet": {"in": 3.0, "cached_in": 0.30, "cache_write": 3.75, "out": 15.0},
    "claude-opus": {"in": 5.0, "cached_in": 0.50, "cache_write": 6.25, "out": 25.0},
    "gemini-2.5-flash": {"in": 0.30, "cached_in": 0.03, "cache_write": 0.30, "out": 2.50},
    "gemini-flash": {"in": 0.30, "cached_in": 0.03, "cache_write": 0.30, "out": 2.50},
}
BILLING_API = "api"
BILLING_BATCH = "batch"
BILLING_DEV = "dev_subscription"  # claude-cli über ein Abo: 0 €, nie Produktion
BILLING_LOCAL = "local"  # Heuristik, Mock, lokaler Fallback: kein Anbieter


def price_table(s: config.Settings | None = None) -> dict[str, dict[str, float]]:
    """Preistabelle: Standard plus Einträge aus ``CHOPSTR_PRICE_TABLE`` (überschreiben je Präfix)."""
    s = s or config.settings()
    table = {k: dict(v) for k, v in DEFAULT_PRICE_TABLE.items()}
    if s.price_table_json:
        try:
            extra = json.loads(s.price_table_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"CHOPSTR_PRICE_TABLE ist kein gültiges JSON: {exc}") from None
        for key, entry in (extra or {}).items():
            if isinstance(entry, dict):
                table[str(key)] = {**table.get(str(key), {}), **{k: float(v) for k, v in entry.items()}}
    return table


def price_for(model: str, s: config.Settings | None = None) -> dict[str, float]:
    """Preise eines Modells: längster passender Präfix der Tabelle, sonst die alten Pauschalpreise."""
    s = s or config.settings()
    table = price_table(s)
    hits = [k for k in table if str(model or "").startswith(k)]
    entry = table[max(hits, key=len)] if hits else {}
    base_in = float(entry.get("in", s.llm_eur_per_1m_input))
    return {
        "in": base_in,
        "cached_in": float(entry.get("cached_in", base_in * 0.1)),
        "cache_write": float(entry.get("cache_write", base_in * 1.25)),
        "out": float(entry.get("out", s.llm_eur_per_1m_output)),
    }


def llm_call_eur(usage: dict[str, Any], s: config.Settings | None = None) -> float:
    """Geschätzte EUR eines Aufrufs aus ``{"model", "in", "cached_in", "cache_write", "out", "billing"}``.

    ``in`` zählt nur die nicht gecachten Eingabetokens (wie ``input_tokens`` der Messages API)."""
    s = s or config.settings()
    billing = str(usage.get("billing") or BILLING_API)
    if billing in (BILLING_DEV, BILLING_LOCAL):
        return 0.0
    p = price_for(str(usage.get("model") or ""), s)
    eur = (
        int(usage.get("in", 0) or 0) * p["in"]
        + int(usage.get("cached_in", 0) or 0) * p["cached_in"]
        + int(usage.get("cache_write", 0) or 0) * p["cache_write"]
        + int(usage.get("out", 0) or 0) * p["out"]
    ) / 1_000_000
    if billing == BILLING_BATCH:
        eur *= s.batch_discount
    return round(eur, 6)


# Aliase der Claude-CLI auf die Präfixe der Preistabelle, für das API-Äquivalent eines Abo-Laufs.
CLI_ALIAS_PRICE_PREFIX = {"haiku": "claude-haiku", "sonnet": "claude-sonnet", "opus": "claude-opus"}
CLI_TOKEN_NOTE = (
    "claude-cli: die Tokens enthalten den eigenen Systemprompt und die Werkzeugdefinitionen der CLI (meist zehntausende "
    "Tokens je Aufruf, überwiegend Cache-Schreiben und -Lesen). eur_api_equivalent rechnet diese Tokens mit der "
    "Preistabelle und liegt deshalb deutlich über dem, was derselbe Lauf über die Anthropic-API kosten würde."
)


def llm_call_eur_api_equivalent(usage: dict[str, Any], s: config.Settings | None = None) -> float:
    """Was ein Aufruf zum Listenpreis der API kosten würde: bei ``api``/``batch`` gleich ``llm_call_eur``, bei
    ``dev_subscription`` (claude-cli) mit dem Preis des Modells hinter dem Alias, lokal 0 €."""
    s = s or config.settings()
    billing = str(usage.get("billing") or BILLING_API)
    if billing == BILLING_LOCAL:
        return 0.0
    if billing != BILLING_DEV:
        return llm_call_eur(usage, s)
    model = str(usage.get("model") or "")
    return llm_call_eur({**usage, "model": CLI_ALIAS_PRICE_PREFIX.get(model, model), "billing": BILLING_API}, s)


TOKEN_FIELDS = ("in", "cached_in", "cache_write", "out")


def usage_tokens(usage: dict[str, Any]) -> int:
    """Alle Tokens eines Aufrufs (Eingabe, gecachte Eingabe, Cache-Schreiben, Ausgabe)."""
    return sum(int(usage.get(k, 0) or 0) for k in TOKEN_FIELDS)


class BudgetExceeded(RuntimeError):
    """Das Budget des Laufs ist erreicht; die Stufe wird übersprungen oder der Lauf endet sauber."""

    def __init__(self, stage: str, detail: str):
        super().__init__(f"Budget erreicht vor Stufe {stage}: {detail}")
        self.stage, self.detail = stage, detail


class RunLedger:
    """Kostenbuch eines Laufs: je Aufruf Tokens, Modell, Stufe und geschätzte EUR, dazu das Budget.

    Als ``cost_sink`` für ``providers_llm.LLM`` und ``providers_mm`` nutzbar (die Instanz ist aufrufbar).
    ``check(stage)`` vor einem Aufruf wirft ``BudgetExceeded``, sobald EUR oder Tokens das Budget erreicht
    haben; 0 heißt ohne Grenze. Übersprungene Stufen stehen in ``skipped`` und damit im Bericht. Ein Treffer
    im Ergebnis-Cache (``cached_result``) wird gezählt, kostet aber nichts."""

    def __init__(self, budget_eur: float | None = None, budget_tokens: int | None = None, s: config.Settings | None = None):
        self.s = s or config.settings()
        self.budget_eur = float(self.s.run_budget_eur if budget_eur is None else budget_eur)
        self.budget_tokens = int(self.s.run_budget_tokens if budget_tokens is None else budget_tokens)
        self.entries: list[dict[str, Any]] = []
        self.skipped: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    @property
    def eur(self) -> float:
        return round(sum(float(e["eur"]) for e in self.entries), 6)

    @property
    def tokens(self) -> int:
        return sum(usage_tokens(e) for e in self.entries)

    def exhausted(self) -> str | None:
        """Grund, wenn das Budget erreicht ist, sonst ``None``."""
        if self.budget_eur > 0 and self.eur >= self.budget_eur:
            return f"{self.eur:.4f} EUR von {self.budget_eur:.4f} EUR verbraucht"
        if self.budget_tokens > 0 and self.tokens >= self.budget_tokens:
            return f"{self.tokens} von {self.budget_tokens} Tokens verbraucht"
        return None

    def check(self, stage: str) -> None:
        reason = self.exhausted()
        if reason:
            with self._lock:
                self.skipped.append({"stage": stage, "reason": "budget_exhausted", "detail": reason})
            raise BudgetExceeded(stage, reason)

    def __call__(self, usage: dict[str, Any]) -> None:
        cached = bool(usage.get("cached_result"))
        entry = {
            "stage": str(usage.get("stage") or usage.get("job_type") or ""),
            "provider": usage.get("provider"),
            "model": usage.get("model"),
            "prompt": usage.get("prompt"),
            "billing": str(usage.get("billing") or BILLING_API),
            "cached_result": cached,
            **{k: 0 if cached else int(usage.get(k, 0) or 0) for k in TOKEN_FIELDS},
        }
        entry["eur"] = 0.0 if cached else llm_call_eur(entry, self.s)
        entry["eur_api_equivalent"] = 0.0 if cached else llm_call_eur_api_equivalent(entry, self.s)
        if usage.get("schema_retry"):
            entry["schema_retry"] = True
        with self._lock:
            self.entries.append(entry)

    def summary(self, source_seconds: float | None = None) -> dict[str, Any]:
        """Kennzahlen: Summen, je Stufe und je Modell, € und Tokens je Quellstunde (``None`` ohne Dauer)."""
        by_stage: dict[str, dict[str, Any]] = {}
        by_model: dict[str, dict[str, Any]] = {}
        for e in self.entries:
            for table, key in ((by_stage, e["stage"]), (by_model, str(e["model"] or ""))):
                row = table.setdefault(key, {"calls": 0, **{k: 0 for k in TOKEN_FIELDS}, "eur": 0.0, "eur_api_equivalent": 0.0})
                row["calls"] += 1
                for k in TOKEN_FIELDS:
                    row[k] += e[k]
                row["eur"] = round(row["eur"] + float(e["eur"]), 6)
                row["eur_api_equivalent"] = round(row["eur_api_equivalent"] + float(e.get("eur_api_equivalent", 0.0)), 6)
        hours = (float(source_seconds) / 3600.0) if source_seconds else None
        api_eq = round(sum(float(e.get("eur_api_equivalent", 0.0)) for e in self.entries), 6)
        billing = sorted({e["billing"] for e in self.entries})
        return {
            "calls": len(self.entries),
            "cached_results": sum(1 for e in self.entries if e["cached_result"]),
            "tokens": self.tokens,
            **{f"tokens_{k}": sum(e[k] for e in self.entries) for k in TOKEN_FIELDS},
            "eur": self.eur,
            "budget_eur": self.budget_eur or None,
            "budget_tokens": self.budget_tokens or None,
            "skipped": list(self.skipped),
            "by_stage": by_stage,
            "by_model": by_model,
            "source_hours": round(hours, 4) if hours else None,
            "eur_per_source_hour": round(self.eur / hours, 4) if hours else None,
            "tokens_per_source_hour": round(self.tokens / hours, 1) if hours else None,
            "eur_api_equivalent": api_eq,
            "eur_api_equivalent_per_source_hour": round(api_eq / hours, 4) if hours else None,
            "schema_retries": sum(1 for e in self.entries if e.get("schema_retry")),
            "billing": billing,
            "notes": [CLI_TOKEN_NOTE] if BILLING_DEV in billing else [],
        }


__all__ = [
    "BILLING_API",
    "BILLING_BATCH",
    "BILLING_DEV",
    "BILLING_LOCAL",
    "DEFAULT_PRICE_TABLE",
    "JOB_TYPES",
    "TOKEN_FIELDS",
    "BudgetExceeded",
    "Cost",
    "RunLedger",
    "estimate_eur",
    "llm_call_eur",
    "llm_call_eur_api_equivalent",
    "make_sink",
    "price_for",
    "price_table",
    "record",
    "usage_tokens",
]
