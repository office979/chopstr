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

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from typing import Any

from .. import editorial, prompts
from ..providers_llm import LLM
from . import compose, dach_nlp, fidelity, story_graph, story_score
from .segment import Sentence, chapterize, numbered, sentences_from_words

CONTRACT = "candidates_v1"
# v2: Bewertung aus der redaktionellen Grundlage (sieben Kriterien statt fuenf), mit
#     Laengenabzug und Klanganteil.
# v3: Hook vorziehen. Der staerkste Satz aus der Mitte kann als Teaser vorangestellt
#     werden; die Laengenbewertung rechnet dann mit der Abspieldauer, nicht der Quellspanne.
# Der Wert steckt im Idempotenz-Schluessel und erzwingt eine Neuberechnung. Ohne ihn
# kaeme das alte Ergebnis aus dem Zwischenspeicher und die Aenderung waere unsichtbar.
ENGINE_VERSION = "story_engine_v3"
MIN_LEN_S = 12.0
MAX_LEN_S = 90.0
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
    """Ergebnis eines Laufs: Kandidaten plus Zähler und Verwerfungsgründe für Event-Payload und Storage."""

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

    @property
    def gate_passed(self) -> int:
        return sum(1 for c in self.candidates if c.gate_passed)

    def to_json(self) -> dict[str, Any]:
        return {
            "contract": CONTRACT,
            "engine": ENGINE_VERSION,
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
        )


# -- Gewichte ------------------------------------------------------------------------------------


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


def _verb_bracket_gate(words: list[dict], sents: list[Sentence], first: int, last: int) -> dict:
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
    warnings = fidelity.check_cut(span + tail, [(0, len(span) - 1)]) if span else []
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
    hits = story_graph.find_later_qualifications(sents, first, last)
    if not hits:
        return []
    clip_text = " ".join(s.text for s in sents[first : last + 1])
    flags = []
    for h in hits:
        out = story_graph.confirm(llm, clip_text, h["text"], h["seconds_after"])
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


def _length_reason(dur: float) -> str | None:
    if dur < MIN_LEN_S:
        return "too_short"
    if dur > MAX_LEN_S:
        return "too_long"
    return None


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
    dur = _duration(sents, first, last)
    reason = _length_reason(dur)
    if reason:
        return {
            "reason": reason + ("_after_repair" if (first, last) != (first0, last0) else ""),
            "first_sent": first, "last_sent": last, "duration_s": round(dur, 2),
        }  # fmt: skip

    span = sents[first : last + 1]
    clip_text = " ".join(s.text for s in span)
    klang = audio_wert(heat_payload, sents[first].start, sents[last].end)

    # Hook vorziehen (Masterclass 10.3). Der Teaser wiederholt sich im Body, die Abspieldauer ist
    # deshalb laenger als die Quellspanne. Genau damit muss die Laengenbewertung rechnen, sonst
    # schoebe das Vorziehen jeden Clip unbemerkt aus dem guten Fenster.
    pol_ = editorial.load()
    segmente = [{"start": round(sents[first].start, 3), "end": round(sents[last].end, 3), "role": "body"}]
    struktur = str(proposal.get("structure") or "hook_build_payoff")
    teaser_idx = teaser_satz(sents, first, last, pol_, heat_payload)
    abspiel_dauer = dur
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
        "proposal_why": str(proposal.get("why") or ""),
        "parent_id": None,
    }
    gate_passed = all(bool(g["passed"]) for g in gates.values())
    platform = str(brief.get("platform") or "linkedin")
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


def select_best(cands: list[CandidateResult], limit: int = MAX_CANDIDATES) -> tuple[list[CandidateResult], list[dict]]:
    """Beste nach Rubrik (Gate-Erfüllung vor Score), überlappende Spannen nur einmal, maximal ``limit``."""
    ordered = sorted(cands, key=lambda c: (c.gate_passed, c.total, -c.start_s), reverse=True)
    kept: list[CandidateResult] = []
    dropped: list[dict] = []
    for c in ordered:
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
        if len(kept) >= limit:
            dropped.append({"reason": "limit", "first_sent": c.first_sent, "last_sent": c.last_sent, "total": c.total})
            continue
        kept.append(c)
    kept.sort(key=lambda c: c.start_s)
    return kept, dropped


# -- Einstieg ------------------------------------------------------------------------------------


def prompt_versions() -> list[str]:
    """Die drei Prompt-Versionen der Engine (für Event-Payload und Idempotenz-Key)."""
    return [
        prompts.load("propose_moments").prompt_version,
        prompts.load("score_clip").prompt_version,
        prompts.load("story_graph_confirm").prompt_version,
    ]


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
    """Alle vier Stufen. ``on_progress(done, total, n_candidates)`` wird nach jedem Kapitel aufgerufen."""
    brief = dict(brief or {})
    brand = dict(brand or {})
    weights = dict(weights) if weights else resolve_weights(brand.get("learned_weights"))
    sents = sentences_from_words(words)
    chapters = chapterize(sents, CHAPTER_SECONDS)
    order = chapter_order(chapters, seeds_from_heat(heat_payload))
    report = DetectReport(
        chapters=len(order),
        chapters_with_seeds=sum(1 for _i, _ch, has in order if has),
        prompt_versions=prompt_versions(),
        model_id=llm.model(),
        provider=llm.provider,
        weights=weights,
    )
    raw: list[CandidateResult] = []
    seen: set[tuple[int, int]] = set()
    for done, (_i, chapter, _has_seed) in enumerate(order, start=1):
        moments = story_score.propose(chapter, brief, llm)[:MAX_PER_CHAPTER]
        report.proposals += len(moments)
        for m in moments:
            first, last = int(m["first_sent"]), int(m["last_sent"])
            dur = _duration(sents, first, last)
            reason = _length_reason(dur)
            if reason:
                report.discarded.append({"reason": reason, "first_sent": first, "last_sent": last, "duration_s": round(dur, 2)})
                continue
            out = evaluate_span(words, sents, m, brief, llm, weights, heat_payload)
            if isinstance(out, dict):
                report.discarded.append(out)
                continue
            key = (out.first_sent, out.last_sent)
            if key in seen:
                report.discarded.append({"reason": "duplicate", "first_sent": key[0], "last_sent": key[1]})
                continue
            seen.add(key)
            raw.append(out)
        if on_progress:
            on_progress(done, len(order), len(raw))
    report.candidates, dropped = select_best(raw, max_candidates)
    report.verworfen = [c for c in raw if all(c is not k for k in report.candidates)]
    report.discarded.extend(dropped)
    return report


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
    "ENGINE_VERSION",
    "MAX_CANDIDATES",
    "MAX_LEN_S",
    "MIN_LEN_S",
    "CandidateResult",
    "DetectReport",
    "build_why",
    "chapter_order",
    "detect",
    "deterministic_gates",
    "evaluate_span",
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
