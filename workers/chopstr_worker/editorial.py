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

Welche Fassung gilt, entscheidet ``CHOPSTR_POLICY_VERSION`` (Standard 1, siehe ``active_version``).
Das ist der Rollback-Schalter: v1 bleibt unverändert und ladbar, neue Regeln kommen nur in v2. Jede
Fassung pinnt ausserdem die Prompt-Versionen (``Policy.prompt_pins``), damit eine neue Prompt-Datei
den laufenden Pfad nicht umschaltet, solange keine Policy sie pinnt.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

# Standard, solange ``CHOPSTR_POLICY_VERSION`` nicht gesetzt ist (bis zur Abnahme in AP11).
POLICY_VERSION = 1
POLICY_VERSION_ENV = "CHOPSTR_POLICY_VERSION"

PFLICHTFELDER = (
    "version", "laenge", "rubrik", "bewertung", "moment_typen",
    "einstieg", "ausstieg", "zusammenhang", "audio", "hook_vorziehen", "ausschluss",
)  # fmt: skip
# Abschnitte mit redaktionellen Regeln; ab v2 braucht jede Regel darin eine Herkunft in ``origins``.
RULE_SECTIONS = PFLICHTFELDER[1:]

# Prompt-Versionen der Fassung 1, im Code eingefroren, weil die v1-Datei nicht verändert wird.
# Genau die Versionen, die ``prompts.load`` ohne Versionsangabe vor AP0b geladen hat.
V1_PROMPT_PINS: dict[str, int] = {
    "system_editor": 1,
    "propose_moments": 1,
    "score_clip": 2,
    "story_graph_confirm": 1,
    "hooks": 1,
    "post_caption": 1,
}

# Ab v2 zusätzlich Pflicht: Prompt-Pins, Schalter je Arbeitspaket, Herkunft je Regel.
V2_REQUIRED_SECTIONS = ("prompts", "implementation", "origins")
# Schalter der folgenden Arbeitspakete (Plan Abschnitt 4), als Pfad in ``implementation``. Alle
# stehen auf false, bis ihr Paket gebaut und gemessen ist; einzeln abschaltbar.
V2_SWITCHES = (
    "sentence_rule",
    "gates.discard_hard",
    "search.payoff_first",
    "hook.native_spoken",
    "trim.enabled",
    "cut.padding",
    "captions.word_bridge",
)
# Schalter, deren Code gebaut ist und den Schalter liest. Jedes Arbeitspaket trägt seinen Schalter
# ein, sobald der Code ihn liest; nur diese stehen in v2 auf true, alle anderen auf false.
V2_IMPLEMENTED_SWITCHES = frozenset({
    "captions.word_bridge", "cut.padding", "gates.discard_hard", "hook.native_spoken", "search.payoff_first", "sentence_rule",
    "trim.enabled",
})  # fmt: skip
# Regelabschnitte, die es nur in v2 gibt. rule_paths und die Herkunftsprüfung laufen zusätzlich über
# sie, wenn der Abschnitt in den Daten steht; v1 hat sie nicht und bleibt unberührt.
V2_RULE_SECTIONS = ("captions", "hook", "segmentation", "verb_bracket")
# Prompt-Pins, die v2 gegenüber V1_PROMPT_PINS ändert (Prompt-Name zu Version).
V2_PIN_CHANGES: dict[str, int] = {"hooks": 2}
# F Forschungsbefund, H Übertragungshypothese, R Produktregel, G gelernte Entscheidung
# (docs/RESEARCH-CLIPPING-KERN.md, Statusschreibweise).
ORIGIN_VALUES = ("F", "H", "R", "G")


class PolicyError(RuntimeError):
    """Die redaktionelle Grundlage fehlt oder ist unbrauchbar."""


def active_version() -> int:
    """Die aktive Fassung aus ``CHOPSTR_POLICY_VERSION``; ohne Wert ``POLICY_VERSION``.

    Ein Wert, der keine ganze Zahl ist, scheitert laut: ein Tippfehler im Rollback-Schalter darf
    nicht still auf eine andere Fassung fallen."""
    raw = os.environ.get(POLICY_VERSION_ENV, "").strip()
    if not raw:
        return POLICY_VERSION
    try:
        return int(raw)
    except ValueError:
        raise PolicyError(f"{POLICY_VERSION_ENV}={raw!r} ist keine Fassungsnummer (erlaubt: 1, 2).") from None


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

    # -- Hook (AP6a, nur ab Fassung 2) ---------------------------------------------------------
    @property
    def hook(self) -> dict[str, Any]:
        """Abschnitt ``hook`` (native_spoken, hyperbole, question_as_variant); Fassung 1 hat ihn nicht."""
        return dict(self.roh.get("hook") or {})

    @property
    def hyperbole(self) -> tuple[str, ...]:
        """Leere Intensivierungen, die der Linter meldet (``hook.hyperbole``), kleingeschrieben."""
        return tuple(str(x).lower() for x in self.hook.get("hyperbole") or ())

    @property
    def allow_partial_opening(self) -> bool:
        """``hook.allow_partial_opening``: Teilsatz-Auszüge als Hook erlaubt. Fehlt die Regel, gilt false
        (ganzer Originalsatz oder kein Overlay)."""
        return self.hook.get("allow_partial_opening") is True

    @property
    def hook_native_spoken(self) -> bool:
        """Gesprochener Hook als Originalstelle und Auswahl v2: Regel ``hook.native_spoken`` und Schalter
        ``implementation.hook.native_spoken`` müssen beide true sein; einer auf false ist der Rollback."""
        if self.version < 2 or self.hook.get("native_spoken") is not True:
            return False
        return _switch_value(self.roh.get("implementation") or {}, "hook.native_spoken") is True

    # -- Prompt-Pins ---------------------------------------------------------------------------
    @property
    def prompt_pins(self) -> dict[str, int]:
        """Prompt-Name zu Version. v1 aus ``V1_PROMPT_PINS``, ab v2 aus dem Abschnitt ``prompts``."""
        if self.version == 1:
            return dict(V1_PROMPT_PINS)
        return {str(name): int(version) for name, version in self.roh["prompts"].items()}

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
    if int(daten["version"]) >= 2:
        _check_v2(daten, quelle)


def rule_paths(data: dict[str, Any]) -> list[str]:
    """Alle Regeln der Abschnitte aus ``RULE_SECTIONS`` als Punktpfad.

    Eine Regel ist ein Blattwert (Zahl, Schalter, Wortliste) oder ein Listeneintrag mit
    ``schluessel`` (Kriterium, Moment-Typ), der als Ganzes eine Regel ist:
    ``laenge.ziel_s``, ``rubrik.kriterien.hook``, ``moment_typen.zahl``, ``audio.merkmale.lachen``."""
    paths: list[str] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{path}.{key}")
        elif isinstance(value, list) and value and all(isinstance(x, dict) and "schluessel" in x for x in value):
            paths.extend(f"{path}.{x['schluessel']}" for x in value)
        else:
            paths.append(path)

    for section in RULE_SECTIONS:
        walk(data[section], section)
    # Abschnitte, die nur v2 kennt, zählen mit, sobald sie in den Daten stehen.
    for section in V2_RULE_SECTIONS:
        if section in data:
            walk(data[section], section)
    return paths


def _switch_value(implementation: dict[str, Any], path: str) -> Any:
    value: Any = implementation
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _check_v2(data: dict[str, Any], source: Path) -> None:
    """Zusätzliche Pflichten ab Fassung 2: Pins, Schalter, Herkunft je Regel."""
    name = source.name
    missing = [f for f in V2_REQUIRED_SECTIONS if not isinstance(data.get(f), dict)]
    if missing:
        raise PolicyError(f"{name}: Pflichtabschnitte fehlen: {', '.join(missing)}")
    pins = data["prompts"]
    unpinned = [prompt for prompt in V1_PROMPT_PINS if prompt not in pins]
    if unpinned:
        raise PolicyError(f"{name}: prompts pinnt nicht: {', '.join(unpinned)}")
    if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 1 for v in pins.values()):
        raise PolicyError(f"{name}: prompts braucht je Name eine ganze Versionsnummer ab 1.")
    missing_switches = [s for s in V2_SWITCHES if _switch_value(data["implementation"], s) is None]
    if missing_switches:
        raise PolicyError(f"{name}: implementation ohne Schalter: {', '.join(missing_switches)}")
    origins = data["origins"]
    paths = rule_paths(data)
    without_origin = [p for p in paths if p not in origins]
    if without_origin:
        raise PolicyError(f"{name}: Regeln ohne Herkunft in origins: {', '.join(without_origin)}")
    orphaned = [p for p in origins if p not in paths]
    if orphaned:
        raise PolicyError(f"{name}: origins nennt Regeln, die es nicht gibt: {', '.join(orphaned)}")
    for path, entry in origins.items():
        origin = entry.get("origin") if isinstance(entry, dict) else None
        if origin not in ORIGIN_VALUES:
            raise PolicyError(f"{name}: origins.{path}.origin muss F, H, R oder G sein, nicht {origin!r}.")
        if not str(entry.get("source") or "").strip():
            raise PolicyError(f"{name}: origins.{path} hat keine source.")


@lru_cache(maxsize=4)
def _load_version(version: int) -> Policy:
    import yaml

    pfad = policy_dir() / f"clip_policy_v{version}.yaml"
    if not pfad.is_file():
        raise PolicyError(
            f"Redaktionelle Grundlage nicht gefunden: {pfad}. "
            "Ohne sie wäre jede Bewertung beliebig. EDITORIAL_DIR setzen oder die Datei anlegen."
        )
    daten = yaml.safe_load(pfad.read_text(encoding="utf-8")) or {}
    _pruefe(daten, pfad)
    if int(daten["version"]) != version:
        raise PolicyError(f"{pfad.name}: Die Datei nennt version {daten['version']}, erwartet {version}.")
    return Policy(version=int(daten["version"]), stand=str(daten.get("stand", "")), roh=daten)


def load(version: int | None = None) -> Policy:
    """Grundlage laden und prüfen; ohne Argument die aktive Fassung. Wirft PolicyError, wenn etwas fehlt."""
    return _load_version(active_version() if version is None else int(version))


def clear_cache() -> None:
    """Zwischenspeicher der geladenen Fassungen leeren, etwa nach einem Wechsel von ``CHOPSTR_POLICY_VERSION``."""
    _load_version.cache_clear()


def policy_version(version: int | None = None) -> str:
    """Kennung für ``candidates.policy_version``, im selben Stil wie prompt_version; ohne Argument die aktive."""
    return f"clip_policy_v{active_version() if version is None else version}"


__all__ = [
    "ORIGIN_VALUES",
    "POLICY_VERSION",
    "POLICY_VERSION_ENV",
    "V1_PROMPT_PINS",
    "V2_SWITCHES",
    "Kriterium",
    "MomentTyp",
    "Policy",
    "PolicyError",
    "active_version",
    "clear_cache",
    "load",
    "policy_dir",
    "policy_version",
    "rule_paths",
]


# -- AP10a: Untertitel-Ereignisse (Abschnitt ``captions``, nur Fassung 2) --------------------------
CAPTION_SWITCH = "captions.word_bridge"


def caption_settings(policy: Policy) -> dict[str, Any] | None:
    """Einstellungen aus ``captions``, wenn Fassung 2 und ``implementation.captions.word_bridge`` an.

    ``None`` heisst: Verhalten vor AP10a (Fassung 1 oder Schalter aus, das ist der Rollback). Fehlt
    der Abschnitt bei eingeschaltetem Schalter oder ist ein Wert unbrauchbar, scheitert das laut:
    stillschweigend auf alte Untertitel zu fallen, sähe aus wie ein gebautes Paket."""
    if policy.version < 2:
        return None
    if _switch_value(policy.roh.get("implementation") or {}, CAPTION_SWITCH) is not True:
        return None
    raw = policy.roh.get("captions")
    if not isinstance(raw, dict):
        raise PolicyError(f"clip_policy_v{policy.version}: {CAPTION_SWITCH} ist an, der Abschnitt captions fehlt.")
    try:
        settings = {
            "bridge_words": raw["bridge_words"],
            "bridge_max_s": float(raw["bridge_max_s"]),
            "min_event_s": float(raw["min_event_s"]),
            "comma_break_only_on_overflow": raw["comma_break_only_on_overflow"],
        }
    except (KeyError, TypeError, ValueError):
        raise PolicyError(
            f"clip_policy_v{policy.version}: captions braucht bridge_words, bridge_max_s, min_event_s und "
            "comma_break_only_on_overflow."
        ) from None
    if not all(isinstance(settings[k], bool) for k in ("bridge_words", "comma_break_only_on_overflow")):
        raise PolicyError(f"clip_policy_v{policy.version}: captions.bridge_words und comma_break_only_on_overflow sind true oder false.")
    if settings["bridge_max_s"] < 0 or settings["min_event_s"] < 0:
        raise PolicyError(f"clip_policy_v{policy.version}: captions.bridge_max_s und min_event_s dürfen nicht negativ sein.")
    return settings


__all__ += ["CAPTION_SWITCH", "V2_IMPLEMENTED_SWITCHES", "V2_PIN_CHANGES", "V2_RULE_SECTIONS", "caption_settings"]


# -- AP2 und AP3: Satzende-Regel, Anfang heilen, Ende vor der Abschwächung, Verbklammer ------------
SENTENCE_RULE_SWITCH = "sentence_rule"


def _sentence_rule_on(policy: Policy) -> bool:
    return policy.version >= 2 and _switch_value(policy.roh.get("implementation") or {}, SENTENCE_RULE_SWITCH) is True


def sentence_rule(policy: Policy) -> str:
    """Satzende-Regel ``v1`` oder ``v2`` (``dach_nlp.sentence_end_kind``).

    ``v1`` in Fassung 1 und bei ausgeschaltetem ``implementation.sentence_rule`` (Rollback). Mit Schalter
    gilt ``segmentation.sentence_rule``; fehlt der Wert oder ist er unbekannt, scheitert das laut."""
    if not _sentence_rule_on(policy):
        return "v1"
    raw = policy.roh.get("segmentation")
    rule = raw.get("sentence_rule") if isinstance(raw, dict) else None
    if rule not in ("v1", "v2"):
        raise PolicyError(f"clip_policy_v{policy.version}: segmentation.sentence_rule muss v1 oder v2 sein, nicht {rule!r}.")
    return str(rule)


def context_front(policy: Policy) -> tuple[int, float] | None:
    """Grenzen für das Heilen des Anfangs (Sätze, Sekunden) oder ``None`` ohne AP2 (Rollback)."""
    if not _sentence_rule_on(policy):
        return None
    laenge = policy.roh["laenge"]
    try:
        return int(laenge["context_front_sentences"]), float(laenge["context_front_s"])
    except (KeyError, TypeError, ValueError):
        raise PolicyError(
            f"clip_policy_v{policy.version}: {SENTENCE_RULE_SWITCH} ist an, laenge.context_front_sentences "
            "oder laenge.context_front_s fehlt."
        ) from None


def never_end_on_qualification(policy: Policy) -> bool:
    """Darf die Heilung des Endes auf einem Abschwächungssatz enden? ``True`` heißt nein (nur mit AP2)."""
    return _sentence_rule_on(policy) and policy.ausstieg.get("never_end_on_qualification") is True


def verb_bracket_settings(policy: Policy) -> dict[str, Any] | None:
    """Einstellungen der Verbklammer-Prüfung über die Schnittgrenze (AP3) oder ``None`` für das Tor vor AP3.

    ``None`` in Fassung 1 und in Fassungen ohne Abschnitt ``verb_bracket``. Sonst ``{active, fallback,
    lists}``; ``active`` ist ``ausstieg.verbklammer_nicht_trennen``."""
    if policy.version < 2 or "verb_bracket" not in policy.roh:
        return None
    raw = policy.roh["verb_bracket"]
    fallback = raw.get("fallback") if isinstance(raw, dict) else None
    if fallback not in ("heuristic", "off"):
        raise PolicyError(f"clip_policy_v{policy.version}: verb_bracket.fallback muss heuristic oder off sein, nicht {fallback!r}.")
    lists = {key: tuple(str(x) for x in (raw.get(key) or ())) for key in ("particles", "subordinators", "auxiliaries")}
    if not all(lists.values()):
        raise PolicyError(f"clip_policy_v{policy.version}: verb_bracket braucht particles, subordinators und auxiliaries.")
    return {"active": policy.ausstieg.get("verbklammer_nicht_trennen") is not False, "fallback": fallback, "lists": lists}


def sentence_limits(policy: Policy) -> tuple[float, int]:
    """Obergrenze der Satzlänge unter Regel v2 (Sekunden, Wörter) aus ``segmentation``; ohne Werte 25 und 40."""
    raw = policy.roh.get("segmentation") if isinstance(policy.roh.get("segmentation"), dict) else {}
    try:
        return float(raw.get("max_sentence_s", 25)), int(raw.get("max_sentence_words", 40))
    except (TypeError, ValueError):
        raise PolicyError(f"clip_policy_v{policy.version}: segmentation.max_sentence_s und max_sentence_words sind Zahlen.") from None


__all__ += [
    "SENTENCE_RULE_SWITCH",
    "context_front",
    "never_end_on_qualification",
    "sentence_limits",
    "sentence_rule",
    "verb_bracket_settings",
]


# -- AP5: Suche vom Payoff und vom Einstieg (Abschnitt ``search``, nur Fassung 2) ------------------
SEARCH_SWITCH = "search.payoff_first"
# Hook-Typen aus Master-Prompt Abschnitt 9, in dieser Reihenfolge; Schlüssel von search.hook_type_markers.
SEARCH_HOOK_TYPES = (
    "concrete_contradiction", "mistake_with_consequence", "result_with_open_cause", "scene_with_stakes",
    "decision_rule", "demonstration", "self_correction", "recognizable_problem", "perspective_shift", "punchline",
)  # fmt: skip
# Payoff-Arten, die über Wortmarker erkannt werden (search.payoff_markers). Ergebnis mit Zahl, Auflösung
# nach Frage, Pointe nach Setup und Lachen erkennt payoff_search aus der Struktur.
SEARCH_PAYOFF_MARKER_TYPES = ("rule", "consequence", "explanation", "lesson", "emotional")
# Wo Rückweg und Verlängerung enden (search.stop_markers).
SEARCH_STOP_MARKER_TYPES = ("sponsor", "farewell", "topic_change")
# Abschnitt search ist eine Regel der Fassung 2 und braucht Herkunft; Pins für AP5.
V2_RULE_SECTIONS = (*V2_RULE_SECTIONS, "search")
V2_PIN_CHANGES.update({"propose_moments": 2, "episode_overview": 1})


def _marker_table(raw: Any, keys: tuple[str, ...], name: str, version: int) -> dict[str, tuple[str, ...]]:
    if not isinstance(raw, dict) or set(raw) != set(keys):
        raise PolicyError(f"clip_policy_v{version}: search.{name} braucht genau die Schlüssel {', '.join(keys)}.")
    table = {key: tuple(str(x).lower() for x in (raw[key] or ()) if str(x).strip()) for key in keys}
    empty = [key for key, markers in table.items() if not markers]
    if empty:
        raise PolicyError(f"clip_policy_v{version}: search.{name} ohne Marker für {', '.join(empty)}.")
    return table


def search_settings(policy: Policy) -> dict[str, Any] | None:
    """Einstellungen der Suche aus ``search`` (AP5) oder ``None`` in Fassung 1 und ohne Abschnitt.

    Rückgabe ``{payoff_first, opening_first, chapter_overlap_s, max_llm_calls_per_source_hour,
    payoff_markers, hook_type_markers, hedge_markers, stop_markers, wired}``. ``payoff_search`` und der Heuristik-Provider lesen die
    Werte immer, sobald der Abschnitt da ist; ``wired`` ist ``implementation.search.payoff_first`` und
    sagt, ob ``story_engine.run`` die Suche schon nutzt (bis zur Verdrahtung false). Ein fehlender oder
    unbrauchbarer Wert scheitert laut."""
    if policy.version < 2 or "search" not in policy.roh:
        return None
    raw = policy.roh["search"]
    v = policy.version
    if not isinstance(raw, dict):
        raise PolicyError(f"clip_policy_v{v}: search muss ein Abschnitt sein.")
    try:
        settings: dict[str, Any] = {
            "payoff_first": raw["payoff_first"],
            "opening_first": raw["opening_first"],
            "chapter_overlap_s": float(raw["chapter_overlap_s"]),
            "max_llm_calls_per_source_hour": int(raw["max_llm_calls_per_source_hour"]),
        }
    except (KeyError, TypeError, ValueError):
        raise PolicyError(
            f"clip_policy_v{v}: search braucht payoff_first, opening_first, chapter_overlap_s und "
            "max_llm_calls_per_source_hour."
        ) from None
    if not all(isinstance(settings[k], bool) for k in ("payoff_first", "opening_first")):
        raise PolicyError(f"clip_policy_v{v}: search.payoff_first und search.opening_first sind true oder false.")
    if settings["chapter_overlap_s"] < 0 or settings["max_llm_calls_per_source_hour"] < 1:
        raise PolicyError(f"clip_policy_v{v}: search.chapter_overlap_s ab 0, search.max_llm_calls_per_source_hour ab 1.")
    settings["payoff_markers"] = _marker_table(raw.get("payoff_markers"), SEARCH_PAYOFF_MARKER_TYPES, "payoff_markers", v)
    settings["hook_type_markers"] = _marker_table(raw.get("hook_type_markers"), SEARCH_HOOK_TYPES, "hook_type_markers", v)
    settings["stop_markers"] = _marker_table(raw.get("stop_markers"), SEARCH_STOP_MARKER_TYPES, "stop_markers", v)
    hedges = raw.get("hedge_markers")
    if not isinstance(hedges, list) or not hedges:
        raise PolicyError(f"clip_policy_v{v}: search.hedge_markers braucht eine Wortliste.")
    settings["hedge_markers"] = tuple(str(x).lower() for x in hedges if str(x).strip())
    settings["wired"] = _switch_value(policy.roh.get("implementation") or {}, SEARCH_SWITCH) is True
    return settings


__all__ += ["SEARCH_HOOK_TYPES", "SEARCH_PAYOFF_MARKER_TYPES", "SEARCH_STOP_MARKER_TYPES", "SEARCH_SWITCH", "search_settings"]


# -- AP7: Kürzen innerhalb des Clips (Abschnitt ``trim``, nur Fassung 2) ----------------------------
TRIM_SWITCH = "trim.enabled"
# Der Abschnitt ``trim`` ist ein Regelabschnitt: jede Regel darin braucht eine Herkunft in ``origins``.
V2_RULE_SECTIONS = (*V2_RULE_SECTIONS, "trim")
# Modalpartikeln aus P3, die ``trim.removal.never_remove`` immer enthalten muss.
TRIM_P3_MODAL_PARTICLES = ("halt", "eigentlich", "mal", "ja", "doch", "eben", "schon", "wohl")
TRIM_PAUSE_CUES = {"dramatic_before": ("number", "negation", "contrast", "punchline"), "reaction_after": ("question", "laughter", "reaction_word")}


def trim_settings(policy: Policy) -> dict[str, Any] | None:
    """Einstellungen für ``pipeline.trim_plan`` aus ``trim`` und ``zusammenhang.mindest_dichte``.

    ``None`` in Fassung 1 und ohne Abschnitt ``trim``. ``enabled`` ist nur true, wenn ``trim.enabled``
    und der Schalter ``implementation.trim.enabled`` beide true sind; das ist die Verdrahtung in der
    Kandidatensuche (Rollback: einer von beiden auf false). Die Bausteine selbst lesen die übrigen
    Werte auch bei ausgeschaltetem Schalter. Ein unbrauchbarer Wert oder eine Lockerung von E6 (mehr
    als zwei Splices, Debatten umordnen) scheitert laut."""
    if policy.version < 2 or not isinstance(policy.roh.get("trim"), dict):
        return None
    name = f"clip_policy_v{policy.version}"
    raw = policy.roh["trim"]
    try:
        pauses, removal, tail = raw["pause_classes"], raw["removal"], raw["reward_end"]
        settings: dict[str, Any] = {
            "enabled": raw["enabled"] is True and _switch_value(policy.roh.get("implementation") or {}, TRIM_SWITCH) is True,
            "pause_target_s": float(raw["pause_target_s"]),
            "min_trim_gain_s": float(raw["min_trim_gain_s"]),
            "long_silence_s": float(raw["long_silence_s"]),
            "min_segment_s": float(raw["min_segment_s"]),
            "max_semantic_splices": int(raw["max_semantic_splices"]),
            "debate_no_reorder": raw["debate_no_reorder"],
            "dramatic_before": tuple(str(x) for x in pauses["dramatic_before"]),
            "reaction_after": tuple(str(x) for x in pauses["reaction_after"]),
            "reaction_words": tuple(str(x).lower() for x in pauses["reaction_words"]),
            "punchline_window_s": float(pauses["punchline_window_s"]),
            "orientation_min_s": float(pauses["orientation_min_s"]),
            "orientation_markers": tuple(str(x).lower() for x in pauses["orientation_markers"]),
            "fillers": str(removal["fillers"]),
            "backchannel": removal["backchannel"],
            "restarts": removal["restarts"],
            "edge_markers": tuple(str(x).lower() for x in removal["edge_markers"]),
            "organisation_markers_trim": tuple(str(x).lower() for x in removal["organisation_markers"]),
            "never_remove": tuple(str(x).lower() for x in removal["never_remove"]),
            "weak_summary": tuple(str(x).lower() for x in tail["weak_summary"]),
            "sales_call": tuple(str(x).lower() for x in tail["sales_call"]),
            "farewell": tuple(str(x).lower() for x in tail["farewell"]),
            "repeat_overlap": float(tail["repeat_overlap"]),
            "organisation_markers": tuple(str(x).lower() for x in policy.ausschluss.get("organisations_marker") or ()),
            "min_density": float(policy.zusammenhang["mindest_dichte"]),
        }
    except (KeyError, TypeError, ValueError):
        raise PolicyError(
            f"{name}: trim braucht enabled, pause_target_s, min_trim_gain_s, long_silence_s, min_segment_s, "
            "max_semantic_splices, debate_no_reorder, pause_classes, removal, reward_end und zusammenhang.mindest_dichte."
        ) from None
    if not all(isinstance(settings[k], bool) for k in ("debate_no_reorder", "backchannel", "restarts")):
        raise PolicyError(f"{name}: trim.debate_no_reorder, removal.backchannel und removal.restarts sind true oder false.")
    if settings["pause_target_s"] <= 0:
        raise PolicyError(f"{name}: trim.pause_target_s muss größer als null sein (Pausen nie auf null kürzen).")
    if settings["max_semantic_splices"] > 2 or settings["max_semantic_splices"] < 0:
        raise PolicyError(f"{name}: trim.max_semantic_splices darf E6 nicht lockern (0 bis 2).")
    if settings["debate_no_reorder"] is not True:
        raise PolicyError(f"{name}: trim.debate_no_reorder muss true sein (E6, Debatten nie umordnen).")
    if settings["fillers"] != "hard":
        raise PolicyError(f"{name}: trim.removal.fillers kennt nur hard (P3).")
    for key, allowed in TRIM_PAUSE_CUES.items():
        unknown = [x for x in settings[key] if x not in allowed]
        if unknown:
            raise PolicyError(f"{name}: trim.pause_classes.{key} kennt {', '.join(unknown)} nicht.")
        missing = [x for x in allowed if x not in settings[key]]
        if missing:
            raise PolicyError(f"{name}: trim.pause_classes.{key} darf {', '.join(missing)} nicht streichen (RK 7, Pausen).")
    missing = [x for x in TRIM_P3_MODAL_PARTICLES if x not in settings["never_remove"]]
    if missing:
        raise PolicyError(f"{name}: trim.removal.never_remove darf {', '.join(missing)} nicht streichen (P3).")
    return settings


__all__ += ["TRIM_SWITCH", "trim_settings"]


# -- AP10b: Schnittkanten an Wortgrenzen (Abschnitt ``cut``, nur Fassung 2) ------------------------
CUT_SWITCH = "cut.padding"
# Der Abschnitt ``cut`` ist ein Regelabschnitt: jede Regel darin braucht eine Herkunft in ``origins``.
V2_RULE_SECTIONS = (*V2_RULE_SECTIONS, "cut")
# ``cut.low_confidence_threshold`` verweist auf die Schwelle der Transkription statt sie zu kopieren.
CUT_LOW_CONF_REFERENCE = "transcribe.LOW_CONF_THRESHOLD"


def cut_settings(policy: Policy) -> dict[str, Any] | None:
    """Einstellungen für ``pipeline.transitions`` aus ``cut``.

    ``None`` heißt: kein Padding, Schnitt exakt auf den Segmentzeiten (Fassung 1, Schalter
    ``implementation.cut.padding`` aus oder Regel ``cut.padding`` false; das ist der Rollback). Fehlt der
    Abschnitt bei eingeschaltetem Schalter oder ist ein Wert unbrauchbar, scheitert das laut."""
    if policy.version < 2 or _switch_value(policy.roh.get("implementation") or {}, CUT_SWITCH) is not True:
        return None
    name = f"clip_policy_v{policy.version}"
    raw = policy.roh.get("cut")
    if not isinstance(raw, dict):
        raise PolicyError(f"{name}: {CUT_SWITCH} ist an, der Abschnitt cut fehlt.")
    if not isinstance(raw.get("padding"), bool):
        raise PolicyError(f"{name}: cut.padding ist true oder false.")
    if raw["padding"] is not True:
        return None
    try:
        settings = {k: float(raw[k]) for k in ("lead_in_s", "lead_out_s", "min_gap_s")}
        threshold = raw["low_confidence_threshold"]
    except (KeyError, TypeError, ValueError):
        raise PolicyError(f"{name}: cut braucht padding, lead_in_s, lead_out_s, min_gap_s und low_confidence_threshold.") from None
    if threshold == CUT_LOW_CONF_REFERENCE:
        from .pipeline import transcribe

        threshold = transcribe.LOW_CONF_THRESHOLD
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0.0 <= float(threshold) <= 1.0:
        raise PolicyError(f"{name}: cut.low_confidence_threshold ist {CUT_LOW_CONF_REFERENCE} oder eine Zahl von 0 bis 1.")
    if any(v < 0 for v in settings.values()):
        raise PolicyError(f"{name}: cut.lead_in_s, lead_out_s und min_gap_s dürfen nicht negativ sein.")
    return {**settings, "low_confidence_threshold": float(threshold)}


__all__ += ["CUT_LOW_CONF_REFERENCE", "CUT_SWITCH", "cut_settings"]


# -- AP4: Harte Gates (Abschnitt ``gates``) und Modus sperren (``bewertung.modus_v2``), nur Fassung 2 --------
GATES_SWITCH = "gates.discard_hard"
GATE_RULE_KEYS = (
    "unresolved_pronoun", "back_reference", "open_question_unanswered", "boundary_negation_condition",
    "reported_speech", "forward_reference", "speaker_turn", "later_correction", "embedded_instruction",
    "meta_speech",
)  # fmt: skip
BLOCK_MODES = ("sortieren", "sperren")
V2_RULE_SECTIONS = (*V2_RULE_SECTIONS, "gates")
V2_PIN_CHANGES.update({"system_editor": 2})


def gates_settings(policy: Policy) -> dict[str, Any] | None:
    """Einstellungen der harten Gates (``pipeline.editorial_gates``) oder ``None`` in Fassung 1 und ohne
    Abschnitt ``gates``.

    ``enabled`` je Gate aus ``gates.<schluessel>``; ``discard_hard`` ist die Regel (verwerfen oder nur
    berichten); ``switch`` ist ``implementation.gates.discard_hard`` und sagt, ob ``story_engine`` die Gates
    schon anwendet (erst mit dem Paket, das sie dort liest). Fehlt ein Schlüssel oder ist er kein
    Wahrheitswert, scheitert das laut."""
    if policy.version < 2 or "gates" not in policy.roh:
        return None
    raw = policy.roh["gates"]
    name = f"clip_policy_v{policy.version}"
    if not isinstance(raw, dict):
        raise PolicyError(f"{name}: gates muss ein Abschnitt mit Schaltern sein.")
    missing = [k for k in (*GATE_RULE_KEYS, "discard_hard") if k not in raw]
    if missing:
        raise PolicyError(f"{name}: gates ohne Schalter: {', '.join(missing)}")
    not_bool = [k for k in (*GATE_RULE_KEYS, "discard_hard") if not isinstance(raw[k], bool)]
    if not_bool:
        raise PolicyError(f"{name}: gates.{not_bool[0]} ist true oder false.")
    return {
        "enabled": {k: raw[k] for k in GATE_RULE_KEYS},
        "discard_hard": raw["discard_hard"],
        "switch": _switch_value(policy.roh.get("implementation") or {}, GATES_SWITCH) is True,
    }


def block_mode_settings(policy: Policy, heuristic: bool | None = None) -> dict[str, Any] | None:
    """Modus der Bewertung ab Fassung 2 (``bewertung.modus_v2``) oder ``None`` in Fassung 1 und ohne Wert.

    ``bewertung.modus`` (v1) bleibt unverändert. ``mode`` ist der Wert aus ``modus_v2``; ``effective_mode`` gilt
    für den Lauf: mit ``only_with_language_model`` gilt ``sperren`` nur bei ``heuristic=False``; mit Heuristik und
    ohne Angabe (``None``) bleibt es bei ``sortieren`` (sichere Richtung), weil die Werte der Heuristik
    unkalibriert sind (RESEARCH-CLIPPING-KERN Abschnitt 2 Nr. 11). ``discard_below`` und
    ``cut_from`` sind die Schwellen 7 und 10 aus ``bewertung``."""
    bewertung = policy.roh.get("bewertung") or {}
    if policy.version < 2 or "modus_v2" not in bewertung:
        return None
    name = f"clip_policy_v{policy.version}"
    mode = bewertung["modus_v2"]
    if mode not in BLOCK_MODES:
        raise PolicyError(f"{name}: bewertung.modus_v2 muss sortieren oder sperren sein, nicht {mode!r}.")
    only_llm = bewertung.get("only_with_language_model")
    if not isinstance(only_llm, bool):
        raise PolicyError(f"{name}: bewertung.only_with_language_model ist true oder false.")
    reason = str(bewertung.get("begruendung") or "").strip()
    if not reason:
        raise PolicyError(f"{name}: bewertung.begruendung fehlt.")
    effective = "sortieren" if (only_llm and heuristic is not False) else mode
    return {
        "mode": mode,
        "effective_mode": effective,
        "only_with_language_model": only_llm,
        "reason": reason,
        "discard_below": policy.schwelle_verwerfen,
        "cut_from": policy.schwelle_schneiden,
    }


__all__ += ["GATES_SWITCH", "GATE_RULE_KEYS", "block_mode_settings", "gates_settings"]


# -- AP6b: Rollen (Abschnitt ``roles``) und Einstiegsvergleich (``search.compare_openings``), nur Fassung 2 ---
# Analyst ist episode_overview (AP5), Editor propose_moments_v2 und die Einstiegswahl, Kritiker critique_clip,
# Evaluator deterministisch (Gates und Teilwerte). Nur der Kritiker hat eine eigene Regel und einen Schalter.
CRITIC_SWITCH = "roles.critic"
V2_SWITCHES = (*V2_SWITCHES, CRITIC_SWITCH)
V2_IMPLEMENTED_SWITCHES = V2_IMPLEMENTED_SWITCHES | {CRITIC_SWITCH}
V2_RULE_SECTIONS = (*V2_RULE_SECTIONS, "roles")
V2_PIN_CHANGES.update({"critique_clip": 1})


def critic_enabled(policy: Policy) -> bool:
    """Läuft der Kritiker (``critique_clip``) für die Überlebenden von ``select_best``?

    Nur in Fassung 2 und nur, wenn die Regel ``roles.critic`` und der Schalter ``implementation.roles.critic``
    beide true sind; einer auf false ist der Rollback. Ohne Abschnitt ``roles`` false; ein Wert, der kein
    Wahrheitswert ist, scheitert laut."""
    if policy.version < 2 or "roles" not in policy.roh:
        return False
    raw = policy.roh["roles"]
    if not isinstance(raw, dict) or not isinstance(raw.get("critic"), bool):
        raise PolicyError(f"clip_policy_v{policy.version}: roles.critic ist true oder false.")
    return raw["critic"] is True and _switch_value(policy.roh.get("implementation") or {}, CRITIC_SWITCH) is True


def compare_openings_enabled(policy: Policy) -> bool:
    """``search.compare_openings``: ``story_engine.evaluate_span`` vergleicht bis zu drei Originaleinstiege
    (``payoff_search.alternative_openings``) und wählt einen. Fassung 1 und ohne Wert false (Rollback: false);
    ein Wert, der kein Wahrheitswert ist, scheitert laut."""
    raw = policy.roh.get("search")
    if policy.version < 2 or not isinstance(raw, dict) or "compare_openings" not in raw:
        return False
    if not isinstance(raw["compare_openings"], bool):
        raise PolicyError(f"clip_policy_v{policy.version}: search.compare_openings ist true oder false.")
    return raw["compare_openings"]


__all__ += ["CRITIC_SWITCH", "compare_openings_enabled", "critic_enabled"]


# -- AP9: Ausgabeumfang und Redundanz (Abschnitt ``output``), Länge nur als Abzug, Register der Schlüssel ---
OUTPUT_SWITCH = "output.max_candidates"
V2_SWITCHES = (*V2_SWITCHES, OUTPUT_SWITCH)
V2_IMPLEMENTED_SWITCHES = V2_IMPLEMENTED_SWITCHES | {OUTPUT_SWITCH}
V2_RULE_SECTIONS = (*V2_RULE_SECTIONS, "output")
# score_clip_v3: sieben Kriterien wie v2 plus Teilwerte nach Master-Prompt 19 (``story_score.editorial_subscores``).
V2_PIN_CHANGES.update({"score_clip": 3})
KEY_STATUSES = ("implemented", "partial", "not_implemented")


def output_settings(policy: Policy) -> dict[str, Any] | None:
    """Obergrenze und Redundanzschwelle für ``story_engine.select_best`` aus ``output`` (AP9).

    ``None`` in Fassung 1 und bei ausgeschaltetem ``implementation.output.max_candidates`` (Rollback: Verhalten
    vor AP9, höchstens ``story_engine.MAX_CANDIDATES``). Fehlt der Abschnitt bei eingeschaltetem Schalter
    oder ist ein Wert unbrauchbar, scheitert das laut."""
    if policy.version < 2 or _switch_value(policy.roh.get("implementation") or {}, OUTPUT_SWITCH) is not True:
        return None
    name = f"clip_policy_v{policy.version}"
    raw = policy.roh.get("output")
    try:
        limit, jaccard = raw["max_candidates"], float(raw["redundancy_jaccard"])
    except (KeyError, TypeError, ValueError):
        raise PolicyError(f"{name}: {OUTPUT_SWITCH} ist an, output braucht max_candidates und redundancy_jaccard.") from None
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise PolicyError(f"{name}: output.max_candidates ist eine ganze Zahl ab 1.")
    if not 0.0 < jaccard <= 1.0:
        raise PolicyError(f"{name}: output.redundancy_jaccard liegt über 0 und höchstens bei 1.")
    return {"max_candidates": limit, "redundancy_jaccard": jaccard}


def length_only_as_penalty(policy: Policy) -> bool:
    """``bewertung.length_only_as_penalty``: kein Längenbonus in der Heuristik, Länge nur über ``laenge_abzug``.

    Fassung 1 und ohne Wert false (Verhalten vor AP9); ein Wert, der kein Wahrheitswert ist, scheitert laut."""
    raw = (policy.roh.get("bewertung") or {}).get("length_only_as_penalty")
    if policy.version < 2 or raw is None:
        return False
    if not isinstance(raw, bool):
        raise PolicyError(f"clip_policy_v{policy.version}: bewertung.length_only_as_penalty ist true oder false.")
    return raw


__all__ += ["KEY_STATUSES", "OUTPUT_SWITCH", "length_only_as_penalty", "output_settings"]

# Register der Schlüssel (AP9): Schlüsselpfad (``rule_paths`` der Fassung 2) zu der Funktion, die ihn liest
# (``modul:qualname``). Status und Grund je Schlüssel stehen in ``implementation.keys`` der Fassung 2; hier
# stehen nur Schlüssel mit Status ``implemented`` oder ``partial``. Jeder Eintrag ist per grep geprüft, der Test
# verlangt, dass die Funktion existiert und den Schlüssel im Quelltext nennt. Ein Verhalten ohne eigenen
# Schlüssel steht in ``IMPLEMENTED_BEHAVIOURS``.
_E, _SE, _H = "chopstr_worker.editorial:", "chopstr_worker.pipeline.story_engine:", "chopstr_worker.heuristic_llm:"
IMPLEMENTED_KEYS: dict[str, str] = {
    "laenge.ziel_s": "chopstr_worker.pipeline.payoff_search:_extend",
    "laenge.gut_von_s": _E + "Policy.laenge_abzug",
    "laenge.gut_bis_s": _E + "Policy.laenge_abzug",
    "laenge.hart_min_s": _SE + "_length_reason",
    "laenge.hart_max_s": _SE + "_length_reason",
    "laenge.kontext_zugabe_s": _SE + "kontext_verlaengern",
    "laenge.kontext_zugabe_saetze": _SE + "kontext_verlaengern",
    "laenge.context_front_sentences": _E + "context_front",
    "laenge.context_front_s": _E + "context_front",
    "rubrik.skala_max": _E + "Policy.gesamtwert",
    "rubrik.kriterien.standalone": _E + "Policy.kriterien",
    "rubrik.kriterien.hook": _E + "Policy.kriterien",
    "rubrik.kriterien.offene_frage": _E + "Policy.kriterien",
    "rubrik.kriterien.spezifitaet": _E + "Policy.kriterien",
    "rubrik.kriterien.emotion": _E + "Policy.kriterien",
    "rubrik.kriterien.aufloesung": _E + "Policy.kriterien",
    "rubrik.kriterien.zielgruppe": _E + "Policy.kriterien",
    "bewertung.schwelle_verwerfen": _E + "block_mode_settings",
    "bewertung.punkte_gesamt": _E + "Policy.gesamtwert",
    "bewertung.modus_v2": _E + "block_mode_settings",
    "bewertung.only_with_language_model": _E + "block_mode_settings",
    "bewertung.begruendung": _E + "block_mode_settings",
    "bewertung.length_only_as_penalty": _H + "_aufloesung",
    "moment_typen.contrarian": _SE + "satz_staerke",
    "moment_typen.zahl": _SE + "satz_staerke",
    "moment_typen.ministory": _SE + "satz_staerke",
    "moment_typen.gestaendnis": _SE + "satz_staerke",
    "moment_typen.merksatz": _SE + "satz_staerke",
    "moment_typen.konflikt": _H + "episode_overview",
    "einstieg.nie_mitten_im_satz": _SE + "start_defects",
    "einstieg.keine_pronomen_ohne_bezug": _SE + "start_defects",
    "einstieg.pronomen": _SE + "start_defects",
    "einstieg.keine_gastgeberfrage": _SE + "heal_start",
    "einstieg.einleitungen_kappen": _H + "_standalone",
    "einstieg.einleitungsfloskeln": _H + "_standalone",
    "ausstieg.satz_zu_ende": _H + "_aufloesung",
    "ausstieg.verbklammer_nicht_trennen": _E + "verb_bracket_settings",
    "ausstieg.vor_der_abschwaechung": _H + "_aufloesung",
    "ausstieg.abschwaechung_marker": _SE + "_qualification_markers",
    "ausstieg.never_end_on_qualification": _E + "never_end_on_qualification",
    "zusammenhang.mindest_dichte": _E + "trim_settings",
    "audio.in_bewertung_verwenden": _SE + "policy_total",
    "audio.gewicht": _SE + "policy_total",
    "hook_vorziehen.aktiv": _SE + "teaser_satz",
    "hook_vorziehen.mindest_vorsprung": _SE + "teaser_satz",
    "hook_vorziehen.max_teaser_s": _SE + "teaser_satz",
    "hook_vorziehen.nicht_aus_letztem_anteil": _SE + "teaser_satz",
    "ausschluss.organisatorisches_gespraech": _E + "Policy.ist_organisatorisch",
    "ausschluss.organisations_marker": _E + "Policy.ist_organisatorisch",
    "captions.bridge_words": _E + "caption_settings",
    "captions.bridge_max_s": _E + "caption_settings",
    "captions.min_event_s": _E + "caption_settings",
    "captions.comma_break_only_on_overflow": _E + "caption_settings",
    "hook.native_spoken": _E + "Policy.hook_native_spoken",
    "hook.hyperbole": _E + "Policy.hyperbole",
    "hook.allow_partial_opening": _E + "Policy.allow_partial_opening",
    "segmentation.sentence_rule": _E + "sentence_rule",
    "segmentation.max_sentence_s": _E + "sentence_limits",
    "segmentation.max_sentence_words": _E + "sentence_limits",
    "verb_bracket.fallback": _E + "verb_bracket_settings",
    "verb_bracket.particles": _E + "verb_bracket_settings",
    "verb_bracket.subordinators": _E + "verb_bracket_settings",
    "verb_bracket.auxiliaries": _E + "verb_bracket_settings",
    "search.payoff_first": _E + "search_settings",
    "search.opening_first": _E + "search_settings",
    "search.chapter_overlap_s": _E + "search_settings",
    "search.max_llm_calls_per_source_hour": _E + "search_settings",
    "search.budget_min_source_s": _E + "budget_min_source_s",
    "search.payoff_markers.rule": _E + "search_settings",
    "search.payoff_markers.consequence": _E + "search_settings",
    "search.payoff_markers.explanation": _E + "search_settings",
    "search.payoff_markers.lesson": _E + "search_settings",
    "search.payoff_markers.emotional": _E + "search_settings",
    "search.hedge_markers": _E + "search_settings",
    "search.stop_markers.sponsor": _E + "search_settings",
    "search.stop_markers.farewell": _E + "search_settings",
    "search.stop_markers.topic_change": _E + "search_settings",
    "search.hook_type_markers.concrete_contradiction": _E + "search_settings",
    "search.hook_type_markers.mistake_with_consequence": _E + "search_settings",
    "search.hook_type_markers.result_with_open_cause": _E + "search_settings",
    "search.hook_type_markers.scene_with_stakes": _E + "search_settings",
    "search.hook_type_markers.decision_rule": _E + "search_settings",
    "search.hook_type_markers.demonstration": _E + "search_settings",
    "search.hook_type_markers.self_correction": _E + "search_settings",
    "search.hook_type_markers.recognizable_problem": _E + "search_settings",
    "search.hook_type_markers.perspective_shift": _E + "search_settings",
    "search.hook_type_markers.punchline": _E + "search_settings",
    "search.compare_openings": _E + "compare_openings_enabled",
    "trim.enabled": _E + "trim_settings",
    "trim.pause_target_s": _E + "trim_settings",
    "trim.min_trim_gain_s": _E + "trim_settings",
    "trim.long_silence_s": _E + "trim_settings",
    "trim.min_segment_s": _E + "trim_settings",
    "trim.max_semantic_splices": _E + "trim_settings",
    "trim.debate_no_reorder": _E + "trim_settings",
    "trim.pause_classes.dramatic_before": _E + "trim_settings",
    "trim.pause_classes.reaction_after": _E + "trim_settings",
    "trim.pause_classes.reaction_words": _E + "trim_settings",
    "trim.pause_classes.punchline_window_s": _E + "trim_settings",
    "trim.pause_classes.orientation_min_s": _E + "trim_settings",
    "trim.pause_classes.orientation_markers": _E + "trim_settings",
    "trim.removal.fillers": _E + "trim_settings",
    "trim.removal.backchannel": _E + "trim_settings",
    "trim.removal.restarts": _E + "trim_settings",
    "trim.removal.edge_markers": _E + "trim_settings",
    "trim.removal.organisation_markers": _E + "trim_settings",
    "trim.removal.never_remove": _E + "trim_settings",
    "trim.reward_end.weak_summary": _E + "trim_settings",
    "trim.reward_end.sales_call": _E + "trim_settings",
    "trim.reward_end.farewell": _E + "trim_settings",
    "trim.reward_end.repeat_overlap": _E + "trim_settings",
    "gates.unresolved_pronoun": _E + "gates_settings",
    "gates.back_reference": _E + "gates_settings",
    "gates.open_question_unanswered": _E + "gates_settings",
    "gates.boundary_negation_condition": _E + "gates_settings",
    "gates.reported_speech": _E + "gates_settings",
    "gates.forward_reference": _E + "gates_settings",
    "gates.speaker_turn": _E + "gates_settings",
    "gates.later_correction": _E + "gates_settings",
    "gates.embedded_instruction": _E + "gates_settings",
    "gates.meta_speech": _E + "gates_settings",
    "gates.discard_hard": _E + "gates_settings",
    "cut.padding": _E + "cut_settings",
    "cut.lead_in_s": _E + "cut_settings",
    "cut.lead_out_s": _E + "cut_settings",
    "cut.min_gap_s": _E + "cut_settings",
    "cut.low_confidence_threshold": _E + "cut_settings",
    "roles.critic": _E + "critic_enabled",
    "output.max_candidates": _E + "output_settings",
    "output.redundancy_jaccard": _E + "output_settings",
}
# Neubewertung nach der Verlängerung (Heilung vorn oder hinten, AP2): genau eine Neubewertung der neuen Spanne.
IMPLEMENTED_BEHAVIOURS: dict[str, str] = {"rescore_after_extension": _SE + "evaluate_span"}


def key_register(policy: Policy) -> dict[str, dict[str, str]]:
    """``implementation.keys`` der Fassung (Schlüsselpfad zu ``{status, reason}``); leer in Fassung 1."""
    if policy.version < 2:
        return {}
    raw = (policy.roh.get("implementation") or {}).get("keys") or {}
    return {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}


__all__ += ["IMPLEMENTED_BEHAVIOURS", "IMPLEMENTED_KEYS", "key_register"]


# -- Verdrahtung AP4 und AP5 in story_engine (Budget-Untergrenze) ------------------------------------------


def budget_min_source_s(policy: Policy) -> float:
    """Mindestdauer in Sekunden, mit der eine Quelle in das Modellbudget eingeht (``search.budget_min_source_s``,
    Fassung 2). Fehlt der Wert, scheitert das laut; in Fassung 1 gibt es kein Budget (0)."""
    if policy.version < 2 or "search" not in policy.roh:
        return 0.0
    try:
        value = float(policy.roh["search"]["budget_min_source_s"])
    except (KeyError, TypeError, ValueError):
        raise PolicyError(f"clip_policy_v{policy.version}: search.budget_min_source_s fehlt oder ist keine Zahl.") from None
    if value < 0:
        raise PolicyError(f"clip_policy_v{policy.version}: search.budget_min_source_s ab 0.")
    return value


__all__ += ["budget_min_source_s"]
