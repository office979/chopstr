"""Stille-Messung: Parser, Binärsuche, Integration in die Satzgrenzen.

Die reinen Funktionen laufen ohne ffmpeg. Die Tests mit echtem Ton sind mit
``needs_ffmpeg`` markiert und überspringen sich, wenn ffmpeg fehlt.
"""

from __future__ import annotations

import shutil
import subprocess
import time

import pytest

from chopstr_worker.pipeline import dach_nlp, segment, silence

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg fehlt")


# -- Parser --------------------------------------------------------------------------------
def test_parse_liest_start_end_paare():
    log = (
        "[silencedetect @ 0x1] silence_start: 1.545813\n"
        "[silencedetect @ 0x1] silence_end: 2.631646 | silence_duration: 1.085833\n"
        "[silencedetect @ 0x1] silence_start: 6.426083\n"
        "[silencedetect @ 0x1] silence_end: 8.6155 | silence_duration: 2.189417\n"
    )
    gaps = silence.parse(log)
    assert len(gaps) == 2
    assert gaps[0].start == 1.546 and gaps[0].end == 2.632
    assert round(gaps[1].length, 2) == 2.19


def test_parse_ignoriert_unvollstaendiges_paar():
    """Ein offener silence_start ohne Ende (Datei endet in Stille) erzeugt kein Intervall."""
    assert silence.parse("silence_start: 3.0\n") == []


def test_parse_ignoriert_leeres_intervall():
    assert silence.parse("silence_start: 3.0\nsilence_end: 3.0\n") == []


def test_parse_ohne_treffer():
    assert silence.parse("nichts hier") == []


# -- Binärsuche ----------------------------------------------------------------------------
@pytest.fixture
def karte() -> silence.SilenceMap:
    return silence.SilenceMap(
        [
            silence.Gap(1.55, 2.63),
            silence.Gap(6.43, 8.62),
            silence.Gap(10.89, 11.84),
            silence.Gap(14.26, 15.06),
        ]
    )


def test_gap_at_findet_und_verfehlt(karte):
    assert karte.gap_at(2.0) is not None
    assert karte.gap_at(7.5).length == pytest.approx(2.19)
    assert karte.gap_at(5.0) is None  # zwischen zwei Pausen
    assert karte.gap_at(0.1) is None  # vor der ersten
    assert karte.gap_at(99.0) is None  # nach der letzten


def test_gap_at_an_den_raendern(karte):
    assert karte.is_silent_at(1.55)
    assert karte.is_silent_at(2.63)
    assert not karte.is_silent_at(2.64)


def test_pause_between_zaehlt_nur_echte_stille(karte):
    # Wortende 6.40, naechster Wortanfang 8.65: dazwischen 2.19s echte Stille,
    # obwohl die Wortluecke 2.25s betraegt.
    assert karte.pause_between(6.40, 8.65) == pytest.approx(2.19, abs=0.01)
    # Kein Ueberlapp -> keine Pause, obwohl Zeit vergeht.
    assert karte.pause_between(3.0, 5.0) == 0.0
    assert karte.pause_between(5.0, 3.0) == 0.0


def test_pause_between_ueber_mehrere_pausen(karte):
    gesamt = karte.pause_between(1.0, 12.0)
    assert gesamt == pytest.approx(1.08 + 2.19 + 0.95, abs=0.02)


def test_boundary_is_clean(karte):
    assert karte.boundary_is_clean(7.5)  # mitten in einer langen Pause
    assert not karte.boundary_is_clean(6.44)  # 10ms hinter dem Pausenanfang
    assert not karte.boundary_is_clean(5.0)  # gar keine Pause


def test_snap_zieht_auf_saubere_stelle(karte):
    assert karte.snap(7.5) == pytest.approx(7.5)  # schon sauber, bleibt
    s = karte.snap(6.43)  # exakt am Pausenanfang
    assert s is not None and karte.boundary_is_clean(s)
    assert karte.snap(5.0, max_shift=0.3) is None  # zu weit weg, ehrlich None


def test_snap_ueberschreitet_max_shift_nicht(karte):
    s = karte.snap(6.20, max_shift=0.40)
    assert s is not None and abs(s - 6.20) <= 0.40


def test_leere_karte_bleibt_benutzbar():
    leer = silence.EMPTY
    assert len(leer) == 0
    assert leer.gap_at(1.0) is None
    assert leer.pause_between(0.0, 5.0) == 0.0
    assert leer.snap(1.0) is None
    assert not leer.boundary_is_clean(1.0)


# -- Integration in die Satzgrenzen ---------------------------------------------------------
def test_verschluckte_pause_erzeugt_trotzdem_eine_satzgrenze():
    """Der Kernfall: Wortzeiten zeigen keine Luecke, im Ton liegen 2,19s Stille.

    Ohne Stille-Karte entsteht keine Satzgrenze, mit Karte schon.
    """
    words = [
        {"text": "schneidest", "start": 5.8, "end": 6.42},
        {"text": "Erstens", "start": 6.45, "end": 9.10},  # Luecke nur 0,03s
    ]
    assert not dach_nlp.is_sentence_end(words, 0, 0.7)

    karte = silence.SilenceMap([silence.Gap(6.43, 8.62)])
    assert dach_nlp.is_sentence_end(words, 0, 0.7, karte)


def test_ohne_karte_unveraendertes_verhalten():
    words = [
        {"text": "eins", "start": 0.0, "end": 1.0},
        {"text": "zwei", "start": 2.0, "end": 3.0},
    ]
    assert dach_nlp.is_sentence_end(words, 0, 0.7) is True
    assert dach_nlp.is_sentence_end(words, 0, 0.7, silence.EMPTY) is True


def test_karte_erfindet_keine_grenze():
    """Ohne echte Stille darf die Karte keine zusaetzliche Grenze erzeugen."""
    words = [
        {"text": "und", "start": 1.0, "end": 1.2},
        {"text": "dann", "start": 1.25, "end": 1.5},
    ]
    karte = silence.SilenceMap([silence.Gap(50.0, 60.0)])
    assert not dach_nlp.is_sentence_end(words, 0, 0.7, karte)


def test_sentences_from_words_nutzt_die_karte():
    words = [
        {"text": "Heute", "start": 0.0, "end": 0.5},
        {"text": "so", "start": 0.55, "end": 6.42},
        {"text": "Erstens", "start": 6.45, "end": 7.0},
        {"text": "fertig", "start": 7.05, "end": 9.0},
    ]
    karte = silence.SilenceMap([silence.Gap(6.43, 8.62)])
    ohne = segment.sentences_from_words(words)
    mit = segment.sentences_from_words(words, silence=karte)
    assert len(mit) > len(ohne)


def test_snap_candidates_zieht_grenzen_und_laesst_sonst_in_ruhe():
    cands = [segment.Candidate(0, 1, start=6.43, end=11.0, text="x")]
    karte = silence.SilenceMap([silence.Gap(6.43, 8.62), silence.Gap(10.89, 11.84)])
    out = segment.snap_candidates(cands, karte)
    assert karte.boundary_is_clean(out[0].start)
    assert karte.boundary_is_clean(out[0].end)
    # Ohne Karte unveraendert
    assert segment.snap_candidates(cands, None)[0].start == 6.43
    assert segment.snap_candidates(cands, silence.EMPTY)[0].start == 6.43


def test_snap_candidates_zieht_nicht_zu_einem_nichts_zusammen():
    cands = [segment.Candidate(0, 0, start=6.50, end=6.90, text="kurz")]
    karte = silence.SilenceMap([silence.Gap(6.43, 8.62)])
    out = segment.snap_candidates(cands, karte)
    assert out[0].start == 6.50 and out[0].end == 6.90


# -- Mit echtem Ton -------------------------------------------------------------------------
@pytest.fixture
def tondatei(tmp_path):
    """4 Toene mit Pausen dazwischen: still 0-1, Ton 1-2, still 2-4, Ton 4-5, still 5-5.5, Ton 5.5-6.5"""
    p = tmp_path / "ton.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=f=440:r=48000:d=6.5",
            "-af",
            "volume='if(between(t,1,2)+between(t,4,5)+between(t,5.5,6.5),1,0)':eval=frame",
            str(p),
        ],
        check=True,
    )
    return str(p)


@needs_ffmpeg
def test_scan_findet_die_echten_pausen(tondatei):
    silence.clear_cache()
    karte = silence.scan(tondatei)
    assert len(karte) >= 3
    assert karte.is_silent_at(3.0)  # lange Pause 2-4
    assert not karte.is_silent_at(1.5)  # mitten im Ton
    assert not karte.is_silent_at(4.5)
    lange = karte.long_gaps(1.5)
    assert len(lange) == 1 and lange[0].length == pytest.approx(2.0, abs=0.15)


@needs_ffmpeg
def test_scan_cache_spart_den_zweiten_durchlauf(tondatei):
    silence.clear_cache()
    t0 = time.perf_counter()
    a = silence.scan(tondatei)
    erste = time.perf_counter() - t0

    t0 = time.perf_counter()
    b = silence.scan(tondatei)
    zweite = time.perf_counter() - t0

    assert a is b, "zweiter Scan muss aus dem Cache kommen"
    assert zweite < erste / 5, f"Cache greift nicht: {erste:.3f}s dann {zweite:.3f}s"


@needs_ffmpeg
def test_abfragen_brauchen_keinen_weiteren_prozess(tondatei):
    """400 Grenzpruefungen muessen ohne ffmpeg-Start auskommen und sehr schnell sein.

    Das ist der Laufzeitpunkt: frueher ein Prozess je Grenze, jetzt Binaersuche.
    """
    silence.clear_cache()
    karte = silence.scan(tondatei)
    t0 = time.perf_counter()
    for i in range(400):
        karte.boundary_is_clean(i * 0.0163)
        karte.snap(i * 0.0163)
    dauer = time.perf_counter() - t0
    assert dauer < 0.2, f"400 Abfragen dauerten {dauer:.3f}s"


@needs_ffmpeg
def test_scan_ohne_datei_gibt_leere_karte():
    assert len(silence.scan("/gibt/es/nicht.wav")) == 0
