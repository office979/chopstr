"""Musik unter dem Clip: die Rechnung, und die Kette durch das echte ffmpeg.

Eine Filterkette, die ffmpeg klaglos annimmt und anders auslegt als gedacht, ist der schlimmste
Fall - sie faellt niemandem auf. Deshalb laeuft hier echter Ton durch die echte Kette, und der
Pegel wird gemessen.
"""

from __future__ import annotations

import subprocess

import pytest

from chopstr_worker.pipeline import musik
from tests.conftest import requires_ffmpeg

pytest.importorskip("imageio_ffmpeg")


def _ffmpeg() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def test_ohne_datei_gibt_es_keine_musik():
    """Grosszuegig beim Lesen, streng beim Ergebnis."""
    assert musik.lesen(None) is None
    assert musik.lesen({}) is None
    assert musik.lesen({"datei": "  "}) is None
    assert musik.lesen("nein") is None


def test_die_lautstaerke_wird_hereingeholt_statt_abgewiesen():
    """Eine alte Zeile mit einer zu grossen Zahl darf keinen Clip scheitern lassen."""
    assert musik.lesen({"datei": "a.mp3", "lautstaerke_db": 99}).lautstaerke_db == musik.MAX_DB
    assert musik.lesen({"datei": "a.mp3", "lautstaerke_db": -900}).lautstaerke_db == musik.MIN_DB
    assert musik.lesen({"datei": "a.mp3", "lautstaerke_db": "laut"}).lautstaerke_db == musik.STANDARD_DB


def test_eine_negative_stelle_gibt_es_nicht():
    assert musik.lesen({"datei": "a.mp3", "ab_s": -5}).ab_s == 0.0


def test_unbekannte_quelle_gilt_als_eigene_datei():
    """Lieber die eigene Datei als ein Katalogstueck, das es nicht gibt."""
    assert musik.lesen({"datei": "a.mp3", "quelle": "spotify"}).quelle == "eigen"


def test_die_sprache_wird_fuer_das_ducking_gespalten():
    """Ein Label laesst sich in ffmpeg nur EINMAL verbrauchen.

    Die Sprache wird zweimal gebraucht - als Ausloeser des Duckings und in der Mischung. Ohne
    asplit bricht der Lauf mit „Cannot find a matching stream" ab."""
    m = musik.lesen({"datei": "a.mp3", "ducking": True})
    kette, _ = musik.ffmpeg_kette(m, 3, 20.0)
    assert "asplit=2" in kette
    assert kette.count("[ac]") == 1


def test_ohne_ducking_kein_asplit():
    m = musik.lesen({"datei": "a.mp3", "ducking": False})
    kette, _ = musik.ffmpeg_kette(m, 3, 20.0)
    assert "asplit" not in kette
    assert "sidechaincompress" not in kette


def test_die_stelle_im_stueck_landet_im_ausdruck():
    m = musik.lesen({"datei": "a.mp3", "ab_s": 42.25})
    kette, _ = musik.ffmpeg_kette(m, 5, 30.0)
    assert "atrim=start=42.250:duration=30.000" in kette
    # Ohne asetpts laege die Musik um ab_s versetzt hinter dem Clipende.
    assert "asetpts=PTS-STARTPTS" in kette


def _pegel(pfad: str) -> float:
    """Mittlerer Pegel der Datei in dBFS, gemessen mit ffmpeg selbst."""
    r = subprocess.run(
        [_ffmpeg(), "-v", "error", "-i", pfad, "-af", "astats=metadata=1:reset=0,ametadata=print:file=-", "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    werte = [float(z.split("=")[1]) for z in r.stdout.splitlines() if "RMS_level=" in z and "=-inf" not in z]
    return max(werte) if werte else -99.0


@requires_ffmpeg
def test_die_kette_laeuft_durch_ffmpeg_und_mischt_wirklich(tmp_path):
    """Sprache und Musik als Toene bekannter Frequenz, dann die echte Kette, dann gemessen.

    Gemessen wird der Pegel bei 1000 Hz (die „Sprache") und bei 300 Hz (die „Musik"). Beide
    muessen im Ergebnis vorkommen - sonst hat die Mischung eine Spur verschluckt."""
    sprache = tmp_path / "sprache.wav"
    mus = tmp_path / "musik.wav"
    subprocess.run(
        [_ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=1000:duration=6", str(sprache)],
        check=True,
    )
    # Das Stueck ist laenger als der Clip: genau der Normalfall.
    subprocess.run(
        [_ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=60", str(mus)],
        check=True,
    )

    m = musik.lesen({"datei": str(mus), "ab_s": 20.0, "lautstaerke_db": -12.0, "ducking": True})
    kette, ausgang = musik.ffmpeg_kette(m, 1, 6.0)
    aus = tmp_path / "mix.wav"
    r = subprocess.run(
        [
            _ffmpeg(), "-y", "-v", "error",
            "-i", str(sprache),
            "-i", str(mus),
            "-filter_complex", f"[0:a]anull[ac];{kette}",
            "-map", ausgang,
            str(aus),
        ],
        capture_output=True,
        text=True,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    assert aus.exists() and aus.stat().st_size > 1000

    # Beide Frequenzen muessen drin sein. Gemessen ueber schmale Bandpaesse: was durchkommt, war da.
    def band(mitte: int) -> float:
        p = tmp_path / f"b{mitte}.wav"
        subprocess.run(
            [_ffmpeg(), "-y", "-v", "error", "-i", str(aus), "-af", f"bandpass=f={mitte}:width_type=h:w=60", str(p)],
            check=True,
        )
        return _pegel(str(p))

    sprach_pegel = band(1000)
    musik_pegel = band(300)
    assert sprach_pegel > -30, f"Die Sprache fehlt in der Mischung ({sprach_pegel:.1f} dB)"
    assert musik_pegel > -45, f"Die Musik fehlt in der Mischung ({musik_pegel:.1f} dB)"
    # Und die Musik liegt UNTER der Sprache - sonst uebertoent sie, was gesagt wird.
    assert musik_pegel < sprach_pegel, f"Musik {musik_pegel:.1f} dB ist nicht leiser als Sprache {sprach_pegel:.1f} dB"


@requires_ffmpeg
def test_ein_zu_kurzes_stueck_bricht_die_mischung_nicht_ab(tmp_path):
    """Ohne apad endet der Clip, wenn die Musik endet - mitten im Satz."""
    sprache = tmp_path / "s.wav"
    kurz = tmp_path / "kurz.wav"
    subprocess.run([_ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=1000:duration=8", str(sprache)], check=True)
    subprocess.run([_ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=2", str(kurz)], check=True)

    m = musik.lesen({"datei": str(kurz), "ab_s": 0.0})
    kette, ausgang = musik.ffmpeg_kette(m, 1, 8.0)
    aus = tmp_path / "mix2.wav"
    subprocess.run(
        [_ffmpeg(), "-y", "-v", "error", "-i", str(sprache), "-i", str(kurz),
         "-filter_complex", f"[0:a]anull[ac];{kette}", "-map", ausgang, str(aus)],
        check=True,
    )  # fmt: skip
    # Die Laenge richtet sich nach der Sprache (acht Sekunden), nicht nach der Musik (zwei).
    # Gemessen an der Dateigroesse: ein Kanal, 44,1 kHz, 16 Bit sind rund 88 kB je Sekunde.
    assert aus.stat().st_size > 6 * 88_000, "Die Mischung endet mit der Musik statt mit der Sprache"


@requires_ffmpeg
def test_lauter_gestellt_ist_wirklich_lauter(tmp_path):
    """Der Regler muss etwas tun. Gemessen, nicht angenommen."""
    sprache = tmp_path / "s.wav"
    mus = tmp_path / "m.wav"
    subprocess.run([_ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=6", str(sprache)], check=True)
    subprocess.run([_ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=10", str(mus)], check=True)

    def mische(db: float) -> float:
        m = musik.lesen({"datei": str(mus), "lautstaerke_db": db, "ducking": False})
        kette, ausgang = musik.ffmpeg_kette(m, 1, 6.0)
        aus = tmp_path / f"v{db}.wav"
        subprocess.run(
            [_ffmpeg(), "-y", "-v", "error", "-i", str(sprache), "-i", str(mus),
             "-filter_complex", f"[0:a]anull[ac];{kette}", "-map", ausgang, str(aus)],
            check=True,
        )  # fmt: skip
        return _pegel(str(aus))

    leise = mische(-30.0)
    laut = mische(-6.0)
    assert laut > leise + 15, f"-6 dB ({laut:.1f}) ist nicht deutlich lauter als -30 dB ({leise:.1f})"
