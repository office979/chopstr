"""Validator für das Gold-Set ``gold_clip_v1`` (T2, Datenmodell für die Trainingsschleife).

Ein Gold-Set ist eine JSON-Datei ``{"version": "gold_clip_v1", "clips": [...]}`` (oder direkt eine Liste). Je Clip
prüft der Validator das Schema ``gold_clip_v1.schema.json`` (ohne Zusatzpaket: die benötigte Teilmenge von JSON
Schema ist hier nachgebaut) und Fachregeln:

- ``rights`` ist immer ``metadata_only``: keine Medien im Repo, nur Metadaten und URLs.
- Keine lokalen Pfade und keine Mediendateien als URL (``.mp4``, ``.mov``, ``.mp3`` ...).
- ``source.start_s < source.end_s`` und, wenn bekannt, ``end_s <= source.duration_s``.
- ``id`` eindeutig im Set.

Felder dürfen ``null`` sein. Die Vollständigkeit (Anteil gefüllter Blätter, fehlende Kernfelder) ist eine Kennzahl,
kein Fehler; ``ready_for_compare`` sagt, ob der Clip für ``eval.train compare`` taugt (Quelle mit Zeiten).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).with_name("gold_clip_v1.schema.json")
VERSION = "gold_clip_v1"
MEDIA_EXT = re.compile(r"\.(mp4|mov|mkv|webm|m4v|avi|mp3|wav|m4a|aac|flac|ogg|jpg|jpeg|png|gif|webp)(\?|#|$)", re.IGNORECASE)
# Kernfelder für Vergleich und Training: fehlen sie, steht das in ``missing_core``
CORE_FIELDS = (
    "clip.url", "clip.platform", "clip.duration_s", "clip.metrics.views", "source.url", "source.start_s", "source.end_s",
    "source.alignment", "breakdown.hook_type", "breakdown.hook_text_first_3s", "breakdown.cut_in.kind",
    "breakdown.cut_out.kind", "breakdown.payoff", "breakdown.payoff_type", "breakdown.structure",
)  # fmt: skip


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _types_of(value: Any) -> set[str]:
    if value is None:
        return {"null"}
    if isinstance(value, bool):
        return {"boolean"}
    if isinstance(value, int):
        return {"integer", "number"}
    if isinstance(value, float):
        return {"number"}
    if isinstance(value, str):
        return {"string"}
    if isinstance(value, list):
        return {"array"}
    if isinstance(value, dict):
        return {"object"}
    return set()


def check_schema(value: Any, schema: dict, root: dict, path: str = "") -> list[str]:
    """Teilmenge von JSON Schema: $ref, type, enum, const, pattern, minLength, minimum, maximum, required,
    properties, additionalProperties: false, items."""
    if "$ref" in schema:
        ref = schema["$ref"]
        target: Any = root
        for part in ref.lstrip("#/").split("/"):
            target = target[part]
        return check_schema(value, target, root, path)
    errs: list[str] = []
    where = path or "(wurzel)"
    if "type" in schema:
        allowed = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not (_types_of(value) & set(allowed)):
            return [f"{where}: Typ {sorted(_types_of(value))} statt {allowed}"]
    if value is None:
        return errs
    if "const" in schema and value != schema["const"]:
        errs.append(f"{where}: muss {schema['const']!r} sein")
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{where}: {value!r} nicht in {[x for x in schema['enum'] if x is not None]}")
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errs.append(f"{where}: {value[:60]!r} passt nicht zu {schema['pattern']}")
        if len(value) < int(schema.get("minLength", 0)):
            errs.append(f"{where}: zu kurz")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{where}: {value} < {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{where}: {value} > {schema['maximum']}")
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        for req in schema.get("required") or []:
            if req not in value:
                errs.append(f"{where}: Pflichtfeld {req} fehlt")
        if schema.get("additionalProperties") is False:
            for k in value:
                if k not in props:
                    errs.append(f"{where}: unbekanntes Feld {k}")
        for k, sub in props.items():
            if k in value:
                errs.extend(check_schema(value[k], sub, root, f"{path}.{k}" if path else k))
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            errs.extend(check_schema(item, schema["items"], root, f"{where}[{i}]"))
    return errs


def _leaves(value: Any, schema: dict, root: dict, path: str = "") -> list[tuple[str, Any]]:
    """Alle Blattfelder laut Schema mit ihrem Wert (fehlend oder ``null`` heißt leer)."""
    if "$ref" in schema:
        target: Any = root
        for part in schema["$ref"].lstrip("#/").split("/"):
            target = target[part]
        schema = target
    props = schema.get("properties")
    if props:
        out: list[tuple[str, Any]] = []
        for k, sub in props.items():
            v = value.get(k) if isinstance(value, dict) else None
            out.extend(_leaves(v, sub, root, f"{path}.{k}" if path else k))
        return out
    return [(path, value)]


def _get(rec: dict, dotted: str) -> Any:
    cur: Any = rec
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _filled(v: Any) -> bool:
    return v is not None and v != "" and v != []


def domain_errors(rec: dict) -> list[str]:
    errs: list[str] = []
    for key in ("clip.url", "source.url"):
        url = _get(rec, key)
        if isinstance(url, str):
            if url.startswith(("file:", "/", "~", ".")) or "://localhost" in url:
                errs.append(f"{key}: lokaler Pfad statt öffentlicher URL")
            if MEDIA_EXT.search(url.split("?", 1)[0]):
                errs.append(f"{key}: verweist auf eine Mediendatei; nur Seiten-URLs, keine Medien")
    src = rec.get("source") if isinstance(rec.get("source"), dict) else {}
    a, b, d = src.get("start_s"), src.get("end_s"), src.get("duration_s")
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not a < b:
        errs.append("source: start_s muss vor end_s liegen")
    if isinstance(b, (int, float)) and isinstance(d, (int, float)) and b > d + 1.0:
        errs.append("source: end_s liegt hinter duration_s")
    return errs


def validate_record(rec: Any, schema: dict | None = None) -> dict[str, Any]:
    """``{id, errors, completeness, missing_core, ready_for_compare}`` für einen Datensatz."""
    schema = schema or load_schema()
    if not isinstance(rec, dict):
        return {"id": None, "errors": ["Datensatz ist kein Objekt"], "completeness": 0.0, "missing_core": list(CORE_FIELDS), "ready_for_compare": False}
    errors = check_schema(rec, schema, schema) + domain_errors(rec)
    leaves = _leaves(rec, schema, schema)
    filled = sum(1 for _p, v in leaves if _filled(v))
    missing_core = [f for f in CORE_FIELDS if not _filled(_get(rec, f))]
    ready = not errors and all(_filled(_get(rec, f)) for f in ("source.url", "source.start_s", "source.end_s"))
    return {
        "id": rec.get("id"), "errors": errors, "completeness": round(filled / max(1, len(leaves)), 3),
        "missing_core": missing_core, "ready_for_compare": ready,
    }  # fmt: skip


def load_set(path: str | Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        if data.get("version") not in (None, VERSION):
            raise ValueError(f"{path}: Version {data.get('version')!r}, erwartet {VERSION}")
        data = data.get("clips")
    if not isinstance(data, list):
        raise ValueError(f"{path}: erwartet eine Liste von Clips oder {{'clips': [...]}}")
    return data


def validate_set(clips: list[Any]) -> dict[str, Any]:
    """Bericht über ein ganzes Set: je Clip das Ergebnis, dazu Dubletten und Summen."""
    schema = load_schema()
    results = [validate_record(c, schema) for c in clips]
    ids = Counter(r["id"] for r in results if r["id"])
    for r in results:
        if r["id"] and ids[r["id"]] > 1:
            r["errors"].append(f"id {r['id']} ist nicht eindeutig")
            r["ready_for_compare"] = False
    n = len(results)
    return {
        "version": VERSION,
        "clips": n,
        "valid": sum(1 for r in results if not r["errors"]),
        "ready_for_compare": sum(1 for r in results if r["ready_for_compare"]),
        "completeness_mean": round(sum(r["completeness"] for r in results) / n, 3) if n else None,
        "results": results,
    }


def stats(clips: list[dict]) -> dict[str, Any]:
    """Kennzahlen des Sets: je Stufe, Plattform, Hook-Typ, Payoff-Typ, Ausrichtung, Längen und Reichweite."""
    def count(key: str) -> dict[str, int]:
        return dict(Counter(str(_get(c, key)) for c in clips if isinstance(c, dict)).most_common())

    lengths = sorted(float(v) for c in clips if isinstance(c, dict) for v in [_get(c, "breakdown.length_s") or _get(c, "clip.duration_s")] if isinstance(v, (int, float)))
    views = sorted(int(v) for c in clips if isinstance(c, dict) for v in [_get(c, "clip.metrics.views")] if isinstance(v, int))

    def median(xs: list) -> float | None:
        if not xs:
            return None
        m = len(xs) // 2
        return float(xs[m]) if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2.0

    return {
        "clips": len(clips), "tier": count("tier"), "platform": count("clip.platform"), "creator": count("creator"),
        "hook_type": count("breakdown.hook_type"), "payoff_type": count("breakdown.payoff_type"),
        "alignment": count("source.alignment"), "sources": len({_get(c, "source.url") for c in clips if isinstance(c, dict)}),
        "length_s": {"median": median(lengths), "min": lengths[0] if lengths else None, "max": lengths[-1] if lengths else None},
        "views": {"median": median(views), "known": len(views)},
    }  # fmt: skip


__all__ = ["CORE_FIELDS", "VERSION", "check_schema", "load_schema", "load_set", "stats", "validate_record", "validate_set"]
