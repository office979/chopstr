"""Story-Engine (Phase 2): aus Transkript und Heatmap werden sinntreue Clip-Kandidaten mit Begründung.

Vier Stufen, alle als reine Funktionen (das LLM wird injiziert, Tests nutzen ein Fake):

  1. Seeds aus der Heatmap bestimmen die Reihenfolge der Kapitel (Kapitel mit Seeds zuerst,
     Kapitel ohne Seeds werden trotzdem bewertet).
  2. ``story_score.propose`` schlägt pro Kapitel 0 bis 4 Satz-Spannen vor (``propose_moments_v1``).
  3. ``story_score.score_with_repair`` bewertet mit der Rubrik (``score_clip_v1``) und erweitert bei
     fehlendem Kontext die Grenzen (erst nach vorn, dann nach hinten, maximal zwei Runden).
     Deterministische Gates laufen zusätzlich: Satzgrenzen, Verbklammer, Open-Loop-Ende, Sinntreue.
  4. ``story_graph.find_later_qualifications`` sucht im 60-Sekunden-Folgefenster nach Relativierungen;
     jeder Treffer wird per ``story_graph_confirm_v1`` bestätigt. Liefert das Modell kein Urteil
     (Heuristik-Provider), bleibt ``confirmed = null``.

Regeln: Länge 12 bis 90 Sekunden hart (Verwerfen ist ein Ergebnis, Gründe landen im Bericht, nicht in
der Tabelle), maximal ``MAX_CANDIDATES`` Kandidaten nach Rubrik. Die Rückgabe entspricht Zeile für Zeile
dem Vertrag ``packages/schema/CANDIDATES.md`` (``candidates_v1``).
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from typing import Any

from .. import editorial, prompts
from ..providers_llm import LLM
from . import compose, dach_nlp, editorial_gates, fidelity, payoff_search, story_graph, story_score, trim_plan
from .segment import Sentence, chapterize, numbered, sentences_from_annotated, sentences_from_words

CONTRACT = "candidates_v1"
# v2: Bewertung aus der redaktionellen Grundlage (sieben Kriterien statt fuenf), mit
#     Laengenabzug und Klanganteil.
# v3: Hook vorziehen. Der staerkste Satz aus der Mitte kann als Teaser vorangestellt
#     werden; die Laengenbewertung rechnet dann mit der Abspieldauer, nicht der Quellspanne.
# Der Wert steckt im Idempotenz-Schluessel und erzwingt eine Neuberechnung. Ohne ihn
# kaeme das alte Ergebnis aus dem Zwischenspeicher und die Aenderung waere unsichtbar.
ENGINE_VERSION = "story_engine_v4"
# v5 (nur Policy-Fassung 2): harte Gates vor dem Ranking (AP4), Payoff-Suche mit Abgleich und Budget (AP5),
# Kürzung (AP7, nur mit trim.enabled) und ClipCandidates im Bericht (AP8). Unter Fassung 1 bleibt v4 im
# Bericht und im Idempotenz-Schlüssel, damit vorhandene Ergebnisse gültig bleiben (Rollback).
ENGINE_VERSION_V2 = "story_engine_v5"
# Die Laengengrenzen stehen in der Richtlinie (packages/editorial/clip_policy_v1.yaml) und nur
# dort. Hier standen frueher 12 und 90 Sekunden, waehrend die Richtlinie 18 und 70 als „hart"
# fuehrte: zwei Wahrheiten, von denen die laxere gewann. So ist an BP CW ein Clip von 78 Sekunden
# entstanden. Die beiden Namen bleiben als Ruecklauf, falls die Richtlinie fehlt.
MIN_LEN_S = 12.0
MAX_LEN_S = 90.0

# Tore, die sich durch Verlaengern nach hinten beheben lassen. Alle drei beschreiben ein kaputtes
# ENDE; was am Anfang fehlt, holt die Verlaengerung nach hinten nicht zurueck.
ENDE_TORE = ("fidelity", "sentence_boundaries", "no_open_loop")
MAX_CANDIDATES = 20
MAX_PER_CHAPTER = 4
MAX_REPAIR_ROUNDS = 2
CHAPTER_SECONDS = 240.0
# Ab wann zwei Spannen als derselbe Clip gelten, gemessen am KUERZEREN der beiden.
#
# Vorher stand hier IoU, also Schnittmenge durch Vereinigung. Das ist das falsche Mass, sobald die
# Laengen auseinandergehen, und das tun sie: die Richtlinie erlaubt 18 bis 70 Sekunden. An BP CW
# gemessen lagen ein Clip von 0 bis 19,6 s und einer von 9,9 bis 87,9 s nebeneinander. Die Haelfte
# des kurzen steckt im langen, aber IoU ist nur 9,7 / 87,9 = 0,11 und damit weit unter jeder
# sinnvollen Schwelle. Der Zuschauer sieht zwei Clips, von denen einer zur Haelfte den anderen
# wiederholt.
#
# Am Anteil des kuerzeren gemessen sind es 49 Prozent. Ueber alle drei vorhandenen Quellen liegt
# kein einziges ueberlappendes Paar zwischen 0 und 49 Prozent; der genaue Wert der Schwelle ist
# deshalb unkritisch, solange er in dieser Luecke liegt. 0,4 ist die Linie, ab der ein Clip nicht
# mehr fuer sich steht.
OVERLAP_SUPPRESS_ANTEIL = 0.4
FIDELITY_TAIL_WORDS = 3
SCORE_KEYS = ("hook", "payoff", "specificity", "tension", "audience_fit")

PLATFORM_LABELS = {"linkedin": "LinkedIn", "tiktok": "TikTok", "reels": "Instagram Reels", "shorts": "YouTube Shorts"}

ProgressFn = Callable[[int, int, int], None]


@dataclass
class CandidateResult:
    """Eine Zeile der Tabelle ``candidates`` (ohne id, version, Urteil, Zeitstempel)."""

    segments: list[dict]
    start_s: float
    end_s: float
    first_sent: int
    last_sent: int
    structure: str
    rubric: dict
    gates: dict
    story_graph_flags: list[dict]
    risk_flags: list[str]
    total: float
    gate_passed: bool
    why: str
    model_id: str
    prompt_version: str | None

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s

    def to_row(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> CandidateResult:
        names = [f.name for f in fields(cls)]
        return cls(**{k: row[k] for k in names})


@dataclass
class DetectReport:
    """Ergebnis eines Laufs: Kandidaten plus Zähler und Verwerfungsgründe für Event-Payload und Storage.

    Die Felder ab ``engine`` gibt es nur unter Fassung 2; leer stehen sie nicht im JSON, damit der Bericht
    unter Fassung 1 byte-gleich bleibt. Alte Berichte ohne sie bleiben lesbar."""

    candidates: list[CandidateResult] = field(default_factory=list)
    # Gefunden, aber nicht angeboten: gerissenes Tor, Ueberlappung oder ueber der Obergrenze. Die
    # Gruende stehen in ``discarded``, die Kandidaten selbst hier. Ohne das waere nach der Auswahl
    # nicht mehr nachvollziehbar, WAS verworfen wurde, nur noch dass etwas verworfen wurde.
    verworfen: list[CandidateResult] = field(default_factory=list)
    discarded: list[dict] = field(default_factory=list)
    chapters: int = 0
    chapters_with_seeds: int = 0
    proposals: int = 0
    prompt_versions: list[str] = field(default_factory=list)
    model_id: str = ""
    provider: str = ""
    weights: dict[str, float] = field(default_factory=dict)
    # Wie die Verbklammer geprüft wurde (AP3, nur Fassung 2): spacy, heuristic oder off. Leer heißt
    # Fassung 1; dann steht der Schlüssel nicht im JSON, damit v1 byte-gleich bleibt.
    nlp_status: str = ""
    # Fassung 2: Engine-Version des Laufs (v5), Episodenübersichten je Kapitel (gecacht mit dem Bericht unter
    # dem Idempotenz-Schlüssel der Kandidaten), Modellbudget, Verwerfungsquote je Gate, Abgleich der Suche
    # und die vollständigen ClipCandidates (Vertrag clip_candidate_v1).
    engine: str = ""
    overviews: list[dict] = field(default_factory=list)
    llm_budget: dict = field(default_factory=dict)
    gate_rejections: dict = field(default_factory=dict)
    search: dict = field(default_factory=dict)
    clip_candidates: list[dict] = field(default_factory=list)
    # Fassung 2 mit Suche: Kapitel ohne tragfähigen Moment (weder Modell- noch Suchvorschlag), je mit Grund.
    rejected_chapters: list[dict] = field(default_factory=list)

    @property
    def gate_passed(self) -> int:
        return sum(1 for c in self.candidates if c.gate_passed)

    def to_json(self) -> dict[str, Any]:
        out = {
            "contract": CONTRACT,
            "engine": self.engine or ENGINE_VERSION,
            "candidates": [c.to_row() for c in self.candidates],
            "discarded": self.discarded,
            "chapters": self.chapters,
            "chapters_with_seeds": self.chapters_with_seeds,
            "proposals": self.proposals,
            "prompt_versions": self.prompt_versions,
            "model_id": self.model_id,
            "provider": self.provider,
            "weights": self.weights,
        }
        if self.nlp_status:
            out["nlp_status"] = self.nlp_status
        for key in ("overviews", "llm_budget", "gate_rejections", "search", "clip_candidates", "rejected_chapters"):
            if getattr(self, key):
                out[key] = getattr(self, key)
        return out

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> DetectReport:
        return cls(
            candidates=[CandidateResult.from_row(r) for r in data.get("candidates", [])],
            discarded=list(data.get("discarded", [])),
            chapters=int(data.get("chapters", 0)),
            chapters_with_seeds=int(data.get("chapters_with_seeds", 0)),
            proposals=int(data.get("proposals", 0)),
            prompt_versions=list(data.get("prompt_versions", [])),
            model_id=str(data.get("model_id", "")),
            provider=str(data.get("provider", "")),
            weights=dict(data.get("weights", {})),
            nlp_status=str(data.get("nlp_status", "") or ""),
            engine=str(data.get("engine", "") or ""),
            overviews=list(data.get("overviews") or []),
            llm_budget=dict(data.get("llm_budget") or {}),
            gate_rejections=dict(data.get("gate_rejections") or {}),
            search=dict(data.get("search") or {}),
            clip_candidates=list(data.get("clip_candidates") or []),
            rejected_chapters=list(data.get("rejected_chapters") or []),
        )


# -- Gewichte ------------------------------------------------------------------------------------


# P14 ist für die Rangfolge ausgesetzt (Entscheidung P29, AP9): ``resolve_weights`` und ``weighted_total`` bleiben
# für Bericht (``DetectReport.weights``) und Decision Log, über die Reihenfolge entscheidet nur ``policy_total``.
# Unter Fassung 2 steht das je Kandidat in ``rubric.learned_weights_applied`` (false) mit diesem Grund.
LEARNED_WEIGHTS_REASON = (
    "P14 ist für die Rangfolge ausgesetzt (Entscheidung P29): gelernte Gewichte werden protokolliert, die "
    "Reihenfolge kommt aus policy_total nach der Grundlage. Es gibt keine Entscheidung der Art G, und die fünf "
    "gelernten Gewichte passen nicht zu den sieben Kriterien der Rubrik."
)


def resolve_weights(learned: dict[str, Any] | None, default: dict[str, float] | None = None) -> dict[str, float]:
    """Gewichte aus ``brand_profiles.learned_weights``, sonst die des Prompts ``score_clip``.

    Gelernte Gewichte gelten nur, wenn alle fünf Schlüssel vorhanden sind und die Summe etwa 1 ist."""
    base = dict(default or story_score.weights())
    if not isinstance(learned, dict):
        return base
    try:
        cand = {k: float(learned[k]) for k in SCORE_KEYS}
    except (KeyError, TypeError, ValueError):
        return base
    if any(v < 0 for v in cand.values()) or abs(sum(cand.values()) - 1.0) > 0.02:
        return base
    return cand


def weighted_total(scores: dict[str, Any], weights: dict[str, float]) -> float:
    """Alte Rechnung über die fünf Schlüssel auf der Skala 0 bis 10.

    Bleibt erhalten, weil die gelernten Gewichte aus ``brand_profiles.learned_weights`` darauf
    aufbauen und weil Bestandszeilen vergleichbar bleiben sollen. Über die Rangfolge entscheidet
    sie nicht mehr, siehe ``policy_total``.
    """
    return round(sum(float(scores.get(k, 0) or 0) * weights[k] for k in SCORE_KEYS), 2)


def audio_wert(heat_payload: dict[str, Any] | None, start_s: float, end_s: float) -> float | None:
    """Wie auffällig ist dieser Abschnitt im Klang? 0 bis 1, wobei 0,5 den Durchschnitt meint.

    Grundlage ist der reine Audioanteil der Heatmap (RMS-Energie und Spectral Flux, bereits als
    z-Wert auf -3 bis 3 begrenzt). Der Textanteil bleibt bewusst aussen vor: Diskursmarker, Fragen
    und Zahlen stecken schon in der Rubrik, sie ein zweites Mal über die Heatmap einzurechnen wäre
    eine Doppelzählung.

    Zwei Anteile, je zur Hälfte:
      * das mittlere Niveau im Abschnitt, also wie laut und bewegt dort gesprochen wird,
      * der Anstieg innerhalb des Abschnitts. Die Masterclass nennt beim Moment-Typ Konflikt
        ausdrücklich die „lauter werdende Stimme"; ein Abschnitt, der sich steigert, ist etwas
        anderes als einer, der durchgehend laut ist.

    None heisst: kein Audioanteil vorhanden. Alte Heatmaps haben ihn nicht, und ein geratener
    Mittelwert wäre schlechter als die ehrliche Auskunft, dass nichts vorliegt.
    """
    if not heat_payload:
        return None
    werte = heat_payload.get("audio_values")
    if not werte:
        return None
    bin_s = float(heat_payload.get("bin_s") or 1.0) or 1.0
    von, bis = int(start_s / bin_s), int(end_s / bin_s) + 1
    teil = [float(v) for v in werte[max(0, von) : bis]]
    if not teil:
        return None

    # z-Werte liegen auf -3 bis 3, also auf 0 bis 1 abbilden.
    niveau = (sum(teil) / len(teil) + 3.0) / 6.0
    if len(teil) >= 4:
        h = len(teil) // 2
        erste, zweite = sum(teil[:h]) / h, sum(teil[h:]) / (len(teil) - h)
        anstieg = (zweite - erste + 3.0) / 6.0
    else:
        anstieg = 0.5
    return round(max(0.0, min(1.0, 0.5 * niveau + 0.5 * anstieg)), 3)


def satz_staerke(s: Sentence, pol: editorial.Policy, heat_payload: dict[str, Any] | None) -> float:
    """Wie stark traegt dieser einzelne Satz, wenn man ihn allein hoert?

    Zwei Quellen, beide schon vorhanden: die Moment-Typen der Grundlage mit ihren Markern, und der
    Klang des Satzes. Ein Satz, bei dem die Stimme hochgeht, traegt anders als einer im Plauderton.

    Ein Satz, der mit einem Rueckverweis beginnt, ist als Teaser disqualifiziert, egal wie stark er
    sonst waere: an den Anfang gezogen haette er nichts, worauf er sich bezieht. Genau diesen Fehler
    machen mehrere der schlechten Beispielclips.
    """
    text = str(s.text or "").strip()
    if not text:
        return -1.0
    woerter = text.split()
    erstes = dach_nlp.core_token(woerter[0]) if woerter else ""
    if erstes in set(pol.einstieg.get("pronomen", ())) or erstes in dach_nlp.OPEN_LOOP_END:
        return -1.0

    klein = text.lower()
    wert = sum(t.bonus for t in pol.moment_typen if not t.braucht_audio and t.trifft(klein))
    klang = audio_wert(heat_payload, s.start, s.end)
    if klang is not None:
        wert += (klang - 0.5) * 4.0  # -2 bis +2
    return round(wert, 3)


def teaser_satz(
    sents: list[Sentence],
    first: int,
    last: int,
    pol: editorial.Policy,
    heat_payload: dict[str, Any] | None,
) -> int | None:
    """Index des Satzes, der nach vorn gezogen werden soll, oder None.

    Masterclass 10.3: „Die staerkste Aussage, oft aus der Mitte, an den Anfang stellen, dann
    zurueckspringen." Drei Bedingungen aus der Grundlage:

      * Der Satz muss deutlich staerker sein als der bisherige Anfang (``mindest_vorsprung``).
        Ohne diesen Abstand waere das Umstellen Selbstzweck und nur Unruhe.
      * Er darf nicht aus dem letzten Teil stammen (``nicht_aus_letztem_anteil``), sonst nimmt der
        Teaser die Aufloesung vorweg und der Clip ist nach drei Sekunden erzaehlt.
      * Er muss in die Teaserlaenge passen (``max_teaser_s``).
    """
    cfg = pol.hook_vorziehen
    if not cfg.get("aktiv"):
        return None
    n = last - first + 1
    if n < 3:
        return None

    anteil = float(cfg.get("nicht_aus_letztem_anteil", 0.25) or 0.0)
    grenze = last - int(n * anteil)
    max_s = float(cfg.get("max_teaser_s", 6.0))
    kandidaten = [i for i in range(first + 1, grenze + 1) if (sents[i].end - sents[i].start) <= max_s]
    if not kandidaten:
        return None

    staerken = {i: satz_staerke(sents[i], pol, heat_payload) for i in kandidaten}
    bester = max(staerken, key=lambda i: staerken[i])
    vorsprung = staerken[bester] - satz_staerke(sents[first], pol, heat_payload)
    if vorsprung < float(cfg.get("mindest_vorsprung", 2.0)):
        return None
    return bester


def policy_total(
    r: dict[str, Any], dauer_s: float, pol: editorial.Policy | None = None, audio: float | None = None
) -> float:
    """Gesamtwert nach der redaktionellen Grundlage, mit Längenabzug und Klang.

    Zwei Dinge fehlten der alten Rechnung, und beide sind genau das, was die Auswertung der
    Beispielclips als Schwäche gezeigt hat:

    Erstens kannte sie nur fünf Kriterien. ``standalone`` und ``emotion`` kamen mit der Grundlage
    neu dazu und hätten ohne diese Änderung keine Wirkung auf die Rangfolge gehabt; sie wären
    berechnet und danach verworfen worden.

    Zweitens wirkte die Länge gar nicht auf den Gesamtwert. Sie ist der grösste gemessene
    Unterschied zur Referenz: 19,3 s im Median bei uns gegen 41,3 s bei 105 guten Beispielclips.

    Fehlen die sieben Punkte (alte Antwort, kaputter Provider), fällt der Wert auf null statt auf
    einen geratenen Mittelwert. Ein unbewertbarer Moment soll nach hinten rutschen, nicht zufällig
    nach vorn.
    """
    pol = pol or editorial.load()
    punkte = r.get("rubric_points") or {}
    if not punkte:
        return 0.0
    wert = pol.gesamtwert(punkte) * (1.0 - pol.laenge_abzug(dauer_s))

    # Klang wirkt symmetrisch um den Durchschnitt: 0,5 lässt den Wert unverändert, darüber hebt er,
    # darunter senkt er. Ein Gewicht von 0,15 heisst also höchstens 15 Prozent in beide Richtungen.
    # Ohne Audioanteil bleibt der Wert unberührt, statt einen Mittelwert zu erfinden.
    cfg = pol.audio
    if audio is not None and cfg.get("in_bewertung_verwenden"):
        w = float(cfg.get("gewicht") or 0.0)
        wert *= (1.0 - w) + w * 2.0 * max(0.0, min(1.0, audio))
    return round(wert, 2)


# -- Kapitel und Seeds ---------------------------------------------------------------------------


def chapter_order(chapters: list[list[Sentence]], seeds: list[float]) -> list[tuple[int, list[Sentence], bool]]:
    """Kapitel mit mindestens einem Seed zuerst (in Zeitreihenfolge), danach die übrigen."""
    seeded, rest = [], []
    for i, ch in enumerate(chapters):
        if not ch:
            continue
        t0, t1 = ch[0].start, ch[-1].end
        has_seed = any(t0 <= float(s) <= t1 for s in seeds)
        (seeded if has_seed else rest).append((i, ch, has_seed))
    return seeded + rest


def seeds_from_heat(heat_payload: dict[str, Any] | None) -> list[float]:
    if not heat_payload:
        return []
    return [float(s) for s in heat_payload.get("seeds", []) or []]


# -- Gates ---------------------------------------------------------------------------------------


def _span_words(words: list[dict], sents: list[Sentence], first: int, last: int) -> tuple[list[dict], int, int]:
    a = sents[first].word_range[0]
    b = sents[last].word_range[1]
    return words[a : b + 1], a, b


def _active_policy() -> editorial.Policy | None:
    """Die aktive Richtlinie, oder None, wenn sie fehlt (dann gilt das Verhalten vor AP2 und AP3)."""
    try:
        return editorial.load()
    except editorial.PolicyError:
        return None


def _sentence_rule(pol: editorial.Policy | None = None) -> str:
    """Satzende-Regel der aktiven Richtlinie: ``v1`` (vor AP2) oder ``v2``."""
    pol = pol or _active_policy()
    return editorial.sentence_rule(pol) if pol is not None else "v1"


def _cut_args(words: list[dict], pol: editorial.Policy | None = None) -> dict[str, Any]:
    """Regel und Satzlängengrenze für Schnittentscheidungen, wie bei der Zerlegung: unter v2 mit
    ``dach_nlp.resolve_sentence_rule`` (kaum Satzzeichen ergibt ``v1_fallback_no_punct``)."""
    pol = pol or _active_policy()
    rule = _sentence_rule(pol)
    if rule == "v1" or pol is None:
        return {"rule": rule}
    max_s, max_words = editorial.sentence_limits(pol)
    return {"rule": dach_nlp.resolve_sentence_rule(words, rule), "max_s": max_s, "max_words": max_words}


def _verb_bracket_method(cfg: dict) -> str:
    if not cfg["active"]:
        return "off"
    if dach_nlp.nlp() is not None:
        return "spacy"
    return "heuristic" if cfg["fallback"] == "heuristic" else "off"


def nlp_status_for(pol: editorial.Policy | None) -> str:
    """Wie die Verbklammer unter dieser Richtlinie geprüft wird: ``spacy``, ``heuristic`` oder ``off``;
    leer ohne Abschnitt ``verb_bracket`` (Fassung 1, dann bleibt der Bericht byte-gleich)."""
    cfg = editorial.verb_bracket_settings(pol) if pol is not None else None
    return _verb_bracket_method(cfg) if cfg is not None else ""


def engine_version(pol: editorial.Policy | None = None) -> str:
    """``story_engine_v5`` unter Fassung 2, sonst ``story_engine_v4`` (Bericht und Idempotenz-Schlüssel)."""
    pol = pol if pol is not None else _active_policy()
    return ENGINE_VERSION_V2 if pol is not None and pol.version >= 2 else ENGINE_VERSION


def gates_wired(pol: editorial.Policy | None) -> dict | None:
    """Einstellungen der harten Gates, wenn ``implementation.gates.discard_hard`` an ist (AP4), sonst None."""
    cfg = editorial.gates_settings(pol) if pol is not None else None
    return cfg if cfg is not None and cfg["switch"] else None


def search_wired(pol: editorial.Policy | None) -> dict | None:
    """Einstellungen der Suche, wenn ``implementation.search.payoff_first`` an ist (AP5), sonst None."""
    cfg = editorial.search_settings(pol) if pol is not None else None
    return cfg if cfg is not None and cfg["wired"] else None


def trim_wired(pol: editorial.Policy | None) -> dict | None:
    """Einstellungen der Kürzung, wenn Regel und Schalter ``trim.enabled`` beide an sind (AP7), sonst None."""
    cfg = editorial.trim_settings(pol) if pol is not None else None
    return cfg if cfg is not None and cfg["enabled"] else None


def marker_rule(pol: editorial.Policy | None = None) -> str:
    """Abgleich der Kontrast- und Korrekturmarker in Sinntreue-Tor und Story-Graph: ``v2`` (Wortgrenzen,
    „außer“ trifft nicht „außerdem“, Korrekturmarker) mit den harten Gates (AP4), sonst ``v1``."""
    pol = pol if pol is not None else _active_policy()
    return "v2" if gates_wired(pol) is not None else "v1"


class LLMBudgetExceeded(RuntimeError):
    """Das Budget ``search.max_llm_calls_per_source_hour`` ist aufgebraucht; kein weiterer Modellaufruf."""


class BudgetLLM:
    """Zählt Modellaufrufe (``structured``) und verweigert jeden weiteren, sobald ``limit`` erreicht ist.

    Alles andere reicht er an das eigentliche LLM durch. Der Lauf bricht nicht ab: wer einen verweigerten
    Aufruf bekommt, lässt den Schritt aus (Master-Prompt 27, keine unkontrollierten Modellaufrufe). Mit
    ``enforce`` false (Heuristik-Provider: kein Modell, keine Kosten) wird nur gezählt, nie verweigert."""

    def __init__(self, llm: Any, limit: int, enforce: bool = True):
        self._llm = llm
        self.limit = int(limit)
        self.enforce = bool(enforce)
        self.used = 0
        self.refused = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._llm, name)

    def structured(self, *args: Any, **kwargs: Any) -> Any:
        if self.enforce and self.used >= self.limit:
            self.refused += 1
            raise LLMBudgetExceeded(f"Modellbudget von {self.limit} Aufrufen aufgebraucht")
        self.used += 1
        return self._llm.structured(*args, **kwargs)


def llm_budget_for(sents: list[Sentence], cfg: dict, pol: editorial.Policy | None = None) -> int:
    """Modellaufrufe für diese Quelle: ``max_llm_calls_per_source_hour`` mal Quelldauer in Stunden, aufgerundet.

    Eine Quelle zählt mindestens ``search.budget_min_source_s`` (ohne Richtlinie ``CHAPTER_SECONDS``): die
    Rechnung in der Policy geht von Kapiteln aus, und ein Ausschnitt von 25 Sekunden braucht dieselben Schritte
    wie ein Kapitel."""
    minimum = editorial.budget_min_source_s(pol) if pol is not None else CHAPTER_SECONDS
    seconds = max((sents[-1].end - sents[0].start) if sents else 0.0, minimum)
    return max(1, math.ceil(float(cfg["max_llm_calls_per_source_hour"]) * seconds / 3600.0))


def _verb_bracket_gate(words: list[dict], sents: list[Sentence], first: int, last: int) -> dict:
    """Verbklammer am Schnitt (AP3): Anfang (Wort vor dem Anfang gegen den ersten Satz) und Ende (letzter
    Satz gegen das Folgewort), jeweils über die Grenze hinweg.

    Ohne Abschnitt ``verb_bracket`` (Fassung 1) gilt das Tor vor AP3 (``_verb_bracket_gate_v1``).
    ``available`` ist nie mehr stilles Bestehen: ohne spaCy entscheidet die Heuristik und ``detail``
    sagt das; nur mit ``fallback: off`` und ohne spaCy bleibt das Tor ungeprüft und meldet es."""
    pol = _active_policy()
    cfg = editorial.verb_bracket_settings(pol) if pol is not None else None
    if cfg is None:
        return _verb_bracket_gate_v1(words, sents, first, last)
    if not cfg["active"]:
        return {"passed": True, "detail": "Verbklammer laut Richtlinie nicht geprüft", "available": False, "method": "off"}
    method = _verb_bracket_method(cfg)
    if method == "off":
        return {
            "passed": True,
            "detail": "Verbklammer-Prüfung nicht verfügbar, spaCy-Modell fehlt und der Rückfall ist abgeschaltet",
            "available": False,
            "method": "off",
        }
    _span, a, b = _span_words(words, sents, first, last)
    rule = _cut_args(words, pol)["rule"]
    problems = []
    for label, cut in (("Anfang", a), ("Ende", b + 1)):
        res = dach_nlp.bracket_open_at_cut(words, cut, rule=rule, fallback=cfg["fallback"], lists=cfg["lists"])
        if res["open"]:
            problems.append(f"{label}: {res['detail']}")
    suffix = "" if method == "spacy" else " (Heuristik, spaCy-Modell fehlt)"
    if problems:
        return {"passed": False, "detail": "Schnitt in einer Verbklammer am " + "; ".join(problems) + suffix, "available": True, "method": method}
    return {"passed": True, "detail": "kein Schnitt in einer Verbklammer" + suffix, "available": True, "method": method}


def _verb_bracket_gate_v1(words: list[dict], sents: list[Sentence], first: int, last: int) -> dict:
    """Das Tor vor AP3 (Fassung 1): prüft innerhalb des ersten und letzten Satzes, ohne spaCy bestanden."""
    pipe = dach_nlp.nlp()
    available = bool(dach_nlp.verb_bracket_available)
    if pipe is None or not available:
        return {"passed": True, "detail": "Verbklammer-Prüfung nicht verfügbar, spaCy fehlt", "available": False}
    problems = []
    for label, s, t in (("Anfang", sents[first], sents[first].start), ("Ende", sents[last], sents[last].end)):
        a, b = s.word_range
        ranges = dach_nlp.forbidden_cut_ranges(s.text, words[a : b + 1])
        if not dach_nlp.cut_is_legal(t, ranges):
            problems.append(label)
    if problems:
        return {"passed": False, "detail": f"Schnitt in einer Verbklammer am {' und '.join(problems)}", "available": True}
    return {"passed": True, "detail": "kein Schnitt in einer Verbklammer", "available": True}


def _fidelity_gate(words: list[dict], sents: list[Sentence], first: int, last: int) -> dict:
    """Sinntreue über die Wortliste des Kandidaten (plus wenige Folgewörter, damit ``ends_before_contrast``
    greifen kann). Behalten wird der gesamte Kandidat; relevant ist nur ``ends_before_contrast``."""
    span, _a, b = _span_words(words, sents, first, last)
    tail = words[b + 1 : b + 1 + FIDELITY_TAIL_WORDS]
    rule = marker_rule()
    warnings = (fidelity.check_cut(span + tail, [(0, len(span) - 1)], rule=rule) if rule != "v1" else fidelity.check_cut(span + tail, [(0, len(span) - 1)])) if span else []
    contrast = next((w for w in warnings if w["type"] == "ends_before_contrast"), None)
    if contrast is None:
        return {"passed": True, "detail": "keine entfernte Verneinung oder Einschränkung"}
    first_word = str(contrast.get("detail", "")).split()[:1]
    token = first_word[0] if first_word else "aber"
    return {"passed": False, "detail": f"endet direkt vor „{token}“"}


def _open_loop_gate(sents: list[Sentence], last: int) -> dict:
    text = sents[last].text
    if dach_nlp.ends_with_open_loop(text):
        tail = re.sub(r"[^\wäöüß. ]", "", text.lower()).replace(".", "").split()
        token = " ".join(tail[-2:]) if " ".join(tail[-2:]) in dach_nlp.OPEN_LOOP_END else tail[-1]
        return {"passed": False, "detail": f"endet auf „{token}“"}
    return {"passed": True, "detail": "endet mit abgeschlossenem Satz"}


# Zeichen, die einen Satz wirklich beenden. Die Auslassungspunkte stehen bewusst NICHT dabei: sie
# markieren im Transkript eine Pause oder ein Abreissen, keinen abgeschlossenen Gedanken.
SATZENDE_ZEICHEN = ".!?\"'»)"
SATZENDE_AUSNAHMEN = ("…", "...")


def _endet_satz(text: str) -> bool:
    t = (text or "").strip()
    if not t or any(t.endswith(a) for a in SATZENDE_AUSNAHMEN):
        return False
    return t[-1] in SATZENDE_ZEICHEN


def _satzgrenzen_gate(words: list[dict], sents: list[Sentence], first: int, last: int) -> dict:
    """Satzgrenzen-Tor. Regel ``v1``: ``_satzgrenzen_gate_v1`` (nur Satzzeichen, wie vor AP2). Regel ``v2``:
    dieselbe Entscheidung wie die Zerlegung (``dach_nlp.cut_boundary_kind``). Satzzeichen und
    Sprecherwechsel gelten (nicht nach Komma: Einwurf des Gegenübers), ein angenommener Pause-Kandidat
    gilt mit dem Hinweis „Grenze nur aus Pause"."""
    pol = _active_policy()
    if _sentence_rule(pol) == "v1":
        return _satzgrenzen_gate_v1(words, sents, first, last)
    args = _cut_args(words, pol)
    _span, a, b = _span_words(words, sents, first, last)
    if a > len(words) - 1 or b > len(words) - 1 or a > b:
        return {"passed": True, "detail": "Abschnitt nicht prüfbar"}
    probleme, nur_pause = [], []
    if a > 0:
        kind = dach_nlp.cut_boundary_kind(words, a - 1, **args)
        if kind == "none":
            probleme.append(f"fängt mitten im Satz an, davor steht \u201e{words[a - 1].get('text') or ''}\u201c")
        elif kind in ("pause_candidate", "length_cap"):
            nur_pause.append("Anfang")
    kind = dach_nlp.cut_boundary_kind(words, b, **args)
    if kind == "none":
        probleme.append(f"endet mitten im Satz auf \u201e{words[b].get('text') or ''}\u201c")
    elif kind in ("pause_candidate", "length_cap"):
        nur_pause.append("Ende")
    if probleme:
        return {"passed": False, "detail": "; ".join(probleme)}
    if nur_pause:
        return {"passed": True, "detail": f"Start und Ende an Satzgrenzen, Grenze nur aus Pause ({' und '.join(nur_pause)})"}
    return {"passed": True, "detail": "Start und Ende an Satzgrenzen"}


def _satzgrenzen_gate_v1(words: list[dict], sents: list[Sentence], first: int, last: int) -> dict:
    """Faengt der Abschnitt an einem Satzanfang an und hoert er an einem Satzende auf?

    Dieses Tor hat frueher ``passed: True`` mit der Begruendung „Start und Ende an Satzgrenzen"
    gemeldet, ohne irgendetwas zu pruefen. An BP CW gemessen war das zweimal von sechs falsch: ein
    Clip endete auf „leckerer," und das naechste Wort war „aber", ein anderer auf „…", also mitten
    in einem abgerissenen Satz.

    Der Grund ist die Satzzerlegung selbst: sie trennt auch an einer langen Sprechpause, und eine
    Pause nach einem Komma ist kein Satzende. Deshalb wird hier am Wortlaut geprueft und nicht an
    der Zerlegung.
    """
    _span, a, b = _span_words(words, sents, first, last)
    if a > len(words) - 1 or b > len(words) - 1 or a > b:
        return {"passed": True, "detail": "Abschnitt nicht pruefbar"}
    letztes = str(words[b].get("text") or "")
    davor = str(words[a - 1].get("text") or "") if a > 0 else ""
    probleme = []
    if a > 0 and not _endet_satz(davor):
        probleme.append(f"faengt mitten im Satz an, davor steht \u201e{davor}\u201c")
    if not _endet_satz(letztes):
        probleme.append(f"endet mitten im Satz auf \u201e{letztes}\u201c")
    if probleme:
        return {"passed": False, "detail": "; ".join(probleme)}
    return {"passed": True, "detail": "Start und Ende an Satzgrenzen"}


def _standalone_gate(r: dict) -> dict:
    reasons = []
    if r.get("needs_earlier_context"):
        reasons.append("Einstieg braucht Vorwissen")
    if r.get("ends_before_answer"):
        reasons.append("endet vor der Antwort")
    refs = [str(x) for x in (r.get("unresolved_references") or []) if str(x).strip()]
    if refs:
        reasons.append("offene Verweise: " + ", ".join(refs[:3]))
    if reasons:
        return {"passed": False, "detail": "; ".join(reasons)}
    return {"passed": True, "detail": "keine offenen Verweise"}


def deterministic_gates(words: list[dict], sents: list[Sentence], first: int, last: int, rubric: dict) -> dict:
    """Gate-Struktur exakt wie im Vertrag: standalone, fidelity, sentence_boundaries, verb_bracket, no_open_loop."""
    return {
        "standalone": _standalone_gate(rubric),
        "fidelity": _fidelity_gate(words, sents, first, last),
        "sentence_boundaries": _satzgrenzen_gate(words, sents, first, last),
        "verb_bracket": _verb_bracket_gate(words, sents, first, last),
        "no_open_loop": _open_loop_gate(sents, last),
    }


# -- Story-Graph ---------------------------------------------------------------------------------


def later_qualifications(sents: list[Sentence], first: int, last: int, llm: LLM) -> list[dict]:
    """Stufe 4: Heuristik-Treffer, jeder per LLM bestätigt. Ohne Urteil bleibt ``confirmed`` None."""
    rule = marker_rule()
    hits = story_graph.find_later_qualifications(sents, first, last, rule=rule) if rule != "v1" else story_graph.find_later_qualifications(sents, first, last)
    if not hits:
        return []
    clip_text = " ".join(s.text for s in sents[first : last + 1])
    flags = []
    for h in hits:
        try:
            out = story_graph.confirm(llm, clip_text, h["text"], h["seconds_after"])
        except LLMBudgetExceeded:
            out = {}  # Modellbudget aufgebraucht: der Treffer bleibt, unbestätigt (confirmed None)
        verdict = out.get("misleading_without")
        confirmed = None if verdict is None else bool(verdict)
        repair = out.get("repair")
        if repair not in ("extend", "overlay"):
            repair = None
        flags.append(
            {
                "sentence_idx": int(h["sentence_idx"]),
                "seconds_after": float(h["seconds_after"]),
                "marker": h["marker"],
                "text": h["text"],
                "overlap": float(h["overlap"]),
                "confirmed": confirmed,
                "reason": (str(out.get("reason")) if out.get("reason") else None),
                "repair": repair if confirmed else None,
                "suggestion": h["suggestion"],
            }
        )
    return flags


# -- Begründung und Risiken ----------------------------------------------------------------------


def build_why(
    scores: dict[str, int],
    rubric: dict,
    gates: dict,
    flags: list[dict],
    duration_s: float,
    platform: str,
    heuristic: bool,
) -> str:
    """Ein deutscher Satz ohne Gedankenstriche aus Rubrik, Gates und Story-Graph."""
    dur = int(round(duration_s))
    parts: list[str] = []
    standalone = gates["standalone"]["passed"]
    if standalone and scores["payoff"] >= 6:
        parts.append(f"Kernaussage in {dur} Sekunden vollständig")
    elif not standalone:
        if rubric.get("needs_earlier_context"):
            parts.append(f"Ausschnitt von {dur} Sekunden, Einstieg braucht Vorwissen")
        elif rubric.get("ends_before_answer"):
            parts.append(f"Ausschnitt von {dur} Sekunden, endet vor der Auflösung")
        else:
            parts.append(f"Ausschnitt von {dur} Sekunden mit offenen Verweisen")
    else:
        parts.append(f"Ausschnitt von {dur} Sekunden mit schwachem Payoff")

    if scores["hook"] >= 7 and scores["tension"] >= 6:
        parts.append("Einstieg mit klarer Gegenposition")
    elif scores["hook"] >= 7:
        parts.append("starker Einstieg")
    elif scores["hook"] >= 4:
        parts.append("solider Einstieg")
    else:
        parts.append("schwacher Einstieg")
    if scores["specificity"] >= 7:
        parts.append("konkret mit Zahlen oder Namen")

    if not gates["no_open_loop"]["passed"]:
        parts.append("endet auf einem offenen Konnektor")
    if not gates["fidelity"]["passed"]:
        parts.append("endet direkt vor einer Relativierung")
    if not gates["verb_bracket"]["passed"]:
        parts.append("Schnitt in einer Verbklammer")

    confirmed = [f for f in flags if f.get("confirmed") is True]
    unverified = [f for f in flags if f.get("confirmed") is None]
    if confirmed:
        parts.append(f"aber {int(round(confirmed[0]['seconds_after']))} Sekunden später relativiert der Sprecher die Aussage")
    elif unverified:
        parts.append(
            f"möglicherweise relativiert der Sprecher die Aussage {int(round(unverified[0]['seconds_after']))} Sekunden später, ungeprüft"
        )
    else:
        parts.append("keine spätere Relativierung gefunden")

    label = PLATFORM_LABELS.get(str(platform or "linkedin").lower(), str(platform or "LinkedIn"))
    if scores["audience_fit"] >= 6:
        parts.append(f"passt für {label}")
    else:
        parts.append(f"Passung für {label} fraglich")
    if heuristic:
        parts.append("Bewertung ohne Sprachmodell")
    text = ", ".join(parts) + "."
    return text.replace(" – ", ", ").replace("–", ",").replace("—", ",")


def risk_flags_for(rubric: dict, clip_text: str, heuristic: bool) -> list[str]:
    flags = []
    if rubric.get("is_humor"):
        flags.append("humor")
    if rubric.get("sensitive_topic"):
        flags.append("sensitive_topic")
    if story_graph.claims_in(clip_text):
        flags.append("claim")
    if heuristic:
        flags.append("heuristic_only")
    return flags


# -- Bewertung einer Spanne ----------------------------------------------------------------------


def _duration(sents: list[Sentence], first: int, last: int) -> float:
    return sents[last].end - sents[first].start


def _length_reason(dur: float, mit_zugabe: bool = False) -> str | None:
    """Verwerfungsgrund wegen der Laenge, oder None.

    Massgeblich ist die Richtlinie. ``mit_zugabe`` gilt nur fuer einen Clip, der nach hinten
    verlaengert wurde, um sein Ende zu heilen; ohne diesen Grund endet es bei ``hart_max_s``."""
    try:
        pol = editorial.load()
        unten, oben = pol.hart_min_s, pol.hart_max_s + (pol.kontext_zugabe_s if mit_zugabe else 0.0)
    except Exception:  # ohne Richtlinie lieber weiter arbeiten als gar nicht
        unten, oben = MIN_LEN_S, MAX_LEN_S
    if dur < unten:
        return "too_short"
    if dur > oben:
        return "too_long"
    return None


def _vorfilter_grund(sents: list[Sentence], first: int, last: int) -> str | None:
    """Billiger Vorfilter vor der Bewertung: verwirft nur, was auch die Reparatur nicht rettet.

    Der Vorfilter spart eine Modellanfrage fuer aussichtslose Vorschlaege. Er darf dabei aber nicht
    die endgueltige Grenze anlegen: ein zu kurzer Vorschlag kann durch die Reparatur (fehlender
    Kontext nach vorne, fehlende Antwort nach hinten) und die Kontextzugabe noch lang genug werden.
    Genau daran ist der erste Versuch gescheitert: mit der harten Untergrenze im Vorfilter fiel ein
    Vorschlag von 17,6 Sekunden heraus, den die Reparatur auf 23,4 gebracht haette.

    Nach oben ist der Vorfilter dagegen exakt: ein Abschnitt waechst nur, er schrumpft nie.
    """
    dur = _duration(sents, first, last)
    if _length_reason(dur, mit_zugabe=True) == "too_long":
        return "too_long"
    # Wie lang koennte dieser Abschnitt nach der groesstmoeglichen Reparatur hoechstens werden?
    vorne = max(0, first - MAX_REPAIR_ROUNDS)
    hinten = min(len(sents) - 1, last + MAX_REPAIR_ROUNDS)
    try:
        zugabe = editorial.load().kontext_zugabe_s
    except Exception:
        zugabe = 0.0
    if _length_reason(_duration(sents, vorne, hinten) + zugabe) == "too_short":
        return "too_short"
    return None


def kontext_verlaengern(
    words: list[dict],
    sents: list[Sentence],
    first: int,
    last: int,
    rubric: dict,
    needs_fn: Callable[[int], dict[str, str]] | None = None,
    reach: tuple[int, float] | None = None,
) -> tuple[int, dict | None]:
    """Den Abschnitt nach hinten wachsen lassen, bis sein Ende nicht mehr kaputt ist.

    Die Laenge entscheidet, aber nicht gegen den Sinn: ein Clip, der vor dem „aber" endet, das ihn
    erst erklaert, ist kein kurzer Clip, sondern ein falscher. Deshalb darf er um bis zu
    ``kontext_zugabe_s`` Sekunden ueber die harte Grenze hinauswachsen.

    Eingesetzt wird die Zugabe nur gegen einen benannten Mangel aus ``ENDE_TORE``, und sie hoert
    auf, sobald er behoben ist. Ein Clip, den sie nicht heilt, bleibt wie er war und wird von der
    Auswahl verworfen. Es gibt keine Verlaengerung „einfach so".

    Zurueck kommt der neue letzte Satz und, falls verlaengert wurde, eine Notiz fuer die Rubrik.

    ``needs_fn(letzter_satz)`` (AP4, harte Gates nach hinten heilbar) nennt zusätzliche Mängel des Endes als
    ``{schluessel: detail}``; geheilt ist dann erst, wenn auch sie leer sind. Ohne ``needs_fn`` wie vorher.
    ``reach`` (Sätze, Sekunden) begrenzt zusätzlich auf die Restreichweite, wenn schon eine Heilung lief.
    """
    gates = deterministic_gates(words, sents, first, last, rubric)
    kaputt = [k for k in ENDE_TORE if k in gates and not gates[k].get("passed")]
    extra = needs_fn(last) if needs_fn is not None else {}
    if not kaputt and not extra:
        return last, None
    try:
        pol = editorial.load()
        max_saetze, max_s = pol.kontext_zugabe_saetze, pol.kontext_zugabe_s
    except Exception:
        return last, None
    if reach is not None:
        max_saetze, max_s = min(max_saetze, int(reach[0])), min(max_s, float(reach[1]))
    if max_saetze <= 0 or max_s <= 0 or last >= len(sents) - 1:
        return last, None

    # AP2 (nur mit implementation.sentence_rule): nie auf einem Satz enden, der mit einem Marker aus
    # ausstieg.abschwaechung_marker beginnt. Befund 6: genau dort endete die Heilung bisher.
    marker = _qualification_markers(pol) if editorial.never_end_on_qualification(pol) else ()
    # AP2: geheilt heisst, die Tore des Endes und die Verbklammer bestehen. standalone gehoert nicht
    # dazu, es beruht auf der Rubrik vor der Heilung und wird nach der Neubewertung frisch geprueft.
    required = (*ENDE_TORE, "verb_bracket") if editorial.context_front(pol) is not None else None
    skipped: list[int] = []
    ende0 = sents[last].end
    for ziel in range(last + 1, min(last + max_saetze, len(sents) - 1) + 1):
        gewonnen = sents[ziel].end - ende0
        # BEIDE Grenzen gelten. Die Sekunden sind die Ansage, wie viel laenger ein Clip aus
        # Kontextgruenden werden darf; die Satzzahl verhindert zusaetzlich, dass viele kurze Saetze
        # zusammen doch eine halbe Minute ergeben.
        if gewonnen > max_s:
            break
        neu_dauer = sents[ziel].end - sents[first].start
        # Die Obergrenze gilt auch fuer eine Heilung. Ein Clip, der nur ueber 77 Sekunden hinaus
        # heilbar waere, wird verworfen und nicht aufgeblasen.
        if _length_reason(neu_dauer, mit_zugabe=True):
            break
        g = deterministic_gates(words, sents, first, ziel, rubric)
        relevant = g.values() if required is None else [g[k] for k in required if k in g]
        if all(bool(x.get("passed")) for x in relevant) and not (needs_fn is not None and needs_fn(ziel)):
            if marker and _starts_with_marker(sents[ziel].text, marker):
                skipped.append(ziel)
                continue
            return ziel, {
                "saetze": ziel - last,
                "sekunden": round(gewonnen, 2),
                "behoben": kaputt + [f"gate:{k}" for k in extra],
                "grund": "; ".join([str(gates[k].get("detail") or "") for k in kaputt] + list(extra.values())),
            }
    if skipped:
        # Geheilt waere das Ende nur auf der Abschwaechung: verwerfen statt dort enden.
        return last, {
            "discarded": "ends_on_qualification",
            "sentences": skipped,
            "detail": f"Heilung endete auf der Abschwächung „{sents[skipped[0]].text.split()[0]}“",
        }
    return last, None


def _qualification_markers(pol: editorial.Policy) -> tuple[str, ...]:
    return tuple(str(m).lower() for m in (pol.ausstieg.get("abschwaechung_marker") or ()) if str(m).strip())


def _starts_with_marker(text: str, marker: tuple[str, ...]) -> bool:
    """Beginnt der Satz mit einem Abschwächungsmarker (ganze Wörter, ohne Satzzeichen)? Führende
    Füllwörter zählen nicht („Äh, wobei …")."""
    tokens = [t for t in (dach_nlp.core_token(x) for x in str(text or "").split()) if t]
    while tokens and tokens[0] in dach_nlp.HARD_FILLERS:
        tokens = tokens[1:]
    joined = " ".join(tokens)
    return any(joined == m or joined.startswith(m + " ") for m in marker)


# Höflichkeitsform nach „Sie" am Satzanfang: Verb auf -en oder eine dieser Formen.
_POLITE_VERB_FORMS = frozenset({"sind", "waren", "wären", "seid"})


def _formal_address(words: list[dict], a: int) -> bool:
    """„Sie haben …", „Sie können …" (förmliche Anrede) oder „Ihr …": kein Pronomen ohne Bezug."""
    first_word = str(words[a].get("text") or "").strip()
    token = dach_nlp.core_token(first_word)
    if token == "ihr":
        return True
    if token != "sie" or not first_word[:1].isupper() or a + 1 >= len(words):
        return False
    following = dach_nlp.core_token(str(words[a + 1].get("text") or ""))
    return following.endswith("en") or following in _POLITE_VERB_FORMS


def start_defects(words: list[dict], sents: list[Sentence], idx: int, pol: editorial.Policy) -> list[str]:
    """Mängel am Anfang, wenn der Clip mit Satz ``idx`` beginnt (AP2, für ``heal_start``).

    Geprüft werden: Anfang mitten im Satz (``einstieg.nie_mitten_im_satz``, gleiche Regel wie die
    Zerlegung), Pronomen ohne Bezug als erstes Wort (``einstieg.keine_pronomen_ohne_bezug``,
    ``einstieg.pronomen``) und eine offene Verbklammer am Schnitt (AP3). Rückverweise und ein fehlendes
    Pointen-Setup kommen mit AP4 und AP7."""
    a = sents[idx].word_range[0]
    einstieg = pol.einstieg
    args = _cut_args(words, pol)
    out: list[str] = []
    if a > 0 and einstieg.get("nie_mitten_im_satz", True) and dach_nlp.cut_boundary_kind(words, a - 1, **args) == "none":
        out.append(f"Anfang mitten im Satz, davor steht „{words[a - 1].get('text') or ''}“")
    first_word = str(words[a].get("text") or "") if a < len(words) else ""
    if (
        einstieg.get("keine_pronomen_ohne_bezug")
        and dach_nlp.core_token(first_word) in set(einstieg.get("pronomen") or ())
        and not _formal_address(words, a)
    ):
        out.append(f"Pronomen ohne Bezug am Anfang („{first_word}“)")
    cfg = editorial.verb_bracket_settings(pol)
    if a > 0 and cfg is not None and cfg["active"]:
        res = dach_nlp.bracket_open_at_cut(words, a, rule=args["rule"], fallback=cfg["fallback"], lists=cfg["lists"])
        if res["open"]:
            out.append(f"Verbklammer am Anfang: {res['detail']}")
    return out


def heal_start(
    words: list[dict],
    sents: list[Sentence],
    first: int,
    last: int,
    rubric: dict,
    pol: editorial.Policy | None = None,
    defects_fn: Callable[[int], list[str]] | None = None,
    reach: tuple[int, float] | None = None,
) -> tuple[int, dict | None]:
    """Den Abschnitt nach vorn wachsen lassen, bis sein Anfang nicht mehr kaputt ist (Spiegel von
    ``kontext_verlaengern``).

    Höchstens ``laenge.context_front_sentences`` Sätze und ``laenge.context_front_s`` Sekunden, beide
    Grenzen gelten, und die harte Obergrenze plus Zugabe gilt auch hier. Nur gegen einen benannten
    Mangel aus ``start_defects``; ohne Mangel bleibt der Anfang. Ein Satz eines anderen Sprechers wird
    nie vorangestellt (``einstieg.keine_gastgeberfrage``). Zurück kommt der neue erste Satz und eine
    Notiz: ``{"healed": True, "sentences", "seconds", "defects"}`` oder ``{"healed": False, "defects"}``,
    wenn der Mangel innerhalb der Grenzen bleibt (der Aufrufer stuft dann über das Tor ``standalone``
    herab). Ohne AP2 (Fassung 1 oder Schalter aus) oder mit Grenze 0 ``(first, None)``. ``rubric``
    bleibt unberührt; die Neubewertung macht der Aufrufer. ``defects_fn(erster_satz)`` ersetzt
    ``start_defects`` (AP4: Mängel aus den harten Gates, die nach vorn heilbar sind). ``reach`` (Sätze,
    Sekunden) begrenzt auf die Restreichweite, wenn schon eine Heilung lief."""
    pol = pol or _active_policy()
    limits = editorial.context_front(pol) if pol is not None else None
    if limits is None or first <= 0:
        return first, None
    max_sentences, max_s = limits
    if reach is not None:
        max_sentences, max_s = min(max_sentences, int(reach[0])), min(max_s, float(reach[1]))
    if max_sentences <= 0 or max_s <= 0:
        return first, None
    if defects_fn is None:
        def defects_fn(i: int) -> list[str]:
            return start_defects(words, sents, i, pol)

    defects = defects_fn(first)
    if not defects:
        return first, None
    same_speaker = bool(pol.einstieg.get("keine_gastgeberfrage"))
    start = sents[first].start
    for before in range(first - 1, max(-1, first - max_sentences - 1), -1):
        gained = start - sents[before].start
        if gained > max_s:
            break
        if same_speaker and sents[before].speaker != sents[first].speaker:
            break
        if _length_reason(sents[last].end - sents[before].start, mit_zugabe=True) == "too_long":
            break
        if not defects_fn(before):
            return before, {"healed": True, "sentences": first - before, "seconds": round(gained, 2), "defects": defects}
    return first, {"healed": False, "defects": defects}


# -- Harte Gates (AP4) und Kürzung (AP7), nur Fassung 2 ---------------------------------------------

GATE_CONTEXT_BEFORE = 2
# Befunde aus ``fidelity.check_cut``, die eine Kürzung zurücksetzen (hohe Schwere, Bedeutung verändert).
TRIM_RESET_FINDINGS = frozenset({"protected_removed", "negation_removed"})
GATE_CONTEXT_AFTER = 2


def _run_gates(words: list[dict], sents: list[Sentence], first: int, last: int, pol: editorial.Policy) -> dict:
    return editorial_gates.run_gates(
        words, sents, first, last, pol, context_before=GATE_CONTEXT_BEFORE, context_after=GATE_CONTEXT_AFTER
    )


def _failed_on(res: dict, side: str) -> dict[str, str]:
    return {k: str(res["results"][k]["detail"]) for k in res["failed"] if res["results"][k].get("healable") == side}


def heal_gates(
    words: list[dict],
    sents: list[Sentence],
    first: int,
    last: int,
    rubric: dict,
    pol: editorial.Policy,
    res: dict,
    origin: tuple[int, int] | None = None,
) -> tuple[int, int, dict]:
    """Heilbare Gate-Mängel zuerst heilen, bevor verworfen wird (AP4).

    ``healable: front`` (Pronomen, Rückverweis, Antwort ohne Frage, Zitatrahmen davor, Grenzsatz davor) läuft
    über ``heal_start`` mit den Gate-Mängeln als Prüfung, in denselben Grenzen (``laenge.context_front_*``,
    kein anderer Sprecher vorn); ``healable: back`` (offene Frage, Vorverweis, Grenzsatz danach, Korrektur
    in Reichweite) über ``kontext_verlaengern``. Zurück kommen neuer Anfang, neues Ende und je Seite eine
    Notiz; ``{"back": {"discarded": ...}}`` heißt, die Heilung endete nur auf einer Abschwächung.

    ``origin`` (erster und letzter Satz vor jeder Heilung): AP2 und AP4 teilen sich die Reichweite. Vorn gelten
    insgesamt höchstens ``laenge.context_front_sentences`` und ``context_front_s``, hinten
    ``kontext_zugabe_saetze`` und ``kontext_zugabe_s``, gemessen ab ``origin``; ist sie aufgebraucht, heilt
    diese Seite nicht mehr (Notiz ``reach_exhausted``)."""
    notes: dict[str, Any] = {}
    front_reach = back_reach = None
    if origin is not None:
        o_first, o_last = origin
        limits = editorial.context_front(pol)
        if limits is not None:
            used = (max(0, o_first - first), max(0.0, sents[o_first].start - sents[first].start))
            front_reach = (limits[0] - used[0], limits[1] - used[1])
        used_b = (max(0, last - o_last), max(0.0, sents[last].end - sents[o_last].end))
        back_reach = (pol.kontext_zugabe_saetze - used_b[0], pol.kontext_zugabe_s - used_b[1])
    if "front" in res["healable"] and front_reach is not None and (front_reach[0] <= 0 or front_reach[1] <= 0):
        notes["front"] = {"healed": False, "reach_exhausted": True, "defects": list(_failed_on(res, "front").values())}
    elif "front" in res["healable"]:
        def front_defects(i: int) -> list[str]:
            healed = _run_gates(words, sents, i, last, pol)
            return start_defects(words, sents, i, pol) + [f"{k}: {d}" for k, d in _failed_on(healed, "front").items()]

        new_first, note = heal_start(words, sents, first, last, rubric, pol, defects_fn=front_defects, reach=front_reach)
        if note is not None:
            notes["front"] = note
            first = new_first
    if "back" in res["healable"] and back_reach is not None and (back_reach[0] <= 0 or back_reach[1] <= 0):
        notes["back"] = {"reach_exhausted": True, "defects": list(_failed_on(res, "back").values())}
    elif "back" in res["healable"]:
        def back_defects(j: int) -> dict[str, str]:
            return _failed_on(_run_gates(words, sents, first, j, pol), "back")

        new_last, note = kontext_verlaengern(words, sents, first, last, rubric, needs_fn=back_defects, reach=back_reach)
        if note is not None:
            notes["back"] = note
            if not note.get("discarded"):
                last = new_last
    return first, last, notes


def _map_legacy_gates(gates: dict, res: dict) -> None:
    """Den ersten Gate-Mangel je Ziel in ``standalone`` oder ``fidelity`` abbilden (``LEGACY_GATE``); die fünf
    Schlüssel bleiben, ein schon gerissenes Tor behält seinen Grund."""
    for key in res["failed"]:
        target = editorial_gates.LEGACY_GATE.get(key)
        if target and gates.get(target, {}).get("passed"):
            gates[target] = {"passed": False, "detail": str(res["results"][key]["detail"]), "reason": f"gate:{key}"}


def _instruction_check(sents: list[Sentence], first: int, last: int, res: dict, r: dict, proposal: dict) -> dict | None:
    """Folgt die Modellantwort einer Anweisung aus dem Transkript? Nur wenn ``embedded_instruction`` markiert."""
    flag = res["results"].get("embedded_instruction") or {}
    quotes = [str(q) for q in flag.get("quotes") or []]
    if not quotes:
        return None
    rest = " ".join(s.text for s in sents[first : last + 1] if s.text not in quotes)
    answer = {
        "suggested_title_card": r.get("suggested_title_card"), "why": r.get("why"), "proposal_why": proposal.get("why"),
        "viewer_promise": proposal.get("viewer_promise"), "central_idea": proposal.get("central_idea"),
    }  # fmt: skip
    return editorial_gates.instruction_followed({k: v for k, v in answer.items() if isinstance(v, str) and v}, quotes, clip_text=rest)


def _payoff_index(proposal: dict, first: int, last: int) -> int | None:
    p = proposal.get("payoff_sent")
    return p if isinstance(p, int) and not isinstance(p, bool) and first <= p <= last else None


def trim_span(
    words: list[dict],
    sents: list[Sentence],
    first: int,
    last: int,
    payoff_idx: int | None,
    pol: editorial.Policy,
    heat_payload: dict[str, Any] | None = None,
) -> dict:
    """Kürzung eines Kandidaten (AP7): Nachlauf nach dem Payoff kappen (``trim_plan.reward_end``), Komposition
    bauen (``trim_plan.build_composition``) und das Ergebnis mit ``fidelity.check_cut`` prüfen.

    ``applied`` false mit ``reason``, wenn die Komposition ungültig ist (E6, Dichte, Schutzbereich), ein Befund
    ``protected_removed`` oder ``negation_removed`` (hoch) auftritt oder die Abspieldauer unter ``laenge.hart_min_s`` fiele: dann gilt die ungekürzte
    Fassung. Sonst ``last`` (neues Ende), ``segments``, ``duration_s`` und ``removed_spans`` aus der Komposition."""
    # Reihenfolge: erst das Ende kappen, dann die Komposition über das neue Ende, dann die Sinntreue über die
    # ganze Spanne bis zum alten Ende (Indizes relativ zum Anfang): der gekappte Nachlauf ergibt dort höchstens
    # protected_omitted (mittel); zurückgesetzt wird nur bei protected_removed oder negation_removed (hoch).
    new_last, cut = trim_plan.reward_end(sents, first, last, payoff_idx, pol)
    a, b0, b = sents[first].word_range[0], sents[last].word_range[1], sents[new_last].word_range[1]
    comp = trim_plan.build_composition(words, a, b, None, pol, heat_payload=heat_payload)
    kept = [(int(x) - a, int(y) - a) for x, y in comp["kept_word_ranges"]]
    findings = fidelity.check_cut(words[a : b0 + 1], kept, rule="v2", policy=pol)
    high = [f for f in findings if f.get("severity") == "high" and f.get("type") in TRIM_RESET_FINDINGS]
    out: dict[str, Any] = {
        "applied": False,
        "reason": None,
        "reward_end": cut,
        "findings": findings,
        "composition": {
            "local_cuts": comp["local_cuts"], "semantic_splices": comp["semantic_splices"], "density": comp["density"],
            "is_debate": comp["is_debate"], "valid": comp["valid"], "issues": comp["issues"],
        },  # fmt: skip
        "is_debate": bool(comp["is_debate"]),
    }
    if not comp["valid"]:
        out["reason"] = "Komposition ungültig: " + "; ".join(comp["issues"])
    elif high:
        out["reason"] = "Sinntreue-Befund hoher Schwere: " + ", ".join(sorted({str(f["type"]) for f in high}))
    elif comp["duration_s"] < pol.hart_min_s:
        out["reason"] = f"gekürzt nur {comp['duration_s']:.1f} s, unter laenge.hart_min_s"
    elif not comp["removed_spans"] and new_last == last:
        out["reason"] = "nichts zu kürzen"
    else:
        out.update(applied=True, last=new_last, segments=comp["segments"], duration_s=comp["duration_s"], removed_spans=comp["removed_spans"])
    return out


# -- Einstiege vergleichen (AP6b, nur Fassung 2 mit search.compare_openings) ---------------------------

MAX_OPENINGS = 3


def _opening_option(
    words: list[dict], sents: list[Sentence], j: int, last: int, pol: editorial.Policy, heat_payload: dict[str, Any] | None,
    lenient: bool, hook_type: str | None = None,
) -> dict:
    """Bewertung eines Einstiegs ``j`` für die Spanne bis ``last``: Gates (``editorial_gates`` und mit AP2 die
    Mängel am Anfang), ``satz_staerke`` und die Länge im Fenster."""
    failed = list(_run_gates(words, sents, j, last, pol)["failed"])
    if editorial.context_front(pol) is not None:
        failed += ["start: " + d for d in start_defects(words, sents, j, pol)]
    dur = _duration(sents, j, last)
    return {
        "opening_sent": j, "first_sent": j, "last_sent": last, "duration_s": round(dur, 2), "hook_type": hook_type,
        "strength": satz_staerke(sents[j], pol, heat_payload), "gates_failed": failed,
        "length_allowed": _length_reason(dur, mit_zugabe=lenient) is None, "length_good": pol.laenge_ok(dur),
    }  # fmt: skip


def _opening_reason(opt: dict, chosen: dict) -> str:
    if not opt["length_allowed"] and chosen["length_allowed"]:
        return f"Länge {opt['duration_s']:.1f} s außerhalb der harten Grenzen"
    if opt["gates_failed"] and not chosen["gates_failed"]:
        return "reißt Gates: " + ", ".join(opt["gates_failed"])
    if not opt["length_good"] and chosen["length_good"]:
        return f"Länge {opt['duration_s']:.1f} s außerhalb des guten Fensters"
    if opt["strength"] < chosen["strength"]:
        return f"schwächerer Einstieg (Satzstärke {opt['strength']} gegen {chosen['strength']})"
    return f"nicht deutlich stärker als der gewählte Einstieg (Satzstärke {opt['strength']} gegen {chosen['strength']}, nötig ist der Vorsprung aus hook_vorziehen.mindest_vorsprung)"


def compare_openings(
    words: list[dict],
    sents: list[Sentence],
    first: int,
    last: int,
    payoff_idx: int | None,
    pol: editorial.Policy,
    heat_payload: dict[str, Any] | None = None,
    lenient: bool = False,
) -> dict:
    """Editor: bis zu ``MAX_OPENINGS`` substanziell verschiedene Originaleinstiege vergleichen (Master-Prompt 8).

    Kandidaten sind der bisherige Einstieg ``first`` und die Sätze aus ``payoff_search.alternative_openings``
    zwischen ``first`` und dem Payoff (ohne Payoff der letzte Satz); das Ende bleibt. Ein Einstieg außerhalb
    der harten Längengrenzen ergäbe keinen Clip und zählt nur, wenn keiner sie einhält. Unter den übrigen wird
    ein Einstieg, der ein Gate reißt, nie gewählt, wenn ein anderer alle besteht; danach zählen Länge im guten
    Fenster und ``satz_staerke``. Der bisherige Einstieg bleibt, solange ein anderer nicht
    mindestens um ``hook_vorziehen.mindest_vorsprung`` stärker ist (sonst wäre der Wechsel Selbstzweck und
    nähme Aufbau weg). Zurück ``{chosen, previous, changed, reason, options, alternatives_considered}``; jede
    Alternative trägt ihren Grund."""
    payoff = payoff_idx if payoff_idx is not None and first < payoff_idx <= last else last
    found = payoff_search.alternative_openings(sents, first, payoff, pol, limit=MAX_OPENINGS) if payoff > first else []
    hook_types = {int(o["opening_sent"]): o.get("hook_type") for o in found}
    order = [first, *[int(o["opening_sent"]) for o in found if int(o["opening_sent"]) != first]][:MAX_OPENINGS]
    options = [_opening_option(words, sents, j, last, pol, heat_payload, lenient, hook_types.get(j)) for j in order]
    current = options[0]
    margin = float(pol.hook_vorziehen.get("mindest_vorsprung", 2.0) or 0.0)

    def rank(o: dict) -> tuple:
        return (o["length_allowed"], not o["gates_failed"], o["length_good"])

    chosen = current
    for o in options[1:]:
        if rank(o) > rank(chosen) or (rank(o) == rank(chosen) and o["strength"] >= chosen["strength"] + (margin if chosen is current else 0.0) and o["strength"] > chosen["strength"]):
            chosen = o
    if chosen is current:
        reason = "bisheriger Einstieg bleibt" + ("" if len(options) > 1 else ", kein anderer Originaleinstieg vor dem Payoff")
    elif rank(chosen) > rank(current):
        reason = "bisheriger Einstieg " + _opening_reason(current, chosen)
    else:
        reason = f"deutlich stärkerer Einstieg (Satzstärke {chosen['strength']} gegen {current['strength']})"
    alternatives = [{**o, "reason": _opening_reason(o, chosen)} for o in options if o is not chosen]
    return {
        "chosen": chosen["opening_sent"], "previous": first, "changed": chosen is not current, "reason": reason,
        "options": len(options), "chosen_option": chosen, "alternatives_considered": alternatives,
    }  # fmt: skip


def evaluate_span(
    words: list[dict],
    sents: list[Sentence],
    proposal: dict,
    brief: dict[str, Any],
    llm: LLM,
    weights: dict[str, float],
    heat_payload: dict[str, Any] | None = None,
) -> CandidateResult | dict:
    """Stufe 3 und 4 für einen Vorschlag. Rückgabe: Kandidat oder ``{"reason": ...}`` bei Verwerfung.

    ``heat_payload`` liefert den Klanganteil. Fehlt er, wird ohne ihn bewertet."""
    first0, last0 = int(proposal["first_sent"]), int(proposal["last_sent"])
    heuristic = getattr(llm, "is_heuristic", False)
    r = story_score.score_with_repair(sents, first0, last0, brief, llm, max_rounds=MAX_REPAIR_ROUNDS)
    first, last = int(r["first_sent"]), int(r["last_sent"])
    origin = (first, last)  # vor jeder Heilung: AP2 und AP4 teilen sich die Reichweite ab hier
    pol_ = editorial.load()
    # AP2 (Fassung 2 mit implementation.sentence_rule): erst den Anfang heilen, wie das Ende.
    ap2 = editorial.context_front(pol_) is not None
    start_note = None
    if ap2:
        # Nicht heilbar heisst nicht verwerfen: das Tor standalone reisst (unten), select_best verwirft
        # wie bei jedem anderen Tor, und der Grund bleibt sichtbar.
        first, start_note = heal_start(words, sents, first, last, r, pol_)
    # Erst das Ende heilen, dann die Laenge pruefen. Andersherum faellt ein Clip wegen einer Laenge
    # durch, die er nach der Heilung gar nicht mehr haette, oder er besteht mit einem Ende, das
    # mitten im Satz abbricht.
    last, zugabe = kontext_verlaengern(words, sents, first, last, r)
    if zugabe is not None and zugabe.get("discarded"):
        return {
            "reason": str(zugabe["discarded"]), "first_sent": first, "last_sent": last,
            "duration_s": round(_duration(sents, first, last), 2), "detail": str(zugabe.get("detail") or ""),
        }  # fmt: skip
    start_healed = bool(start_note and start_note.get("healed"))
    heal_rounds = int(start_healed) + int(zugabe is not None)
    # AP4 (Fassung 2 mit implementation.gates.discard_hard): harte Gates nach den Heilungen aus AP2. Heilbare
    # Mängel lösen zuerst eine Heilung aus, dann laufen die Gates erneut; verworfen wird erst in ``run``.
    gcfg = gates_wired(pol_)
    gate_run: dict | None = None
    gate_heal: dict = {}
    if gcfg is not None:
        gate_run = _run_gates(words, sents, first, last, pol_)
        # Unheilbare Treffer (``unhealable``) werden nicht geheilt: der Kandidat fällt ohnehin.
        unhealable = gate_run.get("unhealable")
        if unhealable is None:
            unhealable = [k for k in gate_run["failed"] if not gate_run["results"][k].get("healable")]
        if gate_run["failed"] and gate_run["healable"] and not unhealable:
            first_g, last_g, gate_heal = heal_gates(words, sents, first, last, r, pol_, gate_run, origin=origin)
            back = gate_heal.get("back") or {}
            if back.get("discarded"):
                return {
                    "reason": str(back["discarded"]), "first_sent": first, "last_sent": last,
                    "duration_s": round(_duration(sents, first, last), 2), "detail": str(back.get("detail") or ""),
                }  # fmt: skip
            if (first_g, last_g) != (first, last):
                heal_rounds += int(first_g != first) + int(last_g != last)
                first, last = first_g, last_g
                gate_run = _run_gates(words, sents, first, last, pol_)
    gate_healed = any(n.get("healed") or n.get("saetze") for n in gate_heal.values())
    # AP6b (Fassung 2, search.compare_openings): der Editor vergleicht bis zu drei Originaleinstiege und wählt
    # einen; die anderen stehen mit Grund in rubric.alternatives_considered. Ein neuer Einstieg wird wie eine
    # Heilung genau einmal neu bewertet.
    openings: dict | None = None
    if editorial.compare_openings_enabled(pol_):
        lenient = zugabe is not None or start_healed or gate_healed
        openings = compare_openings(words, sents, first, last, _payoff_index(proposal, first, last), pol_, heat_payload, lenient)
        if openings["changed"]:
            first = int(openings["chosen"])
            defects = start_defects(words, sents, first, pol_) if ap2 else []
            if defects or start_note is not None:
                # Die Notiz beschreibt jetzt den neuen Einstieg; die alte bleibt zur Nachvollziehbarkeit.
                start_note = {"healed": not defects, "defects": defects, "opening_changed": True, "before": start_note}
            if gate_run is not None:
                gate_run = _run_gates(words, sents, first, last, pol_)
    opening_changed = bool(openings and openings["changed"])
    rescore_skipped: str | None = None
    if ((ap2 or gcfg is not None) and heal_rounds) or opening_changed:
        # Nach der Heilung (vorn, hinten oder beides) genau eine Neubewertung: die Rubrik beschreibt
        # sonst eine Spanne, die es nicht mehr gibt (RESEARCH-CLIPPING-KERN Abschnitt 2, weitere Befunde).
        before = {
            "first_sent": int(r["first_sent"]), "last_sent": int(r["last_sent"]),
            "rubric_points": dict(r.get("rubric_points") or {}), "total": r.get("total"),
            "scores": {k: r.get(k) for k in SCORE_KEYS},
        }  # fmt: skip
        try:
            rescored = story_score.score(sents[first : last + 1], brief, llm)
        except LLMBudgetExceeded:
            # Modellbudget aufgebraucht: die Neubewertung entfällt, die Rubrik ist die der Spanne davor.
            rescore_skipped = "llm_budget"
        else:
            rescored.update(first_sent=first, last_sent=last, start=sents[first].start, end=sents[last].end)
            # Gilt die neue Spanne als nicht eigenständig, ist die Reparatur gescheitert, egal wie die
            # Bewertung davor ausfiel.
            rescored["repair_failed"] = not rescored.get("gate_passed", True)
            rescored["pre_heal_scores"] = before
            r = rescored
    if gate_run is not None:
        # Modellantwort gegen eingebettete Anweisungen prüfen (Master-Prompt 22): folgt sie ihr, wird verworfen.
        followed = _instruction_check(sents, first, last, gate_run, r, proposal)
        if followed is not None and not followed["passed"]:
            return {
                "reason": "instruction_followed", "first_sent": first, "last_sent": last,
                "duration_s": round(_duration(sents, first, last), 2), "detail": followed["detail"],
            }  # fmt: skip
    dur = _duration(sents, first, last)
    reason = _length_reason(dur, mit_zugabe=zugabe is not None or start_healed or gate_healed)
    if reason:
        return {
            "reason": reason + ("_after_repair" if (first, last) != (first0, last0) else ""),
            "first_sent": first, "last_sent": last, "duration_s": round(dur, 2),
        }  # fmt: skip

    # AP7 (Fassung 2, Regel und Schalter trim.enabled): Kürzung mit Sinntreue-Prüfung auf dem Ergebnis. Ein
    # Befund hoher Schwere oder eine ungültige Komposition setzt auf die ungekürzte Fassung zurück.
    trim: dict | None = None
    if trim_wired(pol_) is not None:
        trim = trim_span(words, sents, first, last, _payoff_index(proposal, first, last), pol_, heat_payload)
        if trim["applied"] and trim["last"] != last:
            # Das Ende ist gekappt: die fünf Tore und die harten Gates neu prüfen; reißt eines neu, gilt die
            # ungekürzte Fassung.
            before5 = deterministic_gates(words, sents, first, last, r)
            after5 = deterministic_gates(words, sents, first, trim["last"], r)
            new5 = [k for k, g in after5.items() if not g.get("passed") and before5[k].get("passed")]
            after = _run_gates(words, sents, first, trim["last"], pol_) if gate_run is not None else None
            new = [k for k in after["failed"] if k not in gate_run["failed"]] if after is not None and gate_run is not None else []
            if new5 or new:
                trim.update(applied=False, reason="Kürzung am Ende reißt ein Tor: " + ", ".join(new5 + new))
            elif after is not None:
                gate_run = after
        if trim["applied"]:
            last = trim["last"]
            dur = _duration(sents, first, last)

    span = sents[first : last + 1]
    clip_text = " ".join(s.text for s in span)
    klang = audio_wert(heat_payload, sents[first].start, sents[last].end)

    # Hook vorziehen (Masterclass 10.3). Der Teaser wiederholt sich im Body, die Abspieldauer ist
    # deshalb laenger als die Quellspanne. Genau damit muss die Laengenbewertung rechnen, sonst
    # schoebe das Vorziehen jeden Clip unbemerkt aus dem guten Fenster.
    segmente = [{"start": round(sents[first].start, 3), "end": round(sents[last].end, 3), "role": "body"}]
    struktur = str(proposal.get("structure") or "hook_build_payoff")
    abspiel_dauer = dur
    if trim is not None and trim["applied"]:
        segmente, abspiel_dauer = [dict(x) for x in trim["segments"]], float(trim["duration_s"])
    # E6: in einer Debatte nie umordnen, also kein Teaser (mit der Kürzung aus AP7 geprüft).
    teaser_idx = None if trim is not None and trim["is_debate"] else teaser_satz(sents, first, last, pol_, heat_payload)
    if teaser_idx is not None:
        t = sents[teaser_idx]
        comp = compose.with_teaser(compose.Composition.from_json(segmente), round(t.start, 3), round(t.end, 3))
        maengel = comp.validate(words)
        if maengel:
            # Lieber ohne Teaser als mit einem, den das Zusammensetzen spaeter ablehnt.
            teaser_idx = None
        else:
            segmente = comp.to_json()
            abspiel_dauer = comp.duration
            struktur = "payoff_first"
    scores = {k: int(max(0, min(10, int(r.get(k, 0) or 0)))) for k in SCORE_KEYS}
    gates = deterministic_gates(words, sents, first, last, r)
    if start_note is not None and not start_note.get("healed"):
        gates["standalone"] = {
            "passed": False,
            "detail": "Anfang nicht heilbar: " + "; ".join(start_note["defects"]),
            "reason": "start_not_healed",
        }
    if gate_run is not None and gate_run["decision"] == "rejected":
        # Faltung in die fünf Tore nur, wenn wirklich verworfen wird (Regel und Schalter); „reported“ berichtet nur.
        _map_legacy_gates(gates, gate_run)
    if zugabe is not None:
        r["kontext_zugabe"] = zugabe
    flags = later_qualifications(sents, first, last, llm)
    expanded_front, expanded_back = first0 - first, last - last0
    rubric = {
        "contract": CONTRACT,
        "text": numbered(span),
        "speakers": sorted({s.speaker for s in span if s.speaker}),
        "duration_s": round(dur, 2),
        "scores": {
            k: {"value": scores[k], "weight": round(weights[k], 4), "evidence": str(r.get(f"{k}_evidence", "") or "")}
            for k in SCORE_KEYS
        },
        # Die sieben Kriterien der Grundlage und ihre Fassung: ohne sie laesst sich spaeter nicht
        # nachvollziehen, wie ein Gesamtwert zustande kam, weil "scores" nur die alten fuenf zeigt.
        "rubric_points": dict(r.get("rubric_points") or {}),
        "policy_version": str(r.get("policy_version") or ""),
        "laenge_abzug": round(pol_.laenge_abzug(abspiel_dauer), 3),
        "abspiel_dauer_s": round(abspiel_dauer, 2),
        "teaser_satz": teaser_idx,
        # Klanganteil, 0,5 ist Durchschnitt. null heisst: keine Heatmap mit Audioanteil vorhanden.
        "klang": klang,
        "unresolved_references": [str(x) for x in (r.get("unresolved_references") or [])],
        "needs_earlier_context": bool(r.get("needs_earlier_context")),
        "ends_before_answer": bool(r.get("ends_before_answer")),
        "is_humor": bool(r.get("is_humor")),
        "sensitive_topic": bool(r.get("sensitive_topic")),
        "suggested_title_card": str(r.get("suggested_title_card") or ""),
        "repair": {
            "rounds": max(expanded_front, expanded_back),
            "expanded_front": expanded_front,
            "expanded_back": expanded_back,
            "failed": bool(r.get("repair_failed")),
        },
        # Wurde die Kontextzugabe eingesetzt, steht hier warum und wie viel. Ohne diesen Eintrag
        # waere spaeter nicht mehr zu sehen, ob ein Clip ueber der harten Grenze liegt, weil er
        # etwas brauchte, oder weil ihn niemand aufgehalten hat.
        "kontext_zugabe": r.get("kontext_zugabe"),
        "proposal_why": str(proposal.get("why") or ""),
        "parent_id": None,
    }
    if ap2:
        # Nur Fassung 2 mit AP2; unter Fassung 1 bleibt die Rubrik byte-gleich.
        rubric["sentence_rule"] = _cut_args(words, pol_)["rule"]
        rubric["start_heal"] = start_note
        rubric["pre_heal_scores"] = r.get("pre_heal_scores")
        rubric["heal_rounds"] = heal_rounds
    if openings is not None:
        # AP6b, additiv: gewählter Einstieg und die verworfenen Alternativen mit Grund.
        rubric["opening_choice"] = {k: openings[k] for k in ("chosen", "previous", "changed", "reason", "options")}
        rubric["alternatives_considered"] = openings["alternatives_considered"]
    if rescore_skipped:
        rubric["rescore_skipped"] = rescore_skipped
    if proposal.get("missing_v2_fields"):
        # Vorschlag ohne die Felder aus propose_moments_v2: in der Auswahl abgewertet (select_best).
        rubric["proposal_missing_v2_fields"] = list(proposal["missing_v2_fields"])
    if gate_run is not None:
        # AP4, additiv: alle Gate-Ergebnisse, die Entscheidung und die Heilungen. Die fünf Tore bleiben.
        rubric["quality_gate_results"] = gate_run["results"]
        rubric["quality_gate_decision"] = {
            "decision": gate_run["decision"], "reason": gate_run["decision_reason"], "detail": gate_run["decision_detail"],
            "failed": list(gate_run["failed"]), "flagged": list(gate_run["flagged"]), "discard_hard": gate_run["discard_hard"],
            "unhealable": list(gate_run.get("unhealable") or []), "switch": gate_run.get("switch"),
        }  # fmt: skip
        rubric["gate_heal"] = gate_heal or None
        rubric["heal_rounds"] = heal_rounds
    if trim is not None:
        # AP7, additiv: was gekürzt wurde (oder warum nicht) und die entfernten Stellen nach Master-Prompt 21.
        rubric["trim"] = {k: trim[k] for k in ("applied", "reason", "reward_end", "findings", "composition")}
        rubric["removed_spans"] = list(trim.get("removed_spans") or []) if trim["applied"] else []
        # Mit den Segmenten der Kürzung: die Web-Revision erkennt daran, ob ein Clip noch diese Schnitte hat.
        rubric["composition"] = {**trim["composition"], "segments": [dict(x) for x in trim["segments"]]} if trim["applied"] else None
    if pol_.version >= 2:
        # AP9, additiv: Teilwerte nach Master-Prompt 19 aus ``story_score.score`` (ab score_clip_v3, sonst null)
        # und der Hinweis, dass gelernte Gewichte die Rangfolge nicht ändern (P29). ``anchor_subscores`` heißt
        # nicht ``editorial_subscores``, weil AP8 diesen Schlüssel mit den sieben Rubrikpunkten belegt.
        rubric["anchor_subscores"] = r.get("editorial_subscores")
        rubric["learned_weights_applied"] = False
        rubric["learned_weights_reason"] = LEARNED_WEIGHTS_REASON
    gate_passed = all(bool(g["passed"]) for g in gates.values())
    # Die Begründung nennt die Plattform der Clips (``analyze.clip_platform``); ohne sie das Briefing.
    platform = str(brief.get("clip_platform") or brief.get("platform") or "linkedin")
    return CandidateResult(
        segments=segmente,
        start_s=round(sents[first].start, 3),
        end_s=round(sents[last].end, 3),
        first_sent=first,
        last_sent=last,
        structure=struktur,
        rubric=rubric,
        gates=gates,
        story_graph_flags=flags,
        risk_flags=risk_flags_for(r, clip_text, heuristic),
        # Die Grundlage entscheidet, nicht mehr die alten fuenf Kriterien ohne Laengenabzug.
        total=policy_total(r, abspiel_dauer, pol=pol_, audio=klang),
        gate_passed=gate_passed,
        why=build_why(scores, r, gates, flags, dur, platform, heuristic),
        model_id=str(r.get("model_id") or llm.model()),
        prompt_version=r.get("prompt_version"),
    )


# -- Auswahl -------------------------------------------------------------------------------------


def gemeinsamer_anteil(a_start: float, a_ende: float, b_start: float, b_ende: float) -> float:
    """Wie viel vom KUERZEREN der beiden Abschnitte im anderen steckt, 0 bis 1.

    Nicht IoU: bei sehr unterschiedlichen Laengen verschwindet eine vollstaendige Ueberdeckung des
    kurzen Abschnitts im grossen Nenner. Ein Clip, der ganz in einem anderen liegt, kommt hier
    immer auf 1,0, egal wie lang der andere ist.
    """
    inter = max(0.0, min(a_ende, b_ende) - max(a_start, b_start))
    kuerzer = min(a_ende - a_start, b_ende - b_start)
    return inter / kuerzer if kuerzer > 0 else 0.0


def _ueberdeckung(a: CandidateResult, b: CandidateResult) -> float:
    return gemeinsamer_anteil(a.start_s, a.end_s, b.start_s, b.end_s)


_NUMBERED_PREFIX = re.compile(r"^\[\d+\]\s+\([^)]*\)\s*", re.MULTILINE)


def content_lemmas(c: CandidateResult) -> set[str]:
    """Inhaltswörter des Kandidaten (``story_graph._lemmas``) aus ``rubric.text`` ohne Satznummer und Sprecher."""
    return story_graph._lemmas(_NUMBERED_PREFIX.sub("", str(c.rubric.get("text") or "")))


def lemma_jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard zweier Lemma-Mengen, 0 bis 1; zwei leere Mengen sind 0 (nichts Gemeinsames belegt)."""
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _distinctiveness(cands: list[CandidateResult], lemmas: dict[int, set[str]]) -> None:
    """``distinctiveness_vs_others`` (Master-Prompt 19) additiv in ``rubric.anchor_subscores``: Lemma-Jaccard zum
    nächsten Nachbarn unter allen bewerteten Kandidaten des Laufs, Anker 4 mal (1 minus Jaccard) gerundet. Ohne
    Nachbarn 4. Unkalibriert wie alle Teilwerte."""
    for c in cands:
        best: tuple[float, CandidateResult | None] = (0.0, None)
        for o in cands:
            if o is not c:
                j = lemma_jaccard(lemmas[id(c)], lemmas[id(o)])
                if j > best[0]:
                    best = (j, o)
        sub = c.rubric.get("anchor_subscores")
        if not isinstance(sub, dict):
            sub = c.rubric["anchor_subscores"] = {"scale_max": story_score.SUBSCORE_SCALE_MAX, "calibration": "uncalibrated", "values": {}}
        sub.setdefault("values", {})["distinctiveness_vs_others"] = int(round(story_score.SUBSCORE_SCALE_MAX * (1.0 - best[0])))
        sub["distinctiveness"] = {
            "nearest_jaccard": round(best[0], 3),
            "nearest": [best[1].first_sent, best[1].last_sent] if best[1] is not None else None,
            "method": "lemma_jaccard",
        }


RESERVE_SIZE = 3  # Nachrücker für den Kritiker (AP6b): so viele über der Obergrenze bleiben in Reserve


def select_best(
    cands: list[CandidateResult],
    limit: int = MAX_CANDIDATES,
    pol: editorial.Policy | None = None,
    heuristic: bool = False,
) -> tuple[list[CandidateResult], list[dict]]:
    """Wie ``select_with_reserve`` ohne Reserve."""
    kept, dropped, _reserve = select_with_reserve(cands, limit, pol=pol, heuristic=heuristic)
    return kept, dropped


def select_with_reserve(
    cands: list[CandidateResult],
    limit: int = MAX_CANDIDATES,
    pol: editorial.Policy | None = None,
    heuristic: bool = False,
    reserve_size: int = 0,
) -> tuple[list[CandidateResult], list[dict], list[CandidateResult]]:
    """Beste nach Rubrik (Gate-Erfüllung vor Score), überlappende Spannen nur einmal, maximal ``limit``.

    Mit ``pol`` der Fassung 2 und den harten Gates (AP4) gilt ``editorial.block_mode_settings``: im Modus
    ``sperren`` (nur mit Sprachmodell, mit Heuristik bleibt ``sortieren``) wird ein Kandidat, dessen Punkte
    nach der Grundlage unter ``discard_below`` liegen, verworfen (Grund ``below_threshold``).

    AP9 (Fassung 2 mit ``implementation.output.max_candidates``; ohne ``pol`` die aktive Richtlinie): höchstens
    ``output.max_candidates`` (und nie mehr als ``limit``); ein Kandidat, dessen Inhaltswörter mit einem schon
    behaltenen ab ``output.redundancy_jaccard`` übereinstimmen (Lemma-Jaccard), fällt mit Grund ``redundant``,
    zusätzlich zur zeitlichen Überdeckung; ``distinctiveness_vs_others`` steht additiv in der Rubrik.

    ``reserve``: die ersten ``reserve_size`` Kandidaten, die nur an der Obergrenze scheiterten (Grund ``limit``,
    im Eintrag ``reserve`` true), in Rangfolge; der Kritiker lässt sie nachrücken."""
    reserve: list[CandidateResult] = []
    gcfg = gates_wired(pol)
    block = editorial.block_mode_settings(pol, heuristic=heuristic) if gcfg is not None else None
    # Modus sperren verwirft nur mit Schalter UND Regel gates.discard_hard UND Sprachmodell (effective_mode);
    # im Berichtsmodus (Regel false) steht das Ergebnis nur in rubric.block_mode.
    block_discards = block is not None and bool(gcfg and gcfg["discard_hard"]) and block["effective_mode"] == "sperren"
    active = pol if pol is not None else _active_policy()
    output = editorial.output_settings(active) if active is not None else None
    lemmas: dict[int, set[str]] = {}
    if output is not None:
        limit = min(limit, output["max_candidates"])
        lemmas = {id(c): content_lemmas(c) for c in cands}
        _distinctiveness(cands, lemmas)
    # Ein Vorschlag im alten Format (``proposal_missing_v2_fields``, nur Fassung 2) rückt hinter jeden
    # vollständigen; unter Fassung 1 fehlt der Schlüssel und die Reihenfolge bleibt wie bisher.
    ordered = sorted(cands, key=lambda c: (c.gate_passed, not c.rubric.get("proposal_missing_v2_fields"), c.total, -c.start_s), reverse=True)
    kept: list[CandidateResult] = []
    dropped: list[dict] = []
    for c in ordered:
        if block is not None and pol is not None:
            points = pol.gesamtwert(c.rubric.get("rubric_points") or {}) if c.rubric.get("rubric_points") else 0.0
            below = points < float(block["discard_below"])
            c.rubric["block_mode"] = {
                "mode": block["mode"], "effective_mode": block["effective_mode"], "discard_below": block["discard_below"],
                "points": round(points, 2), "below": below, "applied": block_discards,
            }  # fmt: skip
            if block_discards and below:
                dropped.append({
                    "reason": "below_threshold", "first_sent": c.first_sent, "last_sent": c.last_sent, "total": c.total,
                    "detail": f"{points:.1f} Punkte unter der Schwelle {block['discard_below']} (Modus sperren)",
                })  # fmt: skip
                continue
        # Ein gerissenes Tor ist kein Geschmacksurteil, sondern ein feststellbarer Fehler im
        # Schnitt: der Clip endet vor dem „aber", das ihm den Sinn gibt, er verweist auf etwas
        # Unsichtbares, oder er faengt mitten im Satz an. Bisher wirkte das nur auf die
        # Reihenfolge, und war Platz da, wurde der Clip trotzdem gebaut. An drei echten Quellen
        # gemessen riss bei jeder genau ein Kandidat ein Tor, und alle drei wurden gerendert.
        #
        # Lieber ein Clip weniger als einer, von dem wir schon wissen, dass er kaputt ist.
        if not c.gate_passed:
            grund = "; ".join(str(g.get("detail") or "") for g in c.gates.values() if not g.get("passed"))
            dropped.append({"reason": "gate", "first_sent": c.first_sent, "last_sent": c.last_sent, "total": c.total, "detail": grund})
            continue
        clash = next((k for k in kept if _ueberdeckung(c, k) >= OVERLAP_SUPPRESS_ANTEIL), None)
        if clash is not None:
            dropped.append({"reason": "overlap", "first_sent": c.first_sent, "last_sent": c.last_sent, "total": c.total})
            continue
        if output is not None:
            # Fall 12: dieselbe Aussage an anderer Stelle ist kein zweiter Clip, auch ohne zeitliche Überdeckung.
            twin = max(((lemma_jaccard(lemmas[id(c)], lemmas[id(k)]), k) for k in kept), key=lambda x: x[0], default=None)
            if twin is not None and twin[0] >= output["redundancy_jaccard"]:
                j, k = twin
                dropped.append({
                    "reason": "redundant", "first_sent": c.first_sent, "last_sent": c.last_sent, "total": c.total,
                    "jaccard": round(j, 3), "kept": [k.first_sent, k.last_sent],
                    "detail": f"Lemma-Jaccard {j:.2f} zu Satz {k.first_sent} bis {k.last_sent} ab Schwelle {output['redundancy_jaccard']}",
                })  # fmt: skip
                continue
        if len(kept) >= limit:
            entry = {"reason": "limit", "first_sent": c.first_sent, "last_sent": c.last_sent, "total": c.total}
            if len(reserve) < reserve_size:
                entry["reserve"] = True
                reserve.append(c)
            dropped.append(entry)
            continue
        kept.append(c)
    kept.sort(key=lambda c: c.start_s)
    return kept, dropped, reserve


# -- Einstieg ------------------------------------------------------------------------------------


def prompt_versions() -> list[str]:
    """Die Prompt-Versionen, die die Engine tatsächlich nutzt (für Event-Payload und Idempotenz-Key), so wie
    die aktive Policy sie pinnt. Eine neue Prompt-Datei ändert diese Liste erst, wenn eine Policy sie pinnt.

    Fassung 2: ``propose_moments_v2`` nur mit ``implementation.search.payoff_first`` (sonst nutzt ``propose``
    den Pin der Fassung 1, und genau der steht hier); mit dem Schalter zusätzlich ``episode_overview``, mit
    ``roles.critic`` (AP6b) zusätzlich ``critique_clip``."""
    pol = editorial.load()
    propose = prompts.load_pinned("propose_moments", pol)
    wired = search_wired(pol) is not None
    if propose.version >= 2 and not wired:
        propose = prompts.load_pinned("propose_moments", editorial.load(1))
    out = [
        propose.prompt_version,
        prompts.load_pinned("score_clip", pol).prompt_version,
        prompts.load_pinned("story_graph_confirm", pol).prompt_version,
    ]
    if wired:
        out.append(prompts.load_pinned("episode_overview", pol).prompt_version)
    if editorial.critic_enabled(pol):
        out.append(prompts.load_pinned("critique_clip", pol).prompt_version)
    return out


def run(
    words: list[dict],
    brief: dict[str, Any] | None,
    brand: dict[str, Any] | None,
    heat_payload: dict[str, Any] | None,
    llm: LLM,
    weights: dict[str, float] | None = None,
    on_progress: ProgressFn | None = None,
    max_candidates: int = MAX_CANDIDATES,
) -> DetectReport:
    """Alle vier Stufen. ``on_progress(done, total, n_candidates)`` wird nach jedem Kapitel aufgerufen.

    Fassung 2, je Schalter: mit ``implementation.search.payoff_first`` (AP5) überlappende Kapitel
    (``search.chapter_overlap_s``), Episodenübersicht je Kapitel, ``propose`` mit Übersicht, Seeds und
    Richtlinie, deterministische Vorschläge aus ``payoff_search.search_moments`` und Abgleich beider Quellen
    über ``payoff_search.reconcile``; das Modellbudget ``search.max_llm_calls_per_source_hour`` wird gezählt
    und durchgesetzt (kein Abbruch, nur keine weiteren Modellaufrufe, Hinweis in ``llm_budget``). Mit
    ``implementation.gates.discard_hard`` (AP4) verlassen Gate-Verletzer die Liste vor ``select_best`` (Grund
    ``gate:<schluessel>``, Quote je Gate in ``gate_rejections``). Unter Fassung 2 stehen die ClipCandidates im
    Bericht (AP8) und ihre kompakte Teilmenge additiv in der Rubrik. Mit ``roles.critic`` (AP6b) prüft der
    Kritiker die Überlebenden von ``select_best`` (``apply_critic``)."""
    brief = dict(brief or {})
    brand = dict(brand or {})
    weights = dict(weights) if weights else resolve_weights(brand.get("learned_weights"))
    # Fassung 1: Zerlegung wie vor AP2. Mit AP2 gilt die sentence_idx der Transkriptversion, damit Worker
    # und Web dieselben Saetze sehen; nur ohne sie wird nach der neuen Regel zerlegt.
    pol = _active_policy()
    if _sentence_rule(pol) == "v1":
        sents = sentences_from_words(words)
    else:
        args = _cut_args(words, pol)
        sents = sentences_from_annotated(words) or sentences_from_words(
            words, rule=args["rule"], max_s=args["max_s"], max_words=args["max_words"]
        )
    search_cfg = search_wired(pol)
    gate_cfg = gates_wired(pol)
    heuristic = bool(getattr(llm, "is_heuristic", False))
    if search_cfg is not None:
        chapters = chapterize(sents, CHAPTER_SECONDS, search_cfg["chapter_overlap_s"])
        # Heuristik-Provider: Aufrufe zählen, nie verweigern (kein Modell, keine Kosten).
        llm = BudgetLLM(llm, llm_budget_for(sents, search_cfg, pol), enforce=not heuristic)  # type: ignore[assignment]
    else:
        chapters = chapterize(sents, CHAPTER_SECONDS)
    seeds = seeds_from_heat(heat_payload)
    order = chapter_order(chapters, seeds)
    report = DetectReport(
        chapters=len(order),
        chapters_with_seeds=sum(1 for _i, _ch, has in order if has),
        prompt_versions=prompt_versions(),
        model_id=llm.model(),
        provider=llm.provider,
        weights=weights,
    )
    report.nlp_status = nlp_status_for(pol)
    if pol is not None and pol.version >= 2:
        report.engine = engine_version(pol)
    raw: list[CandidateResult] = []
    gate_rejected: list[CandidateResult] = []
    seen: set[tuple[int, int]] = set()
    proposed: list[tuple[int, int, int]] = []  # (erster, letzter Satz, Kapitel) unter AP5
    skipped_chapters: list[list[int]] = []
    for done, (chapter_no, chapter, _has_seed) in enumerate(order, start=1):
        refused_before = llm.refused if isinstance(llm, BudgetLLM) else 0
        if search_cfg is not None:
            gate_fn = opening_gate(words, sents, chapter, pol)
            moments = _propose_v2(chapter, brief, llm, pol, seeds, heat_payload, report, heuristic=heuristic, gate_fn=gate_fn, words=words)
            if not moments:
                no_viable_moment(report, chapter_no, chapter)
        else:
            moments = story_score.propose(chapter, brief, llm)[:MAX_PER_CHAPTER]
            report.proposals += len(moments)
        for m in moments:
            first, last = int(m["first_sent"]), int(m["last_sent"])
            if search_cfg is not None:
                # Überlappende Kapitel schlagen denselben Moment zweimal vor (auch um einen Satz verschoben):
                # ab CHAPTER_DUPLICATE_SHARE Überdeckung mit einem Vorschlag eines anderen Kapitels nur einmal.
                twin = next(
                    ((f, t) for f, t, ch in proposed
                     if (f, t) == (first, last)
                     or (ch != chapter_no and gemeinsamer_anteil(sents[f].start, sents[t].end, sents[first].start, sents[last].end) >= CHAPTER_DUPLICATE_SHARE)),
                    None,
                )  # fmt: skip
                if twin is not None:
                    note_duplicate(report, "chapter_overlap", [first, last], list(twin))
                    continue
                proposed.append((first, last, chapter_no))
            dur = _duration(sents, first, last)
            reason = _vorfilter_grund(sents, first, last)
            if reason:
                report.discarded.append({"reason": reason, "first_sent": first, "last_sent": last, "duration_s": round(dur, 2)})
                continue
            try:
                out = evaluate_span(words, sents, m, brief, llm, weights, heat_payload)
            except LLMBudgetExceeded:
                report.discarded.append({"reason": "llm_budget", "first_sent": first, "last_sent": last, "duration_s": round(dur, 2)})
                continue
            if isinstance(out, dict):
                report.discarded.append(out)
                continue
            key = (out.first_sent, out.last_sent)
            if key in seen:
                if search_cfg is not None:
                    note_duplicate(report, "same_result", list(key), list(key))
                else:
                    report.discarded.append({"reason": "duplicate", "first_sent": key[0], "last_sent": key[1]})
                continue
            seen.add(key)
            if gate_cfg is not None:
                decision = out.rubric.get("quality_gate_decision") or {}
                if decision.get("decision") == "rejected":
                    # AP4: harte Gates vor dem Ranking. Der Kandidat bleibt im Bericht (verworfen, mit Grund).
                    report.discarded.append({
                        "reason": str(decision.get("reason")), "first_sent": out.first_sent, "last_sent": out.last_sent,
                        "total": out.total, "detail": str(decision.get("detail") or ""),
                    })  # fmt: skip
                    gate_rejected.append(out)
                    continue
            raw.append(out)
        if isinstance(llm, BudgetLLM) and llm.refused > refused_before:
            skipped_chapters.append([chapter[0].idx, chapter[-1].idx])
        if on_progress:
            on_progress(done, len(order), len(raw))
    critic_on = pol is not None and editorial.critic_enabled(pol)
    reserve: list[CandidateResult] = []
    if gate_cfg is not None:
        report.candidates, dropped, reserve = select_with_reserve(
            raw, max_candidates, pol=pol, heuristic=heuristic, reserve_size=RESERVE_SIZE if critic_on else 0
        )
        report.gate_rejections = gate_rejection_rates([*raw, *gate_rejected])
    elif critic_on:
        report.candidates, dropped, reserve = select_with_reserve(raw, max_candidates, reserve_size=RESERVE_SIZE)
    else:
        report.candidates, dropped = select_best(raw, max_candidates)
    report.verworfen = [c for c in raw if all(c is not k for k in report.candidates)] + gate_rejected
    report.discarded.extend(dropped)
    if critic_on:
        # AP6b: Kritiker nur für die Überlebenden der Auswahl, innerhalb des Modellbudgets; verwirft er einen,
        # rückt der nächste aus der Reserve nach und wird ebenfalls geprüft.
        apply_critic(report, words, sents, llm, pol, max_candidates, evaluated=len(raw) + len(gate_rejected), reserve=reserve)
    if isinstance(llm, BudgetLLM):
        report.llm_budget = {
            "limit": llm.limit, "used": llm.used, "refused": llm.refused, "exhausted": llm.refused > 0,
            "enforced": llm.enforce,
            "per_source_hour": int(search_cfg["max_llm_calls_per_source_hour"]) if search_cfg else None,
            "status": "budget_exhausted" if llm.refused else "ok",
            "skipped_chapters": skipped_chapters,
            "note": (
                f"Modellbudget von {llm.limit} Aufrufen erreicht; {llm.refused} weitere Aufrufe nicht ausgeführt, "
                f"betroffen {len(skipped_chapters)} Kapitel (Grund llm_budget im Bericht)." if llm.refused
                else ("Heuristik-Provider: Aufrufe gezählt, nicht begrenzt." if not llm.enforce else None)
            ),
        }  # fmt: skip
        if llm.refused:
            # Kapitel mit Seeds liefen zuerst (chapter_order); was danach kam, bekam kein Modell mehr.
            report.discarded.append({
                "reason": "budget_exhausted", "limit": llm.limit, "used": llm.used, "refused": llm.refused,
                "skipped_chapters": skipped_chapters, "detail": report.llm_budget["note"],
            })  # fmt: skip
    if pol is not None and pol.version >= 2:
        attach_clip_candidates(report, words, sents, pol, brief)
    return report


# Ab diesem Anteil (am kürzeren gemessen) gilt ein Vorschlag aus einem überlappenden Kapitel als derselbe Moment.
CHAPTER_DUPLICATE_SHARE = 0.8
# Gründe in ``discarded``, die keine Dubletten sind; Dubletten stehen getrennt in ``search.duplicates``.
DUPLICATE_KINDS = ("duplicate_payoff", "same_span", "same_opening", "same_statement", "chapter_overlap", "same_result")


def no_viable_moment(report: DetectReport, chapter_no: int, chapter: list[Sentence]) -> None:
    """Ein Kapitel ohne tragfähigen Moment (Fassung 2 mit Suche): weder Modell noch Suche liefern einen
    Vorschlag. Das ist ein Verwerfen mit Grund (``no_viable_moment`` in ``discarded`` und ``rejected_chapters``),
    nicht bloß eine leere Liste; Fall 11 (schwaches Material) wird so ehrlich verworfen."""
    stats = (report.search.get("chapters") or [{}])[-1]
    if stats.get("rejected_reasons"):
        detail = "keine tragfähige Spanne, Vorschläge der Suche verworfen (" + ", ".join(stats["rejected_reasons"]) + ")"
    elif stats.get("diagnosis") and stats["diagnosis"].get("detail"):
        detail = str(stats["diagnosis"]["detail"])
    elif not stats.get("payoffs") and not stats.get("openings") and stats.get("search") == 0:
        detail = "nur Organisatorisches oder Füllgespräch, keine Behauptung mit Beleg und kein Einstieg mit Einlösung"
    else:
        detail = "keine Vorschläge"
    entry = {
        "reason": "no_viable_moment", "chapter": int(chapter_no), "first_sent": chapter[0].idx, "last_sent": chapter[-1].idx,
        "start_s": round(chapter[0].start, 2), "end_s": round(chapter[-1].end, 2), "detail": detail,
    }  # fmt: skip
    report.discarded.append(entry)
    report.rejected_chapters.append(dict(entry))


def note_duplicate(report: DetectReport, kind: str, dropped: list[int], kept: list[int], **extra: Any) -> None:
    """Eine Dublette (AP5) getrennt von den Verwerfungen: ``search.duplicates`` mit Spanne und behaltener Spanne,
    ``search.duplicate_counts`` je Art. Dubletten zählen nicht in die Verwerfungsquote."""
    report.search.setdefault("duplicates", []).append(
        {"kind": kind, "first_sent": int(dropped[0]), "last_sent": int(dropped[1]), "kept": [int(kept[0]), int(kept[1])], **extra}
    )
    counts = report.search.setdefault("duplicate_counts", {})
    counts[kind] = counts.get(kind, 0) + 1


def opening_gate(
    words: list[dict], sents: list[Sentence], chapter: list[Sentence], pol: editorial.Policy | None
) -> Callable[[int], bool] | None:
    """Einstiegsregel für ``payoff_search.search_moments``, dieselbe wie in der Engine: die Prüfung der Suche
    (``payoff_search.opening_defects``), ``start_defects`` (AP2) und die nach vorn heilbaren harten Gates (AP4,
    nur mit Schalter). Ein Satz taugt als Einstieg, wenn keine davon einen Mangel findet. ``None`` ohne AP2 und
    ohne Gates (dann gilt die Standardprüfung der Suche)."""
    if pol is None or (editorial.context_front(pol) is None and gates_wired(pol) is None):
        return None
    cache: dict[int, bool] = {}

    def ok(n: int) -> bool:
        if n not in cache:
            bad = payoff_search.opening_defects(chapter, n, pol)
            if not bad and editorial.context_front(pol) is not None:
                bad = start_defects(words, sents, n, pol)
            if not bad and gates_wired(pol) is not None:
                bad = list(_failed_on(_run_gates(words, sents, n, n, pol), "front"))
            cache[n] = not bad
        return cache[n]

    return ok


def apply_critic(
    report: DetectReport,
    words: list[dict],
    sents: list[Sentence],
    llm: Any,
    pol: editorial.Policy,
    limit: int,
    evaluated: int,
    reserve: list[CandidateResult] | None = None,
) -> None:
    """Kritiker (AP6b, ``roles.critic``) für die angebotenen Kandidaten, höchstens ``limit`` Aufrufe.

    Ein bestätigter Befund der Schwere ``fidelity`` mit wörtlichem Beleg (``critic.critique``) verwirft: Grund
    ``critic:<kind>`` in ``discarded``, der Kandidat wandert nach ``verworfen`` und zählt in
    ``gate_rejections``. Alle übrigen Befunde stehen in ``rubric.critic_findings``, der Ablauf in
    ``rubric.critic``. Befunde der Heuristik verwerfen nie. Ist das Modellbudget aufgebraucht oder die Antwort
    unbrauchbar, bleibt der Kandidat ungeprüft (``status`` ``llm_budget`` oder ``invalid_answer``).

    Nachrücken: verwirft der Kritiker einen Kandidaten, rückt der nächste aus ``reserve`` (``select_with_reserve``)
    nach, sofern er sich nicht mit einem Behaltenen überdeckt, und wird ebenfalls geprüft (``rubric.promoted``).
    Sein Eintrag ``limit`` in ``discarded`` entfällt dann."""
    from ..providers_llm import SchemaError
    from . import critic

    kept: list[CandidateResult] = []
    rejected: list[tuple[CandidateResult, str]] = []
    pending = list(reserve or [])
    promoted: list[CandidateResult] = []
    queue = list(report.candidates)
    n = -1
    while queue:
        c = queue.pop(0)
        n += 1
        if n >= limit + len(promoted):
            c.rubric["critic"] = {"status": "not_checked", "detail": f"über der Obergrenze von {limit} Prüfungen"}
            kept.append(c)
            continue
        try:
            res = critic.critique(c, sents, words, llm, pol)
        except LLMBudgetExceeded:
            c.rubric["critic"] = {"status": "llm_budget"}
            report.discarded.append({"reason": "llm_budget", "stage": "critic", "first_sent": c.first_sent, "last_sent": c.last_sent})
            kept.append(c)
            continue
        except SchemaError as exc:
            c.rubric["critic"] = {"status": "invalid_answer", "detail": str(exc)[:300]}
            kept.append(c)
            continue
        c.rubric["critic"] = {
            "status": "checked", "prompt_version": res["prompt_version"], "heuristic": res["heuristic"],
            "confirmed": res["confirmed"], "model_confirmed": res["model_confirmed"], "hook_source": res["hook_source"],
            "dropped": res["dropped"],
        }  # fmt: skip
        c.rubric["critic_findings"] = res["findings"]
        f = res["reject"]
        if f is None:
            kept.append(c)
            continue
        reason = f"critic:{f['kind']}"
        report.discarded.append({
            "reason": reason, "stage": "critic", "first_sent": c.first_sent, "last_sent": c.last_sent, "total": c.total,
            "detail": f"{f['explanation']} Beleg: „{f['evidence_quote']}“ ({f['location']})".strip(),
        })  # fmt: skip
        rejected.append((c, reason))
        while pending:
            nxt = pending.pop(0)
            if any(_ueberdeckung(nxt, k) >= OVERLAP_SUPPRESS_ANTEIL for k in [*kept, *queue]):
                continue
            nxt.rubric["promoted"] = {"from": "reserve", "replaces": [c.first_sent, c.last_sent]}
            promoted.append(nxt)
            queue.append(nxt)
            break
    report.candidates = sorted(kept, key=lambda c: c.start_s)
    up = [p for p in promoted if any(p is k for k in kept)]
    if up:
        report.verworfen = [v for v in report.verworfen if all(v is not p for p in up)]
        spans = {(p.first_sent, p.last_sent) for p in up}
        report.discarded = [d for d in report.discarded if not (d.get("reason") == "limit" and (d.get("first_sent"), d.get("last_sent")) in spans)]
    report.verworfen.extend(c for c, _reason in rejected if all(c is not v for v in report.verworfen))
    if rejected:
        rates = report.gate_rejections or {"evaluated": evaluated, "by_gate": {}}
        by_gate = rates.setdefault("by_gate", {})
        for _c, reason in rejected:
            entry = by_gate.setdefault(reason, {"failed": 0, "rejected": 0})
            entry["failed"] += 1
            entry["rejected"] += 1
        n_eval = int(rates.get("evaluated") or evaluated)
        for entry in by_gate.values():
            entry["quote"] = round(entry["rejected"] / n_eval, 4) if n_eval else 0.0
        rates["by_gate"] = dict(sorted(by_gate.items()))
        report.gate_rejections = rates


def gate_rejection_rates(evaluated: list[CandidateResult]) -> dict:
    """Verwerfungsquote je Gate (AP4) über alle bewerteten Kandidaten: wie oft ein Gate riss (``failed``) und
    wie oft es der Grund des Verwerfens war (``rejected``), Anteil an ``evaluated``."""
    n = len(evaluated)
    by_gate: dict[str, dict[str, Any]] = {}
    for c in evaluated:
        decision = c.rubric.get("quality_gate_decision") or {}
        for key in decision.get("failed") or []:
            entry = by_gate.setdefault(key, {"failed": 0, "rejected": 0})
            entry["failed"] += 1
        reason = str(decision.get("reason") or "")
        if decision.get("decision") == "rejected" and reason.startswith("gate:"):
            by_gate.setdefault(reason[5:], {"failed": 0, "rejected": 0})["rejected"] += 1
    for entry in by_gate.values():
        entry["quote"] = round(entry["rejected"] / n, 4) if n else 0.0
    return {"evaluated": n, "by_gate": dict(sorted(by_gate.items()))}


def attach_clip_candidates(
    report: DetectReport, words: list[dict], sents: list[Sentence], pol: editorial.Policy, brief: dict[str, Any] | None
) -> None:
    """ClipCandidates des Laufs (AP8, nur Fassung 2): vollständig in ``report.clip_candidates``, die kompakte
    Teilmenge (``clip_candidate.compact_for_rubric``) additiv in der Rubrik jedes Kandidaten. Mit der
    Satzliste des Laufs, damit die Zerlegung dieselbe ist."""
    from . import clip_candidate

    try:
        ccs = clip_candidate.from_report(report, words, pol, brief=brief, sents=sents)
        data = [cc.to_dict() for cc in ccs]
    except (ValueError, TypeError, KeyError) as exc:  # auch SchemaError: der Lauf bleibt gültig, der Verstoß steht im Bericht
        report.discarded.append({"reason": "clip_candidate_error", "detail": str(exc)[:500]})
        return
    report.clip_candidates = data
    for c, cc in zip([*report.candidates, *report.verworfen], ccs):
        c.rubric.update(clip_candidate.compact_for_rubric(cc))


def _search_why(prop: dict) -> str:
    parts = [f"Payoff in Satz {prop['payoff_sent']}" + (f" ({prop['payoff_type']})" if prop.get("payoff_type") else "")]
    parts.append(f"Einstieg in Satz {prop['opening_sent']}")
    if prop.get("hook_type"):
        parts.append(f"Hook-Typ {prop['hook_type']}")
    parts.append(f"Richtung {prop['direction']}")
    return "Deterministische Suche: " + ", ".join(parts) + "."


def _propose_v2(
    chapter: list[Sentence],
    brief: dict[str, Any],
    llm: Any,
    pol: editorial.Policy,
    seeds: list[float],
    heat_payload: dict[str, Any] | None,
    report: DetectReport,
    heuristic: bool = False,
    gate_fn: Callable[[int], bool] | None = None,
    words: list[dict] | None = None,
) -> list[dict]:
    """Vorschläge eines Kapitels unter AP5: Episodenübersicht, Modellvorschläge mit Übersicht und Seeds,
    deterministische Suche, Abgleich über ``payoff_search.reconcile``.

    Die Modellvorschläge gehen als Einstiege mit ihrer Einlösung (``payoff_sent``, ohne Angabe der letzte
    Satz) in den Abgleich, die Suche liefert die Payoff-Seite. Treffer derselben Aussage sind Dubletten;
    einer bleibt, die anderen stehen getrennt in ``search.duplicates`` (``note_duplicate``). Verworfene der
    Suche (``promise_unfulfilled``, ``context_missing``, ``too_short``, ``no_opening``) stehen in
    ``discarded``. Ist das Budget aufgebraucht, fallen Übersicht und Modellvorschläge weg; die Suche läuft
    ohne Modell weiter. Mit dem Heuristik-Provider gibt es nur eine Quelle, die Suche: sein ``propose``
    rechnet dieselbe Suche auf geschätzten Zeiten und ergäbe nur Dubletten. ``gate_fn`` ist die Einstiegsregel
    der Engine (``opening_gate``)."""
    stats = report.search.setdefault("chapters", [])
    span = {"first_sent": chapter[0].idx, "last_sent": chapter[-1].idx}
    overview = None
    try:
        overview = story_score.overview(chapter, llm, pol)
        report.overviews.append(overview)
    except LLMBudgetExceeded:
        report.discarded.append({"reason": "llm_budget", "stage": "overview", **span})
    model: list[dict] = []
    if not heuristic:
        try:
            model = story_score.propose(chapter, brief, llm, overview=overview, seeds=seeds, policy=pol)[:MAX_PER_CHAPTER]
        except LLMBudgetExceeded:
            report.discarded.append({"reason": "llm_budget", "stage": "propose", **span})
    found = payoff_search.search_moments(chapter, pol, heat_payload, gate_fn=gate_fn, words=words)
    payoff_first: list[dict] = []
    duplicates = list(found.get("duplicates") or [])
    for p in found["proposals"]:
        same = next((x for x in payoff_first if int(x["payoff_sent"]) == int(p["payoff_sent"])), None)
        if same is not None:
            duplicates.append({"payoff_sent": int(p["payoff_sent"]), "kept": [same["first_sent"], same["last_sent"]],
                               "dropped": [[p["first_sent"], p["last_sent"]]], "reason": "same_payoff"})  # fmt: skip
            continue
        payoff_first.append(p)
    by_idx = {x.idx: x for x in chapter}
    opening_first = []
    for m in model:
        pay = m.get("payoff_sent")
        opening_first.append({
            "opening_sent": int(m["first_sent"]), "first_sent": int(m["first_sent"]), "last_sent": int(m["last_sent"]),
            "payoff_sent": int(pay) if isinstance(pay, int) and not isinstance(pay, bool) else int(m["last_sent"]),
            "payoff_type": None, "hook_type": None, "required_context_sents": list(m.get("required_context_sents") or []),
            "duration_s": round(by_idx[int(m["last_sent"])].end - by_idx[int(m["first_sent"])].start, 2),
        })  # fmt: skip
    res = payoff_search.reconcile(payoff_first, opening_first)
    duplicates += res["duplicates"]
    for d in [*found["rejected"], *res["rejected"]]:
        report.discarded.append({**d, "stage": "search"})
    for d in duplicates:
        kept_span = list(d.get("kept") or [None, None])
        kind = "duplicate_payoff" if d.get("reason") == "same_payoff" else str(d.get("reason") or "duplicate_payoff")
        for dropped in d.get("dropped") or []:
            note_duplicate(report, kind, list(dropped), kept_span, payoff_sent=d.get("payoff_sent"), stage="search")
    by_model = {(int(m["first_sent"]), int(m["last_sent"])): m for m in model}
    by_search = {(int(p["first_sent"]), int(p["last_sent"])) for p in payoff_first}
    merged = []
    for prop in res["proposals"]:
        key = (int(prop["first_sent"]), int(prop["last_sent"]))
        base = by_model.get(key)
        source = ("both" if key in by_search else "model") if base is not None else "search"
        if base is None:
            base = {"first_sent": key[0], "last_sent": key[1], "structure": "hook_build_payoff", "why": _search_why(prop), "prompt_version": None}
        merged.append({
            **base,
            "payoff_sent": int(prop["payoff_sent"]),
            "opening_sent": int(prop["opening_sent"]),
            "required_context_sents": list(prop.get("required_context_sents") or []),
            "narrative_type": base.get("narrative_type") or prop.get("narrative_type"),
            "direction": prop["direction"],
            "source": source,
        })  # fmt: skip
    rank = {d: n for n, d in enumerate(payoff_search.DIRECTIONS)}
    merged.sort(key=lambda m: (bool(m.get("missing_v2_fields")), rank.get(m["direction"], len(rank)), m["source"] == "search", m["first_sent"]))
    for m in merged[MAX_PER_CHAPTER:]:
        report.discarded.append({"reason": "chapter_limit", "stage": "search", "first_sent": m["first_sent"], "last_sent": m["last_sent"]})
    kept = sorted(merged[:MAX_PER_CHAPTER], key=lambda m: (m["first_sent"], m["last_sent"]))
    report.proposals += len(model) + len(found["proposals"]) + len(found["rejected"])
    stats.append({
        **span, "model": len(model), "model_skipped": "heuristic" if heuristic else None,
        "search": len(found["proposals"]), "search_rejected": len(found["rejected"]) + len(res["rejected"]),
        "duplicates": sum(len(d.get("dropped") or []) for d in duplicates), "evaluated": len(kept),
        "overview": overview is not None, "payoffs": len(found.get("payoffs") or []),
        "openings": len(found.get("openings") or []), "diagnosis": found.get("diagnosis"), "rejected_reasons": sorted({str(d.get("reason")) for d in [*found["rejected"], *res["rejected"]]}),
    })  # fmt: skip
    return kept


def detect(
    words: list[dict],
    brief: dict[str, Any] | None,
    brand: dict[str, Any] | None,
    heat_payload: dict[str, Any] | None,
    llm: LLM,
    weights: dict[str, float] | None = None,
    on_progress: ProgressFn | None = None,
) -> list[CandidateResult]:
    """Kurzform von ``run``: nur die Kandidaten, sortiert nach Startzeit."""
    return run(words, brief, brand, heat_payload, llm, weights=weights, on_progress=on_progress).candidates


__all__ = [
    "CONTRACT",
    "ENDE_TORE",
    "ENGINE_VERSION",
    "MAX_CANDIDATES",
    "MAX_LEN_S",
    "MIN_LEN_S",
    "CandidateResult",
    "DetectReport",
    "apply_critic",
    "build_why",
    "chapter_order",
    "compare_openings",
    "detect",
    "deterministic_gates",
    "evaluate_span",
    "heal_start",
    "nlp_status_for",
    "kontext_verlaengern",
    "start_defects",
    "later_qualifications",
    "prompt_versions",
    "resolve_weights",
    "risk_flags_for",
    "run",
    "select_best",
    "audio_wert",
    "satz_staerke",
    "teaser_satz",
    "policy_total",
    "weighted_total",
]
