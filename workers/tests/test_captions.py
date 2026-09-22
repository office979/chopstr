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
    assert set(cap.PRESETS) == {"tiktok_bold", "reels_clean", "shorts_clean", "linkedin_static", "corporate_third"}
    assert cap.preset_for("tiktok").name == "tiktok_bold"
    assert cap.preset_for("linkedin").name == "linkedin_static"
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
    fast = [{"text": "Donaudampfschifffahrtsgesellschaft", "start": 0.0, "end": 0.5}]
    assert cap.cps_warnings([fast])
    slow = [{"text": "Hallo", "start": 0.0, "end": 2.0}]
    assert cap.cps_warnings([slow]) == []


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
