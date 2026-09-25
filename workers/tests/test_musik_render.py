"""Musik im ECHTEN Renderlauf: kommt sie im fertigen MP4 an, und stimmt die Lautheit?

Die Filterkette allein zu pruefen reicht nicht. Die Musik muss durch beide Loudness-Paesse, an der
richtigen Eingangsnummer haengen und neben dem Logo bestehen - genau dort sind die Fehler, die
man einem fertigen Video nicht ansieht.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from chopstr_worker.pipeline import captions_de, reframe, render, render_plan
from tests.conftest import requires_ffmpeg

pytest.importorskip("imageio_ffmpeg")


def _ffmpeg() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


SEGMENTE = [{"start": 0.0, "end": 4.0}]


def _plan(musik: dict | None = None) -> dict:
    """Ein echter Plan über render_plan.build_plan - kein von Hand gebautes Wörterbuch.

    Ein handgebauter Plan prüft die eigene Annahme über den Plan, nicht den Plan."""
    aspect = "9:16"
    out_w, out_h = render_plan.output_size(aspect)
    shots = reframe.plan_shots_for_positions(SEGMENTE, [], 720, 1280, out_w, out_h, [], {}, strategy="neutral")
    rf = reframe.ReframeResult("neutral", "none", False, [], shots, 720, 1280, out_w, out_h)
    return render_plan.build_plan(
        platform="tiktok", aspect=aspect, segments=SEGMENTE, reframe_result=rf,
        caption_preset=captions_de.PLATFORM_DEFAULT_PRESET["tiktok"], caption_cards=0,
        sources={"storage_key": "uploads/x", "transcript_version": 1, "hook_version": 1, "candidate_id": "c"},
        src_fps=25.0, musik=musik,
    )  # fmt: skip


def _quelle(tmp_path: Path, dauer: float = 4.0) -> Path:
    """Ein Video mit Ton: Farbbalken und ein 1000-Hz-Ton als „Sprache"."""
    p = tmp_path / "quelle.mp4"
    subprocess.run(
        [_ffmpeg(), "-y", "-v", "error",
         "-f", "lavfi", "-i", f"testsrc=size=720x1280:rate=25:duration={dauer}",
         "-f", "lavfi", "-i", f"sine=frequency=1000:duration={dauer}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(p)],
        check=True,
    )  # fmt: skip
    return p


def _musikdatei(tmp_path: Path) -> Path:
    """Laenger als der Clip - der Normalfall. 300 Hz, damit sie sich messen laesst."""
    p = tmp_path / "musik.mp3"
    subprocess.run(
        [_ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=30", str(p)],
        check=True,
    )
    return p


def _band_pegel(datei: Path, mitte: int, tmp_path: Path) -> float:
    """Pegel in einem schmalen Band. Was durchkommt, war im Ton."""
    aus = tmp_path / f"band{mitte}.wav"
    subprocess.run(
        [_ffmpeg(), "-y", "-v", "error", "-i", str(datei), "-vn",
         "-af", f"bandpass=f={mitte}:width_type=h:w=60", str(aus)],
        check=True,
    )  # fmt: skip
    r = subprocess.run(
        [_ffmpeg(), "-v", "error", "-i", str(aus), "-af", "astats=metadata=1:reset=0,ametadata=print:file=-", "-f", "null", "-"],
        capture_output=True, text=True,
    )  # fmt: skip
    werte = [float(z.split("=")[1]) for z in r.stdout.splitlines() if "RMS_level=" in z and "-inf" not in z]
    return max(werte) if werte else -99.0


@requires_ffmpeg
def test_ohne_musik_entsteht_trotzdem_ein_clip(tmp_path):
    """Der Regressionstest: ein Plan ohne Musik darf sich kein Stück anders verhalten."""
    quelle = _quelle(tmp_path)
    aus = tmp_path / "ohne.mp4"
    r = render.render_from_plan(_plan(), quelle, None, aus)
    assert Path(r.out_path).is_file()


@requires_ffmpeg
def test_die_musik_ist_im_fertigen_video_messbar_lauter(tmp_path):
    """Zweimal rendern, einmal ohne und einmal mit Musik, und bei 300 Hz vergleichen.

    Warum der Vergleich und keine feste Schwelle: mein erster Versuch war „ohne Musik muss der
    Pegel bei 300 Hz unter -55 dB liegen". Gemessen wurden -39,7 dB - der Grundrauschteppich aus
    AAC-Kodierung und der Flanke des Bandpasses, ganz ohne Musik. Die Gegenprobe „mit Musik ueber
    -50 dB" waere damit auch OHNE Musik durchgelaufen: ein Test, der nichts beweist und trotzdem
    gruen ist. Der Unterschied zwischen zwei Laeufen kennt dieses Problem nicht.

    Ducking ist hier AUS. Der Testton ist durchgehende „Sprache" ohne eine einzige Pause; mit
    Ducking waere die Musik die ganze Zeit gesenkt, und gemessen wuerde nicht „kommt sie an",
    sondern „wie stark duckt es". Das ist die naechste Frage, nicht diese."""
    quelle = _quelle(tmp_path)
    mus = _musikdatei(tmp_path)

    ohne = tmp_path / "ohne.mp4"
    render.render_from_plan(_plan(), quelle, None, ohne)
    grundrauschen = _band_pegel(ohne, 300, tmp_path)

    mit = tmp_path / "mit.mp4"
    plan = _plan({"datei": "egal", "ab_s": 12.0, "lautstaerke_db": -10.0, "ducking": False})
    render.render_from_plan(plan, quelle, None, mit, musik_path=mus)
    with_musik = _band_pegel(mit, 300, tmp_path)

    assert with_musik > grundrauschen + 10, (
        f"Mit Musik {with_musik:.1f} dB, ohne {grundrauschen:.1f} dB - die Musik ist nicht angekommen"
    )
    # Und die Sprache ist noch da: eine Mischung, die sie verschluckt, waere schlimmer als keine.
    sprache = _band_pegel(mit, 1000, tmp_path)
    assert sprache > with_musik, f"Musik {with_musik:.1f} dB uebertoent die Sprache {sprache:.1f} dB"


@requires_ffmpeg
def test_ducking_senkt_die_musik_unter_der_sprache(tmp_path):
    """Zweimal dieselbe Mischung, einmal mit und einmal ohne Ducking.

    Das ist der Kern des Features: eine feste Lautstaerke ist immer falsch - in den Pausen zu
    leise, unter den Worten zu laut. Wenn sidechaincompress wirkt, MUSS die Musik unter
    durchgehender Sprache hoerbar leiser sein als ohne."""
    quelle = _quelle(tmp_path)
    mus = _musikdatei(tmp_path)

    def pegel(ducking: bool) -> float:
        aus = tmp_path / f"duck{ducking}.mp4"
        plan = _plan({"datei": "egal", "lautstaerke_db": -10.0, "ducking": ducking})
        render.render_from_plan(plan, quelle, None, aus, musik_path=mus)
        return _band_pegel(aus, 300, tmp_path)

    mit_duck = pegel(True)
    ohne_duck = pegel(False)
    assert mit_duck < ohne_duck - 3, (
        f"Ducking wirkt nicht: mit {mit_duck:.1f} dB, ohne {ohne_duck:.1f} dB"
    )


@requires_ffmpeg
def test_ohne_dateipfad_wird_ohne_musik_gerendert(tmp_path):
    """Steht Musik im Plan, fehlt aber die Datei, entsteht trotzdem ein Clip - ohne Musik.

    Ein Clip ohne Musik ist besser als kein Clip. Gemessen gegen denselben Lauf ohne Musik im
    Plan: beide muessen bei 300 Hz gleich still sein."""
    quelle = _quelle(tmp_path)

    ohne = tmp_path / "ohne.mp4"
    render.render_from_plan(_plan(), quelle, None, ohne)

    aus = tmp_path / "ohnedatei.mp4"
    r = render.render_from_plan(_plan({"datei": "verschwunden.mp3"}), quelle, None, aus)  # kein musik_path
    assert Path(r.out_path).is_file()
    assert abs(_band_pegel(aus, 300, tmp_path) - _band_pegel(ohne, 300, tmp_path)) < 3


@requires_ffmpeg
def test_die_lautheit_bleibt_im_ziel(tmp_path):
    """Musik VOR loudnorm: sonst liegt der fertige Clip um die Musik ueber dem Ziel.

    Gemessen mit ebur128 am fertigen MP4, gegen die Zielvorgabe des Plans."""
    quelle = _quelle(tmp_path)
    mus = _musikdatei(tmp_path)
    aus = tmp_path / "laut.mp4"
    plan = _plan({"datei": "egal", "lautstaerke_db": -6.0, "ducking": False})
    render.render_from_plan(plan, quelle, None, aus, musik_path=mus)

    r = subprocess.run(
        [_ffmpeg(), "-v", "info", "-i", str(aus), "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True,
    )  # fmt: skip
    zeilen = [z for z in r.stderr.splitlines() if "I:" in z and "LUFS" in z]
    assert zeilen, r.stderr[-800:]
    gemessen = float(zeilen[-1].split("I:")[1].split("LUFS")[0].strip())
    ziel = plan["audio"]["lufs"]
    assert abs(gemessen - ziel) < 2.0, f"{gemessen:.1f} LUFS statt {ziel} - die Musik ist nicht mitgemessen worden"
