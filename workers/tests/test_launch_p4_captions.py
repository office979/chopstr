"""Lane P4, Aufgabe 3: Lesetempo nach Profil, Du/Sie-Hinweis, Stichprobe der Umbrüche (Gate 4)."""

from __future__ import annotations

import dataclasses

import pytest

from chopstr_worker import editorial
from chopstr_worker.pipeline import ausgabe_pruefung, captions_de
from tests.test_launch_p4_prosody import policy_with, w


@pytest.fixture(autouse=True)
def _fresh_policy_cache():
    editorial.clear_cache()
    yield
    editorial.clear_cache()


def v2_rules(reading: float = 0.0, clip_end: float | None = None) -> captions_de.CaptionRules:
    return dataclasses.replace(captions_de.caption_rules(editorial.load(2)), reading_cps=reading, clip_end_s=clip_end)


# Karte 1 „Das ist ein Satz." (17 Zeichen) in 0,8 s, Karte 2 erst nach einer langen Pause.
WORDS = [
    w("Das", 0.0, 0.15), w("ist", 0.2, 0.35), w("ein", 0.4, 0.55), w("Satz.", 0.6, 0.8),
    w("Danach", 3.0, 3.4), w("geht", 3.45, 3.7), w("es", 3.75, 3.85), w("weiter.", 3.9, 4.3),
]  # fmt: skip


def test_reading_speed_profiles_and_rollback():
    assert captions_de.reading_speed(editorial.load(1)) is None
    v2 = editorial.load(2)
    assert captions_de.reading_speed(v2) == {"profile": "standard", "chars_per_s": 15.0}
    assert captions_de.reading_speed(v2, "langsam") == {"profile": "langsam", "chars_per_s": 12.0}
    assert captions_de.reading_speed(v2, "unbekannt")["profile"] == "standard"
    assert captions_de.reading_speed(policy_with({"implementation.captions.reading_speed": False})) is None
    assert captions_de.reading_speed(policy_with({"implementation.captions.word_bridge": False})) is None
    with pytest.raises(editorial.PolicyError, match="chars_per_s"):
        captions_de.reading_speed(policy_with({"captions.reading_speed.chars_per_s.langsam": 0}), "langsam")


def test_reading_speed_extends_the_card_but_never_into_the_next_or_past_the_clip():
    preset = captions_de.PRESETS["linkedin_static"]
    base = captions_de.cards_for(WORDS, preset, rules=v2_rules())
    std = captions_de.cards_for(WORDS, preset, rules=v2_rules(15.0))
    slow = captions_de.cards_for(WORDS, preset, rules=v2_rules(12.0))
    assert base[0]["end"] == 0.8 and std[0]["end"] == pytest.approx(17 / 15, abs=0.002) and slow[0]["end"] == pytest.approx(17 / 12, abs=0.002)
    assert [c["lines"] for c in std] == [c["lines"] for c in base]  # Text und Umbruch bleiben
    tight = [w("Das", 0.0, 0.15), w("ist", 0.2, 0.35), w("ein", 0.4, 0.55), w("Satz.", 0.6, 0.8), w("Weiter", 1.0, 1.4), w("geht's.", 1.45, 1.8)]
    assert captions_de.cards_for(tight, preset, rules=v2_rules(12.0))[0]["end"] == 1.0  # nie in die nächste Karte
    capped = captions_de.cards_for(WORDS, preset, rules=v2_rules(12.0, clip_end=4.4))
    assert capped[-1]["end"] <= 4.4  # nie über das Clipende


def test_style_of_the_burned_in_captions_stays_the_same():
    preset = captions_de.scaled_preset("linkedin_static", 1080, 1350)
    a = captions_de.to_ass(WORDS, 0.0, preset, (1080, 1350), rules=v2_rules())
    b = captions_de.to_ass(WORDS, 0.0, preset, (1080, 1350), rules=v2_rules(15.0, 4.4))
    head = lambda text: text.split("[Events]")[0]  # noqa: E731
    assert head(a) == head(b)
    texts = lambda text: [ln.split(",Cap,")[1] for ln in text.splitlines() if ln.startswith("Dialogue")]  # noqa: E731
    assert texts(a) == texts(b)
    srt = captions_de.to_srt(WORDS, 0.0, preset, rules=v2_rules(15.0, 4.4))
    assert "00:00:01,133" in srt


def test_du_and_sie_are_counted_and_reported_but_never_changed():
    mixed = [w("Du", 0.0, 0.2), w("kannst", 0.25, 0.5), w("das.", 0.55, 0.8), w("Haben", 1.0, 1.2), w("Sie", 1.25, 1.4), w("Zeit?", 1.45, 1.7)]
    res = captions_de.anrede_pruefen(mixed)
    assert res["du"] == 1 and res["sie"] == 1 and res["gemischt"] is True
    befund = ausgabe_pruefung.anrede_befund(res, "du")
    assert befund.ergebnis == "hinweis" and "Du und Sie" in befund.text and "Markenprofil du" in befund.gemessen
    assert [x["text"] for x in mixed] == ["Du", "kannst", "das.", "Haben", "Sie", "Zeit?"]
    # „Sie" am Satzanfang ist auch die dritte Person und zählt nicht; „Ihnen" zählt immer.
    third = [w("Sie", 0.0, 0.2), w("haben", 0.25, 0.5), w("recht.", 0.55, 0.8), w("Du", 1.0, 1.2), w("auch.", 1.25, 1.5)]
    assert captions_de.anrede_pruefen(third)["gemischt"] is False
    assert captions_de.anrede_pruefen([w("Danke", 0, 0.2), w("Ihnen.", 0.3, 0.6), w("Und", 1, 1.2), w("dir.", 1.3, 1.5)])["gemischt"] is True
    assert ausgabe_pruefung.anrede_befund(captions_de.anrede_pruefen(third)).ergebnis == "ok"
    assert captions_de.address_check_enabled(editorial.load(2)) and not captions_de.address_check_enabled(editorial.load(1))


def _transcript(n_sentences: int = 120) -> list[dict]:
    """Deutsche Sätze mit langen Komposita, Zahlen mit Einheit, Negationen und Kommas."""
    vorlagen = [
        "Die Steuerberatungsgesellschaft hat 40 Prozent mehr Umsatz gemacht.",
        "Wir haben in einer Woche rund 3,5 Mio. Euro verloren, aber nicht alles.",
        "Das Know-how-Transfer-Programm läuft seit 14.30 Uhr.",
        "Ich würde die Preise nie wieder unter die Kosten setzen.",
        "Unsere Donaudampfschifffahrtsgesellschaft braucht 12 Stunden für die Strecke.",
        "Ehrlich gesagt war das der teuerste Fehler meiner Karriere.",
    ]
    out, t = [], 0.0
    for k in range(n_sentences):
        for token in vorlagen[k % len(vorlagen)].split():
            out.append(w(token, round(t, 3), round(t + 0.3, 3)))
            t += 0.35
        t += 0.5
    return out


def test_sample_breaks_draws_200_breaks_and_checks_the_rules():
    words = _transcript()
    res = captions_de.sample_breaks(words, 200, rules=captions_de.caption_rules(editorial.load(2)))
    assert res["n"] == 200 and res["total"] >= 200 and set(res["violations"]) == {"kompositum", "zahl_einheit", "satz"}
    assert res == captions_de.sample_breaks(words, 200, rules=captions_de.caption_rules(editorial.load(2)))  # deterministisch
    assert res["violations"]["zahl_einheit"] == 0 and res["violations"]["satz"] == 0
    assert all(set(b) == {"kind", "left", "right", "issues"} for b in res["breaks"])
    # Ohne AP10a werden Zahl und Einheit getrennt: das Werkzeug muss das finden, mit AP10a nicht.
    narrow = dataclasses.replace(captions_de.PRESETS["linkedin_static"], font_px=140)  # 11 Zeichen je Zeile
    probe = [w(tok, round(0.35 * k, 2), round(0.35 * k + 0.3, 2)) for k, tok in enumerate(["Wir", "haben", "genau", "40", "Prozent", "verloren."])]
    assert captions_de.sample_breaks(probe, 50, preset=narrow, rules=captions_de.LEGACY_RULES)["violations"]["zahl_einheit"] == 1
    assert captions_de.sample_breaks(probe, 50, preset=narrow, rules=captions_de.caption_rules(editorial.load(2)))["violations"]["zahl_einheit"] == 0
    # Silbentrennung in einem Kompositum ist ein Befund (Regel 9 kennt keine Ausnahme für Morphemgrenzen).
    assert captions_de.sample_breaks(words, 500, preset=narrow, rules=captions_de.caption_rules(editorial.load(2)))["violations"]["kompositum"] > 0


def test_a_break_at_an_existing_hyphen_is_no_compound_error():
    issues = captions_de._break_issues(  # noqa: SLF001
        (word := w("Know-how-Transfer", 0, 1), "Know-how-"), (word, "Transfer"), ["Know-how-"], ["Transfer"], "text"
    )
    assert "kompositum" not in issues
    soft = w("Steuerberatung", 0, 1)
    assert "kompositum" in captions_de._break_issues((soft, "Steuer-"), (soft, "beratung"), ["Steuer-"], ["beratung"], "text")  # noqa: SLF001
