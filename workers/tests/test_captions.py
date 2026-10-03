from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from chopstr_worker import editorial
from chopstr_worker.pipeline import captions_de as cap
from chopstr_worker.pipeline import reframe, render_plan


def _words(tokens, dur=0.3, gap=0.05):
    out, t = [], 0.0
    for tok in tokens:
        out.append({"text": tok, "start": round(t, 3), "end": round(t + dur, 3)})
        t += dur + gap
    return out


def test_max_chars_from_font_size():
    assert cap.max_chars(78, 900) == 20
    assert cap.max_chars(50, 900) == 32
    assert cap.max_chars(78, 900) > cap.max_chars(100, 900)
    assert cap.max_chars(400, 900) == 8  # Untergrenze


def test_presets_and_safe_zones():
    tt = cap.PRESETS["tiktok_bold"]
    assert (tt.safe.top, tt.safe.bottom, tt.safe.left, tt.safe.right) == (108, 1600, 60, 960)
    assert cap.PRESETS["reels_clean"].safe.top == 210 and cap.PRESETS["reels_clean"].safe.bottom == 1610
    assert cap.PRESETS["shorts_clean"].safe.top == 120 and cap.PRESETS["shorts_clean"].safe.bottom == 1620
    assert set(cap.PRESETS) == {
        "tiktok_bold",
        "reels_clean",
        "shorts_clean",
        "tiktok_words",
        "reels_words",
        "shorts_words",
        "linkedin_static",
        "corporate_third",
    }
    # Kurzformate wortweise als Standard, LinkedIn bleibt mehrwortig
    assert cap.preset_for("tiktok").name == "tiktok_words"
    assert cap.preset_for("tiktok").words_per_card == 1
    assert cap.preset_for("linkedin").name == "linkedin_static"
    assert cap.preset_for("linkedin").words_per_card is None
    assert cap.preset_for("corporate_third").name == "corporate_third"
    for p in cap.PRESETS.values():
        assert p.safe.top < p.baseline_y < p.safe.bottom


def test_nicht_never_alone_on_new_line():
    lines = cap.wrap_lines(["Das", "war", "damals", "nicht", "gut"], limit=14)
    assert not any(ln.strip().lower() == "nicht" for ln in lines)
    # Konstruiert: „nicht" würde greedy allein in Zeile 2 landen
    lines = cap.wrap_lines(["Ich", "mache", "das", "nicht"], limit=13)
    assert lines == ["Ich mache", "das nicht"]
    lines = cap.wrap_lines(["Riesenwort", "nicht"], limit=10)
    assert lines == ["Riesenwort nicht"]


def test_hyphenate_compound_at_morpheme_boundary():
    parts = cap.hyphenate("Donaudampfschifffahrtsgesellschaft", 16)
    assert len(parts) >= 2
    assert all(len(p) <= 17 for p in parts)
    assert all(p.endswith("-") for p in parts[:-1])
    joined = "".join(p.rstrip("-") for p in parts)
    assert joined == "Donaudampfschifffahrtsgesellschaft"
    assert cap.hyphenate("kurz", 16) == ["kurz"]


def test_build_cards_breaks_on_punctuation_pause_and_long_compound():
    words = _words(["Wir", "haben", "verloren,", "weil", "wir", "Geld", "hatten."])
    words[4]["start"] += 1.0
    words[4]["end"] += 1.0
    words[5]["start"] += 1.0
    words[5]["end"] += 1.0
    words[6]["start"] += 1.0
    words[6]["end"] += 1.0
    cards = cap.build_cards(words, limit=20)
    texts = [" ".join(w["text"] for w in c) for c in cards]
    assert texts[0] == "Wir haben verloren,"
    assert any(t.startswith("weil") for t in texts)
    long_words = _words(["Die", "Krankenversicherungsbeitragsbemessungsgrenze", "steigt."])
    cards = cap.build_cards(long_words, limit=20)
    assert any(len(c) == 1 and len(c[0]["text"]) > 20 for c in cards) or len(cards[0]) <= 2


def test_cps_warnings():
    fast = [
        {"text": "Donaudampfschifffahrtsgesellschaft", "start": 0.0, "end": 0.3},
        {"text": "steigt", "start": 0.3, "end": 0.5},
    ]
    assert cap.cps_warnings([fast])
    slow = [{"text": "Hallo", "start": 0.0, "end": 1.0}, {"text": "Welt", "start": 1.0, "end": 2.0}]
    assert cap.cps_warnings([slow]) == []


def test_cps_warnings_schweigt_bei_einem_wort_je_einblendung():
    """Wort fuer Wort ist ein eigener Stil und kein Fehler.

    Bei einem Wort je Einblendung steht jedes Wort genau so lange, wie es gesprochen wird. Die
    Lesegeschwindigkeit ganzer Saetze sagt darueber nichts. An echtem Material gemessen lagen mit
    der alten Rechnung 1574 von 2007 Woertern ueber der Grenze; die Warnung war damit eine Aussage
    ueber normales Sprechtempo und nicht ueber den Clip.
    """
    schnell = [[{"text": "Der", "start": 0.0, "end": 0.08}], [{"text": "Empfaenger", "start": 0.08, "end": 0.35}]]
    assert cap.cps_warnings(schnell) == []


def test_to_ass_and_srt():
    words = _words(["Das", "ist", "nicht", "gut."])
    ass = cap.to_ass(words, 0.0, "tiktok_bold")
    assert "PlayResX: 1080" in ass
    assert "Style: Cap,Inter,78," in ass
    assert "\\c&H0000D7FF" in ass  # Highlight
    assert ass.count("Dialogue:") == 4
    static = cap.to_ass(words, 0.0, "linkedin_static")
    assert static.count("Dialogue:") == 1
    assert "Style: Cap,Inter,54," in static
    srt = cap.to_srt(words)
    assert srt.startswith("1\n00:00:00,000 --> ")
    assert "nicht gut." in srt


def test_build_cards_teilt_zu_lange_gruppen():
    """Die feste Wortzahl ist eine Obergrenze, keine Vorgabe.

    Vorher entstand aus vier langen Woertern eine Karte, deren Rest in die letzte Zeile gequetscht
    wurde (wrap_lines). Der Text war dann nicht weg, stand aber ueber die sichere Flaeche hinaus
    oder in einer Zeile mehr, als eingestellt war.
    """
    lang = _words(["Personalgewinnungsstrategie", "Unternehmensberatung", "Wirtschaftspruefung", "Vakanzkosten"])
    karten = cap.build_cards(lang, limit=17, max_lines=1, words_per_card=4)
    assert len(karten) > 1
    for k in karten:
        assert len(" ".join(w["text"] for w in k)) <= 17 or len(k) == 1


def test_build_cards_laesst_passende_gruppen_in_ruhe():
    kurz = _words(["Das", "ist", "gut", "so"])
    karten = cap.build_cards(kurz, limit=40, max_lines=2, words_per_card=4)
    assert len(karten) == 1
    assert [w["text"] for w in karten[0]] == ["Das", "ist", "gut", "so"]


def test_build_cards_rechnet_grossbuchstaben_mit():
    """Aus dem deutschen ss wird bei all_caps ein Zeichen mehr, das kann die Karte sprengen."""
    w = _words(["Strassenverkehrsordnung", "Massnahme"])
    ohne = cap.build_cards(w, limit=24, max_lines=1, words_per_card=2, all_caps=False)
    mit = cap.build_cards(w, limit=24, max_lines=1, words_per_card=2, all_caps=True)
    assert len(mit) >= len(ohne)


def test_karten_passen_immer_in_die_zeilen():
    """Der Kern: nach card_lines darf nie mehr als max_lines herauskommen."""
    worte = _words(["Eine", "unbesetzte", "Stelle", "im", "Vertrieb", "kostet", "vierzehntausend", "Euro"])
    preset = cap.scaled_preset("tiktok_bold", 1080, 1920)
    preset = cap.style_anwenden(preset, {"words_per_card": 4, "max_lines": 2, "font_px": 104}, skala=1.0)
    for karte in cap.build_cards(worte, preset.max_chars, preset.max_lines, "text", preset.words_per_card, preset.all_caps):
        zeilen = cap.card_lines(karte, preset)
        assert len(zeilen) <= preset.max_lines
        for z in zeilen:
            assert len(" ".join(t for _, t in z)) <= preset.max_chars or len(z) == 1


def test_beiblaetter_brechen_wie_die_eingebrannten_untertitel():
    """SRT und VTT bekommen dasselbe Preset wie das Bild.

    Vorher bekamen sie nur die Zeichenbreite, und ``max_lines`` blieb bei zwei. Bei den hochkanten
    Stilen steht im Bild eine Zeile; die Beiblaetter brachen an anderen Stellen um."""
    woerter = [
        {"text": w, "start": i * 0.4, "end": i * 0.4 + 0.35}
        for i, w in enumerate(["Der", "Betrieb", "mit", "zwoelf", "Leuten", "hat", "im", "letzten", "Jahr", "mehr", "verdient"])
    ]
    p = cap.preset_for("tiktok_words")
    assert p.max_lines == 1
    karten_mit_preset, _ = cap.beiblatt_karten(woerter, p)
    karten_nur_breite, _ = cap.beiblatt_karten(woerter, p.max_chars)
    # Eine Zeile je Karte statt zwei: mehr Karten, dafuer dieselben Umbruchstellen wie im Bild.
    assert len(karten_mit_preset) > len(karten_nur_breite)
    assert all(len(cap.wrap_lines([cap.word_text(w, "text") for w in k], p.max_chars)) <= 2 for k in karten_mit_preset)


def test_beiblaetter_bleiben_lesbar_und_uebernehmen_kein_wort_je_karte():
    """Ein Wort je Eintrag ist im Video richtig und als Datei unbrauchbar.

    YouTube und jeder Player zeigen eine SRT so an, wie sie dasteht. Ein Wort im Sekundentakt liest
    niemand mit. Deshalb wird ``words_per_card`` bewusst nicht uebernommen."""
    woerter = [
        {"text": w, "start": i * 0.4, "end": i * 0.4 + 0.35}
        for i, w in enumerate(["Der", "Betrieb", "mit", "zwoelf", "Leuten", "hat", "im", "letzten", "Jahr", "mehr", "verdient"])
    ]
    p = cap.preset_for("tiktok_words")
    assert p.words_per_card == 1
    karten, _ = cap.beiblatt_karten(woerter, p)
    assert max(len(k) for k in karten) > 1


def test_alter_aufruf_mit_zeichenbreite_bleibt_gleich():
    woerter = [{"text": w, "start": i * 0.4, "end": i * 0.4 + 0.35} for i, w in enumerate(["eins", "zwei", "drei", "vier"])]
    a, breite = cap.beiblatt_karten(woerter, 30)
    assert breite == 30
    assert a == cap.build_cards(woerter, 30, 2, text_field="text")


def test_geloeschte_woerter_stehen_nicht_im_untertitel():
    """Im Clip-Editor lassen sich einzelne Woerter aus dem Untertitel loeschen.

    Gesagt bleibt gesagt, geschrieben steht es nicht mehr - gedacht fuer Fuellwoerter und
    Versprecher. Ohne den Filter liefe das leere Wort durch und erzeugte doppelte Leerzeichen oder
    eine Karte ohne Inhalt."""
    woerter = [
        {"text": "Das", "start": 0.0, "end": 0.3},
        {"text": "", "start": 0.35, "end": 0.5},
        {"text": "stimmt", "start": 0.55, "end": 0.9},
    ]
    karten = cap.build_cards(woerter, 40)
    flach = [cap.word_text(w) for k in karten for w in k]
    assert flach == ["Das", "stimmt"]
    assert "  " not in cap.to_srt(woerter, 0.0, 40)


def test_ein_wort_aus_nur_leerzeichen_zaehlt_als_geloescht():
    woerter = [{"text": "   ", "start": 0.0, "end": 0.3}, {"text": "ja", "start": 0.4, "end": 0.6}]
    assert [cap.word_text(w) for w in cap.sichtbare_woerter(woerter)] == ["ja"]


# -- AP10a: Caption-Ereignisse ohne Stilwechsel -----------------------------------------------------
AP10A = cap.CaptionRules(
    enabled=True, bridge_words=True, bridge_max_s=0.4, min_event_s=0.8, comma_break_only_on_overflow=True
)
PARITY = json.loads(
    (Path(__file__).resolve().parents[2] / "packages" / "editorial" / "parity" / "caption_cards_v1.json").read_text(
        encoding="utf-8"
    )
)
# Beispiel aus RK 2 Befund 9 und den Pflichtfällen: Lücken, Zahl plus Einheit, Bindestrich, Kompositum.
SAMPLE = [
    ("Ja,", 0.0, 0.2), ("das", 0.5, 0.7), ("kostet", 1.2, 1.6), ("40", 1.65, 1.9), ("Prozent", 1.95, 2.4),
    ("mehr", 2.5, 2.8), ("als", 2.85, 3.0), ("die", 3.05, 3.2), ("Kunden-Anfrage-Bearbeitung.", 3.3, 4.4),
    ("Die", 5.2, 5.35), ("Kundenanfragenbearbeitung", 5.4, 6.5), ("kostet", 6.55, 6.9), ("3,5", 7.0, 7.3),
    ("Mio.", 7.35, 7.7), ("Euro", 7.75, 8.1), ("um", 8.15, 8.3), ("14.30", 8.35, 8.9), ("Uhr.", 8.95, 9.3),
]  # fmt: skip
# Kurzhash der Ausgaben vor AP10a (Stand 35de380), gerechnet wie ``_digest``.
PRE_AP10A_DIGESTS = {
    "ass_tiktok_bold": "59a9719d40ee1bf7",
    "ass_tiktok_words": "87c7e11cf1797377",
    "ass_linkedin_static": "bde27e4ff9db4ac0",
    "cards_tiktok_bold": "fae469b5a1305932",
    "cards_tiktok_words": "42e69658a3cbb594",
    "srt": "786b4d66d15e6bdc",
    "vtt": "f9084ad1461879ce",
}
DIALOGUE = re.compile(r"^Dialogue: 0,(\d+):(\d\d):(\d\d\.\d\d),(\d+):(\d\d):(\d\d\.\d\d),Cap,(.*)$", re.M)


def _sample() -> list[dict]:
    return [{"text": t, "start": s, "end": e} for t, s, e in SAMPLE]


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()[:16]


def _events(ass: str) -> list[tuple[float, float, str]]:
    out = []
    for h1, m1, s1, h2, m2, s2, text in DIALOGUE.findall(ass):
        out.append((int(h1) * 3600 + int(m1) * 60 + float(s1), int(h2) * 3600 + int(m2) * 60 + float(s2), text))
    return out


@pytest.fixture
def policy_version(monkeypatch):
    def use(version: int) -> None:
        monkeypatch.setenv("CHOPSTR_POLICY_VERSION", str(version))
        editorial.clear_cache()

    yield use
    editorial.clear_cache()


def test_policy_v1_keeps_the_old_rules_and_v2_switches_ap10a_on(policy_version):
    policy_version(1)
    assert cap.caption_rules() == cap.LEGACY_RULES
    policy_version(2)
    assert cap.caption_rules() == AP10A
    assert cap.caption_rules(editorial.load(1)) == cap.LEGACY_RULES


def test_switch_off_is_the_rollback(policy_version):
    policy_version(2)
    raw = dict(editorial.load(2).roh)
    raw["implementation"] = {**raw["implementation"], "captions": {"word_bridge": False}}
    off = editorial.Policy(version=2, stand="test", roh=raw)
    assert cap.caption_rules(off) == cap.LEGACY_RULES


def test_v1_output_is_byte_identical_to_before_ap10a(policy_version):
    """Rollback-Nachweis: unter Fassung 1 entstehen dieselben Untertitel wie vor AP10a."""
    policy_version(1)
    w = _sample()
    got = {
        "ass_tiktok_bold": cap.to_ass(w, 0.0, "tiktok_bold"),
        "ass_tiktok_words": cap.to_ass(w, 0.0, "tiktok_words"),
        "ass_linkedin_static": cap.to_ass(w, 0.0, "linkedin_static"),
        "cards_tiktok_bold": cap.cards_for(w, "tiktok_bold"),
        "cards_tiktok_words": cap.cards_for(w, "tiktok_words"),
        "srt": cap.to_srt(w, 0.0, "tiktok_words"),
        "vtt": cap.to_vtt(w, 0.0, "tiktok_bold"),
    }
    assert {k: _digest(v) for k, v in got.items()} == PRE_AP10A_DIGESTS


def test_render_plan_hash_changes_only_with_the_switch(policy_version):
    """Der Plan zählt die Karten. Unter Fassung 1 bleibt die Zahl und damit der Hash; mit AP10a werden
    aus „40" und „Prozent" eine Karte, und der Hash ändert sich (render_plan.py nur gelesen)."""
    out_w, out_h = render_plan.output_size("9:16")
    segments = [{"start": 0.0, "end": 9.3, "role": "body"}]
    shots = reframe.plan_shots_for_positions(segments, [], 1920, 1080, out_w, out_h, [], {}, strategy="neutral")
    rr = reframe.ReframeResult("neutral", "none", False, [], shots, 1920, 1080, out_w, out_h)
    sources = {"storage_key": "k", "transcript_version": 1, "hook_version": 1, "candidate_id": "c"}

    def plan_hash(cards: int) -> str:
        plan = render_plan.build_plan(
            platform="tiktok", segments=segments, reframe_result=rr, caption_preset="tiktok_words",
            caption_cards=cards, sources=sources, src_fps=25.0,
        )  # fmt: skip
        return render_plan.plan_hash(plan, 1, 1)

    pre_ap10a_cards = 18  # ein Wort je Karte, so viele Karten wie Wörter
    policy_version(1)
    v1_cards = len(cap.cards_for(_sample(), "tiktok_words"))
    assert v1_cards == pre_ap10a_cards
    assert plan_hash(v1_cards) == plan_hash(pre_ap10a_cards)
    v1_same = plan_hash(10)
    policy_version(2)
    v2_cards = len(cap.cards_for(_sample(), "tiktok_words"))
    assert v2_cards == 14
    assert plan_hash(v2_cards) != plan_hash(pre_ap10a_cards)
    # Auch bei gleicher Kartenzahl: die Kennung captions_v2 erzwingt einen neuen Render.
    assert plan_hash(10) != v1_same


def test_events_within_a_card_have_no_gaps():
    """RK 2 Befund 9: Events 0,00 bis 0,20 und 0,50 bis 0,70 ließen die Karte in jeder Pause verschwinden."""
    words = [
        {"text": "Das", "start": 0.0, "end": 0.2},
        {"text": "ist", "start": 0.5, "end": 0.7},
        {"text": "gut", "start": 1.0, "end": 1.6},
    ]
    old = _events(cap.to_ass(words, 0.0, "tiktok_bold", rules=cap.LEGACY_RULES))
    assert [(s, e) for s, e, _ in old] == [(0.0, 0.2), (0.5, 0.7), (1.0, 1.6)]
    new = _events(cap.to_ass(words, 0.0, "tiktok_bold", rules=AP10A))
    assert [(s, e) for s, e, _ in new] == [(0.0, 0.5), (0.5, 1.0), (1.0, 1.6)]
    for (_, end, _), (start, _, _) in zip(new, new[1:]):
        assert end == start


def test_gap_above_bridge_max_ends_at_the_word():
    """Feste Wortzahl je Karte (Nutzerstil): dort kann eine Karte längere Pausen enthalten."""
    words = [
        {"text": "Das", "start": 0.0, "end": 0.4},
        {"text": "ist", "start": 0.85, "end": 1.0},  # Lücke 0,45 s > 0,4 s
        {"text": "gut", "start": 1.2, "end": 1.6},
    ]
    preset = cap.style_anwenden(cap.preset_for("tiktok_bold"), {"words_per_card": 3})
    assert len(cap.build_cards(words, preset.max_chars, preset.max_lines, words_per_card=3, rules=AP10A)) == 1
    events = _events(cap.to_ass(words, 0.0, preset, rules=AP10A))
    assert [(s, e) for s, e, _ in events] == [(0.0, 0.4), (0.85, 1.2), (1.2, 1.6)]


def test_multi_word_card_stands_at_least_min_event_s_but_never_into_the_next_card():
    short = [{"text": "Na", "start": 0.0, "end": 0.1}, {"text": "gut.", "start": 0.15, "end": 0.3}]
    events = _events(cap.to_ass(short, 0.0, "tiktok_bold", rules=AP10A))
    assert events[-1][1] == 0.8
    following = [*short, {"text": "Weiter", "start": 0.6, "end": 0.9}]
    events = _events(cap.to_ass(following, 0.0, "tiktok_bold", rules=AP10A))
    assert events[1][1] == 0.6 and events[2][0] == 0.6  # bis zur nächsten Karte, nicht darüber
    static = _events(cap.to_ass(short, 0.0, "linkedin_static", rules=AP10A))
    assert [(s, e) for s, e, _ in static] == [(0.0, 0.8)]


def test_single_word_cards_get_no_minimum_duration():
    words = [{"text": "Na", "start": 0.0, "end": 0.1}, {"text": "gut", "start": 0.6, "end": 0.7}]
    events = _events(cap.to_ass(words, 0.0, "tiktok_words", rules=AP10A))
    assert [(s, e) for s, e, _ in events] == [(0.0, 0.1), (0.6, 0.7)]


def test_bridge_between_cards_one_word_per_card():
    """Jede Caption bis zur nächsten sichtbar: Lücke 0,2 s überbrückt, Lücke 0,6 s nicht."""
    words = [
        {"text": "Das", "start": 0.0, "end": 0.3},
        {"text": "ist", "start": 0.5, "end": 0.8},  # Lücke 0,2 s
        {"text": "gut", "start": 1.4, "end": 1.7},  # Lücke 0,6 s
    ]
    old = _events(cap.to_ass(words, 0.0, "tiktok_words", rules=cap.LEGACY_RULES))
    assert [(s, e) for s, e, _ in old] == [(0.0, 0.3), (0.5, 0.8), (1.4, 1.7)]
    new = _events(cap.to_ass(words, 0.0, "tiktok_words", rules=AP10A))
    assert [(s, e) for s, e, _ in new] == [(0.0, 0.5), (0.5, 0.8), (1.4, 1.7)]
    assert [t for _, _, t in new] == [t for _, _, t in old]  # Stil und Text unverändert
    for (_, end, _), (start, _, _) in zip(new, new[1:]):
        assert end <= start  # keine Überlappung


def test_bridge_between_multi_word_cards_never_overlaps():
    words = _words(["Das", "stimmt.", "Aber", "nicht", "immer."], dur=0.5, gap=0.3)
    events = _events(cap.to_ass(words, 0.0, "tiktok_bold", rules=AP10A))
    starts = sorted({s for s, _, _ in events})
    for s, e, _ in events:
        assert all(not (s < other < e) for other in starts)


def test_style_of_the_events_is_unchanged():
    """Kein Stilwechsel: Kopf, Stilzeile, Farben und Text gleich, nur die Zeiten anders."""
    w = _sample()
    for preset in ("tiktok_bold", "tiktok_words", "linkedin_static", "reels_words", "corporate_third"):
        old = cap.to_ass(w, 0.0, preset, rules=cap.LEGACY_RULES)
        new = cap.to_ass(w, 0.0, preset, rules=AP10A)
        assert old.split("[Events]")[0] == new.split("[Events]")[0], preset
        p = cap.preset_for(preset)
        allowed = {p.base_color, p.highlight_color}
        assert {c for _, _, t in _events(new) for c in re.findall(r"\\c(&H[0-9A-F]+)", t)} <= allowed, preset


@pytest.mark.parametrize(
    "text, token",
    [
        ("Das sind 40 Prozent mehr.", "40 Prozent"),
        ("Es kostet 3,5 Mio. Euro im Jahr.", "3,5 Mio. Euro"),
        ("Dazu kommen 12 € pro Monat.", "12 €"),
        ("Treffen um 14.30 Uhr am Bahnhof.", "14.30 Uhr"),
        ("Wir haben 40.000 Euro verloren.", "40.000 Euro"),
    ],
)
def test_number_and_unit_stay_on_one_card_with_one_word_per_card(text, token):
    words = _words(text.split())
    legacy = [" ".join(w["text"] for w in c) for c in cap.build_cards(words, 15, 1, words_per_card=1, rules=cap.LEGACY_RULES)]
    assert token not in legacy
    cards = [" ".join(w["text"] for w in c) for c in cap.build_cards(words, 15, 1, words_per_card=1, rules=AP10A)]
    assert token in cards
    assert [t for c in cards for t in c.split()] == text.split()


def test_forty_percent_in_one_card_at_words_per_card_one(policy_version):
    policy_version(2)
    cards = cap.cards_for(_words(["Das", "sind", "40", "Prozent", "mehr."]), "tiktok_words")
    assert ["40 Prozent"] in [c["lines"] for c in cards]


def test_number_and_unit_are_never_split_in_semantic_cards():
    words = _words(["Das", "sind", "40", "Prozent", "mehr."])
    assert [[w["text"] for w in c] for c in cap.build_cards(words, 12, 1, rules=cap.LEGACY_RULES)] == [
        ["Das", "sind", "40"], ["Prozent"], ["mehr."],
    ]  # fmt: skip
    assert [[w["text"] for w in c] for c in cap.build_cards(words, 12, 1, rules=AP10A)] == [
        ["Das", "sind"], ["40", "Prozent"], ["mehr."],
    ]  # fmt: skip


@pytest.mark.parametrize("limit", range(11, 30))
def test_hyphenated_word_breaks_only_at_its_hyphens(limit):
    word = "Kunden-Anfrage-Bearbeitung"
    lines = cap.hyphenate(word, limit, AP10A)
    assert "".join(lines) == word  # kein zusätzlicher Trennstrich, nichts verloren
    assert all(line in {"Kunden-", "Anfrage-", "Bearbeitung", "Kunden-Anfrage-", "Anfrage-Bearbeitung", word} for line in lines)


def test_hyphenated_word_was_broken_inside_before():
    assert cap.hyphenate("Kunden-Anfrage-Bearbeitung", 10, cap.LEGACY_RULES) == ["Kunden-An-", "frage-Bea-", "rbeitung"]
    assert cap.hyphenate("Kunden-Anfrage-Bearbeitung", 11, AP10A) == ["Kunden-", "Anfrage-", "Bearbeitung"]


@pytest.mark.parametrize("limit", [15, 20])
def test_hyphen_segment_wider_than_the_line_is_split_further(limit):
    """Zwischen Segmenten nur am Bindestrich; ein Segment, das allein zu breit ist, an Morphemgrenzen."""
    word = "Corona-Soforthilfeprogrammverwaltungsstelle"
    lines = cap.hyphenate(word, limit, AP10A)
    assert all(len(line) <= limit for line in lines), lines
    assert lines[0] == "Corona-"
    assert "".join(line.removesuffix("-") for line in lines[1:]) == "Soforthilfeprogrammverwaltungsstelle"
    assert cap.hyphenate(word, 15, AP10A) == ["Corona-", "Soforthilfe-", "programm-", "verwaltungs-", "stelle"]
    assert cap.hyphenate(word, 20, AP10A) == ["Corona-", "Soforthilfeprogramm-", "verwaltungsstelle"]


def test_trailing_hyphen_stays_at_the_end():
    """„Lieferantendatenbank-“ in „Lieferantendatenbank- und Kundenpflege“: der Bindestrich bleibt am Ende."""
    assert cap.hyphenate("Lieferantendatenbank-", 12, AP10A) == ["Lieferanten-", "datenbank-"]


def test_compound_breaks_at_morpheme_boundaries_not_syllables():
    word = "Kundenanfragenbearbeitung"
    assert cap.hyphenate(word, 10, cap.LEGACY_RULES) == ["Kundenan-", "fragenbea-", "rbeitung"]
    assert cap.hyphenate(word, 10, AP10A) != ["Kundenan-", "fragenbea-", "rbeitung"]
    assert cap.hyphenate(word, 12, AP10A) == ["Kunden-", "anfragen-", "bearbeitung"]
    assert cap.hyphenate(word, 15, AP10A) == ["Kundenanfragen-", "bearbeitung"]
    # Glied breiter als die Zeile: erst an der Morphemgrenze, dann pyphen ohne Einzelbuchstaben.
    assert cap.hyphenate(word, 10, AP10A) == ["Kunden-", "anfragen-", "bearbei-", "tung"]


@pytest.mark.parametrize(
    "word, limit, expected",
    [
        ("Donaudampfschifffahrtsgesellschaft", 16, ["Donaudampf-", "schifffahrts-", "gesellschaft"]),
        ("Krankenversicherungsbeitragsbemessungsgrenze", 15, ["Kranken-", "versicherungs-", "beitrags-", "bemessungs-", "grenze"]),
        ("Bundesgesundheitsministerium", 15, ["Bundes-", "gesundheits-", "ministerium"]),
        ("Unternehmensberatung", 15, ["Unternehmens-", "beratung"]),
        ("Vertriebsmitarbeiterin", 15, ["Vertriebs-", "mitarbeiterin"]),
        ("Zeitungsverlag", 10, ["Zeitungs-", "verlag"]),
        ("Steuererhöhung", 9, ["Steuer-", "erhöhung"]),
    ],
)
def test_morpheme_boundaries_with_fugen(word, limit, expected):
    lines = cap.hyphenate(word, limit, AP10A)
    assert lines == expected
    assert "".join(line.removesuffix("-") for line in lines) == word


def test_comma_breaks_only_on_overflow():
    """P30: ein Komma bricht die Karte nur, wenn sie sonst die Zeilenbreite der Karte überschreitet."""
    fits = _words(["Ja,", "das", "stimmt."])
    assert [len(c) for c in cap.build_cards(fits, 20, 2, rules=cap.LEGACY_RULES)] == [1, 2]
    assert [len(c) for c in cap.build_cards(fits, 20, 2, rules=AP10A)] == [3]
    overflow = _words(["Wenn", "man", "das", "anschaut,", "sieht", "man", "eigentlich", "sofort", "den", "Unterschied."])
    cards = [" ".join(w["text"] for w in c) for c in cap.build_cards(overflow, 24, 1, rules=AP10A)]
    # Der Satzteil nach dem Komma passt nicht mehr dazu, also bricht die Karte am Komma.
    assert cards[0] == "Wenn man das anschaut,"
    assert all(len(c) <= 24 for c in cards)


@pytest.mark.parametrize("case", PARITY["unit_tokens"], ids=lambda c: c["text"])
def test_parity_unit_tokens(case):
    tokens = cap._tokens(_words(case["text"].split()), "text", AP10A, case["limit"])
    assert [[w["text"] for w in t] for t in tokens] == case["expected"]


@pytest.mark.parametrize("case", PARITY["hyphen_words"], ids=lambda c: f"{c['word']}:{c['limit']}")
def test_parity_hyphen_words(case):
    assert cap.hyphenate(case["word"], case["limit"], AP10A) == case["expected"]


@pytest.mark.parametrize("case", PARITY["cards"], ids=lambda c: c["text"])
def test_parity_cards(case):
    cards = cap.build_cards(case["words"], case["limit"], case["max_lines"], rules=AP10A)
    assert [[w["text"] for w in c] for c in cards] == case["expected"]


def test_parity_unit_words():
    assert sorted(cap.UNIT_WORDS) == PARITY["unit_words"]


def test_render_plan_names_the_caption_rules(policy_version):
    policy_version(1)
    assert render_plan.plan_versions() == render_plan.VERSIONS
    policy_version(2)
    assert render_plan.plan_versions()["captions_de"] == "captions_v2"
    assert render_plan.VERSIONS["captions_de"] == "captions_v1"


def test_number_and_units_shrink_to_the_line_width():
    """„3,5 Milliarden Euro" hat 19 Zeichen und passt bei tiktok_words (15 Zeichen) nicht in eine Zeile."""
    preset = cap.preset_for("tiktok_words")
    words = _words(["Das", "kostet", "3,5", "Milliarden", "Euro."])
    cards = cap.build_cards(words, preset.max_chars, preset.max_lines, words_per_card=1, rules=AP10A)
    assert [[w["text"] for w in c] for c in cards] == [["Das"], ["kostet"], ["3,5", "Milliarden"], ["Euro."]]
    for card in cards:
        for line in cap.card_lines(card, preset, rules=AP10A):
            assert len(" ".join(t for _, t in line)) <= preset.max_chars


def test_time_with_colon_is_a_number():
    tokens = cap._tokens(_words(["um", "14:30", "Uhr"]), "text", AP10A)
    assert [[w["text"] for w in t] for t in tokens] == [["um"], ["14:30", "Uhr"]]


@pytest.mark.parametrize(
    "text, token",
    [("Es kostet 40 Prozent", "40 Prozent"), ("Ab sofort 14.30 Uhr", "14.30 Uhr")],
)
def test_number_and_unit_are_never_split_over_two_lines(text, token):
    preset = cap.style_anwenden(cap.preset_for("tiktok_bold"), {"font_px": 104, "words_per_card": 4})
    assert preset.max_chars == 15 and preset.max_lines == 2
    words = _words(text.split())
    card = cap.build_cards(words, preset.max_chars, preset.max_lines, words_per_card=4, rules=AP10A)[0]
    legacy = [" ".join(t for _, t in ln) for ln in cap.card_lines(card, preset, rules=cap.LEGACY_RULES)]
    assert not any(token in ln for ln in legacy), legacy  # vorher über zwei Zeilen verteilt
    lines = [" ".join(t for _, t in ln) for ln in cap.card_lines(card, preset, rules=AP10A)]
    assert lines[-1] == token
    assert all(len(ln) <= preset.max_chars for ln in lines)


def test_overlapping_asr_times_never_reach_into_the_next_card():
    words = [
        {"text": "Das", "start": 0.0, "end": 0.6},
        {"text": "stimmt", "start": 0.5, "end": 0.9},  # ASR-Zeiten überlappen
    ]
    old = _events(cap.to_ass(words, 0.0, "tiktok_words", rules=cap.LEGACY_RULES))
    assert old[0][1] == 0.6
    new = _events(cap.to_ass(words, 0.0, "tiktok_words", rules=AP10A))
    assert [(s, e) for s, e, _ in new] == [(0.0, 0.5), (0.5, 0.9)]


def test_bridge_tolerates_float_noise():
    words = [{"text": "Na", "start": 0.0, "end": 0.7}, {"text": "gut", "start": 1.1, "end": 1.5}]
    assert 1.1 - 0.7 > 0.4  # Gleitkomma: 0,40000000000000013
    events = _events(cap.to_ass(words, 0.0, "tiktok_words", rules=AP10A))
    assert events[0][1] == 1.1


def test_cards_for_srt_and_vtt_end_like_the_burned_in_video(policy_version):
    words = [
        {"text": "Das", "start": 0.0, "end": 0.3},
        {"text": "ist", "start": 0.5, "end": 0.8},
        {"text": "gut.", "start": 1.4, "end": 1.7},
    ]
    policy_version(1)
    assert [c["end"] for c in cap.cards_for(words, "tiktok_words")] == [0.3, 0.8, 1.7]
    policy_version(2)
    cards = cap.cards_for(words, "tiktok_words")
    events = _events(cap.to_ass(words, 0.0, "tiktok_words"))
    assert [c["end"] for c in cards] == [0.5, 0.8, 1.7] == [e for _, e, _ in events]
    short = [{"text": "Na", "start": 0.0, "end": 0.1}, {"text": "gut.", "start": 0.15, "end": 0.3}]
    assert "00:00:00,000 --> 00:00:00,800" in cap.to_srt(short, 0.0, "tiktok_bold")
    assert "00:00:00.000 --> 00:00:00.800" in cap.to_vtt(short, 0.0, "tiktok_bold")
