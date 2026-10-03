"""Wörter zu Sätzen zu Kandidatenfenstern zu Kapiteln.

Harte Regel: Clips beginnen und enden NUR an Satzgrenzen (Pflichtkriterium der Story-Rubrik).
Kandidaten werden als Satz-Spannen erzeugt, nicht als Sekunden-Fenster. Satzgrenzen kommen aus
``dach_nlp.is_sentence_end`` (Abkürzungen, Ordinalzahlen, Pausen, Sprecherwechsel).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from . import dach_nlp

MIN_PAUSE_AS_BOUNDARY = 0.7  # lange Pause zählt auch ohne Satzzeichen als Grenze


@dataclass
class Sentence:
    idx: int
    text: str
    start: float
    end: float
    speaker: str | None
    word_range: tuple[int, int]

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        d = asdict(self)
        d["word_range"] = list(self.word_range)
        return d


@dataclass
class Candidate:
    first_sent: int
    last_sent: int
    start: float
    end: float
    text: str
    speakers: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start


def sentences_from_words(
    words: list[dict],
    min_pause_s: float = MIN_PAUSE_AS_BOUNDARY,
    rule: str = "v1",
    max_s: float | None = None,
    max_words: int | None = None,
) -> list[Sentence]:
    """Sätze nach der Satzende-Regel ``rule`` (``v1`` wie vor AP2, ``v2`` siehe ``dach_nlp.sentence_end_kind``)."""
    sents: list[Sentence] = []
    buf_start = 0
    kinds = dach_nlp.sentence_end_kinds(words, rule, min_pause_s, max_s, max_words)
    for i in range(len(words)):
        if kinds[i] != "none":
            chunk = words[buf_start : i + 1]
            sents.append(
                Sentence(
                    idx=len(sents),
                    text=" ".join(str(x["text"]) for x in chunk),
                    start=float(chunk[0]["start"]),
                    end=float(chunk[-1]["end"]),
                    speaker=chunk[0].get("speaker"),
                    word_range=(buf_start, i),
                )
            )
            buf_start = i + 1
    return sents


def has_sentence_idx(words: list[dict]) -> bool:
    """Tragen alle Wörter eine ``sentence_idx`` (geschrieben von ``dach_nlp.annotate``)?"""
    return bool(words) and all(isinstance(w.get("sentence_idx"), int) and not isinstance(w.get("sentence_idx"), bool) for w in words)


def sentences_from_annotated(words: list[dict]) -> list[Sentence]:
    """Sätze aus der vorhandenen ``sentence_idx`` (Spiegel von ``sentencesFromWords`` im Web).

    Aufeinanderfolgende Wörter mit gleicher ``sentence_idx`` bilden einen Satz; ``idx`` zählt fortlaufend
    ab 0, wie bei ``sentences_from_words``. Damit zerlegen Worker und Web ein bestehendes Transkript
    gleich, egal nach welcher Regel es annotiert wurde. Ohne ``sentence_idx`` an jedem Wort: leere Liste,
    der Aufrufer fällt auf ``sentences_from_words`` zurück."""
    if not has_sentence_idx(words):
        return []
    sents: list[Sentence] = []
    buf_start = 0
    for i in range(len(words)):
        if i + 1 < len(words) and words[i + 1]["sentence_idx"] == words[i]["sentence_idx"]:
            continue
        chunk = words[buf_start : i + 1]
        sents.append(
            Sentence(
                idx=len(sents),
                text=" ".join(str(x["text"]) for x in chunk),
                start=float(chunk[0]["start"]),
                end=float(chunk[-1]["end"]),
                speaker=chunk[0].get("speaker"),
                word_range=(buf_start, i),
            )
        )
        buf_start = i + 1
    return sents


def candidate_windows(sents: list[Sentence], min_len=12.0, max_len=90.0, stride=2) -> list[Candidate]:
    """Alle Satzspannen zwischen min_len und max_len Sekunden.
    stride>1 dünnt Startpunkte aus, damit ein 90-Min-Podcast nicht zehntausende Kandidaten erzeugt."""
    cands: list[Candidate] = []
    for a in range(0, len(sents), max(1, stride)):
        for b in range(a, len(sents)):
            dur = sents[b].end - sents[a].start
            if dur > max_len:
                break
            if dur >= min_len:
                span = sents[a : b + 1]
                cands.append(
                    Candidate(
                        first_sent=a,
                        last_sent=b,
                        start=span[0].start,
                        end=span[-1].end,
                        text=" ".join(s.text for s in span),
                        speakers=sorted({s.speaker for s in span if s.speaker}),
                    )
                )
    return cands


def chapterize(sents: list[Sentence], chunk_seconds=240.0, overlap_s: float = 0.0) -> list[list[Sentence]]:
    """Grobe Kapitel (~4 Min) für den ersten LLM-Durchlauf.

    ``overlap_s`` (Fassung 2: ``search.chapter_overlap_s``, AP5): jedes folgende Kapitel beginnt zusätzlich
    mit den Sätzen des vorigen, die in dessen letzten ``overlap_s`` Sekunden beginnen, damit ein Moment an
    der Kapitelgrenze nicht zerfällt. Ein Kapitel wiederholt nie das ganze vorige. Mit 0 (Standard) wie
    vor AP5."""
    chapters: list[list[Sentence]] = []
    cur: list[Sentence] = []
    t0: float | None = None
    fresh = 0  # Sätze im aktuellen Kapitel, die nicht aus der Überlappung stammen
    for s in sents:
        t0 = s.start if t0 is None else t0
        cur.append(s)
        fresh += 1
        if s.end - t0 >= chunk_seconds:
            chapters.append(cur)
            carry = [x for x in cur if overlap_s > 0 and x.start >= s.end - overlap_s]
            if len(carry) == len(cur):
                carry = carry[1:]
            cur, fresh = list(carry), 0
            t0 = carry[0].start if carry else None
    if cur and fresh:
        chapters.append(cur)
    return chapters


def numbered(sents: list[Sentence]) -> str:
    """„[idx] (Sprecher) Text" pro Zeile, wie es die Prompts erwarten."""
    return "\n".join(f"[{s.idx}] ({s.speaker or '?'}) {s.text}" for s in sents)


__all__ = [
    "MIN_PAUSE_AS_BOUNDARY",
    "Candidate",
    "Sentence",
    "candidate_windows",
    "chapterize",
    "has_sentence_idx",
    "numbered",
    "sentences_from_annotated",
    "sentences_from_words",
]
