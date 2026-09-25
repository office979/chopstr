"""Die technische Prüfung der fertigen Datei, mit Folgen.

WAS HIER SCHIEFLIEF: gemessen wurde schon vorher. ``render.regression_checks`` prüft Dauer,
Auflösung, Tonspur, Bildspur und Schwarzbilder, und ``render.measure_loudness`` misst die Lautheit.
Beides landete in einer Liste ``notes`` aus freien Sätzen, die in ein Ereignis der Pipeline
geschrieben wurde. Danach stand ``status = "rendered"``, unabhängig vom Ergebnis. Eine stumme
Datei, eine Datei mit schwarzem Bild und eine ohne Untertitel sahen für chopstr aus wie eine
fertige, und der Kunde lud sie herunter.

Es fehlte also nicht die Messung, sondern die Folge. Dieses Modul macht aus den Messwerten Befunde
mit einer Schwere, und die Schwere entscheidet: ``fehler`` verhindert, dass die Fassung hinausgeht
(packages/schema/ausgabe_regeln_v1.json, Regel ``technik_fehler``), ``hinweis`` steht nur an der
Karte. Die Grenzwerte stehen in derselben Datei, die auch die Web-App liest, damit nicht wieder
zwei Stellen dasselbe verschieden beantworten.

Dazu kommen zwei Prüfungen, die es vorher gar nicht gab: ob die Lautstärke das trifft, was der Plan
verlangt, und ob überhaupt Untertitel im Bild gelandet sind. Beides ist am fertigen Video nicht
sichtbar, wenn niemand hinsieht, und beides macht den Clip unbrauchbar.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Any

REGELN_DATEI = "ausgabe_regeln_v1.json"


def _regeln_pfad() -> str:
    """Pfad zum gemeinsamen Regelkatalog (packages/schema/ausgabe_regeln_v1.json).

    Wie bei der Schriftenliste und der redaktionellen Grundlage liegt er ausserhalb des Workers,
    damit Oberflaeche und Renderer dieselbe Datei lesen. ``CHOPSTR_AUSGABE_REGELN`` sticht."""
    env = (os.environ.get("CHOPSTR_AUSGABE_REGELN") or "").strip()
    if env:
        return env
    hier = os.path.dirname(os.path.abspath(__file__))
    wurzel = os.path.abspath(os.path.join(hier, "..", "..", ".."))
    return os.path.join(wurzel, "packages", "schema", REGELN_DATEI)


_zwischenspeicher: dict | None = None


def regeln() -> dict:
    global _zwischenspeicher
    if _zwischenspeicher is None:
        with open(_regeln_pfad(), encoding="utf-8") as f:
            _zwischenspeicher = json.load(f)
    return _zwischenspeicher


def _grenzen(code: str) -> dict:
    for p in regeln()["technische_pruefungen"]["pruefungen"]:
        if p["code"] == code:
            return p
    raise KeyError(f"Unbekannte Pruefung: {code}")


@dataclass
class Befund:
    """Ein Ergebnis je Prüfung. ``text`` ist ein Satz für den Nutzer, kein Messprotokoll;
    ``gemessen`` ist der Wert für den Support."""

    pruefung: str
    ergebnis: str  # ok | hinweis | fehler
    text: str
    gemessen: str | None = None

    def als_dict(self) -> dict[str, Any]:
        return asdict(self)


def _schwere(code: str, abweichung: float) -> str:
    g = _grenzen(code)
    if abweichung >= float(g["fehler_ab"]):
        return "fehler"
    if abweichung >= float(g["hinweis_ab"]):
        return "hinweis"
    return "ok"


def pruefen(
    *,
    datei_vorhanden: bool,
    hat_bild: bool,
    hat_ton: bool,
    dauer_s: float | None,
    geplante_dauer_s: float,
    breite: int | None,
    hoehe: int | None,
    geplante_breite: int,
    geplante_hoehe: int,
    schwarzbilder: list[tuple[float, float]],
    lufs: float | None,
    ziel_lufs: float | None,
    spitze_dbtp: float | None,
    ziel_spitze_dbtp: float | None,
    woerter: int,
    untertitelkarten: int,
    untertitel_eingebrannt: bool,
    schrift_ersetzt: str | None = None,
) -> list[Befund]:
    """Alle Prüfungen an einer fertigen Datei, in der Reihenfolge des Katalogs.

    Es wird immer die ganze Liste zurückgegeben, auch die bestandenen Prüfungen. Nur so lässt sich
    später sagen, ob etwas geprüft und in Ordnung war oder gar nicht geprüft wurde - und genau
    dieser Unterschied entscheidet, ob eine alte Datei gesperrt gehört oder nicht."""
    aus: list[Befund] = []

    if not datei_vorhanden:
        # Ohne Datei hat keine weitere Messung einen Sinn, und ein Dutzend Folgefehler zu melden
        # wuerde den einen Grund verstecken, auf den es ankommt.
        return [Befund("datei", "fehler", "Die fertige Datei fehlt oder ist leer.", None)]
    aus.append(Befund("datei", "ok", "Die Datei ist da.", None))

    aus.append(
        Befund("bild", "ok", "Die Datei hat ein Bild.", None)
        if hat_bild
        else Befund("bild", "fehler", "In der Datei ist keine Bildspur. Das Video wäre schwarz.", None)
    )
    aus.append(
        Befund("ton", "ok", "Die Datei hat Ton.", None)
        if hat_ton
        else Befund("ton", "fehler", "In der Datei ist keine Tonspur. Der Clip wäre stumm.", None)
    )

    if dauer_s is None:
        aus.append(Befund("dauer", "hinweis", "Die Länge ließ sich nicht messen.", None))
    else:
        ab = abs(dauer_s - geplante_dauer_s)
        s = _schwere("dauer", ab)
        aus.append(
            Befund(
                "dauer",
                s,
                "Die Länge stimmt mit dem Schnitt überein."
                if s == "ok"
                else f"Das fertige Video ist {ab:.1f} Sekunden {'länger' if dauer_s > geplante_dauer_s else 'kürzer'} als der Schnitt. Es fehlt oder hängt etwas an.",
                f"{dauer_s:.2f} s statt {geplante_dauer_s:.2f} s",
            )
        )

    if breite is None or hoehe is None:
        aus.append(Befund("aufloesung", "hinweis", "Die Bildgröße ließ sich nicht messen.", None))
    elif (breite, hoehe) != (geplante_breite, geplante_hoehe):
        aus.append(
            Befund(
                "aufloesung",
                "fehler",
                "Das Video hat eine andere Bildgröße als eingestellt. Auf der Plattform würde es beschnitten oder verzerrt.",
                f"{breite}x{hoehe} statt {geplante_breite}x{geplante_hoehe}",
            )
        )
    else:
        aus.append(Befund("aufloesung", "ok", f"Bildgröße {breite}x{hoehe} wie eingestellt.", None))

    laengstes = max((b - a for a, b in schwarzbilder), default=0.0)
    s = _schwere("schwarzbild", laengstes)
    aus.append(
        Befund(
            "schwarzbild",
            s,
            "Kein schwarzes Bild im Video."
            if s == "ok"
            else f"Das Bild ist {laengstes:.1f} Sekunden lang schwarz. Wer das sieht, hält den Clip für kaputt.",
            None if s == "ok" else f"{laengstes:.2f} s",
        )
    )

    if lufs is None or ziel_lufs is None:
        aus.append(Befund("pegel", "hinweis", "Die Lautstärke ließ sich nicht messen.", None))
    else:
        ab = abs(lufs - ziel_lufs)
        s = _schwere("pegel", ab)
        aus.append(
            Befund(
                "pegel",
                s,
                "Die Lautstärke passt."
                if s == "ok"
                else f"Der Clip ist {'lauter' if lufs > ziel_lufs else 'leiser'} als üblich. Auf der Plattform fällt er gegen andere Videos ab.",
                f"{lufs:.1f} LUFS statt {ziel_lufs:.1f} LUFS",
            )
        )

    if spitze_dbtp is None or ziel_spitze_dbtp is None:
        aus.append(Befund("spitze", "hinweis", "Der Spitzenpegel ließ sich nicht messen.", None))
    else:
        ueber = max(0.0, spitze_dbtp - ziel_spitze_dbtp)
        s = _schwere("spitze", ueber)
        aus.append(
            Befund(
                "spitze",
                s,
                "Der Ton übersteuert nicht."
                if s == "ok"
                else "Der Ton geht über die erlaubte Spitze. Auf manchen Geräten knackt es dann.",
                f"{spitze_dbtp:.1f} dBTP statt höchstens {ziel_spitze_dbtp:.1f} dBTP",
            )
        )

    if woerter <= 0:
        # In diesem Clip wird nichts gesprochen. Fehlende Untertitel sind dann richtig.
        aus.append(Befund("untertitel", "ok", "In diesem Clip wird nichts gesprochen.", None))
    elif untertitelkarten <= 0:
        aus.append(
            Befund(
                "untertitel",
                "fehler",
                "Es sind keine Untertitel entstanden, obwohl gesprochen wird. Die meisten sehen Kurzvideos ohne Ton.",
                f"{woerter} Wörter, 0 Karten",
            )
        )
    elif not untertitel_eingebrannt:
        # Der Unterschied ist wichtig: die Untertitel gibt es, sie sind nur nicht ins Bild gekommen.
        # Das ist kein Problem dieses Clips, sondern des Servers, auf dem er geclippt wurde, und der
        # Satz muss das sagen - sonst versucht jemand dreimal dasselbe.
        aus.append(
            Befund(
                "untertitel",
                "fehler",
                "Die Untertitel sind nicht ins Bild gekommen. Das liegt am Server, nicht am Clip. Bitte melden.",
                f"{untertitelkarten} Karten vorhanden, keine eingebrannt",
            )
        )
    else:
        aus.append(Befund("untertitel", "ok", f"{untertitelkarten} Untertitelkarten im Bild.", None))

    # Die gewaehlte Schrift. Fehlt ihre Datei, brennt libass etwas anderes ein - der Clip ist
    # brauchbar, sieht aber nicht aus wie eingestellt. Bisher stand das nur in einer Notiz des
    # Renderlaufs, die nach dem Verarbeiten niemand mehr sieht. Nie ein Fehler: ein Video wegen
    # einer Schrift zu sperren waere unverhaeltnismaessig.
    aus.append(
        Befund("schrift", "ok", "Die eingestellte Schrift ist im Bild.", None)
        if not schrift_ersetzt
        else Befund(
            "schrift",
            "hinweis",
            "Die eingestellte Schrift liegt auf diesem Server nicht vor, im Bild steht eine andere. Der Clip ist brauchbar, sieht aber nicht aus wie eingestellt.",
            schrift_ersetzt,
        )
    )

    return aus


def schlimmstes(befunde: list[Befund]) -> str:
    """ok, hinweis oder fehler: das schlechteste Ergebnis der Liste."""
    if any(b.ergebnis == "fehler" for b in befunde):
        return "fehler"
    if any(b.ergebnis == "hinweis" for b in befunde):
        return "hinweis"
    return "ok"


def als_liste(befunde: list[Befund]) -> list[dict[str, Any]]:
    return [b.als_dict() for b in befunde]


def fehlertext(befunde: list[Befund]) -> str | None:
    """Der Satz, der in ``clips.render_error`` steht, wenn die Prüfung fehlschlägt.

    Bewusst nur der erste Fehler: wer drei Sätze auf einmal liest, liest keinen davon, und die
    vollständige Liste steht ohnehin in ``export_checks``."""
    for b in befunde:
        if b.ergebnis == "fehler":
            return b.text
    return None
