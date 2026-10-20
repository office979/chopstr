"""Blindvergleich alt gegen neu (AP11): Policy-Fassung 1 gegen 2 auf demselben Material.

    .venv/bin/python -m eval.blind_compare --out blind/            # Läufe, Bögen, Quellen, Raster, Schlüssel
    .venv/bin/python -m eval.blind_compare --auswerten blind/      # Auswertung nach dem Bewerten

Ablauf und Raster stehen in ``eval/README.md``. Kurz:

1. ``story_engine.run`` läuft je Quelle mit ``CHOPSTR_POLICY_VERSION=1`` und ``2``, mit demselben
   Provider (Standard ``local-heuristic``), demselben Brief und derselben Obergrenze ``--k``. Je Quelle
   zählen die besten n Kandidaten beider Fassungen, n ist die kleinere Ausgabemenge; der Überhang steht
   im Schlüssel.
2. Paare innerhalb einer Quelle nach größter Überdeckung (``--paarung ueberdeckung``, Standard) oder nach
   Rang. Reihenfolge und Seite A oder B sind zufällig mit festem Seed (``--seed``).
3. Zwei Bögen ohne Versionskennung: ``bewertung.json`` bewertet nur den Clip (ohne Hook),
   ``hooks_bewertung.json`` die Hooks in eigenen Paaren. ``quellen.json`` enthält je Quelle das
   Transkript oder plus/minus fünf Sätze um beide Clips eines Paares, für beide Seiten gleich, und bei
   Datenbankquellen den Medienverweis. Die Zuordnung steht getrennt in ``schluessel.json``.
4. Das Erfolgskriterium wird beim Erzeugen festgelegt (Plan Abschnitt 8 Punkt 5) und steht im
   Schlüssel; ``--auswerten`` urteilt danach: Erfüllt, Nicht erfüllt oder Nicht bewertet.

Die Schalter-Varianten entstehen über eine Kopie der Richtlinie mit geänderten Schaltern in
``implementation`` und, wo nötig, der Regel (``EDITORIAL_DIR`` zeigt für die Dauer des Laufs darauf). Overrides:
Schalter ``--override pfad=true``, Regeln aus ``RULE_OVERRIDES`` ``--override regel:pfad=wert`` (mehrfach)
oder ``CHOPSTR_BLIND_OVERRIDES="pfad=true,regel:trim.enabled=true"``. Dubletten zählen nicht in die
Verwerfungsquote (``discard_summary``).

Das Ergebnis ist beobachtend, kein A/B-Test, kein Viralitätsmaß.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import dataclasses
import itertools
import json
import math
import os
import random
import re
import shutil
import statistics
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from chopstr_worker import config, editorial, providers_llm
from chopstr_worker.pipeline import clip_candidate, copy_de, copy_engine, segment, story_engine
from chopstr_worker.providers_llm import LLM
from chopstr_worker.residency import Tenant

RATING_SHEET = "blind_compare_raster_v2"
DEFAULT_SEED = 1729
DEFAULT_K = 5
DEFAULT_BRIEF: dict[str, Any] = {"platform": "linkedin"}
OVERRIDES_ENV = "CHOPSTR_BLIND_OVERRIDES"
NOTE = "beobachtend, kein A/B-Test, kein Viralitätsmaß"
PREFERENCES = ("A", "B", "gleich", "beide_unbrauchbar")
UNUSABLE = "beide_unbrauchbar"
# Frage 6.4 „Was stimmt an dem anderen nicht?“: Kategorie und Freitext je Paar. Bei A oder B betrifft der Mangel die
# nicht gewählte Seite, bei „beide unbrauchbar“ beide, bei „gleich“ keine bestimmte Fassung.
FLAW_CATEGORIES = ("einstieg", "ende", "kontext", "ton", "untertitel", "inhalt", "keine")
NO_VERSION = "ohne_fassung"
PREFERENCE_LABELS = {"gleich": "gleich", UNUSABLE: "beide unbrauchbar", "offen": "offen"}
# Wettbewerbsmodus (--extern): vorab festgelegt, was verglichen wird (Launch-Auftrag 6.4, Review 2D).
COMPARISONS = {
    "voller_output": "vollständiger Output: Momentwahl, Schnitt, Untertitel und Bildausschnitt zusammen",
    "momentwahl": "nur die Wahl des Moments: welcher Ausschnitt ist der bessere Clip-Inhalt",
    "schnitt": "nur der Schnitt desselben Moments: Paare überdecken sich zu mindestens der Hälfte",
}
OWN, EXTERNAL = "chopstr", "extern"
SAME_MOMENT_MIN = 0.5
EXTERNAL_CLIP_FILE = "clip.json"
MEDIA_DIR = "medien"
# Schwellen aus Abschnitt 1 des Launch-Auftrags (Vergleich): Gewinnrate unter den entschiedenen Urteilen und
# höchstens dieser Anteil „beide unbrauchbar“ unter allen abgegebenen Urteilen.
WIN_RATE_MIN = 0.6
BOTH_UNUSABLE_MAX = 0.2
PAIRINGS = ("ueberdeckung", "rang")
CONTEXT_SENTENCES = 5
FULL_TRANSCRIPT_MAX_SENTENCES = 40
VERDICTS = ("Erfüllt", "Nicht erfüllt", "Nicht bewertet")
FILES = {
    "sheet": "bewertung.json",
    "hook_sheet": "hooks_bewertung.json",
    "sources": "quellen.json",
    "key": "schluessel.json",
    "rubric": "raster.json",
    "run": "lauf.json",
    "report": "bericht.md",
}
# Grenzen der Stil-Leck-Prüfung: ab hier können Bewertende Clips oder Hooks einer Fassung zuordnen.
LEAK_SHARE_DIFF = 0.25
LEAK_PREFIX_SHARE = 0.5
LEAK_PREFIX_OTHER = 0.2
LEAK_SEGMENT_DIFF = 0.5
LEAK_LENGTH_RATIO = 0.25

# Gründe aus ``DetectReport.discarded`` (story_engine, payoff_search, editorial_gates) auf Deutsch.
REASON_LABELS = {
    "gate": "Tor",
    "overlap": "Überdeckung",
    "limit": "Obergrenze",
    "duplicate": "Dublette",
    "too_short": "zu kurz",
    "too_long": "zu lang",
    "too_short_after_repair": "zu kurz nach Reparatur",
    "too_long_after_repair": "zu lang nach Reparatur",
    "start_not_healed": "Anfang nicht heilbar",
    "ends_on_qualification": "endet auf Abschwächung",
    "promise_unfulfilled": "Versprechen nicht eingelöst",
    "context_missing": "Kontext fehlt",
    "same_payoff": "gleicher Payoff",
    "no_opening": "kein Einstieg",
    "instruction_followed": "Anweisung befolgt",
    "below_threshold": "unter der Schwelle",
    "redundant": "redundant zu einem angebotenen Kandidaten",
    "chapter_limit": "über der Grenze je Kapitel",
    "llm_budget": "Modellbudget erreicht",
    "budget_exhausted": "Modellbudget erschöpft",
    "clip_candidate_error": "ClipCandidate verletzt den Vertrag",
    "duplicate_payoff": "Dublette, gleicher Payoff",
    "same_span": "gleiche Spanne",
    "same_opening": "gleicher Einstieg",
    "same_statement": "gleiche Aussage",
    "chapter_overlap": "Kapitelüberlappung",
    "same_result": "gleiches Ergebnis nach der Bewertung",
}
# Dubletten: derselbe Moment, mehrfach gefunden. Sie stehen getrennt im Bericht und zählen weder in der
# Verwerfungsquote noch in ihrem Nenner, damit Fassung 1 (Vorschläge des Modells) und Fassung 2
# (Vorschläge der Suche, die denselben Payoff oft mehrfach findet) vergleichbar bleiben.
DUPLICATE_REASONS = frozenset({
    "duplicate", "duplicate_payoff", "same_span", "same_opening", "same_statement", "same_payoff", "chapter_overlap", "same_result",
})  # fmt: skip
# Ereignisse des Laufs, die keinen einzelnen Vorschlag betreffen (Budget, Vertragsfehler).
RUN_EVENT_REASONS = frozenset({"budget_exhausted", "clip_candidate_error"})
STAGE_LABELS = {"search": "Suche", "propose": "Vorschlag", "critic": "Kritiker"}

ANCHORS_TEXT = "0 nicht vorhanden oder kritisch verletzt, 1 schwach, 2 brauchbar, 3 stark und begründet, 4 besonders überzeugend"

# Raster für den Clip (Master-Prompt 19: Anker 0 bis 4; 26: die acht Kriterien). Höher ist immer besser.
CRITERIA: dict[str, dict[str, Any]] = {
    "quellentreue": {
        "titel": "Quellentreue",
        "frage": "Gibt der Clip wieder, was die Quelle sagt, ohne Sinnumkehr, ohne verlorene Bedingung oder Einschränkung, ohne falsche Zuordnung? Mit dem Kontext aus quellen.json prüfen.",
        "anker": {
            "0": "Sinn verkehrt oder verfälscht: Verneinung, Bedingung oder Einschränkung fehlt, Aussage falsch zugeordnet",
            "1": "schwach: Aussage zugespitzt, eine Einschränkung nur angedeutet",
            "2": "brauchbar: Aussage stimmt, kleine Unschärfe ohne Folgen",
            "3": "stark und begründet: Aussage vollständig samt ihren Bedingungen",
            "4": "besonders überzeugend: wörtlich treu, Bedingungen und Zuordnungen klar",
        },
    },
    "eigenstaendigkeit": {
        "titel": "Eigenständigkeit",
        "frage": "Versteht man den Clip ohne Vorwissen aus dem übrigen Material?",
        "anker": {
            "0": "ohne das Material davor nicht verständlich (offene Verweise, Pronomen ohne Bezug)",
            "1": "nur mit Mühe verständlich",
            "2": "verständlich, ein Bezug bleibt vage",
            "3": "für sich verständlich",
            "4": "sofort verständlich, auch ohne die Folge zu kennen",
        },
    },
    "einstieg": {
        "titel": "Einstieg",
        "frage": "Ist der Anfang klar, und trägt er bis zum Kern?",
        "anker": {
            "0": "beginnt mitten im Satz oder mit einem Rückverweis",
            "1": "schwacher Einstieg, Anlauf ohne Inhalt",
            "2": "brauchbarer Einstieg",
            "3": "klarer Einstieg mit Bezug zum Kern",
            "4": "Einstieg, der sofort trägt und im Clip eingelöst wird",
        },
    },
    "aufbau": {
        "titel": "Aufbau",
        "frage": "Führt der Verlauf vom Einstieg zum Kern, ohne Ballast und ohne Sprünge?",
        "anker": {
            "0": "zerfahren, Sprünge oder umgestellte Aussagen",
            "1": "viel Ballast oder Wiederholung",
            "2": "nachvollziehbar, mit Längen",
            "3": "klarer Fortschritt",
            "4": "jeder Satz bringt den Gedanken weiter",
        },
    },
    "abschluss": {
        "titel": "Abschluss",
        "frage": "Endet der Clip mit eingelöstem Versprechen?",
        "anker": {
            "0": "endet vor der Antwort, auf „aber“ oder mitten im Satz",
            "1": "endet offen, ohne dass es gewollt wirkt",
            "2": "endet abgeschlossen, aber schwach",
            "3": "endet auf der Auflösung",
            "4": "endet überzeugend auf dem stärksten Satz",
        },
    },
    "natuerlichkeit": {
        "titel": "Natürlichkeit",
        "frage": "Klingt der Schnitt natürlich (Sprachfluss, Atem, Pausen, keine hörbaren Sprünge)? Am Audio der Quelle mit den Zeiten unter segmente prüfen.",
        "anker": {
            "0": "abgeschnittene Wörter oder hörbare Sprünge",
            "1": "auffällige Schnitte",
            "2": "einzelne kleine Unebenheiten",
            "3": "natürlich",
            "4": "nicht als Schnitt wahrnehmbar",
        },
    },
    "duplikate": {
        "titel": "Duplikate",
        "frage": "Wiederholt der Clip einen anderen Clip derselben Ausgabe (gleiche Angabe unter „ausgabe“)?",
        "anker": {
            "0": "fast identisch mit einem anderen Clip",
            "1": "überdeckt einen anderen Clip zum großen Teil",
            "2": "teilweise Überschneidung",
            "3": "eigener Gedanke, kleine Überschneidung",
            "4": "eigener Gedanke ohne Überschneidung",
        },
    },
    "manuelle_nacharbeit": {
        "titel": "Manuelle Nacharbeit",
        "frage": "Wie viel müsste die Redaktion am Schnitt ändern, bevor sie den Clip veröffentlicht (ohne Hook)?",
        "anker": {
            "0": "unbrauchbar, müsste neu geschnitten werden",
            "1": "viel Nacharbeit (Grenzen, Kontext)",
            "2": "mittlere Nacharbeit",
            "3": "kleine Korrektur",
            "4": "ohne Änderung veröffentlichbar",
        },
    },
}

# Raster für die Hooks (eigener Bogen, damit der Hook-Stil die Clip-Bewertung nicht verrät).
HOOK_CRITERIA: dict[str, dict[str, Any]] = {
    "deckung": {
        "titel": "Deckung durch den Clip",
        "frage": "Behauptet der Hook nicht mehr, als der Clip sagt (Zahlen, Geltungsbereich, Zuspitzung)?",
        "anker": {
            "0": "behauptet etwas, das der Clip nicht sagt, oder verfälscht eine Zahl",
            "1": "spitzt deutlich zu",
            "2": "gedeckt, aber unscharf",
            "3": "gedeckt und genau",
            "4": "wörtlich gedeckt und genau",
        },
    },
    "klarheit": {
        "titel": "Klarheit",
        "frage": "Versteht man den Hook beim ersten Lesen oder Hören?",
        "anker": {
            "0": "unverständlich oder Bruchstück",
            "1": "nur mit Mühe verständlich",
            "2": "verständlich",
            "3": "klar",
            "4": "sofort klar und konkret",
        },
    },
    "einstieg": {
        "titel": "Einstieg in den Clip",
        "frage": "Führt der Hook in den Clip, ohne das Ende vorwegzunehmen oder etwas anderes zu versprechen?",
        "anker": {
            "0": "verspricht etwas anderes als der Clip",
            "1": "passt nur lose",
            "2": "passt",
            "3": "führt gut in den Clip",
            "4": "führt in den Clip und macht den Kern erwartbar",
        },
    },
    "ton": {
        "titel": "Ton",
        "frage": "Klingt der Hook natürlich, ohne Floskel und ohne Übertreibung? Kein Overlay-Text ist eine zulässige Entscheidung.",
        "anker": {
            "0": "Floskel oder reißerisch",
            "1": "formelhaft",
            "2": "unauffällig",
            "3": "natürlich",
            "4": "natürlich und eigenständig",
        },
    },
}

# Gruppen der Schalter in ``implementation`` (Master-Prompt 26: Auswahl, Hooks, Kürzung, Kombination).
SWITCH_GROUPS: dict[str, tuple[str, ...]] = {
    "auswahl": ("gates.discard_hard", "search.payoff_first"),
    "hooks": ("hook.native_spoken",),
    "kuerzung": ("trim.enabled",),
}
# Regeln, die eine Gruppe zusätzlich zum Schalter einschaltet (sonst bliebe sie wirkungslos).
GROUP_RULES: dict[str, tuple[tuple[str, Any], ...]] = {"kuerzung": (("trim.enabled", True),)}
# Regelpfade, die ein Override erreichen darf, mit den erlaubten Werten (Whitelist).
RULE_PREFIX = "regel:"
RULE_OVERRIDES: dict[str, tuple[Any, ...]] = {
    "trim.enabled": (True, False),
    "gates.discard_hard": (True, False),
    "hook.allow_partial_opening": (True, False),
    "bewertung.modus_v2": ("sortieren", "sperren"),
}
GROUP_TITLES = {"basis": "Basis", "auswahl": "Auswahl", "hooks": "Hooks", "kuerzung": "Kürzung", "kombination": "Kombination", "override": "Override"}


@dataclasses.dataclass(frozen=True)
class Variant:
    """Ein Lauf: Richtlinien-Fassung, Schalter-Overrides (Pfad in ``implementation`` zu bool) und
    Regel-Overrides (Pfad einer Regel, nur aus ``RULE_OVERRIDES``)."""

    name: str
    version: int
    overrides: tuple[tuple[str, bool], ...] = ()
    group: str | None = None
    rules: tuple[tuple[str, Any], ...] = ()


BASE_VARIANTS = (Variant("v1", 1), Variant("v2", 2))


def switch_variants(extra: dict[str, bool] | None = None, extra_rules: dict[str, Any] | None = None) -> list[Variant]:
    """Basis (alle Gruppenschalter aus), je Gruppe einzeln an, Kombination (alle Gruppen an).

    Eine Gruppe, deren Regel in der Richtlinie aus steht (``GROUP_RULES``, etwa ``trim.enabled: false``
    bis zur Abnahme), setzt zusätzlich die Regel; sonst wäre sie gleich der Basis."""
    all_switches = [s for group in SWITCH_GROUPS.values() for s in group]
    all_rules = {path: value for group in GROUP_RULES.values() for path, value in group}
    base = {s: False for s in all_switches}
    out = [Variant("v2_basis", 2, tuple(sorted(base.items())), "basis")]
    for group, switches in SWITCH_GROUPS.items():
        out.append(Variant(f"v2_{group}", 2, tuple(sorted({**base, **dict.fromkeys(switches, True)}.items())), group, GROUP_RULES.get(group, ())))
    out.append(Variant("v2_kombination", 2, tuple(sorted(dict.fromkeys(all_switches, True).items())), "kombination", tuple(sorted(all_rules.items()))))
    if extra or extra_rules:
        out.append(Variant("v2_override", 2, tuple(sorted((extra or {}).items())), "override", tuple(sorted((extra_rules or {}).items()))))
    return out


def _parse_value(text: str) -> Any:
    low = text.strip().lower()
    return {"true": True, "false": False}.get(low, text.strip())


def parse_overrides(items: list[str] | None, env: str | None = None) -> tuple[dict[str, bool], dict[str, Any]]:
    """Schalter ``pfad=true|false`` (Pfade aus ``editorial.V2_SWITCHES``) und Regeln ``regel:pfad=wert``
    (nur Pfade und Werte aus ``RULE_OVERRIDES``). Gibt (Schalter, Regeln)."""
    raw = [*(env or "").split(","), *(items or [])]
    switches: dict[str, bool] = {}
    rules: dict[str, Any] = {}
    for item in (x.strip() for x in raw):
        if not item:
            continue
        path, _, value = item.partition("=")
        if path.startswith(RULE_PREFIX):
            rule = path.removeprefix(RULE_PREFIX)
            parsed = _parse_value(value)
            if rule not in RULE_OVERRIDES or parsed not in RULE_OVERRIDES[rule]:
                allowed = "; ".join(f"{RULE_PREFIX}{p}={'|'.join(str(v).lower() for v in vals)}" for p, vals in RULE_OVERRIDES.items())
                raise SystemExit(f"Override {item!r} ungültig: erlaubte Regeln sind {allowed}.")
            rules[rule] = parsed
            continue
        if path not in editorial.V2_SWITCHES or value.lower() not in ("true", "false"):
            raise SystemExit(
                f"Override {item!r} ungültig: erlaubt sind {', '.join(editorial.V2_SWITCHES)} mit =true oder =false, "
                f"oder Regeln mit {RULE_PREFIX}pfad=wert."
            )
        switches[path] = value.lower() == "true"
    return switches, rules


@contextlib.contextmanager
def policy_variant(variant: Variant) -> Iterator[editorial.Policy]:
    """Setzt Fassung und Overrides für die Dauer des Blocks und stellt die Umgebung danach wieder her."""
    saved = {k: os.environ.get(k) for k in (editorial.POLICY_VERSION_ENV, "EDITORIAL_DIR")}
    tmp: str | None = None
    try:
        os.environ[editorial.POLICY_VERSION_ENV] = str(variant.version)
        if variant.overrides or variant.rules:
            import yaml

            tmp = tempfile.mkdtemp(prefix="blind_compare_policy_")
            for path in editorial.policy_dir().glob("clip_policy_v*.yaml"):
                shutil.copy(path, tmp)
            target = Path(tmp) / f"clip_policy_v{variant.version}.yaml"
            data = yaml.safe_load(target.read_text(encoding="utf-8"))
            for switch, value in variant.overrides:
                node = data.setdefault("implementation", {})
                *parents, leaf = switch.split(".")
                for part in parents:
                    node = node.setdefault(part, {})
                node[leaf] = value
            for rule, value in variant.rules:
                node = data
                *parents, leaf = rule.split(".")
                for part in parents:
                    node = node.setdefault(part, {})
                node[leaf] = value
            target.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            os.environ["EDITORIAL_DIR"] = tmp
        editorial.clear_cache()
        yield editorial.load()
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        editorial.clear_cache()
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


# -- Quellen ---------------------------------------------------------------------------------------


def _with_prob(words: list[dict]) -> list[dict]:
    """Fixtures nennen die ASR-Sicherheit ``asr_confidence``; Hooks und Claim-Check lesen ``prob``."""
    return [{**w, "prob": w["asr_confidence"]} if w.get("prob") is None and "asr_confidence" in w else dict(w) for w in words]


def fixture_sources() -> list[dict[str, Any]]:
    """Demo-Skript (``transcript_fixtures.DEMO_SCRIPT``) und die 14 Fälle aus ``editorial_v1``."""
    from tests.editorial_v1 import harness
    from tests.transcript_fixtures import demo_words

    out = [{"name": "demo_script", "words": demo_words(), "case": None, "medien": None}]
    for case in harness.load_cases():
        out.append({"name": f"fall_{case['id']}", "words": _with_prob(case["words"]), "case": case, "medien": None})
    return out


def transcript_sources(folder: str) -> list[dict[str, Any]]:
    """``*.json`` aus einem Ordner: eine Wortliste oder ``{"words": [...], "medien": ...}``."""
    path = Path(folder)
    if not path.is_dir():
        raise SystemExit(f"Transkript-Ordner {folder} gibt es nicht.")
    out = []
    for file in sorted(path.glob("*.json")):
        data = json.loads(file.read_text(encoding="utf-8"))
        words = data if isinstance(data, list) else data.get("words")
        if not isinstance(words, list) or not words:
            raise SystemExit(f"{file.name}: keine Wortliste gefunden.")
        medien = None if isinstance(data, list) else data.get("medien")
        out.append({"name": file.stem, "words": _with_prob(words), "case": None, "medien": medien})
    return out


SQL_MEDIA = "select storage_key, title from sources where id = %s"


def database_sources(source_ids: list[str]) -> list[dict[str, Any]]:
    """Neueste Transkriptversion je Quelle aus Postgres (nur mit ``DATABASE_URL``), mit Medienverweis."""
    if not source_ids:
        return []
    if not os.environ.get("DATABASE_URL"):
        raise SystemExit("--quelle braucht DATABASE_URL. Vorher: source scripts/local_env.sh")
    from chopstr_worker import db
    from eval import clip_eval

    conn = db.connect()
    try:
        out = []
        for sid in source_ids:
            row = db.fetch_one(conn, SQL_MEDIA, (sid,))
            medien = {"quelle_id": sid, "storage_key": row[0], "titel": row[1]} if row else {"quelle_id": sid}
            # Gespeicherte Satzindizes stammen aus der Satzregel zur Zeit der Transkription. Fuer den Vergleich
            # zerlegt jede Fassung die Woerter frisch mit ihrer eigenen Regel.
            words = [{k: v for k, v in w.items() if k != "sentence_idx"} for w in clip_eval.load_words(conn, sid)]
            out.append({"name": f"quelle_{sid}", "words": words, "case": None, "medien": medien})
        return out
    finally:
        conn.close()


def source_hours(words: list[dict]) -> float:
    if not words:
        return 0.0
    return (max(float(w["end"]) for w in words) - min(float(w["start"]) for w in words)) / 3600.0


# -- Läufe -----------------------------------------------------------------------------------------


def reason_label(code: str) -> str:
    """Deutsche Bezeichnung mit Code in Klammern, etwa „Überdeckung (overlap)“."""
    if code.startswith("ohne_grund/"):
        stage = code.split("/", 1)[1]
        return f"ohne Grundangabe, Stufe {STAGE_LABELS.get(stage, stage)} ({code})"
    base, _, sub = code.partition("/")
    if base.startswith("critic:"):
        return f"Kritiker: {base.split(':', 1)[1]} ({code})"
    label = REASON_LABELS.get(base)
    if label and sub and REASON_LABELS.get(sub, sub) not in label:
        label = f"{label}, {REASON_LABELS.get(sub, sub)}"
    return f"{label} ({code})" if label else f"unbekannter Grund ({code})"


def discard_code(d: dict) -> str:
    """Code eines Eintrags aus ``DetectReport.discarded``. Dubletten der Suche tragen ihre Art im Detail
    (``duplicate_payoff/same_span``); ein Eintrag ohne Grund heißt nach seiner Stufe (``ohne_grund/search``)."""
    reason = str(d.get("reason") or "")
    if not reason:
        return f"ohne_grund/{d.get('stage') or 'unbekannt'}"
    if reason == "duplicate_payoff" and d.get("detail") in DUPLICATE_REASONS:
        return f"{reason}/{d['detail']}"
    return reason


def _kind(code: str, d: dict | None = None) -> str:
    base = code.split("/", 1)[0]
    if base in DUPLICATE_REASONS:
        return "dublette"
    if base in RUN_EVENT_REASONS or (base == "llm_budget" and (d or {}).get("stage") == "propose"):
        return "ereignis"
    return "verworfen"


def rejection_rates(discarded: list[dict], denominator: int) -> dict[str, dict[str, float | int]]:
    """Anzahl je Code und Anteil am Nenner, für alle übergebenen Einträge."""
    counts = Counter(discard_code(d) for d in discarded)
    return {code: {"anzahl": n, "quote": round(n / denominator, 4) if denominator else 0.0} for code, n in sorted(counts.items())}


def discard_summary(discarded: list[dict], offered: int, duplicate_counts: dict[str, int] | None = None) -> dict[str, Any]:
    """Verwerfungen getrennt nach echten Verwerfungen, Dubletten und Laufereignissen.

    Nenner der Quote: alle Vorschläge mit Ergebnis, also verworfen oder angeboten (``offered``), ohne
    Dubletten; das ist für Fassung 1 (Vorschläge des Modells) und Fassung 2 (Vorschläge der Suche) gleich
    gebildet. Dubletten kommen ab Fassung 2 aus ``report.search["duplicate_counts"]`` (je Art), ältere aus
    ``discarded`` (``duplicate``); sie zählen wie Laufereignisse nicht in die Quote."""
    groups: dict[str, list[dict]] = {"verworfen": [], "dublette": [], "ereignis": []}
    for d in discarded:
        groups[_kind(discard_code(d), d)].append(d)
    denominator = len(groups["verworfen"]) + int(offered)
    duplicates = Counter(discard_code(d) for d in groups["dublette"])
    duplicates.update({str(k): int(n) for k, n in (duplicate_counts or {}).items()})
    return {
        "nenner": denominator,
        "verworfen": rejection_rates(groups["verworfen"], denominator),
        "verworfen_gesamt": len(groups["verworfen"]),
        "dubletten": dict(sorted(duplicates.items())),
        "laufereignisse": {code: v["anzahl"] for code, v in rejection_rates(groups["ereignis"], 0).items()},
    }


def case_result(case: dict, offered: list[dict], rows: dict[str, dict], hooks: dict[str, dict]) -> dict[str, Any]:
    """Besteht die Ausgabe einer Version den Fall aus editorial_v1? Prüft mit dem Harness."""
    from tests.editorial_v1 import harness

    exp = case["expected"]
    reasons: list[str] = []
    if exp["expect_reject"]["value"]:
        if offered:
            reasons.append(f"Verwerfen erwartet, angeboten werden {len(offered)} Kandidaten")
        return {"bestanden": not reasons, "gruende": reasons}
    if not offered:
        return {"bestanden": False, "gruende": ["clipfähiges Material, aber kein Kandidat angeboten"]}
    for cc in offered:
        row = rows[cc["candidate_id"]]
        hook = hooks.get(cc["candidate_id"]) or {}
        checks = [
            # Die entfernten Stellen der Kürzung aus der Rubrik: lokale Nähte (technische Pause, Füllwort,
            # Einwurf) sind dann keine „Naht mitten im Satz ohne lokale Entfernung“.
            lambda cc=cc, row=row: harness.assert_clip_respects_case(
                case, cc["segments"], removed_spans=(row.get("rubric") or {}).get("removed_spans") or cc["removed_spans"]
            ),
            lambda cc=cc: harness.assert_protected_spans_kept(case, cc["removed_spans"]),
        ]
        if exp.get("uncertain_words"):
            checks.append(lambda cc=cc: harness.assert_uncertainty_marked(case, cc))
        if exp.get("boundary_confidence"):
            checks.append(lambda cc=cc: harness.assert_boundary_confidence_honest(case, cc["segments"]))
        if exp.get("instruction_must_be_ignored"):
            outputs = [row["why"], row["rubric"].get("suggested_title_card"), hook.get("gesprochen"), hook.get("text")]
            checks.append(lambda outputs=outputs: harness.assert_instruction_ignored(case, [o for o in outputs if o]))
        if exp.get("is_humor"):
            checks.append(lambda row=row: harness.assert_humor_flagged(case, row))
        for check in checks:
            try:
                check()
            except AssertionError as exc:
                reasons.append(str(exc))
    if exp.get("near_duplicate_candidates"):
        ranges = [[min(ids), max(ids)] for ids in ([i for s in cc["segments"] for i in s["word_ids"]] for cc in offered) if ids]
        try:
            harness.assert_single_survivor(case, ranges)
        except AssertionError as exc:
            reasons.append(str(exc))
    return {"bestanden": not reasons, "gruende": reasons}


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\wäöüß ]", " ", str(text or "").lower()).split())


def whole_sentence(hook: str, clip_text: str) -> bool:
    """Ist der gesprochene Hook ein ganzer Satz des Clips (wörtlich, von Satzanfang bis Satzende)?"""
    target = _norm(hook)
    return bool(target) and any(_norm(s) == target for s in _SENTENCE_SPLIT.split(clip_text))


def _hook(llm: Any, cc: dict, words: list[dict], settings: config.Settings, platform: str) -> dict[str, Any]:
    clip_words = [words[i] for s in cc["segments"] for i in s["word_ids"]]
    text = " ".join(s["verbatim_text"] for s in cc["segments"])
    brand = copy_de.BrandProfile(platform=platform)
    res = copy_engine.write_copy(llm, text, brand, platforms=(platform,), s=settings, words=clip_words)
    return {
        "gesprochen": res.spoken_hook,
        "text": res.onscreen_hook,
        "muster": res.pattern,
        "befunde": len(res.claim_issues),
        "ganzer_satz": whole_sentence(res.spoken_hook, text),
    }


LLMFactory = Callable[[str, config.Settings, Callable[[dict], None]], Any]


def _default_llm(provider: str, settings: config.Settings, sink: Callable[[dict], None]) -> LLM:
    return LLM(Tenant(id="blind-compare", tier="standard"), provider=provider, s=settings, cost_sink=sink)


def _reject_text(discarded: dict | None) -> str | None:
    """Grund für einen von ``select_best`` verworfenen Kandidaten; ``None`` überlässt das Tor dem Adapter."""
    code = str((discarded or {}).get("reason") or "")
    if code == "overlap":
        return f"Verworfen: {reason_label(code)}, ein besser bewerteter Kandidat überdeckt diesen"
    if code == "limit":
        return f"Verworfen: {reason_label(code)} der Kandidatenzahl"
    return None


def run_variant(
    variant: Variant, source: dict[str, Any], brief: dict[str, Any], provider: str, k: int, llm_factory: LLMFactory | None = None
) -> dict[str, Any]:
    """Ein Lauf von ``story_engine.run`` plus Hooks je angebotenem Kandidaten, mit gezählten Modellaufrufen.

    Ergebnis und ClipCandidate gehören über ``(first_sent, last_sent)`` zusammen; jeder ClipCandidate
    entsteht aus genau seinem Ergebnis."""
    calls: list[dict] = []
    platform = str(brief.get("platform") or "linkedin")
    settings = dataclasses.replace(config.settings(), languagetool_url="")
    with policy_variant(variant) as pol:
        llm = (llm_factory or _default_llm)(provider, settings, calls.append)
        words = copy.deepcopy(source["words"])
        started = time.perf_counter()
        report = story_engine.run(words, dict(brief), {}, None, llm, max_candidates=k)
        sents = clip_candidate.sentences_for(words, pol)
        versions = clip_candidate.versions_for(pol, report)
        dropped = {(d.get("first_sent"), d.get("last_sent")): d for d in report.discarded if d.get("reason") in ("gate", "overlap", "limit")}
        entries: dict[tuple[int, int], tuple[story_engine.CandidateResult, dict]] = {}
        for result, decision in [*((c, "accept") for c in report.candidates), *((v, "reject") for v in report.verworfen)]:
            span = (result.first_sent, result.last_sent)
            reason = None if decision == "accept" else _reject_text(dropped.get(span))
            cc = clip_candidate.from_result(result, words, sents, {"id": source["name"]}, versions, pol, brief, decision=decision, decision_reason=reason)
            entries[span] = (result, cc.to_dict())
        offered_spans = [(c.first_sent, c.last_sent) for c in report.candidates]
        hooks = {span: _hook(llm, entries[span][1], words, settings, platform) for span in offered_spans}
        runtime = time.perf_counter() - started
    ranked = sorted(offered_spans, key=lambda s: (-float(entries[s][0].total), float(entries[s][0].start_s)))
    rows = {entries[s][1]["candidate_id"]: entries[s][0].to_row() for s in entries}
    by_id_hooks = {entries[s][1]["candidate_id"]: hooks[s] for s in offered_spans}
    offered = [entries[s][1] for s in offered_spans]
    angeboten = []
    for span in ranked:
        result, cc = entries[span]
        angeboten.append({
            "candidate_id": cc["candidate_id"],
            "first_sent": span[0], "last_sent": span[1],
            "start_s": result.start_s, "end_s": result.end_s,
            "total": result.total,
            "segmente": [{"von_s": s["source_in"], "bis_s": s["source_out"], "rolle": s["editorial_role"]} for s in cc["segments"]],
            "text": " ".join(s["verbatim_text"] for s in cc["segments"]),
            "dauer_s": round(sum((s["output_out"] or 0) - (s["output_in"] or 0) for s in cc["segments"]), 2),
            "hook": hooks[span],
        })  # fmt: skip
    hook_list = list(hooks.values())
    return {
        "variante": variant.name,
        "fassung": variant.version,
        "schalter": dict(variant.overrides),
        "regeln": dict(variant.rules),
        "quelle": source["name"],
        "quelle_stunden": source_hours(source["words"]),
        "vorschlaege": report.proposals,
        **discard_summary(report.discarded, len(report.candidates), (getattr(report, "search", None) or {}).get("duplicate_counts")),
        "modellaufrufe": len(calls),
        "modellaufrufe_je_prompt": dict(sorted(Counter(str(c.get("prompt")) for c in calls).items())),
        "laufzeit_s": round(runtime, 4),
        "hooks": {
            "gesamt": len(hook_list),
            "native": sum(1 for h in hook_list if h["muster"] == copy_engine.NATIVE_PATTERN),
            "ohne_overlay": sum(1 for h in hook_list if not str(h["text"] or "").strip()),
            "ganzer_satz": sum(1 for h in hook_list if h["ganzer_satz"]),
            "mit_befund": sum(1 for h in hook_list if h["befunde"]),
        },
        "editorial_v1": case_result(source["case"], offered, rows, by_id_hooks) if source.get("case") else None,
        "angeboten": angeboten,
        "clip_candidates": [entries[s][1] for s in entries],
    }


# -- Paare -----------------------------------------------------------------------------------------


def _overlap(a: dict, b: dict) -> float:
    return story_engine.gemeinsamer_anteil(float(a["start_s"]), float(a["end_s"]), float(b["start_s"]), float(b["end_s"]))


def match_pairs(a: list[dict], b: list[dict], pairing: str) -> list[tuple[int, int, float]]:
    """Paare aus zwei gleich langen Listen (je nach Rang sortiert): nach Rang oder nach größter Überdeckung
    (gierig, bei Gleichstand der bessere Rang)."""
    if pairing not in PAIRINGS:
        raise SystemExit(f"--paarung {pairing!r}: erlaubt sind {', '.join(PAIRINGS)}.")
    if pairing == "rang":
        return [(i, i, round(_overlap(a[i], b[i]), 3)) for i in range(len(a))]
    options = sorted(((_overlap(x, y), -(i + j), i, j) for i, x in enumerate(a) for j, y in enumerate(b)), reverse=True)
    used_a, used_b, out = set(), set(), []
    for ov, _rank, i, j in options:
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        out.append((i, j, round(ov, 3)))
    return sorted(out)


def _clip_side(clip: dict, output_label: str) -> dict[str, Any]:
    """Was die Bewertenden vom Clip sehen: Text und Zeiten. Kein Hook, keine Version, kein Score."""
    return {"ausgabe": output_label, "text": clip["text"], "segmente": clip["segmente"], "dauer_s": clip["dauer_s"]}


def _hook_side(clip: dict) -> dict[str, Any]:
    text = str(clip["hook"]["text"] or "").strip()
    return {"hook_gesprochen": clip["hook"]["gesprochen"], "hook_text": text or None, "clip_text": clip["text"]}


def make_pairs(
    runs: dict[str, dict[str, dict]], seed: int, left: str = "v1", right: str = "v2", pairing: str = "ueberdeckung",
    sentences: dict[str, list[segment.Sentence]] | None = None,
) -> tuple[dict, dict, dict]:  # fmt: skip
    """Clip-Bogen, Hook-Bogen und Schlüssel für ``left`` gegen ``right`` bei gleicher Ausgabemenge je Quelle.

    ``sentences`` (Quelle zu neutraler Satzliste) setzt je Paar den Kontextbereich plus/minus
    ``CONTEXT_SENTENCES`` Sätze um beide Clips; ohne sie bleibt ``kontext`` beim Quellnamen."""
    rng = random.Random(seed)
    neutral = {name: f"Q{i:02d}" for i, name in enumerate(sorted(runs), start=1)}
    pairs, surplus = [], []
    for name in sorted(runs):
        a, b = runs[name][left]["angeboten"], runs[name][right]["angeboten"]
        n = min(len(a), len(b))
        flip = rng.random() < 0.5
        labels = {left: f"{neutral[name]}/{2 if flip else 1}", right: f"{neutral[name]}/{1 if flip else 2}"}
        for i, j, ov in match_pairs(a[:n], b[:n], pairing):
            pairs.append({"quelle": name, "labels": labels, "rang": {left: i + 1, right: j + 1}, "ueberdeckung": ov, left: a[i], right: b[j]})
        for version, clips in ((left, a), (right, b)):
            surplus += [{"quelle": name, "version": version, "rang": r + 1, "candidate_id": c["candidate_id"]} for r, c in enumerate(clips[n:], start=n)]
    for p in pairs:
        p["kontext"] = _context_range(sentences.get(p["quelle"]) if sentences else None, p[left], p[right], neutral[p["quelle"]])

    clip_order = list(pairs)
    rng.shuffle(clip_order)
    sheet_pairs, key_pairs = [], {}
    for i, p in enumerate(clip_order, start=1):
        pid = f"P{i:03d}"
        side = _sides(rng, left, right)
        sheet_pairs.append({
            "paar_id": pid, "quelle": neutral[p["quelle"]], "kontext": p["kontext"],
            "A": _clip_side(p[side["A"]], p["labels"][side["A"]]), "B": _clip_side(p[side["B"]], p["labels"][side["B"]]),
            "bewertung": {"A": dict.fromkeys(CRITERIA), "B": dict.fromkeys(CRITERIA), "praeferenz": None, "notiz": "", "mangel": empty_flaw()},
        })  # fmt: skip
        key_pairs[pid] = _key_entry(p, side, neutral)

    hook_order = list(pairs)
    rng.shuffle(hook_order)
    hook_pairs, key_hooks = [], {}
    for i, p in enumerate(hook_order, start=1):
        pid = f"H{i:03d}"
        side = _sides(rng, left, right)
        hook_pairs.append({
            "paar_id": pid, "quelle": neutral[p["quelle"]],
            "A": _hook_side(p[side["A"]]), "B": _hook_side(p[side["B"]]),
            "bewertung": {"A": dict.fromkeys(HOOK_CRITERIA), "B": dict.fromkeys(HOOK_CRITERIA), "praeferenz": None, "notiz": "", "mangel": empty_flaw()},
        })  # fmt: skip
        key_hooks[pid] = _key_entry(p, side, neutral)

    sheet = {
        "raster": RATING_SHEET,
        "hinweis": "Je Paar beide Clips nach raster.json (kriterien) bewerten, 0 bis 4, leer heißt nicht bewertet; dann praeferenz A, B, gleich oder beide_unbrauchbar. Den Kontext unter kontext in quellen.json lesen. Die Herkunft der Clips ist verborgen. Unter rater die eigene Bewerter-ID eintragen.",
        "rater": None,
        "paare": sheet_pairs,
    }
    hook_sheet = {
        "raster": RATING_SHEET,
        "hinweis": "Je Paar beide Hooks nach raster.json (hook_kriterien) bewerten, 0 bis 4; hook_text null heißt kein Overlay-Text. Getrennt vom Clip-Bogen bewerten, am besten von anderen Personen. Unter rater die eigene Bewerter-ID eintragen.",
        "rater": None,
        "paare": hook_pairs,
    }
    key = {
        "raster": RATING_SHEET, "seed": seed, "links": left, "rechts": right, "paarung": pairing,
        "quellen": {v: k for k, v in neutral.items()}, "paare": key_pairs, "hook_paare": key_hooks, "nicht_gepaart": surplus,
    }  # fmt: skip
    return sheet, hook_sheet, key


def _sides(rng: random.Random, left: str, right: str) -> dict[str, str]:
    a_is_left = rng.random() < 0.5
    return {"A": left if a_is_left else right, "B": right if a_is_left else left}


def _key_entry(p: dict, side: dict[str, str], neutral: dict[str, str]) -> dict[str, Any]:
    return {
        "A": side["A"], "B": side["B"], "quelle": p["quelle"], "quelle_neutral": neutral[p["quelle"]],
        "rang_A": p["rang"][side["A"]], "rang_B": p["rang"][side["B"]], "ueberdeckung": p["ueberdeckung"],
        "candidate_A": p[side["A"]]["candidate_id"], "candidate_B": p[side["B"]]["candidate_id"],
    }  # fmt: skip


def _context_range(sents: list[segment.Sentence] | None, a: dict, b: dict, neutral: str) -> dict[str, Any]:
    """Satzbereich plus/minus ``CONTEXT_SENTENCES`` um beide Clips, für beide Seiten gleich."""
    if not sents:
        return {"quelle": neutral, "saetze": None}
    t0 = min(float(s["von_s"]) for c in (a, b) for s in c["segmente"] if s["von_s"] is not None)
    t1 = max(float(s["bis_s"]) for c in (a, b) for s in c["segmente"] if s["bis_s"] is not None)
    inside = [s.idx for s in sents if s.end > t0 and s.start < t1]
    first, last = (min(inside), max(inside)) if inside else (0, len(sents) - 1)
    return {"quelle": neutral, "saetze": [max(0, first - CONTEXT_SENTENCES), min(len(sents) - 1, last + CONTEXT_SENTENCES)]}


def neutral_sentences(words: list[dict]) -> list[segment.Sentence]:
    """Satzliste für den Kontext, unabhängig von der Fassung (Zerlegung vor AP2), für beide Seiten gleich."""
    return segment.sentences_from_words(words)


def sources_document(sources: list[dict], sentences: dict[str, list[segment.Sentence]], key: dict, sheet: dict) -> dict[str, Any]:
    """``quellen.json``: kurze Quellen ganz, lange nur die Kontextbereiche der Paare; Medienverweis."""
    by_neutral = dict(key["quellen"])
    needed: dict[str, set[int]] = {}
    for p in sheet["paare"]:
        rng_ = p["kontext"]["saetze"]
        if rng_:
            needed.setdefault(p["quelle"], set()).update(range(rng_[0], rng_[1] + 1))
    media = {s["name"]: s.get("medien") for s in sources}
    out = {}
    for neutral, name in sorted(by_neutral.items()):
        sents = sentences.get(name) or []
        full = len(sents) <= FULL_TRANSCRIPT_MAX_SENTENCES
        keep = range(len(sents)) if full else sorted(needed.get(neutral, set()))
        out[neutral] = {
            "umfang": "kein Transkript" if not sents else ("ganzes Transkript" if full else f"plus/minus {CONTEXT_SENTENCES} Sätze um die Clips"),
            "medien": media.get(name),
            "saetze": [
                {"nr": s.idx, "von_s": round(s.start, 2), "bis_s": round(s.end, 2), "sprecher": s.speaker, "text": s.text}
                for s in (sents[i] for i in keep)
            ],
        }
    return {"raster": RATING_SHEET, "hinweis": "Kontext für beide Seiten gleich; nr ist die Satznummer, auf die kontext.saetze im Bogen verweist.", "quellen": out}


def _prefix(text: str | None, n: int = 3) -> str:
    return " ".join(_norm(text or "").split()[:n])


def style_leak(runs: dict[str, dict[str, dict]], key: dict) -> dict[str, Any]:
    """Merkmale je Fassung auf dem bewerteten Material und Warnungen, wenn sie die Fassung verraten."""
    left, right = key["links"], key["rechts"]
    clips: dict[str, list[dict]] = {left: [], right: []}
    for entry in key["paare"].values():
        for side in ("A", "B"):
            version = entry[side]
            clip = next(c for c in runs[entry["quelle"]][version]["angeboten"] if c["candidate_id"] == entry[f"candidate_{side}"])
            clips[version].append(clip)
    features: dict[str, dict[str, Any]] = {}
    for version, items in clips.items():
        n = len(items)
        spoken = Counter(_prefix(c["hook"]["gesprochen"]) for c in items)
        overlay = Counter(_prefix(c["hook"]["text"]) for c in items if str(c["hook"]["text"] or "").strip())
        features[version] = {
            "n": n,
            "segmente_mittel": round(statistics.fmean(len(c["segmente"]) for c in items), 2) if n else None,
            "teaser_anteil": round(sum(1 for c in items if any(s["rolle"] == "teaser" for s in c["segmente"])) / n, 3) if n else None,
            "dauer_mittel_s": round(statistics.fmean(c["dauer_s"] for c in items), 2) if n else None,
            "dauer_median_s": round(statistics.median(c["dauer_s"] for c in items), 2) if n else None,
            "ohne_overlay_anteil": round(sum(1 for c in items if not str(c["hook"]["text"] or "").strip()) / n, 3) if n else None,
            "praefix_gesprochen": {p: round(k / n, 3) for p, k in spoken.most_common(3)} if n else {},
            "praefix_overlay": {p: round(k / n, 3) for p, k in overlay.most_common(3)} if n else {},
        }
    warnings: list[str] = []
    a, b = features[left], features[right]
    if a["n"] and b["n"]:
        for field_, title in (("teaser_anteil", "Clip-Bogen, Anteil mit Teaser"), ("ohne_overlay_anteil", "Hook-Bogen, Anteil ohne Overlay-Text")):
            if abs(a[field_] - b[field_]) > LEAK_SHARE_DIFF:
                warnings.append(f"{title}: {left} {_pct(a[field_])}, {right} {_pct(b[field_])}")
        if abs(a["segmente_mittel"] - b["segmente_mittel"]) > LEAK_SEGMENT_DIFF:
            warnings.append(f"Clip-Bogen, Segmente je Clip im Mittel: {left} {_num(a['segmente_mittel'])}, {right} {_num(b['segmente_mittel'])}")
        longer = max(a["dauer_mittel_s"], b["dauer_mittel_s"])
        if longer and abs(a["dauer_mittel_s"] - b["dauer_mittel_s"]) / longer > LEAK_LENGTH_RATIO:
            warnings.append(f"Clip-Bogen, Dauer im Mittel: {left} {_num(a['dauer_mittel_s'], 1)} s, {right} {_num(b['dauer_mittel_s'], 1)} s")
        for field_, title in (("praefix_gesprochen", "Hook-Bogen, gesprochener Hook"), ("praefix_overlay", "Hook-Bogen, Overlay-Text")):
            for mine, other, me, them in ((a, b, left, right), (b, a, right, left)):
                for prefix, share in mine[field_].items():
                    if prefix and share >= LEAK_PREFIX_SHARE and other[field_].get(prefix, 0.0) < LEAK_PREFIX_OTHER:
                        warnings.append(f"{title} beginnt mit „{prefix}“: {me} {_pct(share)}, {them} {_pct(other[field_].get(prefix, 0.0))}")
    return {"merkmale": features, "warnungen": warnings, "wenige_paare": min(a["n"], b["n"]) < 8}


def rubric_template() -> dict[str, Any]:
    return {
        "raster": RATING_SHEET,
        "skala": ANCHORS_TEXT,
        "regeln": [
            "Hohe Werte brauchen einen Bezug zur Quelle; im Zweifel den niedrigeren Anker wählen.",
            "Die Herkunft der Clips ist verborgen; nicht versuchen, sie zu erraten.",
            "Quellentreue mit dem Kontext aus quellen.json prüfen, Natürlichkeit am Audio der Quelle.",
            "Duplikate innerhalb derselben Angabe unter ausgabe beurteilen.",
            "Clips und Hooks getrennt bewerten: der Clip-Bogen zeigt keine Hooks.",
        ],
        "kriterien": CRITERIA,
        "hook_kriterien": HOOK_CRITERIA,
        "praeferenz": list(PREFERENCES),
        "mangel": {"frage": "Was stimmt an dem anderen nicht?", "kategorien": list(FLAW_CATEGORIES),
                   "regel": "Bei A oder B gilt der Mangel für die nicht gewählte Seite, bei beide_unbrauchbar für beide; Freitext unter text."},
        "hinweis": f"Ergebnis {NOTE}.",
    }


def success_criterion(tolerance: float) -> dict[str, Any]:
    """Vorab festgelegt (Plan Abschnitt 8 Punkt 5); steht beim Erzeugen im Schlüssel."""
    return {
        "quelle": "Plan Abschnitt 8 Punkt 5",
        "kriterien": ["quellentreue", "eigenstaendigkeit"],
        "toleranz": tolerance,
        "regel": "Erfüllt, wenn bei gleicher Ausgabemenge das Mittel der neuen Fassung in Quellentreue und Eigenständigkeit nicht unter dem Mittel der alten minus Toleranz liegt; die Verwerfungsquote wird berichtet.",
    }


def generate(sources: list[dict], out_dir: str | Path, seed: int = DEFAULT_SEED, k: int = DEFAULT_K, provider: str = providers_llm.HEURISTIC_PROVIDER,
             brief: dict[str, Any] | None = None, switches: bool = True, overrides: dict[str, bool] | None = None, rule_overrides: dict[str, Any] | None = None,
             pairing: str = "ueberdeckung", tolerance: float = 0.0, llm_factory: LLMFactory | None = None) -> dict[str, Path]:  # fmt: skip
    """Alle Läufe, Bögen, Quellen, Raster und Schlüssel; schreibt die Dateien aus ``FILES`` (ohne Bericht)."""
    if pairing not in PAIRINGS:
        raise SystemExit(f"--paarung {pairing!r}: erlaubt sind {', '.join(PAIRINGS)}.")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    brief = dict(DEFAULT_BRIEF if brief is None else brief)
    variants = [*BASE_VARIANTS, *(switch_variants(overrides, rule_overrides) if switches else [])]
    runs = {src["name"]: {v.name: run_variant(v, src, brief, provider, k, llm_factory) for v in variants} for src in sources}
    sentences = {src["name"]: neutral_sentences(src["words"]) for src in sources}
    sheet, hook_sheet, key = make_pairs(runs, seed, pairing=pairing, sentences=sentences)
    key["erfolgskriterium"] = success_criterion(tolerance)
    run_doc = {
        "hinweis": f"Nicht an die Bewertenden geben (enthält die Versionen). Ergebnis {NOTE}.",
        "provider": provider,
        "k": k,
        "brief": brief,
        "varianten": [{"name": v.name, "fassung": v.version, "gruppe": v.group, "schalter": dict(v.overrides), "regeln": dict(v.rules)} for v in variants],
        "gebaute_schalter": sorted(editorial.V2_IMPLEMENTED_SWITCHES),
        "stil_leck": style_leak(runs, key),
        "quellen": runs,
    }
    docs = {"sheet": sheet, "hook_sheet": hook_sheet, "sources": sources_document(sources, sentences, key, sheet),
            "key": key, "rubric": rubric_template(), "run": run_doc}  # fmt: skip
    paths = {}
    for kind, doc in docs.items():
        paths[kind] = out / FILES[kind]
        paths[kind].write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return paths


# -- Wettbewerbsmodus (--extern) ---------------------------------------------------------------------


def load_clip_folder(folder: str | Path) -> dict[str, list[dict[str, Any]]]:
    """Fertige Clips aus Dateien: je Unterordner ein ``clip.json`` (``start_s``, ``end_s``, ``text``, ``quelle``,
    optional ``rang``) und ein ``.mp4``. Je Quelle nach ``rang``, sonst nach Ordnername sortiert."""
    base = Path(folder)
    if not base.is_dir():
        raise SystemExit(f"Clip-Ordner {folder} gibt es nicht.")
    by_source: dict[str, list[dict[str, Any]]] = {}
    for meta in sorted(base.glob(f"*/{EXTERNAL_CLIP_FILE}")):
        where = f"{meta.parent.name}/{EXTERNAL_CLIP_FILE}"
        doc = json.loads(meta.read_text(encoding="utf-8"))
        for field_ in ("start_s", "end_s", "text", "quelle"):
            if doc.get(field_) in (None, ""):
                raise SystemExit(f"{where}: {field_} fehlt.")
        start, end = float(doc["start_s"]), float(doc["end_s"])
        if end <= start:
            raise SystemExit(f"{where}: end_s muss nach start_s liegen.")
        videos = sorted(meta.parent.glob("*.mp4"))
        if len(videos) != 1:
            raise SystemExit(f"{meta.parent.name}: genau eine .mp4 erwartet, gefunden {len(videos)}.")
        rank = doc.get("rang")
        by_source.setdefault(str(doc["quelle"]), []).append({
            "candidate_id": str(doc.get("id") or meta.parent.name), "start_s": start, "end_s": end, "text": str(doc["text"]),
            "segmente": [{"von_s": start, "bis_s": end, "rolle": "body"}], "dauer_s": round(end - start, 2),
            "video_pfad": str(videos[0]), "rang": rank if isinstance(rank, int) and not isinstance(rank, bool) else None,
        })  # fmt: skip
    if not by_source:
        raise SystemExit(f"Clip-Ordner {folder}: kein Unterordner mit {EXTERNAL_CLIP_FILE}.")
    for clips in by_source.values():
        clips.sort(key=lambda c: (c["rang"] is None, c["rang"] or 0, c["candidate_id"]))
    return by_source


def _extern_side(clip: dict, output_label: str, video: str | None) -> dict[str, Any]:
    side = _clip_side(clip, output_label)
    side["video"] = video
    return side


def make_extern_pairs(own: dict[str, list[dict]], ext: dict[str, list[dict]], seed: int, comparison: str,
                      sentences: dict[str, list[segment.Sentence]] | None = None) -> tuple[dict, dict, list[dict]]:  # fmt: skip
    """Bogen und Schlüssel für chopstr gegen fertige Clips eines anderen Werkzeugs. Gepaart wird je Quelle nach
    größter Überdeckung bei gleicher Ausgabemenge; bei ``schnitt`` nur Paare desselben Moments (Überdeckung
    mindestens ``SAME_MOMENT_MIN``). Videos werden für die Bewertenden neutral benannt."""
    if comparison not in COMPARISONS:
        raise SystemExit(f"--vergleichsart {comparison!r}: erlaubt sind {', '.join(COMPARISONS)}.")
    rng = random.Random(seed)
    names = sorted(set(own) | set(ext))
    neutral = {name: f"Q{i:02d}" for i, name in enumerate(names, start=1)}
    pairs, surplus = [], []
    for name in names:
        a, b = own.get(name, []), ext.get(name, [])
        if comparison == "schnitt":
            matched = [m for m in match_pairs(a, b, "ueberdeckung") if m[2] >= SAME_MOMENT_MIN]
        else:
            n = min(len(a), len(b))
            matched = match_pairs(a[:n], b[:n], "ueberdeckung")
        used = {OWN: {i for i, _j, _o in matched}, EXTERNAL: {j for _i, j, _o in matched}}
        flip = rng.random() < 0.5
        labels = {OWN: f"{neutral[name]}/{2 if flip else 1}", EXTERNAL: f"{neutral[name]}/{1 if flip else 2}"}
        for i, j, ov in matched:
            pairs.append({"quelle": name, "labels": labels, "rang": {OWN: i + 1, EXTERNAL: j + 1}, "ueberdeckung": ov, OWN: a[i], EXTERNAL: b[j]})
        for version, clips in ((OWN, a), (EXTERNAL, b)):
            surplus += [{"quelle": name, "version": version, "rang": r + 1, "candidate_id": c["candidate_id"]} for r, c in enumerate(clips) if r not in used[version]]
    for p in pairs:
        p["kontext"] = _context_range(sentences.get(p["quelle"]) if sentences else None, p[OWN], p[EXTERNAL], neutral[p["quelle"]])
    rng.shuffle(pairs)
    sheet_pairs, key_pairs, media = [], {}, []
    for i, p in enumerate(pairs, start=1):
        pid = f"P{i:03d}"
        side = _sides(rng, OWN, EXTERNAL)
        videos = {}
        for s_ in ("A", "B"):
            src = p[side[s_]].get("video_pfad")
            videos[s_] = f"{MEDIA_DIR}/{pid}_{s_}.mp4" if src else None
            if src:
                media.append({"von": src, "nach": videos[s_]})
        sheet_pairs.append({
            "paar_id": pid, "quelle": neutral[p["quelle"]], "kontext": p["kontext"],
            "A": _extern_side(p[side["A"]], p["labels"][side["A"]], videos["A"]), "B": _extern_side(p[side["B"]], p["labels"][side["B"]], videos["B"]),
            "bewertung": {"A": dict.fromkeys(CRITERIA), "B": dict.fromkeys(CRITERIA), "praeferenz": None, "notiz": "", "mangel": empty_flaw()},
        })  # fmt: skip
        key_pairs[pid] = _key_entry(p, side, neutral)
    sheet = {
        "raster": RATING_SHEET,
        "hinweis": f"Verglichen wird: {COMPARISONS[comparison]}. Je Paar beide Clips nach raster.json bewerten (0 bis 4, leer heißt nicht bewertet), "
                   "dann praeferenz A, B, gleich oder beide_unbrauchbar. Videos liegen unter medien. Unter rater die eigene Bewerter-ID eintragen.",
        "vergleichsart": comparison,
        "rater": None,
        "paare": sheet_pairs,
    }  # fmt: skip
    key = {
        "raster": RATING_SHEET, "modus": "extern", "vergleichsart": comparison, "seed": seed, "links": OWN, "rechts": EXTERNAL,
        "paarung": "ueberdeckung", "quellen": {v: k for k, v in neutral.items()}, "paare": key_pairs, "hook_paare": {}, "nicht_gepaart": surplus,
    }  # fmt: skip
    return sheet, key, media


def generate_extern(own: dict[str, list[dict]], ext: dict[str, list[dict]], out_dir: str | Path, comparison: str, seed: int = DEFAULT_SEED,
                    sources: list[dict] | None = None, own_origin: str = "dateien") -> dict[str, Path]:  # fmt: skip
    """Schreibt Bogen, Quellen, Raster, Schlüssel und Lauf des Wettbewerbsmodus; kopiert die Videos neutral benannt."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    sentences = {src["name"]: neutral_sentences(src["words"]) for src in sources or []}
    sheet, key, media = make_extern_pairs(own, ext, seed, comparison, sentences)
    for m in media:
        target = out / m["nach"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(m["von"], target)
    srcs = sources or [{"name": name, "words": [], "medien": None} for name in sorted(set(own) | set(ext))]
    run_doc = {
        "hinweis": f"Nicht an die Bewertenden geben (enthält die Herkunft). Ergebnis {NOTE}.",
        "modus": "extern", "vergleichsart": comparison, "eigene_herkunft": own_origin,
        "quellen": {name: {OWN: len(own.get(name, [])), EXTERNAL: len(ext.get(name, []))} for name in sorted(set(own) | set(ext))},
        "medien": media,
    }  # fmt: skip
    docs = {"sheet": sheet, "sources": sources_document(srcs, sentences, key, sheet), "key": key, "rubric": rubric_template(), "run": run_doc}
    paths = {}
    for kind, doc in docs.items():
        paths[kind] = out / FILES[kind]
        paths[kind].write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return paths


def own_clips_from_engine(sources: list[dict], provider: str, brief: dict[str, Any] | None, k: int, llm_factory: LLMFactory | None = None) -> dict[str, list[dict]]:
    """chopstr-Seite aus der Engine (Fassung 2, ohne Schalter-Varianten), wenn keine fertigen Clips vorliegen."""
    brief = dict(DEFAULT_BRIEF if brief is None else brief)
    return {src["name"]: run_variant(BASE_VARIANTS[1], src, brief, provider, k, llm_factory)["angeboten"] for src in sources}


# -- Auswertung ------------------------------------------------------------------------------------


def sign_test(wins_a: int, wins_b: int) -> float | None:
    """Zweiseitiger exakter Vorzeichentest (Gleichstände zählen nicht); ``None`` ohne Entscheidung."""
    n = wins_a + wins_b
    if n == 0:
        return None
    tail = sum(math.comb(n, i) for i in range(min(wins_a, wins_b) + 1)) / 2**n
    return round(min(1.0, 2 * tail), 4)


def empty_flaw() -> dict[str, Any]:
    return {"kategorie": None, "text": ""}


def _collect_sheet(sheet: dict, key_pairs: dict, criteria: dict, versions: tuple[str, str], what: str) -> dict[str, Any]:
    """Werte je Fassung und Kriterium sowie Präferenz je Paar aus einem Bogen, mit klaren Fehlermeldungen.

    ``beide_unbrauchbar`` darf ohne Kriterienwerte stehen; A, B und gleich nicht."""
    scores: dict[str, dict[str, list[float]]] = {v: {c: [] for c in criteria} for v in versions}
    prefs: dict[str, str] = {}
    flaws: dict[str, Counter] = {v: Counter() for v in (*versions, NO_VERSION)}
    flaw_texts: list[dict[str, Any]] = []
    rated = 0
    for pair in sheet["paare"]:
        pid = pair.get("paar_id")
        if pid not in key_pairs:
            raise SystemExit(f"{what} {pid}: paar_id fehlt im Schlüssel (schluessel.json passt nicht zum Bogen).")
        mapping = key_pairs[pid]
        rating = pair.get("bewertung") or {}
        any_value = False
        for side in ("A", "B"):
            for crit, value in (rating.get(side) or {}).items():
                if crit not in criteria:
                    raise SystemExit(f"{what} {pid} {side}: unbekanntes Kriterium {crit!r}, erlaubt sind {', '.join(criteria)}.")
                if value is None:
                    continue
                if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 4:
                    raise SystemExit(f"{what} {pid} {side}.{crit}: {value!r} ist kein Wert 0 bis 4.")
                scores[mapping[side]][crit].append(float(value))
                any_value = True
        pref = rating.get("praeferenz")
        if pref not in (*PREFERENCES, None):
            raise SystemExit(f"{what} {pid}: praeferenz {pref!r}, erlaubt sind A, B, gleich, beide_unbrauchbar oder leer.")
        if pref is not None and pref != UNUSABLE and not any_value:
            raise SystemExit(f"{what} {pid}: Präferenz ohne Bewertung der Kriterien; erst die Kriterien bewerten.")
        rated += int(any_value or pref == UNUSABLE)
        prefs[pid] = mapping[pref] if pref in ("A", "B") else (pref or "offen")
        flaw = rating.get("mangel")
        if flaw is not None:
            if not isinstance(flaw, dict) or flaw.get("kategorie") not in (*FLAW_CATEGORIES, None):
                raise SystemExit(f"{what} {pid}: mangel.kategorie, erlaubt sind {', '.join(FLAW_CATEGORIES)} oder leer.")
            if not isinstance(flaw.get("text", ""), str):
                raise SystemExit(f"{what} {pid}: mangel.text muss Text sein.")
            if flaw.get("kategorie"):
                if pref in ("A", "B"):
                    targets = [mapping["B" if pref == "A" else "A"]]
                elif pref == UNUSABLE:
                    targets = list(versions)
                else:
                    targets = [NO_VERSION]
                for t in targets:
                    flaws[t][flaw["kategorie"]] += 1
            if str(flaw.get("text") or "").strip():
                flaw_texts.append({"paar_id": pid, "kategorie": flaw.get("kategorie"), "text": flaw["text"].strip()})
    rater = sheet.get("rater")
    return {"scores": scores, "prefs": prefs, "rated": rated, "paare": len(sheet["paare"]), "rater": None if rater in (None, "") else str(rater),
            "maengel": flaws, "maengel_text": flaw_texts}  # fmt: skip


def cohen_kappa(x: list[str], y: list[str]) -> float | None:
    """Cohen-Kappa zweier Bewerter über dieselben Paare; ``None`` ohne Paare oder wenn beide immer dieselbe eine
    Kategorie wählen (Zufallsübereinstimmung 1, Kappa nicht definiert)."""
    n = len(x)
    if n == 0 or n != len(y):
        return None
    po = sum(1 for a, b in zip(x, y) if a == b) / n
    cx, cy = Counter(x), Counter(y)
    pe = sum(cx[c] / n * cy[c] / n for c in set(cx) | set(cy))
    if pe >= 1.0:
        return None
    return round((po - pe) / (1 - pe), 4)


def agreement(prefs_by_rater: dict[str, dict[str, str]]) -> dict[str, Any] | None:
    """Übereinstimmung der Präferenzen je Bewerterpaar: Anteil gleicher Urteile und Cohen-Kappa, über die Paare,
    die beide entschieden haben (nicht offen); dazu die Mittel über alle Bewerterpaare."""
    if len(prefs_by_rater) < 2:
        return None
    rows = []
    for a, b in itertools.combinations(sorted(prefs_by_rater), 2):
        common = sorted(p for p in prefs_by_rater[a] if p in prefs_by_rater[b] and "offen" not in (prefs_by_rater[a][p], prefs_by_rater[b][p]))
        x, y = [prefs_by_rater[a][p] for p in common], [prefs_by_rater[b][p] for p in common]
        same = sum(1 for u, v in zip(x, y) if u == v)
        rows.append({"bewerter": [a, b], "paare": len(common), "gleich_anteil": round(same / len(common), 4) if common else None, "kappa": cohen_kappa(x, y)})
    shares = [r["gleich_anteil"] for r in rows if r["gleich_anteil"] is not None]
    kappas = [r["kappa"] for r in rows if r["kappa"] is not None]
    return {
        "bewerterpaare": rows,
        "gleich_anteil_mittel": round(statistics.fmean(shares), 4) if shares else None,
        "kappa_mittel": round(statistics.fmean(kappas), 4) if kappas else None,
    }


def _summarize(collected: list[dict[str, Any]], criteria: dict, versions: tuple[str, str], what: str) -> dict[str, Any]:
    """Alle Urteile aller Bögen zusammen; Bewerter-IDs müssen beim Zusammenführen gesetzt und verschieden sein."""
    if len(collected) > 1:
        ids = [c["rater"] for c in collected]
        if None in ids:
            raise SystemExit(f"{what}: beim Zusammenführen braucht jeder Bogen eine Bewerter-ID unter rater.")
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            raise SystemExit(f"{what}: Bewerter-ID {', '.join(dup)} steht in mehreren Bögen.")
    scores: dict[str, dict[str, list[float]]] = {v: {c: [] for c in criteria} for v in versions}
    preference = Counter({v: 0 for v in versions} | {"gleich": 0, UNUSABLE: 0, "offen": 0})
    flaws = {v: dict.fromkeys(FLAW_CATEGORIES, 0) for v in (*versions, NO_VERSION)}
    for c in collected:
        for v in versions:
            for crit in criteria:
                scores[v][crit] += c["scores"][v][crit]
        preference.update(c["prefs"].values())
        for v, counts in c["maengel"].items():
            for cat, n in counts.items():
                flaws[v][cat] += n
    return {
        "mittel": {v: {c: round(statistics.fmean(x), 2) if x else None for c, x in crits.items()} for v, crits in scores.items()},
        "streuung": {v: {c: round(statistics.stdev(x), 2) if len(x) > 1 else None for c, x in crits.items()} for v, crits in scores.items()},
        "anzahl": {v: {c: len(x) for c, x in crits.items()} for v, crits in scores.items()},
        "praeferenz": dict(preference),
        "vorzeichentest_p": sign_test(preference[versions[0]], preference[versions[1]]),
        "paare": max(c["paare"] for c in collected),
        "bewertete_paare": sum(c["rated"] for c in collected),
        "bewerter": [c["rater"] for c in collected],
        "uebereinstimmung": agreement({c["rater"]: c["prefs"] for c in collected}) if len(collected) > 1 else None,
        "maengel": flaws,
        "maengel_text": [{**t, "bewerter": c["rater"]} for c in collected for t in c["maengel_text"]],
    }


def _read_sheet(sheet: dict, key_pairs: dict, criteria: dict, versions: tuple[str, str], what: str) -> dict[str, Any]:
    """Ein Bogen allein (ohne Zusammenführung)."""
    return _summarize([_collect_sheet(sheet, key_pairs, criteria, versions, what)], criteria, versions, what)


def _sheet_kind(sheet: Any, key: dict, name: str) -> str:
    if not isinstance(sheet, dict) or not isinstance(sheet.get("paare"), list) or not sheet["paare"]:
        raise SystemExit(f"{name}: kein Bogen mit Paaren.")
    ids = {p.get("paar_id") for p in sheet["paare"]}
    if ids <= set(key["paare"]):
        return "sheet"
    if ids <= set(key.get("hook_paare") or {}):
        return "hook_sheet"
    raise SystemExit(f"{name}: paar_id passt zu keinem Bogen im Schlüssel (schluessel.json).")


def load_rater_sheets(paths: list[str | Path], key: dict) -> dict[str, list[tuple[str, dict]]]:
    """Bögen mehrerer Bewerter (``--bewerter a.json b.json``), nach Clip- und Hook-Bogen getrennt."""
    out: dict[str, list[tuple[str, dict]]] = {"sheet": [], "hook_sheet": []}
    for p in paths:
        path = Path(p)
        if not path.is_file():
            raise SystemExit(f"{path} fehlt.")
        sheet = json.loads(path.read_text(encoding="utf-8"))
        out[_sheet_kind(sheet, key, path.name)].append((path.name, sheet))
    return out


def competition(clip: dict[str, Any]) -> dict[str, Any]:
    """Gewinnrate von chopstr unter den entschiedenen Urteilen und Anteil „beide unbrauchbar“ unter allen
    abgegebenen Urteilen, gegen die Schwellen aus Abschnitt 1."""
    pref = clip["praeferenz"]
    own, ext, same, unusable = pref.get(OWN, 0), pref.get(EXTERNAL, 0), pref.get("gleich", 0), pref.get(UNUSABLE, 0)
    decided = own + ext
    judged = decided + same + unusable
    win = own / decided if decided else None
    both = unusable / judged if judged else None

    def state(value: float | None, ok: bool) -> str:
        return "nicht messbar" if value is None else ("erreicht" if ok else "nicht erreicht")

    return {
        "urteile": judged, "entschieden": decided, "gewinnrate": win, "beide_unbrauchbar_anteil": both,
        "gewinnrate_urteil": state(win, win is not None and win >= WIN_RATE_MIN),
        "beide_unbrauchbar_urteil": state(both, both is not None and both <= BOTH_UNUSABLE_MAX),
        "schwellen": {"gewinnrate_min": WIN_RATE_MIN, "beide_unbrauchbar_max": BOTH_UNUSABLE_MAX},
        "metriken": {
            "blind_gewinnrate": {"wert": win, "stichprobe": decided, "ursache": None if win is not None else "keine entschiedenen Urteile"},
            "beide_unbrauchbar_anteil": {"wert": both, "stichprobe": judged, "ursache": None if both is not None else "keine abgegebenen Urteile"},
        },
    }  # fmt: skip


def verdict(criterion: dict[str, Any], clip: dict[str, Any], versions: tuple[str, str]) -> dict[str, Any]:
    """Urteil nach dem vorab festgelegten Kriterium: Erfüllt, Nicht erfüllt oder Nicht bewertet."""
    old, new = versions
    rows = []
    for crit in criterion["kriterien"]:
        a, b = clip["mittel"][old][crit], clip["mittel"][new][crit]
        ok = None if a is None or b is None else b >= a - float(criterion["toleranz"])
        rows.append({"kriterium": crit, old: a, new: b, "erfuellt": ok})
    if any(r["erfuellt"] is None for r in rows):
        result = "Nicht bewertet"
    else:
        result = "Erfüllt" if all(r["erfuellt"] for r in rows) else "Nicht erfüllt"
    return {"urteil": result, "zeilen": rows}


def _sheets(out: Path, kind: str, key: dict, raters: dict[str, list[tuple[str, dict]]] | None) -> list[tuple[str, dict]]:
    """Bögen einer Art: die mit ``--bewerter`` übergebenen, sonst die Datei im Ordner (falls vorhanden)."""
    if raters and raters.get(kind):
        return raters[kind]
    path = out / FILES[kind]
    return [(path.name, json.loads(path.read_text(encoding="utf-8")))] if path.is_file() else []


def _evaluate_sheets(sheets: list[tuple[str, dict]], key_pairs: dict, criteria: dict, versions: tuple[str, str], what: str) -> dict[str, Any] | None:
    if not sheets:
        return None
    collected = [_collect_sheet(doc, key_pairs, criteria, versions, f"{what} ({name})" if len(sheets) > 1 else what) for name, doc in sheets]
    return _summarize(collected, criteria, versions, what)


def evaluate(out_dir: str | Path, rater_files: list[str | Path] | None = None) -> dict[str, Any]:
    """Liest Bögen, Schlüssel und Lauf und rechnet alle Kennzahlen des Berichts. ``rater_files`` sind Bögen
    mehrerer Bewerter (Clip- oder Hook-Bogen, an den Paar-IDs erkannt); sie ersetzen die Bögen im Ordner."""
    out = Path(out_dir)

    def load(kind: str) -> dict:
        path = out / FILES[kind]
        if not path.is_file():
            raise SystemExit(f"{path} fehlt.")
        return json.loads(path.read_text(encoding="utf-8"))

    key, run_doc = load("key"), load("run")
    raters = load_rater_sheets(rater_files, key) if rater_files else None
    versions = (key["links"], key["rechts"])
    clip_sheets = _sheets(out, "sheet", key, raters)
    if not clip_sheets:
        raise SystemExit(f"{out / FILES['sheet']} fehlt.")
    clip = _evaluate_sheets(clip_sheets, key["paare"], CRITERIA, versions, "Clip-Bogen")
    if key.get("modus") == "extern":
        comp = competition(clip)
        return {"modus": "extern", "vergleichsart": key["vergleichsart"], "versionen": list(versions), "paarung": key.get("paarung"),
                "clip": clip, "wettbewerb": comp, "metriken": comp["metriken"], "nicht_gepaart": key["nicht_gepaart"],
                "quellen": len(key["quellen"]), "lauf": run_doc}  # fmt: skip
    hook = _evaluate_sheets(_sheets(out, "hook_sheet", key, raters), key.get("hook_paare", {}), HOOK_CRITERIA, versions, "Hook-Bogen")

    per_variant: dict[str, dict[str, Any]] = {}
    for name_src, runs in run_doc["quellen"].items():
        for name, r in runs.items():
            agg = per_variant.setdefault(name, {
                "vorschlaege": 0, "nenner": 0, "verworfen": Counter(), "verworfen_gesamt": 0, "dubletten": Counter(),
                "laufereignisse": Counter(), "angeboten": 0, "modellaufrufe": 0,
                "laufzeit_s": 0.0, "stunden": 0.0, "hooks": Counter(), "faelle": 0, "bestanden": 0,
                "ohne_vorschlag": [], "ohne_kandidat": [],
            })  # fmt: skip
            agg["vorschlaege"] += r["vorschlaege"]
            agg["nenner"] += r["nenner"]
            agg["verworfen_gesamt"] += r["verworfen_gesamt"]
            for reason, v in r["verworfen"].items():
                agg["verworfen"][reason] += v["anzahl"]
            agg["dubletten"].update(r["dubletten"])
            agg["laufereignisse"].update(r["laufereignisse"])
            agg["angeboten"] += len(r["angeboten"])
            agg["modellaufrufe"] += r["modellaufrufe"]
            agg["laufzeit_s"] += r["laufzeit_s"]
            agg["stunden"] += r["quelle_stunden"]
            agg["hooks"].update(r["hooks"])
            if not r["vorschlaege"]:
                agg["ohne_vorschlag"].append(name_src)
            if not r["angeboten"]:
                agg["ohne_kandidat"].append(name_src)
            if r["editorial_v1"] is not None:
                agg["faelle"] += 1
                agg["bestanden"] += int(r["editorial_v1"]["bestanden"])
    for agg in per_variant.values():
        props, hours = agg["nenner"], agg["stunden"]
        agg["verworfen"] = {r: {"anzahl": n, "quote": round(n / props, 4) if props else 0.0} for r, n in sorted(agg["verworfen"].items())}
        agg["dubletten"] = dict(sorted(agg["dubletten"].items()))
        agg["laufereignisse"] = dict(sorted(agg["laufereignisse"].items()))
        agg["hooks"] = dict(agg["hooks"])
        agg["verwerfungsquote"] = round(agg["verworfen_gesamt"] / props, 4) if props else 0.0
        agg["modellaufrufe_je_stunde"] = round(agg["modellaufrufe"] / hours, 1) if hours else None
        agg["laufzeit_s_je_stunde"] = round(agg["laufzeit_s"] / hours, 1) if hours else None
        agg["bestehensquote"] = round(agg["bestanden"] / agg["faelle"], 4) if agg["faelle"] else None
    criterion = key.get("erfolgskriterium") or success_criterion(0.0)
    return {
        "versionen": list(versions),
        "paarung": key.get("paarung", "rang"),
        "clip": clip,
        "hook": hook,
        "erfolgskriterium": criterion,
        "urteil": verdict(criterion, clip, versions),
        "nicht_gepaart": key["nicht_gepaart"],
        "varianten": per_variant,
        "varianten_info": {v["name"]: v for v in run_doc["varianten"]},
        "gebaute_schalter": run_doc["gebaute_schalter"],
        "stil_leck": run_doc.get("stil_leck") or {"merkmale": {}, "warnungen": [], "wenige_paare": True},
        "provider": run_doc["provider"],
        "k": run_doc["k"],
        "quellen": len(run_doc["quellen"]),
        "faelle": {
            name: {v: runs[v]["editorial_v1"] for v in versions}
            for name, runs in run_doc["quellen"].items()
            if any(runs[v]["editorial_v1"] for v in versions)
        },
    }


def _num(value: Any, digits: int = 2) -> str:
    if value is None:
        return "nicht bewertet"
    return f"{value:.{digits}f}".replace(".", ",")


def _pct(value: float | None) -> str:
    return "keine Daten" if value is None else f"{value * 100:.1f} %".replace(".", ",")


def _share(part: int, whole: int) -> str:
    return f"{part} von {whole} ({_pct(part / whole)})" if whole else "keine"


def _rating_table(res: dict, criteria: dict, left: str, right: str) -> list[str]:
    lines = [f"| Kriterium | {left}: Mittel (Streuung, n) | {right}: Mittel (Streuung, n) |", "|---|---|---|"]
    for crit, spec in criteria.items():
        cells = [
            f"{_num(res['mittel'][v][crit])} ({_num(res['streuung'][v][crit]) if res['streuung'][v][crit] is not None else 'keine'}, n = {res['anzahl'][v][crit]})"
            for v in (left, right)
        ]
        lines.append(f"| {spec['titel']} | {cells[0]} | {cells[1]} |")
    pref = res["praeferenz"]
    p = res["vorzeichentest_p"]
    lines += [
        "",
        f"Präferenz: {left} {pref.get(left, 0)}, {right} {pref.get(right, 0)}, gleich {pref.get('gleich', 0)}, "
        f"beide unbrauchbar {pref.get(UNUSABLE, 0)}, offen {pref.get('offen', 0)}. "
        + (f"Vorzeichentest (zweiseitig, ohne Gleichstände): p = {_num(p, 3)}." if p is not None else "Vorzeichentest: keine entschiedenen Paare."),
    ]
    return lines + _flaw_lines(res, left, right) + _agreement_lines(res)


def _flaw_lines(res: dict, left: str, right: str) -> list[str]:
    """Häufigkeit der Mängel je Kategorie und Fassung (Frage „Was stimmt an dem anderen nicht?“)."""
    flaws = res.get("maengel") or {}
    total = sum(n for counts in flaws.values() for n in counts.values())
    if not total:
        return ["", "Mängel (Was stimmt an dem anderen nicht?): keine Angaben."]
    lines = ["", "Mängel (Was stimmt an dem anderen nicht?), gezählt bei der nicht gewählten Fassung, bei beide unbrauchbar bei beiden:", "",
             f"| Kategorie | {left} | {right} | ohne Fassung (gleich gut) |", "|---|---|---|---|"]  # fmt: skip
    for cat in FLAW_CATEGORIES:
        cells = [flaws.get(v, {}).get(cat, 0) for v in (left, right, NO_VERSION)]
        if any(cells):
            lines.append(f"| {cat} | {cells[0]} | {cells[1]} | {cells[2]} |")
    texts = res.get("maengel_text") or []
    if texts:
        lines += ["", f"Freitexte: {len(texts)}, Wortlaut in der JSON-Auswertung unter maengel_text."]
    return lines


def _agreement_lines(res: dict) -> list[str]:
    raters = [r for r in res.get("bewerter") or [] if r]
    if len(res.get("bewerter") or []) < 2:
        return ["", f"Bewerter: {', '.join(raters) or 'ohne ID'} (ein Bogen, keine Übereinstimmung berechenbar)."]
    agr = res["uebereinstimmung"]
    lines = ["", f"Bewerter: {', '.join(raters)}. Die Präferenzen sind über alle Bewerter gezählt; Urteile derselben Paare sind nicht unabhängig, "
                 "der Vorzeichentest ist deshalb nur ein Hinweis.", "",
             "| Bewerterpaar | gemeinsam entschiedene Paare | gleiche Präferenz | Cohen-Kappa |", "|---|---|---|---|"]  # fmt: skip
    for row in agr["bewerterpaare"]:
        kappa = _num(row["kappa"], 2) if row["kappa"] is not None else "nicht berechenbar"
        lines.append(f"| {' und '.join(row['bewerter'])} | {row['paare']} | {_pct(row['gleich_anteil'])} | {kappa} |")
    mean_k = _num(agr["kappa_mittel"], 2) if agr["kappa_mittel"] is not None else "nicht berechenbar"
    lines += ["", f"Mittel: gleiche Präferenz {_pct(agr['gleich_anteil_mittel'])}, Cohen-Kappa {mean_k}."]
    return lines


def report_extern(result: dict[str, Any]) -> str:
    """Bericht des Wettbewerbsmodus: Vergleichsart, Gewinnrate gegen die Schwellen, Raster, Bewerter."""
    left, right = result["versionen"]
    comp = result["wettbewerb"]
    lines = [f"# Blindvergleich {left} gegen {right} (Wettbewerbsmodus)", "",
             f"Vergleichsart (vorab festgelegt): {result['vergleichsart']}, {COMPARISONS[result['vergleichsart']]}.",
             f"Hinweis: {NOTE}. Gleiche Quellen, gleiches Briefing und gleiches Ausgabebudget sind Voraussetzung und nicht vom Werkzeug geprüft.", "",
             "## Ergebnis gegen die Schwellen (Abschnitt 1)", "",
             f"* Urteile: {comp['urteile']}, davon entschieden ({left} oder {right}): {comp['entschieden']}",
             f"* Gewinnrate {left} unter den entschiedenen: {_pct(comp['gewinnrate']) if comp['gewinnrate'] is not None else 'nicht messbar: keine entschiedenen Urteile'}, "
             f"Schwelle mindestens {_pct(WIN_RATE_MIN)}: {comp['gewinnrate_urteil']}",
             f"* Beide unbrauchbar unter allen Urteilen: {_pct(comp['beide_unbrauchbar_anteil']) if comp['beide_unbrauchbar_anteil'] is not None else 'nicht messbar: keine Urteile'}, "
             f"Schwelle höchstens {_pct(BOTH_UNUSABLE_MAX)}: {comp['beide_unbrauchbar_urteil']}",
             f"* Quellen: {result['quellen']}, Clip-Paare: {result['clip']['paare']}, nicht gepaart: {len(result['nicht_gepaart'])}", ""]  # fmt: skip
    for item in result["nicht_gepaart"]:
        lines.append(f"  * {item['quelle']}: {item['version']} Rang {item['rang']}")
    lines += ["## Clips (blind, Anker 0 bis 4)", ""] + _rating_table(result["clip"], CRITERIA, left, right)
    lines += ["", "## Grenzen der Aussage", "",
              "* Drei Bewerter über dieselben Paare liefern abhängige Urteile, keine unabhängigen Paare.",
              "* Die Rechte am Material und an den Clips des Wettbewerbstools sind vorab zu klären.",
              "* Negative und gleiche Ergebnisse werden wie positive berichtet."]  # fmt: skip
    return "\n".join(lines) + "\n"


def report_markdown(result: dict[str, Any]) -> str:
    """Bericht ohne Gedankenstriche; Werte mit Dezimalkomma."""
    if result.get("modus") == "extern":
        return report_extern(result)
    left, right = result["versionen"]
    var = result["varianten"]
    lines = [f"# Blindvergleich {left} gegen {right}", "", f"Hinweis: {NOTE}. Das Material ist klein; Unterschiede sind Beobachtungen, keine Belege.", ""]

    lines += ["## Quellen ohne Vorschlag und ohne Kandidat", "", f"| | {left} | {right} |", "|---|---|---|"]
    for field_, title in (("ohne_vorschlag", "ohne Vorschlag (Stufe 2 liefert nichts)"), ("ohne_kandidat", "ohne angebotenen Kandidaten")):
        cells = [f"{len(var[v][field_])}: {', '.join(var[v][field_]) or 'keine'}" for v in (left, right)]
        lines.append(f"| {title} | {cells[0]} | {cells[1]} |")

    crit = result["erfolgskriterium"]
    lines += ["", "## Erfolgskriterium (vorab festgelegt)", "", f"{crit['regel']} Toleranz: {_num(float(crit['toleranz']))}. Quelle: {crit['quelle']}.", ""]
    for row in result["urteil"]["zeilen"]:
        state = "nicht bewertet" if row["erfuellt"] is None else ("erfüllt" if row["erfuellt"] else "nicht erfüllt")
        lines.append(f"* {CRITERIA[row['kriterium']]['titel']}: {left} {_num(row[left])}, {right} {_num(row[right])}, {state}")
    lines += [
        f"* Verwerfungsquote: {left} {_pct(var[left]['verwerfungsquote'])}, {right} {_pct(var[right]['verwerfungsquote'])}",
        "",
        f"**Urteil: {result['urteil']['urteil']}**",
        "",
        "## Material und Ausgabemenge",
        "",
        f"* Quellen: {result['quellen']}, Provider: {result['provider']}, Obergrenze k: {result['k']}, Paarung: {result['paarung']}",
        f"* Clip-Paare bei gleicher Ausgabemenge: {result['clip']['paare']}, davon bewertet: {result['clip']['bewertete_paare']}",
        f"* Nicht gepaart (Überhang einer Version): {len(result['nicht_gepaart'])}",
    ]  # fmt: skip
    for item in result["nicht_gepaart"]:
        lines.append(f"  * {item['quelle']}: {item['version']} Rang {item['rang']}")

    leak = result["stil_leck"]
    lines += ["", "## Stil-Leck-Prüfung", "", "Merkmale der bewerteten Clips und Hooks je Fassung. Weichen sie deutlich ab, können Bewertende die Fassung erkennen.", "",
              f"| Merkmal | {left} | {right} |", "|---|---|---|"]  # fmt: skip
    feats = leak["merkmale"]
    if feats:
        for field_, title, fmt in (
            ("n", "bewertete Clips", str),
            ("segmente_mittel", "Segmente je Clip (Mittel)", _num),
            ("teaser_anteil", "Anteil mit Teaser", _pct),
            ("dauer_mittel_s", "Dauer Mittel (s)", lambda x: _num(x, 1)),
            ("dauer_median_s", "Dauer Median (s)", lambda x: _num(x, 1)),
            ("ohne_overlay_anteil", "Hooks ohne Overlay-Text", _pct),
        ):
            lines.append(f"| {title} | {fmt(feats[left][field_]) if feats[left][field_] is not None else 'keine'} | {fmt(feats[right][field_]) if feats[right][field_] is not None else 'keine'} |")
        for field_, title in (("praefix_gesprochen", "häufigster Anfang gesprochener Hook"), ("praefix_overlay", "häufigster Anfang Overlay-Text")):
            cells = []
            for v in (left, right):
                top = next(iter(feats[v][field_].items()), None)
                cells.append(f"„{top[0]}“ {_pct(top[1])}" if top else "keiner")
            lines.append(f"| {title} | {cells[0]} | {cells[1]} |")
    lines.append("")
    if leak["warnungen"]:
        lines += ["**Warnung: Die Verblindung ist gefährdet.**", ""] + [f"* {w}" for w in leak["warnungen"]]
        if any(w.startswith("Hook-Bogen") for w in leak["warnungen"]):
            lines += ["", "Im Hook-Bogen ist der Stil Teil des Bewerteten; erkennbare Fassungen machen die Hook-Präferenz unsicher. "
                          "Der Clip-Bogen zeigt keine Hooks und ist davon nicht betroffen."]  # fmt: skip
    else:
        lines.append("Keine deutliche Abweichung gefunden.")
    if leak.get("wenige_paare"):
        lines += ["", "Weniger als acht Paare je Fassung: die Prüfung ist nur ein grober Hinweis."]

    lines += ["", "## Clips (blind, ohne Hook, Anker 0 bis 4)", ""] + _rating_table(result["clip"], CRITERIA, left, right)
    lines += ["", "## Hooks (eigener Bogen, Anker 0 bis 4)", ""]
    lines += _rating_table(result["hook"], HOOK_CRITERIA, left, right) if result["hook"] else ["Kein Hook-Bogen vorhanden."]

    reasons = sorted({r for v in (left, right) for r in var[v]["verworfen"]})
    lines += ["", "## Verwerfungsquote je Grund und Version", "",
              "Nenner: alle Vorschläge der Stufe 2 (Modell beziehungsweise Suche) mit Ergebnis, also verworfen oder angeboten, ohne Dubletten. "
              "Dubletten und Laufereignisse stehen getrennt darunter und zählen nicht in die Quote.", "",
              f"| Grund | {left} | {right} |", "|---|---|---|"]  # fmt: skip
    for reason in reasons:
        cells = []
        for v in (left, right):
            entry = var[v]["verworfen"].get(reason)
            cells.append(f"{entry['anzahl']} ({_pct(entry['quote'])})" if entry else "0")
        lines.append(f"| {reason_label(reason)} | {cells[0]} | {cells[1]} |")
    lines.append(f"| gesamt | {var[left]['verworfen_gesamt']} von {var[left]['nenner']} ({_pct(var[left]['verwerfungsquote'])}) "
                 f"| {var[right]['verworfen_gesamt']} von {var[right]['nenner']} ({_pct(var[right]['verwerfungsquote'])}) |")  # fmt: skip
    lines += ["", f"Zum Vergleich `DetectReport.proposals`: {left} {var[left]['vorschlaege']}, {right} {var[right]['vorschlaege']}.", "",
              "### Dubletten (nicht in der Quote)", "", f"| Art | {left} | {right} |", "|---|---|---|"]  # fmt: skip
    dup_codes = sorted({c for v in (left, right) for c in var[v]["dubletten"]})
    for code in dup_codes:
        lines.append(f"| {reason_label(code)} | {var[left]['dubletten'].get(code, 0)} | {var[right]['dubletten'].get(code, 0)} |")
    lines.append(f"| gesamt | {sum(var[left]['dubletten'].values())} | {sum(var[right]['dubletten'].values())} |")
    event_codes = sorted({c for v in (left, right) for c in var[v]["laufereignisse"]})
    if event_codes:
        lines += ["", "### Laufereignisse (betreffen keinen einzelnen Vorschlag)", "", f"| Ereignis | {left} | {right} |", "|---|---|---|"]
        for code in event_codes:
            lines.append(f"| {reason_label(code)} | {var[left]['laufereignisse'].get(code, 0)} | {var[right]['laufereignisse'].get(code, 0)} |")

    lines += ["", "## Modellaufrufe und Laufzeit je Quellstunde", "", "Gezählt am Provider (jeder strukturierte Aufruf, auch Hooks).", "",
              f"| Kennzahl | {left} | {right} |", "|---|---|---|",
              f"| Modellaufrufe gesamt | {var[left]['modellaufrufe']} | {var[right]['modellaufrufe']} |",
              f"| Modellaufrufe je Quellstunde | {_num(var[left]['modellaufrufe_je_stunde'], 1)} | {_num(var[right]['modellaufrufe_je_stunde'], 1)} |",
              f"| Laufzeit je Quellstunde (s) | {_num(var[left]['laufzeit_s_je_stunde'], 1)} | {_num(var[right]['laufzeit_s_je_stunde'], 1)} |",
              f"| angebotene Kandidaten | {var[left]['angeboten']} | {var[right]['angeboten']} |", ""]  # fmt: skip

    lines += ["## editorial_v1 Bestehensquote", "",
              f"* {left}: {var[left]['bestanden']} von {var[left]['faelle']} ({_pct(var[left]['bestehensquote'])})",
              f"* {right}: {var[right]['bestanden']} von {var[right]['faelle']} ({_pct(var[right]['bestehensquote'])})", "",
              f"| Fall | {left} | {right} |", "|---|---|---|"]  # fmt: skip
    for name, per_version in sorted(result["faelle"].items()):
        cells = []
        for v in (left, right):
            res = per_version.get(v)
            cells.append("keine Daten" if res is None else ("bestanden" if res["bestanden"] else "nicht bestanden: " + _short(res["gruende"][0])))
        lines.append(f"| {name.removeprefix('fall_')} | {cells[0]} | {cells[1]} |")

    built = set(result["gebaute_schalter"])
    switch_rows = [n for n, info in result["varianten_info"].items() if info["gruppe"]]
    if switch_rows:
        lines += ["", "## Einzelne Schalter (Auswahl, Hooks, Kürzung, Kombination)", "",
                  "Fassung 2, Basis: alle Gruppenschalter aus. Hook-Kennzahlen je angebotenem Kandidaten.", "",
                  "| Variante | Schalter an (gebaut); Regeln | Kandidaten | Verwerfungsquote | Modellaufrufe je Quellstunde | Hooks native | ohne Overlay | ganzer Satz | mit Claim-Befund | editorial_v1 |",
                  "|---|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
        for name in switch_rows:
            info, agg = result["varianten_info"][name], var[name]
            on = [s for s, value in info["schalter"].items() if value]
            title = GROUP_TITLES.get(info["gruppe"], str(info["gruppe"]))
            switches = ", ".join(f"{s} ({'ja' if s in built else 'nein'})" for s in on) or "keiner"
            rules = info.get("regeln") or {}
            if rules:
                switches += "; Regel " + ", ".join(f"{p}={str(v).lower()}" for p, v in rules.items())
            h = agg["hooks"]
            total = int(h.get("gesamt", 0))
            lines.append(
                f"| {title} | {switches} | {agg['angeboten']} | {_pct(agg['verwerfungsquote'])} | {_num(agg['modellaufrufe_je_stunde'], 1)} "
                f"| {_share(int(h.get('native', 0)), total)} | {_share(int(h.get('ohne_overlay', 0)), total)} | {_share(int(h.get('ganzer_satz', 0)), total)} "
                f"| {_share(int(h.get('mit_befund', 0)), total)} | {agg['bestanden']} von {agg['faelle']} |"
            )  # fmt: skip

    lines += ["", "## Grenzen der Aussage", "",
              f"* {NOTE[0].upper() + NOTE[1:]}. Organische Veröffentlichungen sind kein A/B-Test.",
              "* Streuung und Vorzeichentest beschreiben nur dieses Material; bei wenigen Paaren ist jeder Unterschied unsicher.",
              "* Mit dem Heuristik-Provider sind alle Werte unkalibriert; belastbar wird der Vergleich erst mit einem echten Provider und echtem Material.",
              "* Laufzeit hängt von der Maschine ab; nur innerhalb eines Laufs vergleichbar.",
              "* Negative und gleiche Ergebnisse werden wie positive berichtet."]  # fmt: skip
    return "\n".join(lines) + "\n"


def _short(text: str, limit: int = 120) -> str:
    text = " ".join(str(text).replace("|", "/").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Blindvergleich Policy-Fassung 1 gegen 2 (AP11).")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--out", help="Ordner für Bögen, Quellen, Raster, Schlüssel und Lauf")
    mode.add_argument("--auswerten", help="Ordner eines früheren Laufs mit ausgefüllten Bögen")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"Zufallsseed für Reihenfolge und A/B, Standard {DEFAULT_SEED}")
    ap.add_argument("--k", type=int, default=DEFAULT_K, help=f"Obergrenze der Kandidaten je Quelle und Version, Standard {DEFAULT_K}")
    ap.add_argument("--paarung", choices=PAIRINGS, default="ueberdeckung", help="Paare nach größter Überdeckung (Standard) oder nach Rang")
    ap.add_argument("--toleranz", type=float, default=0.0, help="Toleranz des Erfolgskriteriums in Ankerpunkten, Standard 0")
    ap.add_argument("--provider", default=providers_llm.HEURISTIC_PROVIDER, help="LLM-Provider für beide Versionen, Standard local-heuristic")
    ap.add_argument("--transkripte", help="Ordner mit Transkript-JSON (Wortliste oder {\"words\": [...], \"medien\": ...})")
    ap.add_argument("--quelle", action="append", default=[], help="UUID einer Quelle aus der Datenbank (braucht DATABASE_URL), mehrfach")
    ap.add_argument("--ohne-fixtures", action="store_true", help="Demo-Skript und editorial_v1 nicht verwenden")
    ap.add_argument("--ohne-schalter", action="store_true", help="keine Schalter-Varianten rechnen")
    ap.add_argument("--override", action="append", default=[], help=f"zusätzliche Variante: Schalter pfad=true|false oder Regel {RULE_PREFIX}pfad=wert (Whitelist), mehrfach; auch {OVERRIDES_ENV}")
    ap.add_argument("--brief", help="Brief als JSON-Datei (gleich für beide Versionen, platform steuert die Hooks)")
    ap.add_argument("--bericht", help="Pfad des Berichts, Standard <ordner>/bericht.md")
    ap.add_argument("--bewerter", nargs="+", help="mit --auswerten: Bögen mehrerer Bewerter zusammenführen (je mit rater)")
    ap.add_argument("--json", dest="json_out", help="mit --auswerten: Ergebnis als JSON (mit metriken für eval.baseline)")
    ap.add_argument("--extern", help="Wettbewerbsmodus: Ordner mit fertigen Clips des anderen Werkzeugs (je Unterordner clip.json und .mp4)")
    ap.add_argument("--eigene", help="Wettbewerbsmodus: fertige chopstr-Clips im selben Format statt eines Engine-Laufs")
    ap.add_argument("--vergleichsart", choices=tuple(COMPARISONS), help="Wettbewerbsmodus: vorab festgelegt, was verglichen wird")
    args = ap.parse_args(argv)

    if args.auswerten:
        result = evaluate(args.auswerten, args.bewerter)
        text = report_markdown(result)
        target = Path(args.bericht or Path(args.auswerten) / FILES["report"])
        target.write_text(text, encoding="utf-8")
        print(text)
        print(f"Bericht geschrieben: {target}")
        if args.json_out:
            result.setdefault("metriken", {})
            Path(args.json_out).write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return
    if args.bewerter:
        raise SystemExit("--bewerter gehört zu --auswerten.")

    if args.extern:
        if not args.vergleichsart:
            raise SystemExit("--extern braucht --vergleichsart (voller_output, momentwahl oder schnitt), vorab festgelegt.")
        ext = load_clip_folder(args.extern)
        sources = transcript_sources(args.transkripte) if args.transkripte else []
        sources += database_sources(args.quelle)
        if args.eigene:
            own, origin = load_clip_folder(args.eigene), "dateien"
        else:
            if not sources:
                raise SystemExit("Ohne --eigene braucht der Wettbewerbsmodus Quellen für die Engine (--transkripte oder --quelle).")
            brief = json.loads(Path(args.brief).read_text(encoding="utf-8")) if args.brief else None
            own, origin = own_clips_from_engine(sources, args.provider, brief, args.k), "engine"
        paths = generate_extern(own, ext, args.out, args.vergleichsart, seed=args.seed, sources=sources, own_origin=origin)
        print(f"Wettbewerbsmodus ({args.vergleichsart}): {len(set(own) | set(ext))} Quellen.")
        print(f"An die Bewertenden: {paths['sheet']}, {paths['sources']}, {paths['rubric']} und der Ordner {Path(args.out) / MEDIA_DIR}")
        print(f"Nicht weitergeben: {paths['key']}, {paths['run']}")
        return

    sources = [] if args.ohne_fixtures else fixture_sources()
    if args.transkripte:
        sources += transcript_sources(args.transkripte)
    sources += database_sources(args.quelle)
    if not sources:
        raise SystemExit("Keine Quellen: Fixtures, --transkripte oder --quelle angeben.")
    brief = json.loads(Path(args.brief).read_text(encoding="utf-8")) if args.brief else None
    overrides, rule_overrides = parse_overrides(args.override, os.environ.get(OVERRIDES_ENV))
    paths = generate(sources, args.out, seed=args.seed, k=args.k, provider=args.provider, brief=brief,
                     switches=not args.ohne_schalter, overrides=overrides, rule_overrides=rule_overrides, pairing=args.paarung, tolerance=args.toleranz)  # fmt: skip
    print(f"{len(sources)} Quellen gerechnet.")
    print(f"An die Bewertenden: {paths['sheet']}, {paths['hook_sheet']}, {paths['sources']}, {paths['rubric']}")
    print(f"Nicht weitergeben: {paths['key']}, {paths['run']}")
    print(f"Nach dem Bewerten: python -m eval.blind_compare --auswerten {args.out}")


if __name__ == "__main__":
    main(sys.argv[1:])
