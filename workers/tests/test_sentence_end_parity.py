"""Satzende im Worker gleich wie im Web (AP2): gemeinsame Falldatei für pytest und vitest.

``packages/editorial/parity/sentence_end_v1.json`` hält je Wort die erwartete Art des Satzendes unter
Regel v1 und v2. ``apps/web/tests/satzende.test.ts`` prüft den Port in ``lib/transcript/sentences.ts``
gegen dieselbe Datei. Weicht einer ab, zerlegen Worker und Web dasselbe Transkript verschieden.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chopstr_worker.pipeline import dach_nlp

PARITY = Path(__file__).resolve().parents[2] / "packages" / "editorial" / "parity" / "sentence_end_v1.json"
DATA = json.loads(PARITY.read_text(encoding="utf-8"))


def test_parity_file_names_the_kinds_of_the_code():
    assert DATA["version"] == 1
    assert tuple(DATA["kinds"]) == dach_nlp.END_KINDS
    assert DATA["min_pause_s"] == 0.7
    assert len(DATA["cases"]) > 15


@pytest.mark.parametrize("rule", ["v1", "v2"])
@pytest.mark.parametrize("case", DATA["cases"], ids=[c["id"] for c in DATA["cases"]])
def test_sentence_end_kind_matches_parity_file(case, rule):
    words = case["words"]
    kinds = [dach_nlp.sentence_end_kind(words, i, rule, DATA["min_pause_s"]) for i in range(len(words))]
    assert kinds == case["expected"][rule]


@pytest.mark.parametrize("case", DATA["cases"], ids=[c["id"] for c in DATA["cases"]])
def test_cut_boundary_kind_matches_parity_file(case):
    words = case["words"]
    assert [dach_nlp.cut_boundary_kind(words, i, "v2") for i in range(len(words))] == case["expected"]["cut_v2"]


@pytest.mark.parametrize("case", DATA["cases"], ids=[c["id"] for c in DATA["cases"]])
def test_v1_kinds_reproduce_is_sentence_end_before_ap2(case):
    """Regel v1 ist ein Adapter: Satzende genau dort, wo ``is_sentence_end`` es vor AP2 meldete."""
    words = case["words"]
    assert [k != "none" for k in case["expected"]["v1"]] == [dach_nlp.is_sentence_end(words, i) for i in range(len(words))]


def test_parity_file_has_no_dashes():
    text = PARITY.read_text(encoding="utf-8")
    assert "–" not in text and "—" not in text
