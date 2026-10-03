"""Blindvergleich alt gegen neu (AP11): Policy-Fassung 1 gegen 2 auf demselben Material.

    .venv/bin/python -m eval.blind_compare --out blind/            # Läufe, Paare, Raster, Schlüssel
    .venv/bin/python -m eval.blind_compare --auswerten blind/      # Auswertung nach dem Bewerten

Ablauf und Raster stehen in ``eval/README.md``. Kurz:

1. ``story_engine.run`` läuft je Quelle einmal mit ``CHOPSTR_POLICY_VERSION=1`` und einmal mit ``2``,
   mit demselben Provider (Standard ``local-heuristic``), demselben Brief und derselben Obergrenze
   ``--k``. Je Quelle wird die Ausgabemenge auf die kleinere der beiden gekürzt (Top-k nach ``total``),
   damit Qualität bei gleicher Menge verglichen wird; der Überhang steht im Schlüssel.
2. Paare: Rang i von v1 gegen Rang i von v2. Reihenfolge der Paare und Seite A oder B je Paar sind
   zufällig mit festem Seed (``--seed``). ``bewertung.json`` enthält keine Versionskennung, die
   Zuordnung steht getrennt in ``schluessel.json``.
3. Bewertet wird mit dem Raster ``raster.json`` (Anker 0 bis 4, Master-Prompt Abschnitte 19 und 26).
4. ``--auswerten`` liest die ausgefüllte Bewertung, den Schlüssel und ``lauf.json`` und schreibt
   ``bericht.md``: Mittel je Kriterium, Präferenz, Verwerfungsquote je Grund und Version, Modellaufrufe
   und Laufzeit je Quellstunde (am Provider gezählt), editorial_v1-Bestehensquote je Version und,
   getrennt, die einzelnen Schalter (Auswahl, Hooks, Kürzung, Kombination).

Die Schalter-Varianten entstehen über eine Kopie der Richtlinie mit geänderten Schaltern in
``implementation`` (``EDITORIAL_DIR`` zeigt für die Dauer des Laufs darauf). Eigene Overrides:
``--override pfad=true`` (mehrfach) oder ``CHOPSTR_BLIND_OVERRIDES="pfad=true,pfad=false"``.

Das Ergebnis ist beobachtend, kein A/B-Test, kein Viralitätsmaß.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import dataclasses
import json
import os
import random
import shutil
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from chopstr_worker import config, editorial, providers_llm
from chopstr_worker.pipeline import clip_candidate, copy_de, copy_engine, story_engine
from chopstr_worker.providers_llm import LLM
from chopstr_worker.residency import Tenant

RATING_SHEET = "blind_compare_raster_v1"
DEFAULT_SEED = 1729
DEFAULT_K = 5
DEFAULT_BRIEF: dict[str, Any] = {"platform": "linkedin"}
OVERRIDES_ENV = "CHOPSTR_BLIND_OVERRIDES"
NOTE = "beobachtend, kein A/B-Test, kein Viralitätsmaß"
PREFERENCES = ("A", "B", "gleich")
FILES = {"sheet": "bewertung.json", "key": "schluessel.json", "rubric": "raster.json", "run": "lauf.json", "report": "bericht.md"}

# Raster (Master-Prompt 19: Anker 0 bis 4; 26: die acht Kriterien des Blindvergleichs). Höher ist
# immer besser, auch bei Duplikaten und Nacharbeit.
CRITERIA: dict[str, dict[str, Any]] = {
    "quellentreue": {
        "titel": "Quellentreue",
        "frage": "Gibt der Clip wieder, was die Quelle sagt, ohne Sinnumkehr, ohne verlorene Bedingung oder Einschränkung, ohne falsche Zuordnung?",
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
        "frage": "Klingt der Schnitt natürlich (Sprachfluss, Atem, Pausen, keine hörbaren Sprünge)? Am Audio der Quelle mit den angegebenen Zeiten prüfen.",
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
        "frage": "Wie viel müsste die Redaktion ändern, bevor sie den Clip veröffentlicht?",
        "anker": {
            "0": "unbrauchbar, müsste neu geschnitten werden",
            "1": "viel Nacharbeit (Grenzen, Kontext, Hook)",
            "2": "mittlere Nacharbeit",
            "3": "kleine Korrektur",
            "4": "ohne Änderung veröffentlichbar",
        },
    },
}

# Gruppen der Schalter in ``implementation`` (Master-Prompt 26: Auswahl, Hooks, Kürzung, Kombination).
SWITCH_GROUPS: dict[str, tuple[str, ...]] = {
    "auswahl": ("gates.discard_hard", "search.payoff_first"),
    "hooks": ("hook.native_spoken",),
    "kuerzung": ("trim.enabled",),
}
GROUP_TITLES = {"auswahl": "Auswahl", "hooks": "Hooks", "kuerzung": "Kürzung", "kombination": "Kombination"}


@dataclasses.dataclass(frozen=True)
class Variant:
    """Ein Lauf: Richtlinien-Fassung plus Schalter-Overrides (Pfad in ``implementation`` zu bool)."""

    name: str
    version: int
    overrides: tuple[tuple[str, bool], ...] = ()
    group: str | None = None


BASE_VARIANTS = (Variant("v1", 1), Variant("v2", 2))


def switch_variants(extra: dict[str, bool] | None = None) -> list[Variant]:
    """Basis (alle Gruppenschalter aus), je Gruppe einzeln an, Kombination (alle Gruppen an)."""
    all_switches = [s for group in SWITCH_GROUPS.values() for s in group]
    base = {s: False for s in all_switches}
    out = [Variant("v2_basis", 2, tuple(sorted(base.items())), "basis")]
    for group, switches in SWITCH_GROUPS.items():
        out.append(Variant(f"v2_{group}", 2, tuple(sorted({**base, **dict.fromkeys(switches, True)}.items())), group))
    out.append(Variant("v2_kombination", 2, tuple(sorted(dict.fromkeys(all_switches, True).items())), "kombination"))
    if extra:
        out.append(Variant("v2_override", 2, tuple(sorted(extra.items())), "override"))
    return out


def parse_overrides(items: list[str] | None, env: str | None = None) -> dict[str, bool]:
    """``pfad=true`` oder ``pfad=false``; Pfade müssen Schalter aus ``editorial.V2_SWITCHES`` sein."""
    raw = [*(env or "").split(","), *(items or [])]
    out: dict[str, bool] = {}
    for item in (x.strip() for x in raw):
        if not item:
            continue
        path, _, value = item.partition("=")
        if path not in editorial.V2_SWITCHES or value.lower() not in ("true", "false"):
            raise SystemExit(f"Override {item!r} ungültig: erlaubt sind {', '.join(editorial.V2_SWITCHES)} mit =true oder =false.")
        out[path] = value.lower() == "true"
    return out


@contextlib.contextmanager
def policy_variant(variant: Variant) -> Iterator[editorial.Policy]:
    """Setzt Fassung und Overrides für die Dauer des Blocks und stellt die Umgebung danach wieder her."""
    saved = {k: os.environ.get(k) for k in (editorial.POLICY_VERSION_ENV, "EDITORIAL_DIR")}
    tmp: str | None = None
    try:
        os.environ[editorial.POLICY_VERSION_ENV] = str(variant.version)
        if variant.overrides:
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
    return [{**w, "prob": w["asr_confidence"]} if "prob" not in w and "asr_confidence" in w else dict(w) for w in words]


def fixture_sources() -> list[dict[str, Any]]:
    """Demo-Skript (``transcript_fixtures.DEMO_SCRIPT``) und die 14 Fälle aus ``editorial_v1``."""
    from tests.editorial_v1 import harness
    from tests.transcript_fixtures import demo_words

    out = [{"name": "demo_script", "words": demo_words(), "case": None}]
    for case in harness.load_cases():
        out.append({"name": f"fall_{case['id']}", "words": _with_prob(case["words"]), "case": case})
    return out


def transcript_sources(folder: str) -> list[dict[str, Any]]:
    """``*.json`` aus einem Ordner: eine Wortliste oder ``{"words": [...]}``."""
    path = Path(folder)
    if not path.is_dir():
        raise SystemExit(f"Transkript-Ordner {folder} gibt es nicht.")
    out = []
    for file in sorted(path.glob("*.json")):
        data = json.loads(file.read_text(encoding="utf-8"))
        words = data if isinstance(data, list) else data.get("words")
        if not isinstance(words, list) or not words:
            raise SystemExit(f"{file.name}: keine Wortliste gefunden.")
        out.append({"name": file.stem, "words": _with_prob(words), "case": None})
    return out


def database_sources(source_ids: list[str]) -> list[dict[str, Any]]:
    """Neueste Transkriptversion je Quelle aus Postgres (nur mit ``DATABASE_URL``)."""
    if not source_ids:
        return []
    if not os.environ.get("DATABASE_URL"):
        raise SystemExit("--quelle braucht DATABASE_URL. Vorher: source scripts/local_env.sh")
    from chopstr_worker import db
    from eval import clip_eval

    conn = db.connect()
    try:
        return [{"name": f"quelle_{sid}", "words": clip_eval.load_words(conn, sid), "case": None} for sid in source_ids]
    finally:
        conn.close()


def source_hours(words: list[dict]) -> float:
    if not words:
        return 0.0
    return (max(float(w["end"]) for w in words) - min(float(w["start"]) for w in words)) / 3600.0


# -- Läufe -----------------------------------------------------------------------------------------


def rejection_rates(discarded: list[dict], proposals: int) -> dict[str, dict[str, float | int]]:
    """Verwerfungen je Grund: Anzahl und Anteil an allen Vorschlägen (``DetectReport.proposals``)."""
    counts = Counter(str(d.get("reason") or "unbekannt") for d in discarded)
    return {reason: {"anzahl": n, "quote": round(n / proposals, 4) if proposals else 0.0} for reason, n in sorted(counts.items())}


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
            lambda cc=cc: harness.assert_clip_respects_case(case, cc["segments"]),
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


def _hook(llm: LLM, cc: dict, words: list[dict], settings: config.Settings) -> dict[str, Any]:
    clip_words = [words[i] for s in cc["segments"] for i in s["word_ids"]]
    text = " ".join(s["verbatim_text"] for s in cc["segments"])
    res = copy_engine.write_copy(llm, text, copy_de.BrandProfile(), platforms=("linkedin",), s=settings, words=clip_words)
    return {"gesprochen": res.spoken_hook, "text": res.onscreen_hook, "befunde": len(res.claim_issues)}


def run_variant(variant: Variant, source: dict[str, Any], brief: dict[str, Any], provider: str, k: int) -> dict[str, Any]:
    """Ein Lauf von ``story_engine.run`` plus Hooks je angebotenem Kandidaten, mit gezählten Modellaufrufen."""
    calls: list[dict] = []
    settings = dataclasses.replace(config.settings(), languagetool_url="")
    with policy_variant(variant) as pol:
        llm = LLM(Tenant(id="blind-compare", tier="standard"), provider=provider, s=settings, cost_sink=calls.append)
        words = copy.deepcopy(source["words"])
        started = time.perf_counter()
        report = story_engine.run(words, dict(brief), {}, None, llm, max_candidates=k)
        ccs = [c.to_dict() for c in clip_candidate.from_report(report, words, pol, source={"id": source["name"]}, brief=brief)]
        offered = [c for c in ccs if c["decision"] == "accept"]
        hooks = {c["candidate_id"]: _hook(llm, c, words, settings) for c in offered}
        runtime = time.perf_counter() - started
    rows = {c["candidate_id"]: r.to_row() for c, r in zip(ccs, [*report.candidates, *report.verworfen])}
    ranked = sorted(offered, key=lambda c: (-float(rows[c["candidate_id"]]["total"]), float(rows[c["candidate_id"]]["start_s"])))
    return {
        "variante": variant.name,
        "fassung": variant.version,
        "schalter": dict(variant.overrides),
        "quelle": source["name"],
        "quelle_stunden": source_hours(source["words"]),
        "vorschlaege": report.proposals,
        "verworfen": rejection_rates(report.discarded, report.proposals),
        "verworfen_gesamt": len(report.discarded),
        "modellaufrufe": len(calls),
        "modellaufrufe_je_prompt": dict(sorted(Counter(str(c.get("prompt")) for c in calls).items())),
        "laufzeit_s": round(runtime, 4),
        "hooks_mit_befund": sum(1 for h in hooks.values() if h["befunde"]),
        "editorial_v1": case_result(source["case"], offered, rows, hooks) if source.get("case") else None,
        "angeboten": [
            {
                "candidate_id": c["candidate_id"],
                "total": rows[c["candidate_id"]]["total"],
                "segmente": [{"von_s": s["source_in"], "bis_s": s["source_out"], "rolle": s["editorial_role"]} for s in c["segments"]],
                "text": " ".join(s["verbatim_text"] for s in c["segments"]),
                "dauer_s": round(sum((s["output_out"] or 0) - (s["output_in"] or 0) for s in c["segments"]), 2),
                "hook": hooks[c["candidate_id"]],
            }
            for c in ranked
        ],
        "clip_candidates": ccs,
    }


# -- Paare -----------------------------------------------------------------------------------------


def _side(clip: dict[str, Any], output_label: str) -> dict[str, Any]:
    """Was die Bewertenden sehen: Text, Zeiten, Hook. Keine Version, kein Score, keine Begründung."""
    return {
        "ausgabe": output_label,
        "text": clip["text"],
        "segmente": clip["segmente"],
        "dauer_s": clip["dauer_s"],
        "hook_gesprochen": clip["hook"]["gesprochen"],
        "hook_text": clip["hook"]["text"],
    }


def make_pairs(runs: dict[str, dict[str, dict]], seed: int, left: str = "v1", right: str = "v2") -> tuple[dict, dict]:
    """Bewertungsbogen und Schlüssel für ``left`` gegen ``right`` bei gleicher Ausgabemenge je Quelle."""
    rng = random.Random(seed)
    pairs, surplus, labels = [], [], {}
    for name in sorted(runs):
        a, b = runs[name][left]["angeboten"], runs[name][right]["angeboten"]
        n = min(len(a), len(b))
        flip = rng.random() < 0.5
        labels[name] = {left: f"{name}/{2 if flip else 1}", right: f"{name}/{1 if flip else 2}"}
        for rank in range(n):
            pairs.append({"quelle": name, "rang": rank + 1, left: a[rank], right: b[rank]})
        for version, clips in ((left, a), (right, b)):
            surplus += [{"quelle": name, "version": version, "rang": r + 1, "candidate_id": c["candidate_id"]} for r, c in enumerate(clips[n:], start=n)]
    rng.shuffle(pairs)
    sheet_pairs, key_pairs = [], {}
    for i, p in enumerate(pairs, start=1):
        pid = f"P{i:03d}"
        a_is_left = rng.random() < 0.5
        side = {"A": left if a_is_left else right, "B": right if a_is_left else left}
        sheet_pairs.append({
            "paar_id": pid,
            "quelle": p["quelle"],
            "A": _side(p[side["A"]], labels[p["quelle"]][side["A"]]),
            "B": _side(p[side["B"]], labels[p["quelle"]][side["B"]]),
            "bewertung": {"A": dict.fromkeys(CRITERIA), "B": dict.fromkeys(CRITERIA), "praeferenz": None, "notiz": ""},
        })  # fmt: skip
        key_pairs[pid] = {
            "A": side["A"], "B": side["B"], "quelle": p["quelle"], "rang": p["rang"],
            "candidate_A": p[side["A"]]["candidate_id"], "candidate_B": p[side["B"]]["candidate_id"],
        }  # fmt: skip
    sheet = {
        "raster": RATING_SHEET,
        "hinweis": "Je Paar beide Seiten nach raster.json bewerten (0 bis 4, leer heißt nicht bewertet), dann praeferenz: A, B oder gleich. Die Herkunft der Clips ist verborgen.",
        "paare": sheet_pairs,
    }
    key = {"raster": RATING_SHEET, "seed": seed, "links": left, "rechts": right, "paare": key_pairs, "nicht_gepaart": surplus}
    return sheet, key


def rubric_template() -> dict[str, Any]:
    return {
        "raster": RATING_SHEET,
        "skala": "0 nicht vorhanden oder kritisch verletzt, 1 schwach, 2 brauchbar, 3 stark und begründet, 4 besonders überzeugend",
        "regeln": [
            "Hohe Werte brauchen einen Bezug zur Quelle; im Zweifel den niedrigeren Anker wählen.",
            "Die Herkunft der Clips ist verborgen; nicht versuchen, sie zu erraten.",
            "Natürlichkeit am Audio der Quelle mit den Zeiten unter segmente prüfen.",
            "Duplikate innerhalb derselben Angabe unter ausgabe beurteilen.",
        ],
        "kriterien": CRITERIA,
        "praeferenz": list(PREFERENCES),
        "hinweis": f"Ergebnis {NOTE}.",
    }


def generate(sources: list[dict], out_dir: str | Path, seed: int = DEFAULT_SEED, k: int = DEFAULT_K, provider: str = providers_llm.HEURISTIC_PROVIDER,
             brief: dict[str, Any] | None = None, switches: bool = True, overrides: dict[str, bool] | None = None) -> dict[str, Path]:  # fmt: skip
    """Alle Läufe, Paare, Raster und Schlüssel; schreibt die Dateien aus ``FILES`` (ohne Bericht)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    brief = dict(DEFAULT_BRIEF if brief is None else brief)
    variants = [*BASE_VARIANTS, *(switch_variants(overrides) if switches else [])]
    runs: dict[str, dict[str, dict]] = {}
    for src in sources:
        runs[src["name"]] = {v.name: run_variant(v, src, brief, provider, k) for v in variants}
    sheet, key = make_pairs(runs, seed)
    run_doc = {
        "hinweis": f"Nicht an die Bewertenden geben (enthält die Versionen). Ergebnis {NOTE}.",
        "provider": provider,
        "k": k,
        "brief": brief,
        "varianten": [{"name": v.name, "fassung": v.version, "gruppe": v.group, "schalter": dict(v.overrides)} for v in variants],
        "gebaute_schalter": sorted(editorial.V2_IMPLEMENTED_SWITCHES),
        "quellen": runs,
    }
    paths = {}
    for kind, doc in (("sheet", sheet), ("key", key), ("rubric", rubric_template()), ("run", run_doc)):
        paths[kind] = out / FILES[kind]
        paths[kind].write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return paths


# -- Auswertung ------------------------------------------------------------------------------------


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def evaluate(out_dir: str | Path) -> dict[str, Any]:
    """Liest Bewertung, Schlüssel und Lauf und rechnet alle Kennzahlen des Berichts."""
    out = Path(out_dir)
    sheet = json.loads((out / FILES["sheet"]).read_text(encoding="utf-8"))
    key = json.loads((out / FILES["key"]).read_text(encoding="utf-8"))
    run_doc = json.loads((out / FILES["run"]).read_text(encoding="utf-8"))
    versions = (key["links"], key["rechts"])
    scores: dict[str, dict[str, list[float]]] = {v: {c: [] for c in CRITERIA} for v in versions}
    preference = Counter({v: 0 for v in versions} | {"gleich": 0, "offen": 0})
    for pair in sheet["paare"]:
        mapping = key["paare"][pair["paar_id"]]
        rating = pair.get("bewertung") or {}
        for side in ("A", "B"):
            for crit, value in (rating.get(side) or {}).items():
                if value is None:
                    continue
                if crit not in CRITERIA or not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 4:
                    raise SystemExit(f"{pair['paar_id']} {side}.{crit}: {value!r} ist kein Wert 0 bis 4.")
                scores[mapping[side]][crit].append(float(value))
        pref = rating.get("praeferenz")
        if pref not in (*PREFERENCES, None):
            raise SystemExit(f"{pair['paar_id']}: praeferenz {pref!r}, erlaubt sind A, B, gleich oder leer.")
        preference[mapping[pref] if pref in ("A", "B") else ("gleich" if pref == "gleich" else "offen")] += 1

    per_variant: dict[str, dict[str, Any]] = {}
    for runs in run_doc["quellen"].values():
        for name, r in runs.items():
            agg = per_variant.setdefault(name, {"vorschlaege": 0, "verworfen": Counter(), "verworfen_gesamt": 0, "angeboten": 0, "modellaufrufe": 0,
                                                "laufzeit_s": 0.0, "stunden": 0.0, "hooks_mit_befund": 0, "faelle": 0, "bestanden": 0})  # fmt: skip
            agg["vorschlaege"] += r["vorschlaege"]
            agg["verworfen_gesamt"] += r["verworfen_gesamt"]
            for reason, v in r["verworfen"].items():
                agg["verworfen"][reason] += v["anzahl"]
            agg["angeboten"] += len(r["angeboten"])
            agg["modellaufrufe"] += r["modellaufrufe"]
            agg["laufzeit_s"] += r["laufzeit_s"]
            agg["stunden"] += r["quelle_stunden"]
            agg["hooks_mit_befund"] += r["hooks_mit_befund"]
            if r["editorial_v1"] is not None:
                agg["faelle"] += 1
                agg["bestanden"] += int(r["editorial_v1"]["bestanden"])
    for agg in per_variant.values():
        props, hours = agg["vorschlaege"], agg["stunden"]
        agg["verworfen"] = {r: {"anzahl": n, "quote": round(n / props, 4) if props else 0.0} for r, n in sorted(agg["verworfen"].items())}
        agg["verwerfungsquote"] = round(agg["verworfen_gesamt"] / props, 4) if props else 0.0
        agg["modellaufrufe_je_stunde"] = round(agg["modellaufrufe"] / hours, 1) if hours else None
        agg["laufzeit_s_je_stunde"] = round(agg["laufzeit_s"] / hours, 1) if hours else None
        agg["bestehensquote"] = round(agg["bestanden"] / agg["faelle"], 4) if agg["faelle"] else None
    return {
        "versionen": list(versions),
        "paare": len(sheet["paare"]),
        "bewertete_paare": sum(1 for p in sheet["paare"] if any(v is not None for s in ("A", "B") for v in ((p.get("bewertung") or {}).get(s) or {}).values())),
        "nicht_gepaart": key["nicht_gepaart"],
        "mittel": {v: {c: _mean(vals) for c, vals in crits.items()} for v, crits in scores.items()},
        "anzahl": {v: {c: len(vals) for c, vals in crits.items()} for v, crits in scores.items()},
        "praeferenz": dict(preference),
        "varianten": per_variant,
        "varianten_info": {v["name"]: v for v in run_doc["varianten"]},
        "gebaute_schalter": run_doc["gebaute_schalter"],
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


def report_markdown(result: dict[str, Any]) -> str:
    """Bericht ohne Gedankenstriche; Werte mit Dezimalkomma."""
    left, right = result["versionen"]
    var = result["varianten"]
    lines = [
        f"# Blindvergleich {left} gegen {right}",
        "",
        f"Hinweis: {NOTE}. Das Material ist klein; Unterschiede sind Beobachtungen, keine Belege.",
        "",
        "## Material und Ausgabemenge",
        "",
        f"* Quellen: {result['quellen']}, Provider: {result['provider']}, Obergrenze k: {result['k']}",
        f"* Paare bei gleicher Ausgabemenge: {result['paare']}, davon bewertet: {result['bewertete_paare']}",
        f"* Nicht gepaart (Überhang einer Version): {len(result['nicht_gepaart'])}",
    ]
    for item in result["nicht_gepaart"]:
        lines.append(f"  * {item['quelle']}: {item['version']} Rang {item['rang']}")
    lines += ["", "## Redaktionelle Bewertung (blind, Anker 0 bis 4)", "", f"| Kriterium | {left} | {right} |", "|---|---|---|"]
    for crit, spec in CRITERIA.items():
        cells = [f"{_num(result['mittel'][v][crit])} (n = {result['anzahl'][v][crit]})" for v in (left, right)]
        lines.append(f"| {spec['titel']} | {cells[0]} | {cells[1]} |")
    pref = result["praeferenz"]
    lines += ["", f"Präferenz: {left} {pref.get(left, 0)}, {right} {pref.get(right, 0)}, gleich {pref.get('gleich', 0)}, offen {pref.get('offen', 0)}.", ""]

    reasons = sorted({r for v in (left, right) for r in var[v]["verworfen"]})
    lines += ["## Verwerfungsquote je Grund und Version", "", "Anteil an allen Vorschlägen der Stufe 2 (`DetectReport.proposals`).", "",
              f"| Grund | {left} | {right} |", "|---|---|---|"]  # fmt: skip
    for reason in reasons:
        cells = []
        for v in (left, right):
            entry = var[v]["verworfen"].get(reason)
            cells.append(f"{entry['anzahl']} ({_pct(entry['quote'])})" if entry else "0")
        lines.append(f"| {reason} | {cells[0]} | {cells[1]} |")
    lines.append(f"| gesamt | {var[left]['verworfen_gesamt']} von {var[left]['vorschlaege']} ({_pct(var[left]['verwerfungsquote'])}) "
                 f"| {var[right]['verworfen_gesamt']} von {var[right]['vorschlaege']} ({_pct(var[right]['verwerfungsquote'])}) |")  # fmt: skip

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
                  "Fassung 2, Basis: alle Gruppenschalter aus. Ein Schalter ohne Code (nicht gebaut) ändert nichts; seine Zeile entspricht dann der Basis.", "",
                  "| Variante | Schalter an | gebaut | Kandidaten | Verwerfungsquote | Modellaufrufe je Quellstunde | Hooks mit Befund | editorial_v1 |",
                  "|---|---|---|---|---|---|---|---|"]  # fmt: skip
        for name in switch_rows:
            info, agg = result["varianten_info"][name], var[name]
            on = [s for s, value in info["schalter"].items() if value]
            title = GROUP_TITLES.get(info["gruppe"], info["gruppe"].capitalize())
            built_cell = "keiner" if not on else ", ".join(f"{s} {'ja' if s in built else 'nein'}" for s in on)
            lines.append(f"| {title} | {', '.join(on) or 'keiner'} | {built_cell} | {agg['angeboten']} | {_pct(agg['verwerfungsquote'])} "
                         f"| {_num(agg['modellaufrufe_je_stunde'], 1)} | {agg['hooks_mit_befund']} | {agg['bestanden']} von {agg['faelle']} |")  # fmt: skip

    lines += ["", "## Grenzen der Aussage", "",
              f"* {NOTE[0].upper() + NOTE[1:]}. Organische Veröffentlichungen sind kein A/B-Test.",
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
    mode.add_argument("--out", help="Ordner für Bewertungsbogen, Raster, Schlüssel und Lauf")
    mode.add_argument("--auswerten", help="Ordner eines früheren Laufs mit ausgefüllter bewertung.json")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"Zufallsseed für Reihenfolge und A/B, Standard {DEFAULT_SEED}")
    ap.add_argument("--k", type=int, default=DEFAULT_K, help=f"Obergrenze der Kandidaten je Quelle und Version, Standard {DEFAULT_K}")
    ap.add_argument("--provider", default=providers_llm.HEURISTIC_PROVIDER, help="LLM-Provider für beide Versionen, Standard local-heuristic")
    ap.add_argument("--transkripte", help="Ordner mit Transkript-JSON (Wortliste oder {\"words\": [...]})")
    ap.add_argument("--quelle", action="append", default=[], help="UUID einer Quelle aus der Datenbank (braucht DATABASE_URL), mehrfach")
    ap.add_argument("--ohne-fixtures", action="store_true", help="Demo-Skript und editorial_v1 nicht verwenden")
    ap.add_argument("--ohne-schalter", action="store_true", help="keine Schalter-Varianten rechnen")
    ap.add_argument("--override", action="append", default=[], help=f"zusätzliche Variante: Schalter pfad=true|false, mehrfach; auch {OVERRIDES_ENV}")
    ap.add_argument("--brief", help="Brief als JSON-Datei (gleich für beide Versionen)")
    ap.add_argument("--bericht", help="Pfad des Berichts, Standard <ordner>/bericht.md")
    args = ap.parse_args(argv)

    if args.auswerten:
        text = report_markdown(evaluate(args.auswerten))
        target = Path(args.bericht or Path(args.auswerten) / FILES["report"])
        target.write_text(text, encoding="utf-8")
        print(text)
        print(f"Bericht geschrieben: {target}")
        return

    sources = [] if args.ohne_fixtures else fixture_sources()
    if args.transkripte:
        sources += transcript_sources(args.transkripte)
    sources += database_sources(args.quelle)
    if not sources:
        raise SystemExit("Keine Quellen: Fixtures, --transkripte oder --quelle angeben.")
    brief = json.loads(Path(args.brief).read_text(encoding="utf-8")) if args.brief else None
    overrides = parse_overrides(args.override, os.environ.get(OVERRIDES_ENV))
    paths = generate(sources, args.out, seed=args.seed, k=args.k, provider=args.provider, brief=brief,
                     switches=not args.ohne_schalter, overrides=overrides)  # fmt: skip
    print(f"{len(sources)} Quellen gerechnet.")
    print(f"Bewertungsbogen (an die Bewertenden): {paths['sheet']}")
    print(f"Raster: {paths['rubric']}")
    print(f"Schlüssel und Lauf (nicht weitergeben): {paths['key']}, {paths['run']}")
    print(f"Nach dem Bewerten: python -m eval.blind_compare --auswerten {args.out}")


if __name__ == "__main__":
    main(sys.argv[1:])
