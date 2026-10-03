from __future__ import annotations

import json
from pathlib import Path

from chopstr_worker.pipeline import fidelity


def _words(tokens, gap=0.1):
    out, t = [], 0.0
    for tok in tokens:
        out.append({"text": tok, "start": round(t, 3), "end": round(t + 0.3, 3)})
        t += 0.3 + gap
    return out


def test_negation_removed_is_high_severity():
    words = _words(["Das", "ist", "nicht", "gut"])
    warns = fidelity.check_cut(words, [(0, 1), (3, 3)])
    assert any(w["type"] == "negation_removed" and w["severity"] == "high" for w in warns)


def test_qualifier_removed():
    words = _words(["Das", "gilt", "nur", "bei", "uns"])
    warns = fidelity.check_cut(words, [(0, 1)])
    types = {w["type"] for w in warns}
    assert "qualifier_removed" in types


def test_ends_before_contrast():
    words = _words(["Das", "war", "gut.", "Aber", "nur", "kurz."])
    warns = fidelity.check_cut(words, [(0, 2)])
    assert any(w["type"] == "ends_before_contrast" for w in warns)


def test_joined_statements():
    words = _words(["a", "b"]) + [{"text": "c", "start": 60.0, "end": 60.3}, {"text": "d", "start": 60.4, "end": 60.7}]
    warns = fidelity.check_cut(words, [(0, 1), (2, 3)])
    assert any(w["type"] == "joined_statements" for w in warns)


def test_clean_cut_has_no_warnings():
    words = _words(["Wir", "haben", "äh", "gewonnen."])
    assert fidelity.check_cut(words, [(0, 1), (3, 3)]) == []


def test_hook_claim_check():
    issues = fidelity.hook_claim_check("50.000 Euro garantiert verloren", "Wir haben 40.000 Euro verloren")
    assert any("50.000" in i for i in issues)
    assert any("garantiert" in i for i in issues)
    assert fidelity.hook_claim_check("40.000 Euro verloren", "Wir haben 40.000 Euro verloren") == []


# -- Claim-Check v2 (AP6a, RESEARCH-CLIPPING-KERN Abschnitt 2 Nr. 7) --------------------------------

PARITY = Path(__file__).resolve().parents[2] / "packages" / "editorial" / "parity" / "claim_check_v1.json"


def test_v2_forty_euro_is_not_four_hundred_thousand():
    clip = "Wir haben 400.000 Euro gespart."
    assert fidelity.hook_claim_check("40 Euro gespart", clip) == []  # v1 per Teilstring: übersehen
    assert fidelity.hook_claim_check_v2("40 Euro gespart", clip) == ["Zahl '40' (Euro) steht so nicht im Clip"]


def test_v2_four_tips_are_not_in_2024():
    assert fidelity.hook_claim_check("4 Tipps", "Das war 2024.") == []
    assert fidelity.hook_claim_check_v2("4 Tipps", "Das war 2024.") == ["Zahl '4' (Tipps) steht so nicht im Clip"]


def test_v2_percent_sign_and_word_are_the_same():
    assert fidelity.hook_claim_check_v2("40 % Marge", "Wir haben 40 Prozent Marge verloren.") == []
    assert fidelity.hook_claim_check_v2("40 Prozent", "Minus 40 % im Jahr.") == []
    assert fidelity.hook_claim_check_v2("40 Prozent", "Minus 40 Euro im Jahr.") == ["Zahl '40' (Prozent) steht so nicht im Clip"]


def test_v2_normalizes_separators_decimals_and_number_words():
    values = [(m.value, m.unit) for m in fidelity.number_mentions("40.000 Euro, 40 000 Euro, 3,5 Prozent, zwölf Leute, € 500")]
    assert values == [(40000.0, "EUR"), (40000.0, "EUR"), (3.5, "%"), (12.0, "noun:leute"), (500.0, "EUR")]
    assert fidelity.hook_claim_check_v2("Von 12 auf 4 Lieferanten", "Die Lieferanten sanken von zwölf auf vier.") == []
    assert fidelity.hook_claim_check_v2("40 Tausend Euro", "Wir haben 40.000 Euro gespart.") == []


def test_v2_scope_generalizer_against_restrictor():
    issues = fidelity.hook_claim_check_v2("Jedes Unternehmen spart so", "Bei einem Kunden hat das viel gespart.")
    assert issues == ["Geltungsbereich: 'jedes unternehmen' im Hook, der Clip schränkt ein ('bei einem kunden')"]
    assert fidelity.hook_claim_check_v2("Für jeden ein Gewinn", "Damals war das für uns ein Gewinn.")
    assert fidelity.hook_claim_check_v2("Alle sparen damit", "Alle unsere Kunden sparen damit.") == []


def test_v2_uncertain_number_must_not_be_in_the_hook():
    clip = "Bei uns hat das rund 40.000 Euro gespart."
    assert fidelity.hook_claim_check_v2("40.000 Euro gespart", clip) == []
    issues = fidelity.hook_claim_check_v2("40.000 Euro gespart", clip, ["40.000"])
    assert issues == ["Zahl '40.000' ist im Clip unsicher erkannt und darf nicht in den Hook (am Audio prüfen)"]
    words = [{"text": "rund", "prob": 0.96}, {"text": "40.000", "prob": 0.46}, {"text": "Meier,", "prob": 0.38}, {"text": "Euro"}]
    # Wortfolge ab der Zahl und Rohform; Namen sind keine Zahl, fehlendes prob gilt als sicher
    assert fidelity.uncertain_number_tokens(words) == ["40.000 Meier, Euro", "40.000"]


def test_v2_uncertain_number_is_read_in_context_and_as_raw_value():
    words = [{"text": "rund"}, {"text": "40", "prob": 0.3}, {"text": "Tausend"}, {"text": "Euro"}, {"text": "gespart."}]
    tokens = fidelity.uncertain_number_tokens(words)
    assert tokens == ["40 Tausend Euro", "40"]
    clip = "Rund 40 Tausend Euro gespart."
    assert fidelity.hook_claim_check_v2("40.000 Euro gespart", clip, tokens)  # Kontext: 40.000
    assert fidelity.hook_claim_check_v2("40 Tausend Euro", clip, tokens)  # Rohwert und Kontext


def test_v2_superlatives_at_word_boundaries():
    assert fidelity.hook_claim_check("Immer der beste Weg", "Der beste Weg, nimmermehr anders.") == []
    assert fidelity.hook_claim_check_v2("Immer der beste Weg", "Der beste Weg, nimmermehr anders.") == [
        "Zuspitzung 'immer' nicht durch Clip gedeckt"
    ]


def test_v2_matches_the_shared_parity_cases():
    """Dieselben Fälle prüft apps/web/tests/claim-pruefung.test.ts gegen ``hookClaimCheckV2``."""
    data = json.loads(PARITY.read_text(encoding="utf-8"))
    assert data["version"] == "claim_check_v1" and len(data["cases"]) >= 20
    for case in data["cases"]:
        got = fidelity.hook_claim_check_v2(case["hook"], case["clip_text"], case["uncertain_tokens"])
        assert got == case["expected_issues"], case["id"]


def test_v2_scope_no_finding_when_hook_restricts_or_clip_generalizes_itself():
    assert fidelity.hook_claim_check_v2("Bei uns sparen alle", "Bei uns spart man.") == []  # Hook schränkt selbst ein
    # „immer“ steht im Clip in einem Satz ohne Einschränker: gedeckt
    assert fidelity.hook_claim_check_v2("Jeder spart immer", "Immer sparen wir. Bei uns sowieso.") == [
        "Geltungsbereich: 'jeder' im Hook, der Clip schränkt ein ('bei uns')"
    ]
    # Kein Doppelbefund für „immer“ als Zuspitzung und als Verallgemeinerer
    assert fidelity.hook_claim_check_v2("Das klappt immer", "Bei uns hat das geklappt.") == [
        "Geltungsbereich: 'immer' im Hook, der Clip schränkt ein ('bei uns')"
    ]


def test_v2_noun_unit_needs_the_same_noun():
    assert fidelity.hook_claim_check_v2("40 Kunden", "40 Mitarbeiter und viele Kunden") == [
        "Zahl '40' (Kunden) steht so nicht im Clip"
    ]
    assert fidelity.hook_claim_check_v2("40 Kunden", "Wir hatten 40 neue Kunden.") == []  # Zahl ohne Einheit, Nomen im Text
    assert fidelity.hook_claim_check_v2("40 Kunden", "Wir hatten 40 Kundinnen.") == []  # gleicher Stamm


def test_v2_number_words_beyond_twenty():
    assert fidelity.parse_number_word("einundzwanzig") == 21
    assert fidelity.parse_number_word("vierzigtausend") == 40000
    assert fidelity.parse_number_word("zweihundertfünfzig") == 250
    assert fidelity.parse_number_word("Leipzig") is None
    assert fidelity.hook_claim_check_v2("40.000 Euro gespart", "Wir haben vierzigtausend Euro gespart.") == []
    assert fidelity.hook_claim_check_v2("21 Kunden", "Wir haben einundzwanzig Kunden.") == []
    assert fidelity.hook_claim_check_v2("Zehntausende Kunden", "Wir haben viele Kunden.") == [
        "Zahlwort 'Zehntausende' nicht erkannt, am Clip prüfen"
    ]
    assert fidelity.hook_claim_check_v2("Das einzige Problem", "Das einzige Problem war der Preis.") == []


def test_v2_ambiguous_number_words_times_and_spaces():
    values = [(m.value, m.unit) for m in fidelity.number_mentions("Gib acht, acht Leute, eine Million Euro, elf Freunde")]
    assert values == [(8.0, "noun:leute"), (1e6, "EUR"), (11.0, "noun:freunde")]
    assert fidelity.hook_claim_check_v2("Start 9:30 Uhr", "Wir starten um 9.30 Uhr.") == []
    assert fidelity.hook_claim_check_v2("40\u00a0000 Euro", "Wir haben 40.000 Euro gespart.") == []
