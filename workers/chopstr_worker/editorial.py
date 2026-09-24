"""Zugriff auf die redaktionelle Grundlage (``packages/editorial/clip_policy_v<N>.yaml``).

Die Datei beantwortet die Frage, was einen guten Clip ausmacht. Sie wird von beiden
Bewertungswegen gelesen: von der Heuristik, die heute läuft, und vom Sprachmodell, das später
kommt. Dieses Modul lädt sie, prüft sie auf Vollständigkeit und stellt getippte Zugriffe bereit.

Warum eine eigene Datei und keine Konstanten im Code: Die Regeln stammen aus einer Masterclass,
aus Messungen an Beispielclips und aus Recherche. Sie werden sich ändern, und dann muss
nachvollziehbar bleiben, welcher Clip nach welcher Fassung entstanden ist. Deshalb trägt jeder
Kandidat die ``policy_version`` mit.

Fehlt die Datei oder ist sie unvollständig, wird das nicht stillschweigend übergangen: Die
Bewertung ohne redaktionelle Grundlage wäre beliebig, und eine beliebige Bewertung sieht von
aussen genauso aus wie eine gute.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

POLICY_VERSION = 1

PFLICHTFELDER = (
    "version", "laenge", "rubrik", "bewertung", "moment_typen",
    "einstieg", "ausstieg", "zusammenhang", "audio", "hook_vorziehen", "ausschluss",
)  # fmt: skip


class PolicyError(RuntimeError):
    """Die redaktionelle Grundlage fehlt oder ist unbrauchbar."""


def policy_dir() -> Path:
    """Ordner mit der Grundlage: ``EDITORIAL_DIR`` oder ``<monorepo>/packages/editorial``."""
    env = os.environ.get("EDITORIAL_DIR", "").strip()
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "packages" / "editorial"
        if cand.is_dir():
            return cand
    return here.parents[2] / "packages" / "editorial"


@dataclass(frozen=True)
class Kriterium:
    schluessel: str
    frage: str
    gewicht: float
    null_punkte: str = ""
    zwei_punkte: str = ""
    herkunft: str = ""
    hinweis: str = ""


@dataclass(frozen=True)
class MomentTyp:
    schluessel: str
    name: str
    hebel: str
    bonus: float
    marker: tuple[str, ...] = ()
    marker_regex: str | None = None
    braucht_audio: bool = False

    def trifft(self, text_klein: str) -> bool:
        """Kommt dieser Typ im Text vor? Ohne Audio-Anteil, den kennt nur die Pipeline."""
        if any(m in text_klein for m in self.marker):
            return True
        return bool(self.marker_regex and re.search(self.marker_regex, text_klein))


@dataclass(frozen=True)
class Policy:
    version: int
    stand: str
    roh: dict[str, Any] = field(repr=False, default_factory=dict)

    # -- Länge ---------------------------------------------------------------------------------
    @property
    def ziel_s(self) -> float:
        return float(self.roh["laenge"]["ziel_s"])

    @property
    def gut_von_s(self) -> float:
        return float(self.roh["laenge"]["gut_von_s"])

    @property
    def gut_bis_s(self) -> float:
        return float(self.roh["laenge"]["gut_bis_s"])

    @property
    def hart_min_s(self) -> float:
        return float(self.roh["laenge"]["hart_min_s"])

    @property
    def hart_max_s(self) -> float:
        return float(self.roh["laenge"]["hart_max_s"])

    @property
    def kontext_zugabe_s(self) -> float:
        """Wie viele Sekunden ein Clip ueber die harte Grenze wachsen darf, um sein Ende zu heilen.

        Nur gegen einen benannten Mangel einsetzbar, nicht als allgemeine Verlaengerung. Fehlt der
        Wert in einer aelteren Richtlinie, gibt es keine Zugabe: lieber streng als stillschweigend
        grosszuegig."""
        return float(self.roh["laenge"].get("kontext_zugabe_s") or 0.0)

    @property
    def kontext_zugabe_saetze(self) -> int:
        """Wie viele Saetze die Heilung eines kaputten Endes anhaengen darf.

        Getrennt von ``kontext_zugabe_s``, weil es zwei verschiedene Dinge sind: die Sekunden sagen,
        wie weit ein Clip ueber die harte Grenze darf, die Saetze, wie weit die Heilung reichen
        darf. An echtem Material sind 27 Prozent der Saetze laenger als sieben Sekunden; mit einer
        reinen Sekundengrenze bliebe jedes vierte kaputte Ende ungeheilt."""
        return int(self.roh["laenge"].get("kontext_zugabe_saetze") or 0)

    def laenge_erlaubt(self, sekunden: float, mit_zugabe: bool = False) -> bool:
        """Darf ein Clip dieser Laenge ueberhaupt angeboten werden?

        ``mit_zugabe`` gilt nur fuer einen Clip, der nach hinten verlaengert wurde, um einen
        Mangel am Ende zu beheben. Ohne diesen Grund endet es bei ``hart_max_s``."""
        oben = self.hart_max_s + (self.kontext_zugabe_s if mit_zugabe else 0.0)
        return self.hart_min_s <= sekunden <= oben

    def laenge_ok(self, sekunden: float) -> bool:
        return self.gut_von_s <= sekunden <= self.gut_bis_s

    def laenge_abzug(self, sekunden: float) -> float:
        """0.0 im guten Fenster, wächst linear bis 1.0 an den harten Grenzen und darüber hinaus."""
        if self.laenge_ok(sekunden):
            return 0.0
        if sekunden < self.gut_von_s:
            spanne = max(1e-6, self.gut_von_s - self.hart_min_s)
            return min(1.0, (self.gut_von_s - sekunden) / spanne)
        spanne = max(1e-6, self.hart_max_s - self.gut_bis_s)
        return min(1.0, (sekunden - self.gut_bis_s) / spanne)

    # -- Rubrik --------------------------------------------------------------------------------
    @property
    def skala_max(self) -> int:
        return int(self.roh["rubrik"]["skala_max"])

    @property
    def kriterien(self) -> tuple[Kriterium, ...]:
        return tuple(
            Kriterium(
                schluessel=k["schluessel"],
                frage=k.get("frage", ""),
                gewicht=float(k.get("gewicht", 0.0)),
                null_punkte=k.get("null_punkte", ""),
                zwei_punkte=k.get("zwei_punkte", ""),
                herkunft=k.get("herkunft", ""),
                hinweis=k.get("hinweis", ""),
            )
            for k in self.roh["rubrik"]["kriterien"]
        )

    @property
    def gewichte(self) -> dict[str, float]:
        return {k.schluessel: k.gewicht for k in self.kriterien}

    @property
    def modus(self) -> str:
        return str(self.roh["bewertung"]["modus"])

    @property
    def sperrt(self) -> bool:
        return self.modus == "sperren"

    @property
    def schwelle_schneiden(self) -> int:
        return int(self.roh["bewertung"]["schwelle_schneiden"])

    @property
    def schwelle_verwerfen(self) -> int:
        return int(self.roh["bewertung"]["schwelle_verwerfen"])

    @property
    def punkte_gesamt(self) -> int:
        return int(self.roh["bewertung"]["punkte_gesamt"])

    def gesamtwert(self, punkte: dict[str, float]) -> float:
        """Gewichtete Summe, umgerechnet auf die Gesamtpunktzahl der Rubrik.

        Erwartet Punkte auf der Skala der Rubrik (0 bis skala_max). Fehlende Kriterien zählen als
        null, denn ein nicht bewertetes Kriterium ist kein erfülltes.
        """
        summe = sum(self.gewichte.get(s, 0.0) * float(p) for s, p in punkte.items())
        gewicht_summe = sum(self.gewichte.values()) or 1.0
        return round(summe / gewicht_summe / self.skala_max * self.punkte_gesamt, 2)

    # -- Moment-Typen --------------------------------------------------------------------------
    @property
    def moment_typen(self) -> tuple[MomentTyp, ...]:
        return tuple(
            MomentTyp(
                schluessel=m["schluessel"],
                name=m.get("name", m["schluessel"]),
                hebel=m.get("hebel", ""),
                bonus=float(m.get("bonus", 0.0)),
                marker=tuple(m.get("marker", ()) or ()),
                marker_regex=m.get("marker_regex"),
                braucht_audio=bool(m.get("braucht_audio", False)),
            )
            for m in self.roh["moment_typen"]
        )

    def typen_im_text(self, text: str) -> list[str]:
        """Welche Moment-Typen kommen im Text vor? Typen, die Audio brauchen, bleiben aussen vor."""
        klein = text.lower()
        return [t.schluessel for t in self.moment_typen if not t.braucht_audio and t.trifft(klein)]

    # -- Abschnitte als Rohdaten ---------------------------------------------------------------
    @property
    def einstieg(self) -> dict[str, Any]:
        return dict(self.roh["einstieg"])

    @property
    def ausstieg(self) -> dict[str, Any]:
        return dict(self.roh["ausstieg"])

    @property
    def zusammenhang(self) -> dict[str, Any]:
        return dict(self.roh["zusammenhang"])

    @property
    def audio(self) -> dict[str, Any]:
        return dict(self.roh["audio"])

    @property
    def hook_vorziehen(self) -> dict[str, Any]:
        return dict(self.roh["hook_vorziehen"])

    @property
    def ausschluss(self) -> dict[str, Any]:
        return dict(self.roh["ausschluss"])

    def ist_organisatorisch(self, text: str) -> bool:
        if not self.ausschluss.get("organisatorisches_gespraech"):
            return False
        klein = text.lower()
        return any(m in klein for m in self.ausschluss.get("organisations_marker", []))

    # -- Für den Prompt ------------------------------------------------------------------------
    def als_prompt_text(self) -> str:
        """Die Grundlage in der Form, in der sie einem Sprachmodell vorgelegt wird.

        Bewusst knapp: Herkunftsangaben und Begründungen bleiben in der Datei, ins Modell geht nur
        die Regel selbst. Wer die Begründung sucht, liest die YAML.
        """
        zeilen: list[str] = []
        zeilen.append(f"LÄNGE: Ziel {self.ziel_s:.0f} s, gut zwischen {self.gut_von_s:.0f} und {self.gut_bis_s:.0f} s.")
        zeilen.append("")
        zeilen.append(f"RUBRIK, je {self.skala_max} Punkte möglich:")
        for k in self.kriterien:
            zeilen.append(f"  {k.schluessel}: {k.frage}")
            if k.null_punkte and k.zwei_punkte:
                zeilen.append(f"      0 = {k.null_punkte}   {self.skala_max} = {k.zwei_punkte}")
        zeilen.append("")
        zeilen.append("MOMENT-TYPEN, die tragen:")
        for t in self.moment_typen:
            zeilen.append(f"  {t.name} ({t.hebel})")
        zeilen.append("")
        zeilen.append("EINSTIEG: nie mitten im Satz, nie in einer Selbstkorrektur, kein Pronomen ohne Bezug,")
        zeilen.append("  nicht mit der Frage eines anderen Sprechers, Einleitungsfloskeln weglassen.")
        zeilen.append("AUSSTIEG: Satz zu Ende nehmen, vor der Abschwächung aufhören, auf der Pointe enden.")
        zeilen.append("ZUSAMMENHANG: ein Gedanke, ein zusammenhängender Abschnitt, keine Collage.")
        return "\n".join(zeilen)


def _pruefe(daten: dict[str, Any], quelle: Path) -> None:
    fehlend = [f for f in PFLICHTFELDER if f not in daten]
    if fehlend:
        raise PolicyError(f"{quelle.name}: Pflichtfelder fehlen: {', '.join(fehlend)}")
    kriterien = daten.get("rubrik", {}).get("kriterien") or []
    if not kriterien:
        raise PolicyError(f"{quelle.name}: Die Rubrik hat kein einziges Kriterium.")
    summe = sum(float(k.get("gewicht", 0.0)) for k in kriterien)
    if abs(summe - 1.0) > 0.01:
        raise PolicyError(f"{quelle.name}: Die Gewichte der Rubrik ergeben {summe:.2f} statt 1,00.")
    laenge = daten["laenge"]
    if not (laenge["hart_min_s"] <= laenge["gut_von_s"] <= laenge["gut_bis_s"] <= laenge["hart_max_s"]):
        raise PolicyError(f"{quelle.name}: Die Längengrenzen stehen nicht in aufsteigender Reihenfolge.")
    if daten["bewertung"]["modus"] not in ("sortieren", "sperren"):
        raise PolicyError(f"{quelle.name}: bewertung.modus muss sortieren oder sperren sein.")


@lru_cache(maxsize=4)
def load(version: int = POLICY_VERSION) -> Policy:
    """Grundlage laden und prüfen. Wirft PolicyError, wenn etwas fehlt."""
    import yaml

    pfad = policy_dir() / f"clip_policy_v{version}.yaml"
    if not pfad.is_file():
        raise PolicyError(
            f"Redaktionelle Grundlage nicht gefunden: {pfad}. "
            "Ohne sie wäre jede Bewertung beliebig. EDITORIAL_DIR setzen oder die Datei anlegen."
        )
    daten = yaml.safe_load(pfad.read_text(encoding="utf-8")) or {}
    _pruefe(daten, pfad)
    return Policy(version=int(daten["version"]), stand=str(daten.get("stand", "")), roh=daten)


def policy_version(version: int = POLICY_VERSION) -> str:
    """Kennung für ``candidates.policy_version``, im selben Stil wie prompt_version."""
    return f"clip_policy_v{version}"


__all__ = [
    "POLICY_VERSION",
    "Kriterium",
    "MomentTyp",
    "Policy",
    "PolicyError",
    "load",
    "policy_dir",
    "policy_version",
]
