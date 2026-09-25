"""Der Zoom muss in den Bildpunkten ankommen, nicht nur im Filterausdruck.

Ein Ausdruck, den ffmpeg klaglos annimmt und dann anders auslegt als gedacht, ist der schlimmste
Fall: er faellt niemandem auf. Deshalb wird hier ein statisches weisses Quadrat durch dieselbe
Filterkette geschickt und seine Breite je Bild gemessen. Sie IST der Zoomfaktor.
"""

from __future__ import annotations

import subprocess

import pytest

from chopstr_worker.pipeline import effekte as ef
from tests.conftest import requires_ffmpeg

np = pytest.importorskip("numpy")
Image = pytest.importorskip("PIL.Image")

KANTE = 200
BREITE, HOEHE = 540, 960


def _kette(ausdruck: str) -> str:
    """Dieselbe Filterkette wie im Renderer (pipeline/render.video_chain)."""
    gross_w, gross_h = BREITE * 2, HOEHE * 2
    rand_w = int(round(gross_w * ef.RESERVE))
    rand_h = int(round(gross_h * ef.RESERVE))
    return (
        f"drawbox=x={(BREITE - KANTE) // 2}:y={(HOEHE - KANTE) // 2}:w={KANTE}:h={KANTE}:color=white:t=fill,"
        f"scale={gross_w}:{gross_h}:flags=lanczos,"
        f"pad={rand_w}:{rand_h}:(ow-iw)/2:(oh-ih)/2:black,"
        f"zoompan=z='{ausdruck}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={BREITE}x{HOEHE}:fps=25,setsar=1"
    )


def _breite_bei(video, t: float, tmp_path) -> int:
    bild = tmp_path / f"f{t}.png"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{t}", "-i", str(video), "-frames:v", "1", str(bild)],
        check=True,
    )
    feld = np.array(Image.open(bild).convert("L"))
    zeile = feld[feld.shape[0] // 2]
    idx = np.where(zeile > 128)[0]
    return int(idx[-1] - idx[0] + 1)


@requires_ffmpeg
def test_der_zoom_kommt_in_den_bildpunkten_an(tmp_path):
    effekt = ef.Effekt("zoom_in", 1.0, 1.4)
    video = tmp_path / "zoom.mp4"
    vf = _kette(ef.ffmpeg_ausdruck([effekt], 25))
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=black:s={BREITE}x{HOEHE}:r=25:d=4",
         "-vf", vf, str(video)],
        check=True,
    )  # fmt: skip

    ruhe = _breite_bei(video, 0.5, tmp_path)
    assert ruhe == KANTE, "vor dem Effekt darf nichts passieren"

    for t in (1.25, 1.60, 1.90, 2.39, 3.0):
        gemessen = _breite_bei(video, t, tmp_path) / ruhe
        erwartet = ef.faktor([effekt], t)
        assert abs(gemessen - erwartet) < 0.02, f"bei {t} s: {gemessen:.3f} statt {erwartet:.3f}"


@requires_ffmpeg
def test_heraus_macht_das_bild_kleiner_mit_schwarzem_rand(tmp_path):
    """Kleiner zu werden heisst, mehr zu zeigen als da ist. Ohne die schwarze Reserve koennte
    zoompan das nicht, und der Effekt bliebe wirkungslos."""
    effekt = ef.Effekt("zoom_out", 1.0, 1.4)
    video = tmp_path / "heraus.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=black:s={BREITE}x{HOEHE}:r=25:d=4",
         "-vf", _kette(ef.ffmpeg_ausdruck([effekt], 25)), str(video)],
        check=True,
    )  # fmt: skip
    ruhe = _breite_bei(video, 0.5, tmp_path)
    assert ruhe == KANTE
    for t in (1.25, 1.60, 2.39):
        gemessen = _breite_bei(video, t, tmp_path) / ruhe
        erwartet = ef.faktor([effekt], t)
        assert abs(gemessen - erwartet) < 0.02, f"bei {t} s: {gemessen:.3f} statt {erwartet:.3f}"
    assert _breite_bei(video, 1.25, tmp_path) < KANTE, "das Bild muss kleiner werden"


@requires_ffmpeg
def test_ohne_effekte_bleibt_das_bild_unberuehrt(tmp_path):
    """Der Ausdruck „1" muss eine glatte Eins sein - sonst zoomt jeder Clip ein bisschen."""
    video = tmp_path / "ruhig.mp4"
    vf = _kette(ef.ffmpeg_ausdruck([], 25))
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=black:s={BREITE}x{HOEHE}:r=25:d=2",
         "-vf", vf, str(video)],
        check=True,
    )  # fmt: skip
    for t in (0.4, 1.0, 1.6):
        assert _breite_bei(video, t, tmp_path) == KANTE
