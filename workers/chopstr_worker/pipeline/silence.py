"""Sprechpausen aus dem Ton messen statt aus Transkript-Wortzeiten ableiten.

WARUM DAS NÖTIG IST
-------------------
``segment.sentences_from_words`` setzt Satzgrenzen unter anderem an langen Pausen
(``MIN_PAUSE_AS_BOUNDARY``). Die Pause wird dabei als Lücke zwischen zwei Wortzeiten
berechnet. Verschluckt das ASR eine Pause, fehlt die Grenze — und ein Clip beginnt
mitten im Satz.

Messung vom 26.09.2026 (deutsche Aufnahme, whisper small, ``--language de``):

    echte Stille laut silencedetect : 1,55-2,63s · 6,43-8,62s (2,19s) · 10,89-11,84s
    größte Lücke laut Wortzeiten    : 0,47s

Eine reale Pause von 2,19 Sekunden erschien in den Wortzeiten als 0,0 Sekunden.
Ein Fehlstart, bei dem derselbe Satz neu begonnen wurde, fehlte im Transkript ganz.

chopstr nutzt faster-whisper, dessen Alignment genauer ist als das dieser Messung.
Dieses Modul ersetzt die Wortzeiten deshalb nicht, es gibt ihnen eine zweite Meinung.

LAUFZEIT
--------
Entscheidend für lange Podcasts: **ein** ffmpeg-Durchlauf pro Datei, danach nur noch
Suchen im Speicher.

    naiv     : ein ffmpeg-Prozess je geprüfter Grenze  ->  bei 400 Kandidatengrenzen
               400 Prozessstarts, jeder mit Datei öffnen und Suchen
    hier     : ein Durchlauf (nur Audio, ``-vn``), danach bisect in O(log n)

Gemessen am 27.09.2026 (Apple M4, ffmpeg 8.0.1) an einem 10-Minuten-Video,
1920x1080, 692 MB:

    Scan mit -vn (nur Ton)      : 0,33 s
    derselbe Scan ohne -vn      : 4,21 s   -> Faktor 12,9
    hochgerechnet auf 90 Minuten: rund 3 s
    50.000 Grenzprüfungen       : 7 ms     (85 Pausen, reine Binärsuche)

Das ``-vn`` ist damit kein Detail, sondern der Unterschied zwischen "läuft nebenbei"
und "hält die CPU-Queue auf".

WIRKUNG
-------
Praxislauf vom 27.09.2026 an einer 17-Sekunden-Aufnahme mit verschluckter Pause:

    ohne Stille-Karte : 1 Satz über die ganze Datei  -> keine Clipgrenze möglich
    mit Stille-Karte  : 3 Sätze an den echten Pausen -> Fehlstart sauber abgetrennt

Die Karte macht Grenzen auffindbar. Wie gut die Wörter dann den Sätzen zugeordnet
sind, hängt weiterhin am Alignment des ASR.
"""

from __future__ import annotations

import bisect
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass

log = logging.getLogger("chopstr.silence")

NOISE_DB = -40  # ab hier gilt es als still; Raumton liegt typisch darunter
MIN_SILENCE_S = 0.30  # kürzer ist Atmen, keine Pause
SCAN_TIMEOUT_S = 900
EPS = 1e-6  # Gleitkommaluft: 6.49 - 6.43 ergibt 0.05999999999999872

_RE = re.compile(r"silence_(start|end):\s*(-?[0-9.]+)")
_CACHE: dict[tuple[str, int, float, int, float], SilenceMap] = {}


@dataclass(frozen=True)
class Gap:
    start: float
    end: float

    @property
    def length(self) -> float:
        return self.end - self.start

    @property
    def middle(self) -> float:
        return (self.start + self.end) / 2.0


class SilenceMap:
    """Gemessene Stille einer Datei. Alle Abfragen laufen über Binärsuche.

    Die Intervalle sind aufsteigend und überschneidungsfrei — das garantiert
    ``silencedetect`` durch sein Start/Ende-Paarmuster. Darauf baut ``bisect``.
    """

    __slots__ = ("gaps", "_starts", "media")

    def __init__(self, gaps: list[Gap], media: str = "") -> None:
        self.gaps = gaps
        self._starts = [g.start for g in gaps]
        self.media = media

    def __len__(self) -> int:
        return len(self.gaps)

    def __bool__(self) -> bool:
        # Eine Datei ohne jede Pause ist gültig, aber verdächtig.
        return True

    def gap_at(self, t: float, tol: float = 0.0) -> Gap | None:
        """Stille, die ``t`` enthält (O(log n)). ``tol`` weitet die Intervalle beidseitig."""
        if not self.gaps:
            return None
        i = bisect.bisect_right(self._starts, t + tol) - 1
        if i < 0:
            return None
        g = self.gaps[i]
        return g if (g.start - tol) <= t <= (g.end + tol) else None

    def is_silent_at(self, t: float, tol: float = 0.0) -> bool:
        return self.gap_at(t, tol) is not None

    def pause_between(self, a: float, b: float) -> float:
        """Gemessene Stille zwischen Wortende ``a`` und Wortanfang ``b``.

        Gibt die Länge der überlappenden Stille zurück, nicht ``b - a``. Damit zählt
        nur, was wirklich still ist — nicht, was das ASR an Zeit übrig gelassen hat.
        """
        if b <= a or not self.gaps:
            return 0.0
        i = bisect.bisect_right(self._starts, b) - 1
        gesamt = 0.0
        while i >= 0:
            g = self.gaps[i]
            if g.end < a:
                break
            gesamt += max(0.0, min(g.end, b) - max(g.start, a))
            i -= 1
        return gesamt

    def pause_after(self, t: float, tol: float = 0.25) -> float:
        """Länge der Sprechpause, die bei ``t`` (einem Wortende) beginnt.

        Das ist die Methode für den Kernfall. ``pause_between(wortende, wortanfang)``
        greift dort zu kurz: Verschluckt das ASR eine Pause, liegt der Anfang des
        nächsten Wortes laut Transkript **innerhalb** der echten Stille, und das
        Messfenster umfasst nur einen Bruchteil davon.

        Beispiel aus der Messung vom 26.09.2026:
            Wortende 6.42 · nächster Wortanfang laut ASR 6.45 · echte Stille 6.43-8.62
            pause_between(6.27, 6.60) -> 0.17s   (zu klein, Grenze wird verfehlt)
            pause_after(6.42)         -> 2.19s   (richtig)

        ``tol`` erlaubt, dass die Stille kurz nach dem Wortende beginnt.
        """
        g = self.gap_at(t)
        if g is None:
            i = bisect.bisect_left(self._starts, t)
            if i < len(self.gaps) and (self.gaps[i].start - t) <= tol:
                g = self.gaps[i]
            else:
                return 0.0
        return max(0.0, g.end - max(t, g.start))

    def boundary_is_clean(self, t: float, rand: float = 0.06) -> bool:
        """Liegt ``t`` so in einer Pause, dass beidseitig ``rand`` Sekunden still sind?

        Das ist die Bedingung für einen Schnitt, der kein Wort anschneidet. Ersetzt
        die frühere Messung per ``volumedetect`` pro Grenze — gleiche Aussage,
        ohne Prozessstart.
        """
        g = self.gap_at(t)
        return g is not None and (t - g.start) >= rand - EPS and (g.end - t) >= rand - EPS

    def snap(self, t: float, max_shift: float = 0.40, rand: float = 0.06) -> float | None:
        """Nächstgelegener sauberer Schnittpunkt zu ``t``, höchstens ``max_shift`` entfernt.

        Bevorzugt die Mitte der nächsten Stille: dort ist der Abstand zu beiden
        Wörtern am größten. Gibt ``None``, wenn in Reichweite keine taugliche Pause liegt.
        """
        if not self.gaps:
            return None
        if self.boundary_is_clean(t, rand):
            return t
        i = bisect.bisect_left(self._starts, t)
        beste: float | None = None
        bester_abstand = max_shift
        for j in (i - 1, i, i + 1):
            if not (0 <= j < len(self.gaps)):
                continue
            g = self.gaps[j]
            if g.length < 2 * rand:
                continue
            # Innerhalb der Stille der Punkt, der t am nächsten liegt und den Rand einhält.
            kandidat = round(min(max(t, g.start + rand), g.end - rand), 3)
            if not (g.start + rand - EPS <= kandidat <= g.end - rand + EPS):
                continue
            abstand = abs(kandidat - t)
            if abstand < bester_abstand:
                beste, bester_abstand = kandidat, abstand
        return beste

    def long_gaps(self, min_s: float) -> list[Gap]:
        return [g for g in self.gaps if g.length >= min_s]


EMPTY = SilenceMap([], "")


def available() -> bool:
    return shutil.which("ffmpeg") is not None


def parse(log_text: str) -> list[Gap]:
    """Liest silencedetect-Meldungen. Rein, damit ohne ffmpeg testbar.

    ffmpeg schreibt diese Meldungen auf **stderr**, nicht auf stdout.
    """
    gaps: list[Gap] = []
    offen: float | None = None
    for m in _RE.finditer(log_text):
        wert = float(m.group(2))
        if m.group(1) == "start":
            offen = wert
        elif offen is not None:
            if wert > offen:
                gaps.append(Gap(round(offen, 3), round(wert, 3)))
            offen = None
    return gaps


def scan(
    media_path: str | os.PathLike,
    *,
    noise_db: int = NOISE_DB,
    min_silence_s: float = MIN_SILENCE_S,
    use_cache: bool = True,
) -> SilenceMap:
    """Einmaliger Stille-Scan einer Datei. Ergebnis wird pro (Pfad, mtime, Parameter) gehalten.

    Schlägt der Scan fehl oder fehlt ffmpeg, kommt eine leere Karte zurück — die
    aufrufende Logik verhält sich dann wie bisher. Kein harter Fehler: eine fehlende
    Zweitmeinung darf keinen Clip verhindern.
    """
    pfad = str(media_path)
    try:
        st = os.stat(pfad)
        key = (pfad, int(st.st_mtime), st.st_size, noise_db, min_silence_s)
    except OSError:
        log.warning("Stille-Scan: %s nicht lesbar", pfad)
        return EMPTY

    if use_cache and key in _CACHE:
        return _CACHE[key]
    if not available():
        log.info("Stille-Scan übersprungen: ffmpeg fehlt")
        return EMPTY

    # -vn: das Bild wird nicht dekodiert. Das ist der Unterschied zwischen
    # Sekunden und Minuten bei einer langen Datei.
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-vn",
        "-i",
        pfad,
        "-af",
        f"silencedetect=noise={noise_db}dB:d={min_silence_s}",
        "-f",
        "null",
        "-",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=SCAN_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("Stille-Scan fehlgeschlagen (%s): %s", pfad, e)
        return EMPTY

    karte = SilenceMap(parse(r.stderr + r.stdout), pfad)
    if use_cache:
        _CACHE[key] = karte
    log.info("Stille-Scan %s: %d Pausen", os.path.basename(pfad), len(karte))
    return karte


def clear_cache() -> None:
    _CACHE.clear()


__all__ = [
    "EMPTY",
    "Gap",
    "MIN_SILENCE_S",
    "NOISE_DB",
    "SilenceMap",
    "available",
    "clear_cache",
    "parse",
    "scan",
]
