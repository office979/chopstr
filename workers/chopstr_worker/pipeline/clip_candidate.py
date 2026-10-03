"""ClipCandidate (Vertrag ``clip_candidate_v1``): das interne Ergebnisformat aus Master-Prompt Abschnitt 21.

Ein Adapter über ``story_engine.CandidateResult``: er liest, was der Lauf schon weiß, und schreibt
nichts zurück. Das Kandidaten-JSON der Web-App (``candidates_v1``) bleibt unverändert; in die Rubrik
geht später nur die kompakte Teilmenge aus ``compact_for_rubric`` (additive Schlüssel).

Regeln (Vertrag ``packages/schema/CLIP_CANDIDATE.md``):

* Fehlende Datenbasis ist ``None``. Kein Zeitstempel außerhalb von Wortgrenzen (``source_in`` ist
  immer der Anfang eines Wortes, ``source_out`` das Ende eines Wortes), kein Sprecher ohne
  Sprecherangabe in den Wörtern, keine Sicherheit ohne Grundlage (``boundary_confidence`` bleibt
  ``None`` bis AP10b, ``externally_verified`` ist immer ``None``).
* ``audience_context`` kommt nur aus dem Brief und trägt dann ``audience_context_provenance =
  "explicit"``.
* ``assessment_uncertainties`` nennt, was am Audio oder von einem Menschen zu prüfen ist: Zahlen und
  Namen mit ``prob`` unter ``transcribe.LOW_CONF_THRESHOLD`` (Testfall 6), Heuristik ohne
  Sprachmodell, fehlendes spaCy, Grenzen nur aus einer Pause, fehlende ``boundary_confidence`` und
  unbestätigte Relativierungen aus dem Story-Graph.
* Die Ausgabe-Timeline (``output_in``, ``output_out``) ist deterministisch aus den Segmenten in
  Abspielreihenfolge berechnet (``output_timeline``): mit ``compose.output_timeline`` (AP7), solange
  es die nicht gibt mit derselben Rechnung hier. Der lokale Zweig entfällt, sobald AP7 eingecheckt ist.

Die Schema-Prüfung braucht keine externe Bibliothek: ``SCHEMA`` ist das JSON-Schema (Draft 2020-12)
als Python-Wert, ``packages/schema/clip_candidate_v1.json`` ist seine Kopie (ein Test hält beide
gleich), und ``validate`` prüft die Teilmenge der Schlüsselwörter, die das Schema benutzt.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field, fields
from typing import Any

from .. import editorial
from . import compose, dach_nlp, fidelity, segment, story_engine
from .segment import Sentence
from .transcribe import LOW_CONF_THRESHOLD

CONTRACT = "clip_candidate_v1"
DECISIONS = ("accept", "reject")
CALIBRATIONS = ("uncalibrated", "calibrated")
UNCERTAINTY_KINDS = (
    "low_confidence_number",
    "low_confidence_name",
    "heuristic_only",
    "nlp_unavailable",
    "boundary_from_pause",
    "boundary_from_length_cap",
    "boundary_confidence_missing",
    "story_graph_unconfirmed",
)
# Toleranz beim Zuordnen von Wörtern zu Segmenten: die Segmentgrenzen sind auf Millisekunden gerundet.
WORD_EPS_S = 0.001
# Arten mit Wortbezug: nur sie tragen word_id, text und prob.
WORD_KINDS = frozenset({"low_confidence_number", "low_confidence_name"})
# Großgeschrieben, aber kein Name: Anrede, Pronomen, Artikel, Funktionswörter (kleingeschrieben verglichen).
NOT_NAMES = frozenset({
    "sie", "ihr", "ihre", "ihren", "ihrem", "ihrer", "ihres", "ihnen", "du", "dich", "dir", "dein", "deine",
    "ich", "mich", "mir", "mein", "meine", "wir", "uns", "unser", "unsere", "er", "es", "man", "euch", "euer",
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem", "einer", "eines",
    "und", "oder", "aber", "doch", "denn", "dass", "weil", "wenn", "als", "wie", "so", "also", "ja", "nein",
    "nicht", "auch", "noch", "nur", "schon", "dann", "da", "hier", "dort", "jetzt", "heute", "mit", "von",
    "bei", "zu", "in", "im", "an", "am", "auf", "für", "über", "unter", "nach", "vor", "aus", "um", "ohne",
    "okay", "ok", "genau", "gut", "na", "äh", "ähm", "hm",
})  # fmt: skip
# Anreden und Titel: das Wort danach ist ein Name, auch am Satzanfang („Frau Meier hat …“).
TITLES = frozenset({"frau", "herr", "herrn", "dr", "prof", "doktor", "professor", "professorin", "mag", "ing"})
# Bruchzahlwörter zählen als Zahl (falsch erkannt ändern sie den Wert).
FRACTION_WORDS = frozenset({
    "halb", "halbe", "halben", "halber", "hälfte", "drittel", "viertel", "fünftel", "zehntel", "hundertstel",
    "tausendstel", "anderthalb", "eineinhalb", "zweieinhalb", "dreiviertel",
})  # fmt: skip
SENTENCE_FINAL = (".", "!", "?", ":")

# -- JSON-Schema -----------------------------------------------------------------------------------

_NUM_OR_NULL = {"type": ["number", "null"]}
_STR_OR_NULL = {"type": ["string", "null"]}
_INT_PAIR_OR_NULL = {"type": ["array", "null"], "items": {"type": "integer"}, "minItems": 2, "maxItems": 2}

SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "clip_candidate_v1.json",
    "title": "ClipCandidate (clip_candidate_v1)",
    "description": "Internes Ergebnisformat nach Master-Prompt Abschnitt 21. Vertrag: packages/schema/CLIP_CANDIDATE.md.",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "contract", "candidate_id", "source_asset_id", "source_version", "objective", "audience_context",
        "audience_context_provenance", "central_idea", "viewer_promise", "payoff_description",
        "narrative_type", "opening_source_span", "required_context_spans", "payoff_source_span",
        "segments", "removed_spans", "meaning_dependencies", "unresolved_questions",
        "quality_gate_results", "editorial_subscores", "assessment_uncertainties", "decision",
        "decision_reason", "alternatives_considered", "model_version", "prompt_version", "policy_version",
        "externally_verified", "calibration",
    ],
    "properties": {
        "contract": {"const": CONTRACT},
        "candidate_id": {"type": "string", "minLength": 1},
        "source_asset_id": _STR_OR_NULL,
        "source_version": {"type": ["integer", "string", "null"]},
        "objective": _STR_OR_NULL,
        "audience_context": _STR_OR_NULL,
        "audience_context_provenance": {"enum": ["explicit", None]},
        "central_idea": _STR_OR_NULL,
        "viewer_promise": _STR_OR_NULL,
        "payoff_description": _STR_OR_NULL,
        "narrative_type": _STR_OR_NULL,
        "opening_source_span": {"anyOf": [{"$ref": "#/$defs/span"}, {"type": "null"}]},
        "required_context_spans": {"type": "array", "items": {"$ref": "#/$defs/span"}},
        "payoff_source_span": {"anyOf": [{"$ref": "#/$defs/span"}, {"type": "null"}]},
        "segments": {"type": "array", "items": {"$ref": "#/$defs/segment"}},
        "removed_spans": {"type": "array", "items": {"$ref": "#/$defs/removed_span"}},
        "meaning_dependencies": {"type": "array", "items": {"$ref": "#/$defs/meaning_dependency"}},
        "unresolved_questions": {"type": "array", "items": {"$ref": "#/$defs/question"}},
        "quality_gate_results": {"type": "object", "additionalProperties": {"$ref": "#/$defs/gate"}},
        "editorial_subscores": {
            "type": "object",
            "additionalProperties": False,
            "required": ["scale_max", "values"],
            "properties": {
                "scale_max": {"type": ["integer", "null"]},
                "values": {"type": "object", "additionalProperties": _NUM_OR_NULL},
            },
        },
        "assessment_uncertainties": {"type": "array", "items": {"$ref": "#/$defs/uncertainty"}},
        "decision": {"enum": list(DECISIONS)},
        "decision_reason": {"type": "string", "minLength": 1},
        "alternatives_considered": {"type": ["array", "null"], "items": {"$ref": "#/$defs/alternative"}},
        "model_version": _STR_OR_NULL,
        "prompt_version": {"type": "object", "additionalProperties": {"type": "string"}},
        "policy_version": {"type": "string", "minLength": 1},
        "externally_verified": {"type": "null"},
        "calibration": {"enum": list(CALIBRATIONS)},
    },
    "$defs": {
        "span": {
            "type": "object",
            "additionalProperties": False,
            "required": ["source_in", "source_out", "word_range", "sentence_range", "note"],
            "properties": {
                "source_in": _NUM_OR_NULL,
                "source_out": _NUM_OR_NULL,
                "word_range": _INT_PAIR_OR_NULL,
                "sentence_range": _INT_PAIR_OR_NULL,
                "note": _STR_OR_NULL,
            },
        },
        "segment": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "segment_id", "source_in", "source_out", "output_in", "output_out", "speaker_id",
                "word_ids", "verbatim_text", "editorial_role", "boundary_confidence",
            ],
            "properties": {
                "segment_id": {"type": "string", "minLength": 1},
                "source_in": _NUM_OR_NULL,
                "source_out": _NUM_OR_NULL,
                "output_in": _NUM_OR_NULL,
                "output_out": _NUM_OR_NULL,
                "speaker_id": _STR_OR_NULL,
                "word_ids": {"type": "array", "items": {"type": "integer", "minimum": 0}},
                "verbatim_text": {"type": "string"},
                "editorial_role": {"enum": ["teaser", "body"]},
                "boundary_confidence": {"type": ["number", "string", "null"]},
            },
        },
        "removed_span": {
            "type": "object",
            "additionalProperties": False,
            "required": ["source_in", "source_out", "removal_reason", "protected_context_check"],
            "properties": {
                "source_in": {"type": "number"},
                "source_out": {"type": "number"},
                "removal_reason": {"type": "string", "minLength": 1},
                "protected_context_check": {"type": ["object", "null"]},
            },
        },
        "meaning_dependency": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "sentence_idx", "source_in", "source_out", "text", "marker", "confirmed", "detail"],
            "properties": {
                "kind": {"enum": ["later_qualification"]},
                "sentence_idx": {"type": ["integer", "null"]},
                "source_in": _NUM_OR_NULL,
                "source_out": _NUM_OR_NULL,
                "text": {"type": "string"},
                "marker": _STR_OR_NULL,
                "confirmed": {"type": ["boolean", "null"]},
                "detail": _STR_OR_NULL,
            },
        },
        "question": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "text"],
            "properties": {
                "kind": {"enum": ["unresolved_reference", "needs_earlier_context", "ends_before_answer"]},
                "text": {"type": "string", "minLength": 1},
            },
        },
        "gate": {
            "type": "object",
            "required": ["passed", "detail"],
            "properties": {"passed": {"type": "boolean"}, "detail": {"type": "string"}},
        },
        "uncertainty": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "detail", "word_id", "text", "prob"],
            "properties": {
                "kind": {"enum": list(UNCERTAINTY_KINDS)},
                "detail": {"type": "string", "minLength": 1},
                "word_id": {"type": ["integer", "null"]},
                "text": _STR_OR_NULL,
                "prob": _NUM_OR_NULL,
            },
        },
        "alternative": {
            "type": "object",
            "additionalProperties": False,
            "required": ["candidate_id", "first_sent", "last_sent", "total", "reason"],
            "properties": {
                "candidate_id": _STR_OR_NULL,
                "first_sent": {"type": "integer"},
                "last_sent": {"type": "integer"},
                "total": _NUM_OR_NULL,
                "reason": {"type": "string", "minLength": 1},
            },
        },
    },
}  # fmt: skip


class SchemaError(ValueError):
    """Ein ClipCandidate entspricht nicht dem Vertrag ``clip_candidate_v1``."""


_TYPES: dict[str, Any] = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def _resolve(ref: str, root: dict[str, Any]) -> dict[str, Any]:
    node: Any = root
    for part in ref.removeprefix("#/").split("/"):
        node = node[part]
    return node


def _check(value: Any, schema: dict[str, Any], path: str, root: dict[str, Any], errors: list[str]) -> None:
    if "$ref" in schema:
        _check(value, _resolve(schema["$ref"], root), path, root, errors)
        return
    if "anyOf" in schema:
        branches = [_errors(value, sub, path, root) for sub in schema["anyOf"]]
        if all(branches):
            # Der Zweig, dessen Typ passt, mit den wenigsten Fehlern sagt, was wirklich fehlt.
            best = min(branches, key=lambda errs: (any(e.startswith(f"{path}: Typ") for e in errs), len(errs)))
            errors.append(f"{path}: passt zu keiner erlaubten Form")
            errors.extend(best)
        return
    if isinstance(value, float) and not math.isfinite(value):
        errors.append(f"{path}: {value} ist keine endliche Zahl")
        return
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: erwartet {schema['const']!r}, steht {value!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} ist nicht erlaubt ({schema['enum']})")
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_TYPES[t](value) for t in types):
            errors.append(f"{path}: Typ {type(value).__name__}, erwartet {' oder '.join(types)}")
            return
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        errors.append(f"{path}: leer")
    if _TYPES["number"](value) and "minimum" in schema and value < schema["minimum"]:
        errors.append(f"{path}: {value} unter {schema['minimum']}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", len(value)):
            errors.append(f"{path}: {len(value)} Einträge")
        if "items" in schema:
            for i, item in enumerate(value):
                _check(item, schema["items"], f"{path}[{i}]", root, errors)
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}: Pflichtfeld fehlt")
        extra = schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in props:
                _check(item, props[key], f"{path}.{key}", root, errors)
            elif extra is False:
                errors.append(f"{path}.{key}: Feld ist im Vertrag nicht vorgesehen")
            elif isinstance(extra, dict):
                _check(item, extra, f"{path}.{key}", root, errors)


def _errors(value: Any, schema: dict[str, Any], path: str, root: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _check(value, schema, path, root, errors)
    return errors


def validate(data: Any, schema: dict[str, Any] | None = None) -> list[str]:
    """Prüft ``data`` gegen das Schema (Standard ``SCHEMA``). Leere Liste heißt gültig."""
    own = schema is None or schema is SCHEMA
    schema = SCHEMA if schema is None else schema
    errors = _errors(data, schema, "$", schema)
    # Die Regeln über Felder hinweg gelten nur für den Vertrag selbst, nicht für ein fremdes Schema.
    if own and not errors and isinstance(data, dict):
        errors += _semantic_errors(data)
    return errors


def _semantic_errors(data: dict[str, Any]) -> list[str]:
    """Was JSON-Schema nicht ausdrücken kann: Felder, die nur gemeinsam gelten, Reihenfolge der Zeiten,
    Pflicht-Segmente und Wortbezug der Unsicherheiten."""
    out: list[str] = []
    if data["decision"] == "accept" and not data["segments"]:
        out.append("$.segments: angenommener Kandidat ohne Segmente")
    if (data["audience_context"] is None) != (data["audience_context_provenance"] is None):
        out.append("$.audience_context: audience_context und audience_context_provenance nur gemeinsam gesetzt oder beide null")
    for i, seg in enumerate(data["segments"]):
        for a, b in (("source_in", "source_out"), ("output_in", "output_out")):
            if seg[a] is not None and seg[b] is not None and seg[b] < seg[a]:
                out.append(f"$.segments[{i}]: {b} liegt vor {a}")
        for src, dst in (("source_in", "output_in"), ("source_out", "output_out")):
            if seg[src] is None and seg[dst] is not None:
                out.append(f"$.segments[{i}]: {dst} ohne {src}")
        if seg["speaker_id"] is not None and not seg["word_ids"]:
            out.append(f"$.segments[{i}]: speaker_id ohne Wörter")
    for i, r in enumerate(data["removed_spans"]):
        if r["source_out"] <= r["source_in"]:
            out.append(f"$.removed_spans[{i}]: source_out liegt nicht nach source_in")
    for i, u in enumerate(data["assessment_uncertainties"]):
        word_fields = [k for k in ("word_id", "text", "prob") if u[k] is not None]
        if u["kind"] in WORD_KINDS and u["word_id"] is None:
            out.append(f"$.assessment_uncertainties[{i}]: {u['kind']} ohne word_id")
        if u["kind"] not in WORD_KINDS and word_fields:
            out.append(f"$.assessment_uncertainties[{i}]: {', '.join(word_fields)} nur bei Wortbefunden")
    return out


# -- Dataclasses -----------------------------------------------------------------------------------


@dataclass
class ClipSegment:
    segment_id: str
    source_in: float | None
    source_out: float | None
    output_in: float | None
    output_out: float | None
    speaker_id: str | None
    word_ids: list[int]
    verbatim_text: str
    editorial_role: str
    boundary_confidence: float | str | None = None


@dataclass
class RemovedSpan:
    source_in: float
    source_out: float
    removal_reason: str
    protected_context_check: dict[str, Any] | None = None


# Felder einer entfernten Stelle im Vertrag; trim_plan liefert zusätzlich kind, word_ids und text.
_REMOVED_FIELDS = tuple(f.name for f in fields(RemovedSpan))


@dataclass
class ClipCandidate:
    """Ein Kandidat nach Master-Prompt Abschnitt 21. Alle Werte sind JSON-Typen (keine Tupel)."""

    candidate_id: str
    source_asset_id: str | None
    source_version: int | str | None
    objective: str | None
    audience_context: str | None
    audience_context_provenance: str | None
    central_idea: str | None
    viewer_promise: str | None
    payoff_description: str | None
    narrative_type: str | None
    opening_source_span: dict[str, Any] | None
    required_context_spans: list[dict[str, Any]]
    payoff_source_span: dict[str, Any] | None
    segments: list[ClipSegment]
    removed_spans: list[RemovedSpan]
    meaning_dependencies: list[dict[str, Any]]
    unresolved_questions: list[dict[str, Any]]
    quality_gate_results: dict[str, Any]
    editorial_subscores: dict[str, Any]
    assessment_uncertainties: list[dict[str, Any]]
    decision: str
    decision_reason: str
    alternatives_considered: list[dict[str, Any]] | None
    model_version: str | None
    prompt_version: dict[str, str]
    policy_version: str
    externally_verified: None = None
    calibration: str = "uncalibrated"
    contract: str = field(default=CONTRACT)

    def to_dict(self) -> dict[str, Any]:
        """JSON-Form; wirft ``SchemaError``, wenn sie den Vertrag verletzt."""
        data = asdict(self)
        errors = validate(data)
        if errors:
            raise SchemaError("; ".join(errors))
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClipCandidate:
        """Liest die JSON-Form nach der Schema-Prüfung; wirft ``SchemaError`` bei Verstößen."""
        errors = validate(data)
        if errors:
            raise SchemaError("; ".join(errors))
        values = {f.name: data[f.name] for f in fields(cls)}
        values["segments"] = [ClipSegment(**s) for s in data["segments"]]
        values["removed_spans"] = [RemovedSpan(**r) for r in data["removed_spans"]]
        return cls(**values)


# -- Hilfen ----------------------------------------------------------------------------------------


def sentences_for(words: list[dict], policy: editorial.Policy | None = None) -> list[Sentence]:
    """Dieselbe Satzzerlegung wie ``story_engine.run`` unter der Richtlinie (ohne Angabe die aktive)."""
    pol = policy if policy is not None else story_engine._active_policy()
    rule = editorial.sentence_rule(pol) if pol is not None else "v1"
    if rule == "v1":
        return segment.sentences_from_words(words)
    return segment.sentences_from_annotated(words) or segment.sentences_from_words(words, **story_engine._cut_args(words, pol))


def versions_for(policy: editorial.Policy, report: story_engine.DetectReport | None = None) -> dict[str, Any]:
    """Versionen eines Laufs: Engine, Richtlinie, alle gepinnten Prompts, Modell und NLP-Status."""
    return {
        "engine": (report.engine if report is not None and report.engine else story_engine.engine_version(policy)),
        "policy_version": editorial.policy_version(policy.version),
        "prompts": {name: f"{name}_v{v}" for name, v in sorted(policy.prompt_pins.items())},
        "model_id": report.model_id if report is not None else None,
        "nlp_status": report.nlp_status if report is not None else "",
    }


def output_timeline(segments: list[dict]) -> list[tuple[float, float]]:
    """Ausgabezeit je Segment in Abspielreihenfolge: lückenlos ab 0, Länge wie in der Quelle
    (``compose.output_timeline``, dieselbe Rechnung wie ``compose.remap_words``)."""
    return [(float(e["output_in"]), float(e["output_out"])) for e in compose.output_timeline(compose.Composition.from_json(segments))]


def _prob(w: dict) -> float | None:
    """ASR-Sicherheit eines Wortes: ``prob`` (Transkript), sonst ``asr_confidence`` (Fixtures)."""
    raw = w.get("prob")
    if raw is None:
        raw = w.get("asr_confidence")
    return float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None


def _word_ids_in(words: list[dict], start: float, end: float) -> list[int]:
    return [
        i for i, w in enumerate(words)
        if float(w["start"]) >= start - WORD_EPS_S and float(w["end"]) <= end + WORD_EPS_S
    ]  # fmt: skip


def _span(words: list[dict], sents: list[Sentence], first: int, last: int, note: str | None) -> dict[str, Any]:
    a, b = sents[first].word_range[0], sents[last].word_range[1]
    return {
        "source_in": float(words[a]["start"]),
        "source_out": float(words[b]["end"]),
        "word_range": [a, b],
        "sentence_range": [first, last],
        "note": note,
    }


def _norm(text: str) -> str:
    return re.sub(r"[^\wäöüß ]", "", str(text or "").lower()).strip()


def _payoff_sentence(sents: list[Sentence], first: int, last: int, evidence: str) -> int | None:
    needle = _norm(evidence)
    if not needle:
        return None
    return next((i for i in range(first, last + 1) if needle in _norm(sents[i].text)), None)


def _core(text: str) -> str:
    return str(text).strip(".,;:!?\"'„“»«()")


def _is_number(text: str) -> bool:
    core = _core(text)
    low = core.lower()
    return bool(fidelity.number_mentions(core)) or fidelity.parse_number_word(low) is not None or low in FRACTION_WORDS


def _sentence_initial(words: list[dict], i: int) -> bool:
    """Erstes Wort eines Satzes: Anfang der Liste, nach Satzzeichen oder nach Sprecherwechsel."""
    if i == 0:
        return True
    before = str(words[i - 1].get("text") or "").rstrip("\"'»«“”‘’)")
    return before.endswith(SENTENCE_FINAL) or words[i - 1].get("speaker") != words[i].get("speaker")


def _is_name(words: list[dict], i: int, names: frozenset[str]) -> bool:
    """Möglicher Name: großgeschrieben, kein Funktionswort oder Pronomen. Am Satzanfang nur nach einem
    Titel oder wenn das Wort in der bekannten Namensliste steht (Großschreibung sagt dort nichts)."""
    core = _core(words[i].get("text") or "")
    low = core.lower()
    if not core[:1].isupper() or low in NOT_NAMES or low.rstrip(".") in TITLES:
        return False
    if low in names:
        return True
    after_title = i > 0 and _core(words[i - 1].get("text") or "").lower().rstrip(".") in TITLES
    return after_title or not _sentence_initial(words, i)


def _de(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def low_confidence_uncertainties(words: list[dict], word_ids: list[int], names: tuple[str, ...] | list[str] = ()) -> list[dict[str, Any]]:
    """Zahlen (auch Bruchzahlwörter) und mögliche Namen im Clip mit ``prob`` unter ``LOW_CONF_THRESHOLD``.

    Name heißt: großgeschrieben, kein Funktionswort oder Pronomen, nicht am Satzanfang, außer nach einem
    Titel („Frau“, „Dr.“) oder wenn das Wort in ``names`` steht (etwa ``brand_vocab``)."""
    known = frozenset(_core(n).lower() for n in names)
    out = []
    for i in sorted(set(word_ids)):
        prob = _prob(words[i])
        if prob is None or prob >= LOW_CONF_THRESHOLD:
            continue
        text = str(words[i].get("text") or "")
        if _is_number(text):
            kind, what = "low_confidence_number", "Zahl"
        elif _is_name(words, i, known):
            kind, what = "low_confidence_name", "Name oder Begriff"
        else:
            continue
        out.append({
            "kind": kind,
            "detail": f"{what} „{text}“ unsicher erkannt (Sicherheit {_de(prob)} unter {_de(LOW_CONF_THRESHOLD)}), am Audio prüfen",
            "word_id": i, "text": text, "prob": prob,
        })  # fmt: skip
    return out


def _note(kind: str, detail: str) -> dict[str, Any]:
    return {"kind": kind, "detail": detail, "word_id": None, "text": None, "prob": None}


def _candidate_id(source_asset_id: Any, source_version: Any, result: story_engine.CandidateResult, versions: dict[str, Any] | None = None) -> str:
    """Deterministisch aus Quelle, Transkriptversion, Richtlinie, Engine, Satzspanne und Segmenten: derselbe
    Schnitt unter einer anderen Fassung ist ein anderer Kandidat."""
    versions = versions or {}
    key = json.dumps(
        [source_asset_id, source_version, versions.get("policy_version"), versions.get("engine") or story_engine.ENGINE_VERSION,
         result.first_sent, result.last_sent, result.segments],
        sort_keys=True,
    )  # fmt: skip
    return "cc_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _nlp_note(vb: dict[str, Any], nlp_status: str) -> str | None:
    """Unterscheidet „laut Richtlinie aus“ von „spaCy fehlt“ (heuristisch oder gar nicht geprüft)."""
    detail = str(vb.get("detail") or "")
    method = vb.get("method") or nlp_status
    if "laut Richtlinie" in detail:
        return f"Verbklammer laut Richtlinie abgeschaltet, nicht geprüft: {detail}"
    if method == "heuristic":
        return f"spaCy-Modell fehlt, Verbklammer nur heuristisch geprüft: {detail or nlp_status}"
    if vb.get("available") is False or method == "off":
        return f"spaCy-Modell fehlt, Verbklammer nicht geprüft: {detail or nlp_status}"
    return None


def _boundary_notes(words: list[dict], segs: list[ClipSegment], policy: editorial.Policy) -> list[tuple[str, str]]:
    """Schnittkanten ohne Satzzeichen oder Sprecherwechsel, aus derselben Grenzart wie die Zerlegung
    (``dach_nlp.cut_boundary_kind``): nur aus einer Pause (``pause_candidate``) oder aus der
    Satzlängengrenze (``length_cap``)."""
    cut_args = getattr(story_engine, "_cut_args", None)
    args = cut_args(words, policy) if cut_args is not None else {"rule": editorial.sentence_rule(policy)}
    found: dict[str, list[str]] = {"pause_candidate": [], "length_cap": []}
    for seg in segs:
        if not seg.word_ids:
            continue
        a, b = seg.word_ids[0], seg.word_ids[-1]
        edges = [("Anfang", a - 1)] if a > 0 else []
        edges.append(("Ende", b))
        for label, i in edges:
            kind = dach_nlp.cut_boundary_kind(words, i, **args)
            if kind in found:
                found[kind].append(f"{label} {seg.segment_id} bei {_de(float(words[i]['end']))} s")
    out = []
    if found["pause_candidate"]:
        out.append(("boundary_from_pause", f"Satzgrenze ohne Satzzeichen, nur aus einer Pause abgeleitet (Regel {args['rule']}): {', '.join(found['pause_candidate'])}"))
    if found["length_cap"]:
        out.append(("boundary_from_length_cap", f"Satzgrenze aus der Satzlängengrenze, nicht aus Satzzeichen (Regel {args['rule']}): {', '.join(found['length_cap'])}"))
    return out


def _reject_reason(result: story_engine.CandidateResult) -> str:
    failed = [f"{k}: {g.get('detail') or ''}" for k, g in result.gates.items() if not g.get("passed")]
    return "Verworfen, gerissenes Tor (" + "; ".join(failed) + ")" if failed else "Verworfen"


# -- Adapter ---------------------------------------------------------------------------------------


def from_result(
    result: story_engine.CandidateResult,
    words: list[dict],
    sents: list[Sentence],
    source: dict[str, Any] | None,
    versions: dict[str, Any],
    policy: editorial.Policy,
    brief: dict[str, Any] | None = None,
    decision: str | None = None,
    decision_reason: str | None = None,
    alternatives: list[dict[str, Any]] | None = None,
) -> ClipCandidate:
    """ClipCandidate aus einem Ergebnis von ``story_engine``.

    ``sents`` ist die Satzliste des Laufs (``sentences_for``), ``source`` optional ``{"id", "version"}``
    (Quelle und Transkriptversion), ``versions`` aus ``versions_for``. Ohne ``decision`` gilt: Tore
    bestanden heißt ``accept`` mit ``why`` als Grund, sonst ``reject`` mit den gerissenen Toren.
    ``alternatives`` kennt nur der Aufrufer, der die Auswahl gesehen hat (``from_report``); ohne sie
    bleibt ``alternatives_considered`` ``None``."""
    # Der Kandidat beginnt mit seinem ersten Satz; seine Segmente dürfen später beginnen (AP7 kürzt Füllwörter
    # am Rand) und müssen nicht auf Satz- oder Wortgrenzen liegen.
    if not (0 <= result.first_sent <= result.last_sent < len(sents)) or abs(sents[result.first_sent].start - result.start_s) > 0.01:
        raise ValueError("Die Satzliste passt nicht zum Kandidaten (andere Zerlegung als im Lauf?)")
    source = dict(source or {})
    brief = dict(brief or {})
    rubric = result.rubric
    first, last = result.first_sent, result.last_sent

    segs: list[ClipSegment] = []
    for n, (seg, (out_in, out_out)) in enumerate(zip(result.segments, output_timeline(result.segments)), start=1):
        ids = _word_ids_in(words, float(seg["start"]), float(seg["end"]))
        speakers = {words[i].get("speaker") for i in ids}
        # Schnittgrenze ist die Segmentgrenze; liegt sie auf der Grenze des ersten oder letzten Wortes, gilt
        # dessen Zeit (keine erfundene Genauigkeit), sonst die tatsächliche Schnittzeit aus der Komposition.
        cut_in, cut_out = float(seg["start"]), float(seg["end"])
        segs.append(ClipSegment(
            segment_id=f"s{n}",
            source_in=(float(words[ids[0]]["start"]) if abs(float(words[ids[0]]["start"]) - cut_in) <= WORD_EPS_S else cut_in) if ids else None,
            source_out=(float(words[ids[-1]]["end"]) if abs(float(words[ids[-1]]["end"]) - cut_out) <= WORD_EPS_S else cut_out) if ids else None,
            output_in=out_in if ids else None,
            output_out=out_out if ids else None,
            speaker_id=str(next(iter(speakers))) if len(speakers) == 1 and None not in speakers else None,
            word_ids=ids,
            verbatim_text=" ".join(str(words[i].get("text") or "") for i in ids),
            editorial_role=str(seg.get("role") or "body"),
            boundary_confidence=None,
        ))  # fmt: skip

    teaser = rubric.get("teaser_satz")
    if isinstance(teaser, int) and 0 <= teaser < len(sents):
        opening = _span(words, sents, teaser, teaser, "teaser")
    else:
        opening = _span(words, sents, first, first, "body")

    repair = rubric.get("repair") or {}
    context: list[dict[str, Any]] = []
    front, back = int(repair.get("expanded_front") or 0), int(repair.get("expanded_back") or 0)
    if 0 < front <= last - first:
        context.append(_span(words, sents, first, first + front - 1, "Kontext vorn ergänzt (Reparatur oder Heilung)"))
    if 0 < back <= last - first:
        context.append(_span(words, sents, last - back + 1, last, "Kontext hinten ergänzt (Reparatur oder Kontextzugabe)"))

    payoff_evidence = str(((rubric.get("scores") or {}).get("payoff") or {}).get("evidence") or "").strip()
    payoff_idx = _payoff_sentence(sents, first, last, payoff_evidence)

    dependencies = []
    for f in result.story_graph_flags:
        idx = f.get("sentence_idx")
        known = isinstance(idx, int) and 0 <= idx < len(sents)
        dep_span = _span(words, sents, idx, idx, None) if known else None
        dependencies.append({
            "kind": "later_qualification",
            "sentence_idx": idx if known else None,
            "source_in": dep_span["source_in"] if dep_span else None,
            "source_out": dep_span["source_out"] if dep_span else None,
            "text": str(f.get("text") or ""),
            "marker": f.get("marker"),
            "confirmed": f.get("confirmed"),
            "detail": f.get("reason") or f.get("suggestion"),
        })  # fmt: skip

    questions = [{"kind": "unresolved_reference", "text": str(x)} for x in rubric.get("unresolved_references") or [] if str(x).strip()]
    if rubric.get("needs_earlier_context"):
        questions.append({"kind": "needs_earlier_context", "text": "Der Einstieg braucht Vorwissen aus dem Material davor."})
    if rubric.get("ends_before_answer"):
        questions.append({"kind": "ends_before_answer", "text": "Der Clip endet vor der Antwort."})

    uncertainties = low_confidence_uncertainties(words, [i for s in segs for i in s.word_ids])
    heuristic = "heuristic_only" in result.risk_flags
    if heuristic:
        uncertainties.append(_note("heuristic_only", "Bewertung ohne Sprachmodell (Heuristik): Werte unkalibriert, Humor, Sensitivität und Relativierungen ungeprüft."))
    nlp_note = _nlp_note(result.gates.get("verb_bracket") or {}, str(versions.get("nlp_status") or ""))
    if nlp_note:
        uncertainties.append(_note("nlp_unavailable", nlp_note))
    for kind, detail in _boundary_notes(words, segs, policy):
        uncertainties.append(_note(kind, detail))
    if any(s.boundary_confidence is None for s in segs):
        uncertainties.append(_note("boundary_confidence_missing", "Keine Angabe zur Sicherheit der Schnittkanten (kommt mit AP10b), Wortgrenzen aus der Transkription."))
    if any(f.get("confirmed") is None for f in result.story_graph_flags):
        uncertainties.append(_note("story_graph_unconfirmed", "Spätere Relativierung gefunden, aber von keinem Sprachmodell bestätigt; Mensch prüft."))

    if decision is None:
        decision = "accept" if result.gate_passed else "reject"
    if not decision_reason:
        decision_reason = result.why if decision == "accept" and result.why else _reject_reason(result)

    audience = str(brief.get("audience") or "").strip() or None
    objective = str(brief.get("objective") or "").strip() or None
    sid = source.get("id")
    sver = source.get("version")
    return ClipCandidate(
        candidate_id=_candidate_id(sid, sver, result, versions),
        source_asset_id=str(sid) if sid is not None else None,
        source_version=sver if isinstance(sver, (int, str)) and not isinstance(sver, bool) else None,
        objective=objective,
        audience_context=audience,
        audience_context_provenance="explicit" if audience else None,
        central_idea=None,
        viewer_promise=None,
        payoff_description=payoff_evidence or None,
        narrative_type=result.structure or None,
        opening_source_span=opening,
        required_context_spans=context,
        payoff_source_span=_span(words, sents, payoff_idx, payoff_idx, "Satz mit dem Beleg der Rubrik für payoff") if payoff_idx is not None else None,
        segments=segs,
        removed_spans=[RemovedSpan(**{k: r[k] for k in _REMOVED_FIELDS if k in r}) for r in rubric.get("removed_spans") or []],
        meaning_dependencies=dependencies,
        unresolved_questions=questions,
        # Die fünf Tore und, unter Fassung 2 mit den harten Gates (AP4), deren Einzelergebnisse.
        quality_gate_results=json.loads(json.dumps({**(rubric.get("quality_gate_results") or {}), **result.gates})),
        editorial_subscores={
            "scale_max": int(policy.skala_max),
            "values": {str(k): (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None) for k, v in (rubric.get("rubric_points") or {}).items()},
        },
        assessment_uncertainties=uncertainties,
        decision=decision,
        decision_reason=decision_reason,
        alternatives_considered=alternatives,
        model_version=result.model_id or versions.get("model_id") or None,
        prompt_version=dict(versions.get("prompts") or {}),
        policy_version=str(versions.get("policy_version") or editorial.policy_version(policy.version)),
        externally_verified=None,
        # Ohne Ergebnisdaten gibt es keine Kalibrierung, weder für die Heuristik noch für ein Modell
        # (Master-Prompt Abschnitt 19). "calibrated" ist für später reserviert.
        calibration="uncalibrated",
    )  # fmt: skip


def from_report(
    report: story_engine.DetectReport,
    words: list[dict],
    policy: editorial.Policy,
    source: dict[str, Any] | None = None,
    brief: dict[str, Any] | None = None,
    sents: list[Sentence] | None = None,
) -> list[ClipCandidate]:
    """Alle angebotenen (``accept``) und von ``select_best`` verworfenen (``reject``) Kandidaten eines
    Laufs. Grund und Alternativen kommen aus ``report.discarded`` (``gate``, ``overlap``, ``limit``)."""
    sents = sents if sents is not None else sentences_for(words, policy)
    versions = versions_for(policy, report)
    reasons = {
        (d.get("first_sent"), d.get("last_sent")): d for d in report.discarded
        if d.get("reason") in ("gate", "overlap", "limit", "below_threshold") or str(d.get("reason") or "").startswith("gate:")
    }  # fmt: skip
    ids = {id(c): _candidate_id((source or {}).get("id"), (source or {}).get("version"), c, versions) for c in [*report.candidates, *report.verworfen]}

    def alt(c: story_engine.CandidateResult, reason: str) -> dict[str, Any]:
        return {"candidate_id": ids[id(c)], "first_sent": c.first_sent, "last_sent": c.last_sent, "total": c.total, "reason": reason}

    def overlaps(a: story_engine.CandidateResult, b: story_engine.CandidateResult) -> bool:
        share = story_engine.gemeinsamer_anteil(a.start_s, a.end_s, b.start_s, b.end_s)
        return share >= story_engine.OVERLAP_SUPPRESS_ANTEIL

    out = []
    for c in report.candidates:
        alts = [alt(v, "überdeckt diesen Kandidaten und ist schwächer bewertet") for v in report.verworfen
                if reasons.get((v.first_sent, v.last_sent), {}).get("reason") == "overlap" and overlaps(c, v)]  # fmt: skip
        out.append(from_result(c, words, sents, source, versions, policy, brief, decision="accept", alternatives=alts))
    for v in report.verworfen:
        d = reasons.get((v.first_sent, v.last_sent), {})
        reason = str(d.get("reason") or "")
        if reason.startswith("gate:"):
            why = f"Verworfen vor dem Ranking, hartes Gate {reason[5:]}: {d.get('detail') or _reject_reason(v)}"
            alts = [alt(c, "angeboten statt dieses Kandidaten") for c in report.candidates if overlaps(c, v)]
            out.append(from_result(v, words, sents, source, versions, policy, brief, decision="reject", decision_reason=why, alternatives=alts))
            continue
        why = {
            "gate": _reject_reason(v),
            "below_threshold": f"Verworfen im Modus sperren: {d.get('detail') or 'unter der Schwelle'}",
            "overlap": f"Verworfen, überdeckt einen besser bewerteten Kandidaten zu mindestens {story_engine.OVERLAP_SUPPRESS_ANTEIL:.0%}",
            "limit": "Verworfen, über der Obergrenze der Kandidatenzahl",
        }.get(str(d.get("reason")), _reject_reason(v))
        alts = [alt(c, "angeboten statt dieses Kandidaten") for c in report.candidates if overlaps(c, v)]
        out.append(from_result(v, words, sents, source, versions, policy, brief, decision="reject", decision_reason=why, alternatives=alts))
    return out


RUBRIC_KEYS = (
    "versions", "decision", "decision_reason", "quality_gate_results", "editorial_subscores",
    "assessment_uncertainties", "removed_spans", "calibration",
)  # fmt: skip


def compact_for_rubric(cc: ClipCandidate) -> dict[str, Any]:
    """Die additive Teilmenge für ``candidates.rubric`` (Plan AP8): genau ``RUBRIC_KEYS``."""
    data = cc.to_dict()
    return {
        "versions": {
            "contract": CONTRACT,
            "model_version": data["model_version"],
            "prompt_version": data["prompt_version"],
            "policy_version": data["policy_version"],
        },
        **{k: data[k] for k in RUBRIC_KEYS if k != "versions"},
    }


__all__ = [
    "CALIBRATIONS",
    "CONTRACT",
    "DECISIONS",
    "RUBRIC_KEYS",
    "SCHEMA",
    "UNCERTAINTY_KINDS",
    "ClipCandidate",
    "ClipSegment",
    "RemovedSpan",
    "SchemaError",
    "compact_for_rubric",
    "from_report",
    "from_result",
    "low_confidence_uncertainties",
    "output_timeline",
    "sentences_for",
    "validate",
    "versions_for",
]
