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
import re
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


# -- Lane P4: Export als Abnahmeobjekt (Regel 16) ----------------------------------------------------
# Fassung 2 mit dem Schalter ``implementation.export.strict`` und der Regel ``export.strict`` (Standard aus,
# Fassung 1 bleibt unverändert). Zusätzlich zu ``pruefen``: Dauer gegen die Schnittbeschreibung, Untertitel
# innerhalb der Timeline, Untertitelzeiten aus derselben Schnittbeschreibung, Synchronität, Ton nicht stumm,
# Bild nicht schwarz, Datei abrufbar. Am Ende ein Eintrag ``abnahme`` mit ``export_ok``: nur dann gilt der
# Clip als fertig (``rendered``) und ``clips.file_key`` wird freigegeben.
EXPORT_SWITCH = "export.strict"
# Unter diesem Pegel gilt der Ton als stumm (integrierte Lautheit in LUFS; Stille misst ebur128 als -70).
STUMM_UNTER_LUFS = -60.0
# Ab diesem Anteil Schwarzbild an der Dauer gilt das Bild als schwarz.
SCHWARZ_ANTEIL = 0.9
# Zeitvergleich der Untertitel: Wortzeiten sind auf ms gerundet, SRT auch.
ZEIT_EPS_S = 0.002
_SRT_ZEIT = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{3})\s*-->\s*(\d+):(\d\d):(\d\d)[,.](\d{3})")


def export_rules(policy=None) -> dict[str, float] | None:
    """``export.strict`` und ``export.duration_tolerance_s``; ``None`` heißt: Abnahme wie bisher (Fassung 1,
    Schalter ``implementation.export.strict`` aus oder Regel ``export.strict`` false; Rollback)."""
    from .. import editorial

    pol = policy if policy is not None else editorial.load()
    impl = (pol.roh.get("implementation") or {}).get("export") or {}
    if pol.version < 2 or impl.get("strict") is not True:
        return None
    raw = pol.roh.get("export")
    name = f"clip_policy_v{pol.version}"
    if not isinstance(raw, dict) or not isinstance(raw.get("strict"), bool):
        raise editorial.PolicyError(f"{name}: export.strict ist true oder false ({EXPORT_SWITCH} ist an).")
    if not raw["strict"]:
        return None
    try:
        tol = float(raw["duration_tolerance_s"])
    except (KeyError, TypeError, ValueError):
        raise editorial.PolicyError(f"{name}: export.duration_tolerance_s fehlt oder ist keine Zahl.") from None
    if tol < 0:
        raise editorial.PolicyError(f"{name}: export.duration_tolerance_s darf nicht negativ sein.")
    return {"duration_tolerance_s": tol}


def srt_cues(text: str) -> list[tuple[float, float]]:
    """Zeiten der Einträge einer SRT- oder VTT-Datei in Sekunden."""
    out = []
    for m in _SRT_ZEIT.finditer(text or ""):
        g = [int(x) for x in m.groups()]
        out.append((g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000.0, g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000.0))
    return out


def plan_timeline(plan: dict) -> list[dict]:
    """``plan.timeline`` (AP10b) oder, ohne sie, dieselbe Rechnung aus ``plan.segments``."""
    if plan.get("timeline"):
        return list(plan["timeline"])
    from . import compose

    return compose.output_timeline(compose.Composition.from_json([dict(s) for s in plan["segments"]]))


def erwartete_woerter(timeline: list[dict], source_words: list[dict], by_midpoint: bool = True) -> list[tuple[str, float]]:
    """Wörter mit Ausgabezeit, abgeleitet nur aus der Schnittbeschreibung (``source_in`` bis ``output_out``):
    ein Wort gehört zu dem Segment, in dem seine Mitte liegt (``by_midpoint``, wie unter ``cut.padding``), sonst
    nur, wenn es ganz darin liegt; Ausgabezeit = ``output_in`` plus Abstand zu ``source_in``."""
    out: list[tuple[str, float]] = []
    for e in timeline:
        s0, s1, o0 = float(e["source_in"]), float(e["source_out"]), float(e["output_in"])
        for w in source_words:
            ws, we = float(w["start"]), float(w["end"])
            if (s0 <= (ws + we) / 2.0 < s1) if by_midpoint else (s0 <= ws and we <= s1):
                out.append((str(w.get("text", "")), round(o0 + max(ws, s0) - s0, 3)))
    return out


def abnahme_pruefen(
    *,
    plan: dict,
    dauer_s: float | None,
    srt_text: str,
    out_words: list[dict],
    source_words: list[dict],
    hat_ton: bool,
    lufs: float | None,
    schwarzbilder: list[tuple[float, float]],
    toleranz_s: float,
) -> list[Befund]:
    """Die zusätzlichen Prüfungen der Abnahme (Modulabschnitt Lane P4), jede mit Ergebnis ``ok`` oder ``fehler``."""
    aus: list[Befund] = []
    timeline = plan_timeline(plan)
    soll = round(sum(float(e["source_out"]) - float(e["source_in"]) for e in timeline), 3)
    if dauer_s is None:
        aus.append(Befund("timeline_dauer", "fehler", "Die Länge der fertigen Datei ließ sich nicht messen.", None))
    else:
        ab = abs(float(dauer_s) - soll)
        aus.append(
            Befund("timeline_dauer", "ok", "Die Länge entspricht der Schnittbeschreibung.", f"{dauer_s:.3f} s, Soll {soll:.3f} s")
            if ab <= toleranz_s + 1e-9
            else Befund(
                "timeline_dauer", "fehler",
                f"Die Datei ist {ab:.2f} Sekunden {'länger' if dauer_s > soll else 'kürzer'} als die Schnittbeschreibung.",
                f"{dauer_s:.3f} s statt {soll:.3f} s, Toleranz {toleranz_s:.2f} s",
            )
        )  # fmt: skip

    cues = srt_cues(srt_text)
    ausserhalb = [c for c in cues if c[0] < -ZEIT_EPS_S or c[1] > soll + ZEIT_EPS_S or c[1] < c[0]]
    aus.append(
        Befund("untertitel_abdeckung", "ok", "Alle Untertitel liegen innerhalb des Clips.", f"{len(cues)} Einträge")
        if not ausserhalb
        else Befund(
            "untertitel_abdeckung", "fehler", "Untertitel stehen ausserhalb des Clips oder laufen über sein Ende hinaus.",
            f"{len(ausserhalb)} von {len(cues)} Einträgen, erster {ausserhalb[0][0]:.3f} bis {ausserhalb[0][1]:.3f} s, Clip {soll:.3f} s",
        )
    )  # fmt: skip

    erwartet = erwartete_woerter(timeline, source_words, by_midpoint=bool(plan.get("timeline")))
    ist = [(str(w.get("text", "")), round(float(w["start"]), 3)) for w in out_words]
    abweichend = len(erwartet) != len(ist) or any(a[0] != b[0] or abs(a[1] - b[1]) > ZEIT_EPS_S for a, b in zip(erwartet, ist))
    aus.append(
        Befund("untertitel_zeiten", "ok", "Die Untertitelzeiten folgen der Schnittbeschreibung.", f"{len(ist)} Wörter")
        if not abweichend
        else Befund(
            "untertitel_zeiten", "fehler", "Die Untertitel passen nicht zur Schnittbeschreibung. Text und Bild laufen auseinander.",
            f"{len(ist)} Wörter im Untertitel, {len(erwartet)} laut Schnittbeschreibung",
        )
    )  # fmt: skip

    def im_segment(t: float) -> bool:
        return any(float(e["output_in"]) - ZEIT_EPS_S <= t <= float(e["output_out"]) + ZEIT_EPS_S for e in timeline)

    asynchron = [w for w in out_words if not im_segment(float(w["start"]))]
    aus.append(
        Befund("synchron", "ok", "Jeder Wortanfang der Untertitel liegt in einem geschnittenen Abschnitt.", None)
        if not asynchron
        else Befund(
            "synchron", "fehler", "Untertitel beginnen an Stellen, an denen im Clip kein Ton aus der Quelle liegt.",
            f"{len(asynchron)} Wörter, erstes bei {float(asynchron[0]['start']):.3f} s",
        )
    )  # fmt: skip

    stumm = not hat_ton or lufs is None or float(lufs) < STUMM_UNTER_LUFS
    aus.append(
        Befund("ton_stumm", "fehler", "Der Clip ist stumm.", None if lufs is None else f"{float(lufs):.1f} LUFS")
        if stumm
        else Befund("ton_stumm", "ok", "Im Clip ist Ton zu hören.", f"{float(lufs):.1f} LUFS")
    )
    schwarz = sum(max(0.0, b - a) for a, b in schwarzbilder)
    anteil = schwarz / float(dauer_s) if dauer_s else 0.0
    aus.append(
        Befund("bild_schwarz", "fehler", "Das Bild ist fast durchgehend schwarz.", f"{anteil:.0%} schwarz")
        if anteil >= SCHWARZ_ANTEIL
        else Befund("bild_schwarz", "ok", "Das Bild ist nicht schwarz.", None)
    )
    return aus


def abrufbar_befund(abrufbar: bool) -> Befund:
    """Ist die Exportdatei nach dem Hochladen im Speicher abrufbar?"""
    if abrufbar:
        return Befund("abrufbar", "ok", "Die Exportdatei ist abrufbar.", None)
    return Befund("abrufbar", "fehler", "Die Exportdatei liegt nicht im Speicher. Bitte neu clippen.", None)


def anrede_befund(ergebnis: dict, marke: str | None = None) -> Befund:
    """Du/Sie-Hinweis aus ``captions_de.anrede_pruefen``. Nie ein Fehler und keine Textänderung: die Untertitel
    geben wieder, was gesagt wurde."""
    gemessen = f"{ergebnis['du']} Du-Formen, {ergebnis['sie']} Sie-Formen" + (f", Markenprofil {marke}" if marke else "")
    if ergebnis.get("gemischt"):
        return Befund(
            "anrede", "hinweis",
            "Im Untertitel stehen Du und Sie gemischt. Bitte prüfen, ob die Anrede so stehen bleiben soll; der Text gibt wieder, was gesagt wurde.",
            gemessen,
        )  # fmt: skip
    return Befund("anrede", "ok", "Die Anrede im Untertitel ist einheitlich.", gemessen)


def abnahme_zusammenfassung(befunde: list[Befund]) -> dict[str, Any]:
    """Letzter Eintrag in ``export_checks`` unter ``export.strict``: ``export_ok`` ist true, wenn kein Befund
    ``fehler`` ist; nur dann ist der Clip fertig."""
    ok = schlimmstes(befunde) != "fehler"
    return {
        "pruefung": "abnahme",
        "ergebnis": "ok" if ok else "fehler",
        "text": "Die Exportdatei ist abgenommen." if ok else "Die Exportdatei ist nicht abgenommen und wird nicht freigegeben.",
        "gemessen": None,
        "export_ok": ok,
    }


def export_ok_aus(export_checks: Any) -> bool:
    """``export_ok`` aus gespeicherten ``export_checks`` (Liste); ohne Abnahme-Eintrag false."""
    if not isinstance(export_checks, list):
        return False
    return any(isinstance(e, dict) and e.get("pruefung") == "abnahme" and e.get("export_ok") is True for e in export_checks)
