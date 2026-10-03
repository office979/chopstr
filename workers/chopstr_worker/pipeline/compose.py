"""Compose: ein Clip ist eine LISTE von Quell-Segmenten mit eigener Abspielreihenfolge.

Ermöglicht Füller-Schnitte (viele kleine Segmente) und Cold Open (stärkster Satz vorne als Teaser).

DACH-Trust-Regeln:
- Teaser muss vom selben Sprecher stammen und als Teaser markiert werden.
- Teaser-Satz kommt im Clip-Verlauf noch einmal vollständig vor.
- Segmente aus weit auseinanderliegenden Stellen ohne Teaser-Markierung: Sinntreue-Warnung (fidelity.py).
- Policy v2 (AP7): höchstens zwei semantische Splices (Verbindung nicht benachbarter Sätze), lokale
  Schnitte (Pausen, Füllwörter innerhalb einer Passage) zählen nicht mit; in einer Debatte kein Teaser
  und keine Umstellung (E6). Beides prüft ``Composition.validate`` nur, wenn der Aufrufer es verlangt.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from . import dach_nlp

MAX_TEASER_S = 6.0
MICRO_FADE_S = 0.02  # 20 ms Audio-Blende gegen Knackser an Klebestellen
LEAD_IN_S = 0.05
LEAD_OUT_S = 0.08
MERGE_GAP_S = 0.15


@dataclass
class Segment:
    start: float
    end: float
    role: str = "body"  # "teaser" | "body"

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Composition:
    segments: list[Segment] = field(default_factory=list)  # in ABSPIELREIHENFOLGE

    @property
    def duration(self) -> float:
        return sum(s.end - s.start for s in self.segments)

    def to_json(self) -> list[dict]:
        return [asdict(s) for s in self.segments]

    @classmethod
    def from_json(cls, data: list[dict]) -> Composition:
        return cls([Segment(float(d["start"]), float(d["end"]), d.get("role", "body")) for d in data])

    def validate(
        self,
        words: list[dict],
        max_splices: int | None = None,
        debate_no_reorder: bool = False,
        forced_semantic: set[int] | None = None,
    ) -> list[str]:
        """Trust-Regeln aus E6. ``max_splices`` (Policy v2, ``trim.max_semantic_splices``) zählt nur
        semantische Splices (``splice_kinds``, ``forced_semantic`` wie dort); ``debate_no_reorder``
        verbietet in einer Debatte (``is_debate``) Teaser und Umstellung. Ohne diese Angaben gilt das
        Verhalten vor AP7."""
        issues = []
        teasers = [s for s in self.segments if s.role == "teaser"]
        body = [s for s in self.segments if s.role == "body"]
        for s in self.segments:
            if s.end <= s.start:
                issues.append(f"Segment mit Länge 0 oder negativ ({s.start:.2f} bis {s.end:.2f})")
        for t in teasers:
            if t.end - t.start > MAX_TEASER_S:
                issues.append(f"Teaser zu lang ({t.end - t.start:.1f}s > {MAX_TEASER_S}s)")
            if not any(b.start <= t.start and t.end <= b.end for b in body):
                issues.append("Teaser-Satz kommt im Clip nicht noch einmal im Kontext vor")
            t_spk = {w.get("speaker") for w in words if t.start <= float(w["start"]) < t.end}
            if len(t_spk) > 1:
                issues.append("Teaser enthält mehrere Sprecher")
        if self.segments and self.segments[0].role != "teaser":
            body_sorted = sorted(body, key=lambda s: s.start)
            if body_sorted != body:
                issues.append("Body-Segmente sind umsortiert: nur mit ausdrücklicher Freigabe")
        if max_splices is not None:
            n = splice_kinds(self, words, forced_semantic).count("semantic")
            if n > max_splices:
                issues.append(f"Zu viele Splices ({n} statt höchstens {max_splices} Verbindungen nicht benachbarter Sätze, E6)")
        if debate_no_reorder and body and words:
            ids = _word_ids_between(words, min(b.start for b in body), max(b.end for b in body))
            if ids and is_debate(words, ids[0], ids[-1]):
                if teasers:
                    issues.append("Debatte: kein Teaser, die Reihenfolge des Gesprächs bleibt (E6)")
                if sorted(body, key=lambda s: s.start) != body:
                    issues.append("Debatte: Body-Segmente umgestellt, Debatten nie umordnen (E6)")
        return issues


def from_keep_ranges(words: list[dict], keep: list[tuple[int, int]]) -> Composition:
    """Füller-Schnitte: Wortindex-Bereiche zu Segmenten (Pausen am Rand leicht mitnehmen)."""
    segs = [Segment(max(0.0, float(words[a]["start"]) - LEAD_IN_S), float(words[b]["end"]) + LEAD_OUT_S) for a, b in keep]
    merged = [segs[0]] if segs else []
    for s in segs[1:]:
        if s.start - merged[-1].end < MERGE_GAP_S:
            merged[-1].end = s.end
        else:
            merged.append(s)
    return Composition(merged)


def with_teaser(comp: Composition, teaser_start: float, teaser_end: float) -> Composition:
    return Composition([Segment(teaser_start, teaser_end, "teaser"), *comp.segments])


def remap_words(words: list[dict], comp: Composition, by_midpoint: bool = False) -> list[dict]:
    """Wortzeiten von Quell- auf Ausgabe-Timeline (für Captions). Wörter können doppelt vorkommen
    (Teaser + Body), deshalb wird pro Segment kopiert.

    Standard: ein Wort zählt nur, wenn es ganz im Segment liegt; ein Wort, das eine Segmentgrenze
    streift, fällt heraus. ``by_midpoint=True`` (AP7, für Kompositionen mit vielen lokalen Schnitten)
    ordnet ein solches Wort dem Segment zu, in dem seine Mitte liegt (halboffen ``[start, end)``), und
    kürzt seine Zeiten auf die Segmentgrenzen; so geht kein Wort verloren und keins steht doppelt."""
    out, offset = [], 0.0
    for seg in comp.segments:
        for w in words:
            ws, we = float(w["start"]), float(w["end"])
            if by_midpoint:
                if not seg.start <= (ws + we) / 2.0 < seg.end:
                    continue
                ws, we = max(ws, seg.start), min(we, seg.end)
            elif not (seg.start <= ws and we <= seg.end):
                continue
            nw = dict(w)
            nw["start"] = round(ws - seg.start + offset, 3)
            nw["end"] = round(we - seg.start + offset, 3)
            nw["segment_role"] = seg.role
            out.append(nw)
        offset += seg.end - seg.start
    return out


# -- AP7: Splice-Zählung, Debattenregel, Ausgabetimeline ----------------------------------------------

# Kurzer Einwurf des Gegenübers, dessen Entfernung keinen Satz neu verknüpft („Okay.“, „Genau.“).
BACKCHANNEL_MAX_WORDS = 3  # „Ja, ja, klar.“
_BACKCHANNEL_TOKENS = frozenset(dach_nlp.BACKCHANNEL) | frozenset(dach_nlp.HARD_FILLERS) | {"aha", "ah", "oh"}
_CLOSERS = "\"'»«“”‘’)]}"


def _ends_sentence(text: str) -> bool:
    """Satzzeichen am Wort (ohne Abkürzung, Ordinalzahl, Auslassungspunkte); Pausen zählen hier nicht."""
    t = str(text).strip().rstrip(_CLOSERS)
    if t.endswith(("…", "...")):
        return False
    if t.endswith(("!", "?")):
        return True
    return t.endswith(".") and not dach_nlp.is_ordinal(t) and not dach_nlp.is_abbreviation(t, "v2")


def _word_ids_between(words: list[dict], t0: float, t1: float) -> list[int]:
    """Indizes der Wörter, deren Mitte in ``[t0, t1]`` liegt."""
    return [i for i, w in enumerate(words) if t0 <= (float(w["start"]) + float(w["end"])) / 2.0 <= t1]


def _is_backchannel_run(words: list[dict], ids: list[int]) -> bool:
    if not ids or len(ids) > BACKCHANNEL_MAX_WORDS:
        return False
    if any(dach_nlp.core_token(str(words[i]["text"])) not in _BACKCHANNEL_TOKENS for i in ids):
        return False
    spk = {words[i].get("speaker") for i in ids}
    before = words[ids[0] - 1].get("speaker") if ids[0] > 0 else None
    return len(spk) == 1 and before is not None and before not in spk


def splice_kinds(comp: Composition, words: list[dict], forced_semantic: set[int] | None = None) -> list[str]:
    """Art jeder Naht zwischen aufeinanderfolgenden Body-Segmenten in Abspielreihenfolge.

    ``semantic``: die Naht verbindet nicht benachbarte Sätze, das heißt zwischen den Segmenten fällt
    ein Satzende weg, der Body ist umgestellt oder ein entferntes Wort steht in ``forced_semantic``
    (redaktionell weggelassen, ``keep_decisions`` in ``trim_plan.build_composition``; immer semantisch).
    ``local``: innerhalb einer Passage wurde nur eine Pause gekürzt oder etwas ohne Inhalt entfernt;
    eine Naht über reine Füll- oder Rückmeldewörter („Äh.“, „Okay.“) ist immer lokal."""
    body = [s for s in comp.segments if s.role != "teaser"]
    kinds: list[str] = []
    for prev, nxt in zip(body, body[1:]):
        if nxt.start < prev.end:
            kinds.append("semantic")
            continue
        between = [i for i, w in enumerate(words) if prev.end < (float(w["start"]) + float(w["end"])) / 2.0 < nxt.start]
        if forced_semantic and any(i in forced_semantic for i in between):
            kinds.append("semantic")
            continue
        if all(dach_nlp.core_token(str(words[i]["text"])) in _BACKCHANNEL_TOKENS for i in between):
            kinds.append("local")
            continue
        ends = any(_ends_sentence(str(words[i]["text"])) for i in between)
        kinds.append("semantic" if ends and not _is_backchannel_run(words, between) else "local")
    return kinds


def is_debate(words: list[dict], first: int, last: int) -> bool:
    """Debatte im Body (Wörter ``first`` bis ``last``, inklusiv): mindestens zwei Sprecher mit eigener
    Aussage und mindestens zwei Wechsel zwischen ihren Redebeiträgen. Kurze Einwürfe
    (``_is_backchannel_run``) zählen nicht als Beitrag. Wer nur fragt, debattiert nicht: Frage, Antwort
    und Nachfrage sind ein Interview, keine Debatte."""
    runs: list[tuple[object, list[int]]] = []
    for i in range(max(0, first), min(len(words) - 1, last) + 1):
        spk = words[i].get("speaker")
        if runs and runs[-1][0] == spk:
            runs[-1][1].append(i)
        else:
            runs.append((spk, [i]))
    turns = [(spk, ids) for spk, ids in runs if spk is not None and not _is_backchannel_run(words, ids)]
    merged = [s for k, (s, _ids) in enumerate(turns) if k == 0 or s != turns[k - 1][0]]
    stating = {
        spk for spk, ids in turns
        if not str(words[ids[-1]]["text"]).strip().rstrip(_CLOSERS).endswith("?")
    }  # fmt: skip
    return len(stating) >= 2 and len(merged) - 1 >= 2


def output_timeline(comp: Composition) -> list[dict]:
    """Herkunft und Ziel je Segment, deterministisch: ``source_in``, ``source_out`` auf der Quelle,
    ``output_in``, ``output_out`` auf dem Clip (Master-Prompt Abschnitt 20 und 21). Die Ausgabezeit
    wird aus gerundeten Segmentlängen aufsummiert, damit gleiche Eingaben gleiche Zahlen ergeben."""
    out, t = [], 0.0
    for k, seg in enumerate(comp.segments):
        source_in, source_out = round(float(seg.start), 3), round(float(seg.end), 3)
        output_in = round(t, 3)
        t = round(t + (source_out - source_in), 3)
        out.append({
            "segment_index": k, "role": seg.role, "source_in": source_in, "source_out": source_out,
            "output_in": output_in, "output_out": t,
        })  # fmt: skip
    return out


__all__ = [
    "BACKCHANNEL_MAX_WORDS",
    "MAX_TEASER_S",
    "MICRO_FADE_S",
    "Composition",
    "Segment",
    "from_keep_ranges",
    "is_debate",
    "output_timeline",
    "remap_words",
    "splice_kinds",
    "with_teaser",
]
