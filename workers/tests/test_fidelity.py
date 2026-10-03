from __future__ import annotations

import json
from pathlib import Path

import pytest

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


def test_v2_scope_uses_dach_nlp_sentences():
    """M4: „z. B.“ und „am 3. Mai“ trennen keinen Satz; Einschränker und Verallgemeinerer stehen zusammen."""
    finding = ["Geltungsbereich: 'für alle' im Hook, der Clip schränkt ein ('bei uns')"]
    assert fidelity.hook_claim_check_v2("Das gilt für alle", "Bei uns z. B. gilt das für alle.") == finding
    assert fidelity.hook_claim_check_v2("Das gilt für alle", "Bei uns, also am 3. Mai, galt das für alle.") == finding
    assert fidelity.text_sentences("Bei uns z. B. gilt das. Am 3. Mai auch.") == ["Bei uns z. B. gilt das.", "Am 3. Mai auch."]


def test_v2_immer_idioms_quantity_words_direction_and_single_scope_finding():
    assert fidelity.hook_claim_check_v2("Immer mehr Kunden", "Bei uns kommen immer mehr Kunden.") == []
    assert fidelity.hook_claim_check_v2("Wie immer pünktlich", "Wir waren pünktlich.") == []
    assert fidelity.hook_claim_check_v2("Millionen Kunden", "Wir haben viele Kunden.") == ["Mengenwort 'Millionen' steht so nicht im Clip"]
    assert fidelity.hook_claim_check_v2("2 Millionen Kunden", "Wir haben 2 Millionen Kunden.") == []
    assert fidelity.hook_claim_check_v2("Das gilt für jede Firma", "Bei uns gilt das.") == [
        "Geltungsbereich: 'jede firma' im Hook, der Clip schränkt ein ('bei uns')"
    ]
    assert fidelity.hook_claim_check_v2("Über 40 Prozent sparen", "Fast 40 % sparen wir.") == [
        "Zahl '40': der Hook sagt mehr, als der Clip trägt (Richtung umgekehrt)"
    ]
    assert fidelity.hook_claim_check_v2("Fast 40 Prozent", "Wir sparen fast 40 % im Jahr.") == []


def test_v2_uncertain_multiplier_or_unit_transfers_to_the_number():
    words = [{"text": "rund"}, {"text": "40"}, {"text": "Tausend", "prob": 0.3}, {"text": "Euro"}, {"text": "gespart."}]
    assert fidelity.uncertain_number_tokens(words) == ["40 Tausend Euro", "40"]
    words = [{"text": "40.000"}, {"text": "Euro", "prob": 0.3}, {"text": "gespart."}]
    assert fidelity.uncertain_number_tokens(words) == ["40.000 Euro gespart.", "40.000"]


# -- AP7: Schutzbereiche aus trim_plan (nur Policy v2) ------------------------------------------------


def test_protected_removed_is_high_under_v2_only():
    from chopstr_worker import editorial

    words = _words(["Ja,", "aber", "nur,", "wenn", "ihr", "vorher", "dokumentiert.", "Dann", "klappt", "es."])
    cut = [(0, 1), (7, 9)]  # Bedingung „nur, wenn ihr vorher dokumentiert“ fehlt
    v2 = fidelity.check_cut(words, cut, policy=editorial.load(2))
    hit = next(w for w in v2 if w["type"] == "protected_removed")
    assert hit["severity"] == "high"
    assert {d["type"] for d in hit["detail"]} >= {"condition", "qualifier"}
    without = fidelity.check_cut(words, cut)
    assert without == fidelity.check_cut(words, cut, policy=editorial.load(1))
    assert not any(w["type"] == "protected_removed" for w in without)
    assert not any(w["type"] == "protected_removed" for w in fidelity.check_cut(words, [(0, 9)], policy=editorial.load(2)))


def test_protected_removed_also_catches_a_removed_correction():
    from chopstr_worker import editorial

    words = _words(["Drei", "Monate,", "beziehungsweise", "vier.", "Das", "war", "lang."])
    v2 = fidelity.check_cut(words, [(0, 1), (4, 6)], policy=editorial.load(2))
    hit = next(w for w in v2 if w["type"] == "protected_removed")
    assert [d["type"] for d in hit["detail"]] == ["correction"]
    assert not any(w["type"] == "negation_removed" for w in v2)  # die alte Prüfung sah das nicht


# -- CONTRAST_STARTS an Wortgrenzen (AP4, nur Regel v2) --------------------------------------------------


def _ends_before_contrast(tail_tokens, rule):
    words = _words(["Wir", "rechnen", "jede", "Preisänderung", "durch.", *tail_tokens])
    return any(w["type"] == "ends_before_contrast" for w in fidelity.check_cut(words, [(0, 4)], rule=rule))


def test_v1_reads_ausserdem_as_contrast_unchanged():
    """Bekannter Defekt (RK 2 Befund 6), unter v1 bewusst unverändert."""
    assert _ends_before_contrast(["Außerdem", "sprechen", "wir"], "v1") is True
    assert fidelity.check_cut(_words(["Wir", "rechnen.", "Außerdem", "nie."]), [(0, 1)]) == fidelity.check_cut(
        _words(["Wir", "rechnen.", "Außerdem", "nie."]), [(0, 1)], rule="v1"
    )


@pytest.mark.parametrize(
    ("tail", "expected"),
    [
        (["Außerdem", "sprechen", "wir"], False),
        (["Außerhalb", "der", "Saison"], False),
        (["Aberglaube", "hilft", "nicht"], False),
        (["Außer", "im", "Sommer"], True),
        (["Aber,", "und", "das"], True),
        (["Wobei", "ich", "dazusagen"], True),
    ],
)
def test_v2_matches_contrast_starts_at_word_boundaries(tail, expected):
    assert _ends_before_contrast(tail, "v2") is expected


def test_starts_with_contrast_rule_switch():
    assert fidelity.starts_with_contrast("außerdem sprechen wir") is True
    assert fidelity.starts_with_contrast("außerdem sprechen wir", "v2") is False
    assert fidelity.starts_with_contrast("„aber das", "v2") is True
