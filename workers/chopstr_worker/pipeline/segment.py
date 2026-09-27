"""Wörter zu Sätzen zu Kandidatenfenstern zu Kapiteln.

Harte Regel: Clips beginnen und enden NUR an Satzgrenzen (Pflichtkriterium der Story-Rubrik).
Kandidaten werden als Satz-Spannen erzeugt, nicht als Sekunden-Fenster. Satzgrenzen kommen aus
``dach_nlp.is_sentence_end`` (Abkürzungen, Ordinalzahlen, Pausen, Sprecherwechsel).

Pausen stammen aus den ASR-Wortzeiten. Wird zusätzlich eine ``silence.SilenceMap`` übergeben,
zählt die im Ton gemessene Stille, wo sie länger ist — ASR-Wortzeiten verschlucken Pausen
gelegentlich (Beleg in ``silence.py``). ``snap_candidates`` zieht Clipgrenzen danach auf einen
Punkt, an dem wirklich Stille ist.
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
    silence=None,
) -> list[Sentence]:
    """Wörter zu Sätzen. ``silence`` ist eine optionale ``silence.SilenceMap``.

    Mit ``silence`` zählt an jeder Wortgrenze die gemessene Stille, falls sie länger ist
    als die Lücke in den Wortzeiten — siehe ``pipeline/silence.py``. Ohne ``silence``
    unverändertes Verhalten.
    """
    sents: list[Sentence] = []
    buf_start = 0
    for i in range(len(words)):
        if dach_nlp.is_sentence_end(words, i, min_pause_s, silence):
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


def silence_changes_boundaries(words: list[dict], silence, min_pause_s: float = MIN_PAUSE_AS_BOUNDARY) -> bool:
    """Aendert die Stille-Karte die Satzgrenzen dieser Wortliste ueberhaupt?

    Gebraucht fuer den Idempotenz-Key der Kandidatensuche. Kaeme die Karte dort bedingungslos
    hinein, braeche sie jeden bestehenden Zwischenspeicher und loeste einen neuen LLM-Lauf samt
    Kosten aus, auch wenn sich am Ergebnis nichts aendert.

    Gemessen am 27.09.2026: bei faster-whisper mit ``vad_filter=True`` waren die Grenzen mit und
    ohne Karte identisch - die Pausen stehen dort bereits in den Wortzeiten. Bei whisper.cpp
    fehlten zwei von vier Pausen, dort aendert die Karte die Grenzen sehr wohl.

    Kostet zwei Durchlaeufe durch die Wortliste, kein ffmpeg, kein LLM."""
    if silence is None or not len(silence):
        return False
    ohne = dach_nlp.sentence_boundaries(words, min_pause_s)
    mit = dach_nlp.sentence_boundaries(words, min_pause_s, silence)
    return ohne != mit


def snap_candidates(cands: list[Candidate], silence, max_shift: float = 0.40) -> list[Candidate]:
    """Zieht Anfang und Ende jedes Kandidaten auf einen Punkt, an dem wirklich Stille ist.

    Transkriptzeiten liegen oft ein paar Hundertstel neben dem hörbaren Wortrand. Schneidet
    man exakt dort, wird der Wortanlauf angeschnitten oder der Ausklang abgeschnitten.
    Gemessen am 26.09.2026 lagen zwei von sieben geplanten Grenzen im Wort — nach dem
    Verschieben um 60 bis 130 ms waren alle beidseitig unter -45 dB.

    Findet sich in Reichweite keine Pause, bleibt die Grenze wie sie war. Lieber die
    ursprüngliche Satzgrenze als ein Schnitt an der falschen Stelle.

    Laufzeit: zwei bisect-Suchen je Kandidat, kein ffmpeg-Aufruf.
    """
    if silence is None or not len(silence):
        return cands
    out: list[Candidate] = []
    for c in cands:
        s = silence.snap(c.start, max_shift)
        e = silence.snap(c.end, max_shift)
        neu_start = c.start if s is None else s
        neu_ende = c.end if e is None else e
        if neu_ende - neu_start < 1.0:  # nie zu einem Nichts zusammenziehen
            out.append(c)
            continue
        out.append(
            Candidate(
                first_sent=c.first_sent,
                last_sent=c.last_sent,
                start=round(neu_start, 3),
                end=round(neu_ende, 3),
                text=c.text,
                speakers=c.speakers,
            )
        )
    return out


def chapterize(sents: list[Sentence], chunk_seconds=240.0) -> list[list[Sentence]]:
    """Grobe Kapitel (~4 Min) für den ersten LLM-Durchlauf."""
    chapters: list[list[Sentence]] = []
    cur: list[Sentence] = []
    t0: float | None = None
    for s in sents:
        t0 = s.start if t0 is None else t0
        cur.append(s)
        if s.end - t0 >= chunk_seconds:
            chapters.append(cur)
            cur, t0 = [], None
    if cur:
        chapters.append(cur)
    return chapters


def numbered(sents: list[Sentence]) -> str:
    """„[idx] (Sprecher) Text" pro Zeile, wie es die Prompts erwarten."""
    return "\n".join(f"[{s.idx}] ({s.speaker or '?'}) {s.text}" for s in sents)


__all__ = ["MIN_PAUSE_AS_BOUNDARY", "Candidate", "Sentence", "candidate_windows", "chapterize", "numbered",
           "sentences_from_words", "silence_changes_boundaries", "snap_candidates"]
