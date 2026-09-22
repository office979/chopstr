"""Schweizerdeutsch-Beta (Phase 5c): Dialekterkennung, sichere Normalisierung, getrennte Ausgabe in Captions,
Activity ``fuse_and_nlp`` mit ``stats.dialect`` und Hinweis."""

from __future__ import annotations

import pytest

from chopstr_worker import config
from chopstr_worker.activities import nlp as act_nlp
from chopstr_worker.activities.transcribe import asr_key_for, diar_key_for
from chopstr_worker.pipeline import captions_de, dach_nlp, render
from chopstr_worker.pipeline import transcribe as asr

CH = "Hoi zäme, das isch nöd öppis, wo mer chli gsi sind, gäll. Merci vilmal, jetz hät es gnueg, wänn du chunsch."
AT = "Heuer im Jänner war das Sackerl mit den Paradeisern und der Semmel leiwand, oida, passt eh."
DE = "Wir haben im Januar den Umsatz um zwei Prozent gesteigert, und das ist nicht wenig für ein kleines Team."


def _words(text: str, dur: float = 0.3, gap: float = 0.1) -> list[dict]:
    out, t = [], 0.0
    for tok in text.split():
        out.append({"text": tok, "start": round(t, 3), "end": round(t + dur, 3), "prob": 0.9, "speaker": "SPEAKER_00"})
        t += dur + gap
    return out


def test_detect_dialect_ch_at_de():
    ch = dach_nlp.detect_dialect(_words(CH))
    assert ch["variant"] == "de-CH" and ch["confidence"] == 1.0
    assert {"isch", "nöd", "öppis", "chli", "gsi", "gäll", "merci", "jetz", "hät", "wänn", "mer"} <= set(ch["markers"])
    at = dach_nlp.detect_dialect(_words(AT))
    assert at["variant"] == "de-AT" and at["confidence"] == 1.0 and at["markers"][:1] == ["heuer"] or "heuer" in at["markers"]
    assert {"jänner", "sackerl", "semmel", "leiwand", "oida"} <= set(at["markers"])
    de = dach_nlp.detect_dialect(_words(DE))
    assert de == {"variant": "de", "confidence": 0.0, "markers": [], "ratios": {"de-CH": 0.0, "de-AT": 0.0}, "word_count": len(DE.split())}
    assert dach_nlp.detect_dialect([])["variant"] == "de"


def test_detect_dialect_thresholds_and_weak_markers():
    # ein einzelner Marker in 100 Wörtern reicht nicht (Mindesttreffer 2, Anteil 2 %)
    words = _words(" ".join(["Wort"] * 99 + ["isch"]))
    assert dach_nlp.detect_dialect(words)["variant"] == "de"
    # zwei starke Marker in 100 Wörtern: genau an der Schwelle, Sicherheit 0,2
    words = _words(" ".join(["Wort"] * 98 + ["isch", "nöd"]))
    d = dach_nlp.detect_dialect(words)
    assert d["variant"] == "de-CH" and d["confidence"] == pytest.approx(0.2)
    # schwache Marker („eh", „passt") zählen halb: vier davon in 100 Wörtern ergeben 2 Treffer
    words = _words(" ".join(["Wort"] * 96 + ["eh", "passt", "eh", "passt"]))
    d = dach_nlp.detect_dialect(words)
    assert d["variant"] == "de-AT" and d["ratios"]["de-AT"] == pytest.approx(0.02)
    # drei schwache Marker (1,5 Treffer) reichen nicht
    words = _words(" ".join(["Wort"] * 97 + ["eh", "passt", "eh"]))
    assert dach_nlp.detect_dialect(words)["variant"] == "de"
    assert dach_nlp.WEAK_MARKERS <= (dach_nlp.CH_MARKERS | dach_nlp.AT_MARKERS)


def test_normalize_ch_only_safe_entries_and_never_protected_terms():
    assert dach_nlp.normalize_ch("nöd") == "nicht"
    assert dach_nlp.normalize_ch("Isch,") == "Ist,"
    assert dach_nlp.normalize_ch("chli") == "ein wenig"
    assert dach_nlp.normalize_ch("gsi.") == "gewesen."
    assert dach_nlp.normalize_ch("Öppis?") == "Etwas?"
    assert dach_nlp.normalize_ch("jetz") == "jetzt" and dach_nlp.normalize_ch("hät") == "hat" and dach_nlp.normalize_ch("wänn") == "wenn"
    # regionale Wörter ohne sichere Entsprechung werden nie umgeschrieben (P2)
    for w in ("Velo", "Merci", "gäll", "hoi", "chum", "mer", "Grüezi", "Semmel", "heuer"):
        assert dach_nlp.normalize_ch(w) is None
    # geschützte Begriffe nie, auch wenn eine Entsprechung existiert
    assert dach_nlp.normalize_ch("nöd", ["nöd"]) is None
    assert dach_nlp.normalize_ch("Isch", ["isch"]) is None
    assert dach_nlp.normalize_ch("gsi", ["GSI"]) is None
    assert dach_nlp.normalize_ch("", []) is None and dach_nlp.normalize_ch("...", []) is None


def test_annotate_writes_text_norm_only_for_ch():
    words = _words("Das isch nöd gsi, gäll.")
    dach_nlp.annotate(words)  # ohne Dialekt: kein text_norm
    assert not any("text_norm" in w for w in words)
    dach_nlp.annotate(words, dialect="de-CH", protected_terms=["gsi"])
    by = {w["text"]: w for w in words}
    assert by["isch"]["text_norm"] == "ist" and by["nöd"]["text_norm"] == "nicht"
    assert "text_norm" not in by["gsi,"] and "text_norm" not in by["gäll."] and "text_norm" not in by["Das"]
    assert all(w["text"] in ("Das", "isch", "nöd", "gsi,", "gäll.") for w in words)  # Original bleibt
    assert by["nöd"]["negation"] is True and words[-1]["sentence_idx"] == 0


def test_captions_use_text_norm_with_fallback(tmp_path):
    words = _words("Das isch nöd gsi, gäll.")
    dach_nlp.annotate(words, dialect="de-CH", protected_terms=["gsi"])
    assert captions_de.word_text(words[1], "text_norm") == "ist" and captions_de.word_text(words[3], "text_norm") == "gsi,"
    assert captions_de.word_text(words[1]) == "isch"
    orig = captions_de.to_srt(words, 0.0, 30)
    norm = captions_de.to_srt(words, 0.0, 30, text_field="text_norm")
    assert "Das isch nöd gsi," in orig and "Das ist nicht gsi," in norm
    vtt = captions_de.to_vtt(words, 0.0, 30, text_field="text_norm")
    assert vtt.startswith("WEBVTT") and "ist nicht gsi," in vtt and "isch" not in vtt
    ass = captions_de.to_ass(words, 0.0, "tiktok_bold", text_field="text_norm")
    assert "nicht" in ass and "isch" not in ass
    cards = captions_de.cards_for(words, "tiktok_bold", text_field="text_norm")
    assert cards and "ist nicht gsi," in " ".join(" ".join(c["lines"]) for c in cards)
    assert captions_de.cps_warnings(captions_de.build_cards(words, 30, 2, "text_norm"), text_field="text_norm") == []
    with pytest.raises(ValueError, match="Caption-Textfeld"):
        captions_de.to_srt(words, 0.0, 30, text_field="lemma")
    paths = render.write_captions(words, captions_de.PRESETS["tiktok_bold"], (1080, 1920), tmp_path, "ch", text_field="text_norm")
    from pathlib import Path

    assert "ist nicht" in Path(paths["srt"]).read_text(encoding="utf-8")
    assert "ist nicht" in Path(paths["vtt"]).read_text(encoding="utf-8")


def test_transcribe_result_marks_ch_as_beta():
    r = asr.TranscriptResult(words=[], model_id="m", variant="de-CH", beta=True)
    assert r.to_dict()["beta"] is True
    assert asr.TranscriptResult(words=[], model_id="m", variant="de").beta is False
    assert "de-CH" in asr.VARIANTS


@pytest.fixture
def ch_source(fake_db, fake_context, monkeypatch):
    monkeypatch.setenv("ASR_MODEL_DE", "dummy/model")
    config.reload()
    fake_context.settings = config.settings()
    wid = fake_db.add_workspace()
    pid = fake_db.add_brand_profile(wid, asr_variant="de", protected_terms=["gsi"], brand_vocab=[])
    sid = fake_db.add_source(wid, "uploads/ch.mp4", brand_profile_id=pid, audio_key="audio/ch.wav", duration_s=6.0, status="analyzing")
    s = fake_context.settings
    akey = asr_key_for("audio/ch.wav", "de", [], "dummy/model", s)
    fake_context.store.put_json("derived", akey, {"words": _words(CH), "model_id": "dummy/model", "variant": "de", "beta": False})
    dkey = diar_key_for("audio/ch.wav", None, s.diarizer_model or asr._DEFAULT_DIARIZER)
    fake_context.store.put_json("derived", dkey, {"turns": [[0.0, 10.0, "SPEAKER_00"]], "model_id": "diar-x"})
    return sid


def test_fuse_and_nlp_writes_dialect_stats_and_hint(fake_db, fake_context, ch_source):
    act_nlp.run(fake_context, ch_source)
    tv = fake_db.transcript_versions[-1]
    stats = tv["stats"]
    assert stats["dialect"]["variant"] == "de-CH" and stats["dialect"]["confidence"] > 0.5
    assert "isch" in stats["dialect"]["markers"] and set(stats["dialect"]) == {"variant", "confidence", "markers"}
    words = tv["words"]
    by = {w["text"]: w for w in words}
    assert by["isch"]["text_norm"] == "ist" and by["nöd"]["text_norm"] == "nicht"
    assert "text_norm" not in by["gsi"]  # geschützter Begriff des Markenprofils
    assert stats["text_norm_count"] == sum(1 for w in words if w.get("text_norm")) >= 5
    fin = fake_db.events_for(act_nlp.STEP)[-1]
    assert fin["status"] == "finished" and fin["payload"]["hint"] == act_nlp.HINT_CH_MODEL
    assert act_nlp.HINT_CH_MODEL in fin["message"] and fin["payload"]["dialect"]["variant"] == "de-CH"
