"""Golden-Snapshot der Kandidatensuche unter Policy v1 (Rollback-Beweis, Plan Abschnitt 4).

``story_engine.run`` läuft mit dem Heuristik-Provider auf ``transcript_fixtures.DEMO_SCRIPT``, einmal
ohne Heatmap und einmal mit Seeds, und auf jedem der 14 Fälle des Testsatzes ``editorial_v1`` ohne
Heatmap. Das Ergebnis muss byte-gleich zu ``snapshots/detect_v1.json`` bleiben, solange
``CHOPSTR_POLICY_VERSION`` auf 1 steht. Jede Änderung, die unter v1 ein anderes
Ergebnis liefert, fällt hier auf; neue Logik gehört hinter einen Schalter in Policy v2.

Normalisiert wird nichts: Der Lauf enthält weder Zeitstempel noch Zufall (zweimal hintereinander
gerechnet ergibt dieselben Bytes, siehe ``test_snapshot_is_deterministic``). Neben ``to_json`` steht
auch die Liste der verworfenen Kandidaten im Snapshot, weil eine geänderte Verwerfung sonst
unsichtbar bliebe.

spaCy ist im Test fest abgeschaltet (``dach_nlp.nlp`` liefert ``None``), so wie im Lauf, aus dem der
Snapshot stammt. Sonst würde der Test rot, sobald ein Modell installiert ist, obwohl sich unter v1
nichts geändert hat.

Der Snapshot wurde vor AP0b aus dem damaligen Code erzeugt; die Szenarien des Testsatzes kamen in der
Nacharbeit zu AP0b dazu, gerechnet auf dem Stand 35de380, der unter v1 dem Stand vor AP0b entspricht. Neu schreiben nur bewusst und nur mit
Begründung im Commit: ``python -m tests.test_policy_snapshot_v1 --write`` (im Ordner ``workers``).
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

from chopstr_worker import config, editorial, providers_llm
from chopstr_worker.pipeline import dach_nlp, story_engine
from chopstr_worker.providers_llm import LLM
from chopstr_worker.residency import Tenant
from tests.editorial_v1 import harness
from tests.transcript_fixtures import demo_words

SNAPSHOT = Path(__file__).resolve().parent / "snapshots" / "detect_v1.json"
BRIEF = {"audience": "Gründer im DACH-Raum", "wanted": "Fehler mit Zahlen", "exclude": "Werbung", "platform": "linkedin"}
BRAND = {"country": "AT", "address": None, "learned_weights": None}
SCENARIOS = {
    "demo_without_heatmap": None,
    "demo_with_seeds": {"bin_s": 1, "n_bins": 80, "values": [], "seeds": [3, 50]},
}
# Je Fall des Testsatzes ein Szenario ohne Heatmap, Schlüssel ``editorial_v1_<id>``.
CASES = {f"editorial_v1_{c['id']}": c["words"] for c in harness.load_cases()}


def _llm() -> LLM:
    return LLM(Tenant(id="ws", tier="standard"), provider=providers_llm.HEURISTIC_PROVIDER, s=config.settings())


def render() -> str:
    """Alle Szenarien als stabil formatierter JSON-Text (sortierte Schlüssel, UTF-8, Zeilenende)."""
    runs = [(name, demo_words(), heat) for name, heat in SCENARIOS.items()]
    runs += [(name, copy.deepcopy(words), None) for name, words in CASES.items()]
    out = {}
    for name, words, heat in runs:
        report = story_engine.run(words, dict(BRIEF), dict(BRAND), heat, _llm())
        data = report.to_json()
        data["verworfen"] = [c.to_row() for c in report.verworfen]
        out[name] = data
    return json.dumps(out, ensure_ascii=False, sort_keys=True, indent=1) + "\n"


def _without_spacy(mp: pytest.MonkeyPatch) -> None:
    """spaCy gilt als nicht verfügbar, unabhängig davon, ob ein Modell installiert ist."""
    mp.setattr(dach_nlp, "nlp", lambda: None)
    mp.setattr(dach_nlp, "verb_bracket_available", False)


@pytest.fixture(autouse=True)
def _no_spacy(monkeypatch):
    _without_spacy(monkeypatch)


def _v1(monkeypatch) -> None:
    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "1")
    editorial.clear_cache()


def test_v1_matches_golden_snapshot(monkeypatch):
    _v1(monkeypatch)
    assert editorial.load().version == 1
    assert render() == SNAPSHOT.read_text(encoding="utf-8")


def test_v1_is_the_default_without_environment(monkeypatch):
    monkeypatch.delenv("CHOPSTR_POLICY_VERSION", raising=False)
    editorial.clear_cache()
    assert render() == SNAPSHOT.read_text(encoding="utf-8")


def test_snapshot_is_deterministic(monkeypatch):
    _v1(monkeypatch)
    assert render() == render()


def test_snapshot_covers_every_editorial_v1_case():
    stored = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert len(CASES) == len(harness.REQUIRED_CASE_IDS) == 14
    assert set(stored) == set(SCENARIOS) | set(CASES)


def test_spacy_counts_as_unavailable():
    assert dach_nlp.nlp() is None
    assert dach_nlp.verb_bracket_available is False


if __name__ == "__main__":  # pragma: no cover
    if "--write" not in sys.argv:
        raise SystemExit("Nur mit --write: überschreibt snapshots/detect_v1.json mit dem aktuellen Lauf.")
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    with pytest.MonkeyPatch.context() as mp:
        _without_spacy(mp)
        mp.setenv("CHOPSTR_POLICY_VERSION", "1")
        SNAPSHOT.write_text(render(), encoding="utf-8")
    print(f"geschrieben: {SNAPSHOT}")
