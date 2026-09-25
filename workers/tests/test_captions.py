from __future__ import annotations

from chopstr_worker.pipeline import captions_de as cap


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
