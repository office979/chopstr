"""Wörter zu Sätzen zu Kandidatenfenstern zu Kapiteln.

Harte Regel: Clips beginnen und enden NUR an Satzgrenzen (Pflichtkriterium der Story-Rubrik).
Kandidaten werden als Satz-Spannen erzeugt, nicht als Sekunden-Fenster. Satzgrenzen kommen aus
``dach_nlp.is_sentence_end`` (Abkürzungen, Ordinalzahlen, Pausen, Sprecherwechsel).
"""

from __future__ import annotations

import math
import re
from collections import Counter
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
    silence=None,
) -> list[Sentence]:
    """Sätze nach der Satzende-Regel ``rule`` (``v1`` wie vor AP2, ``v2`` siehe ``dach_nlp.sentence_end_kind``).

    ``silence`` ist eine optionale ``silence.SilenceMap``. Sie wirkt nur darauf, ob an einer
    Wortgrenze ueberhaupt eine Pause vorliegt - verschluckt das ASR eine, entsteht sonst keine
    Satzgrenze und ein Clip beginnt mitten im Satz. Ohne ``silence`` unveraendertes Verhalten."""
    sents: list[Sentence] = []
    buf_start = 0
    kinds = dach_nlp.sentence_end_kinds(words, rule, min_pause_s, max_s, max_words, silence)
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
    mit = dach_nlp.sentence_boundaries(words, min_pause_s, silence=silence)
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


# -- Kapitel an Themenwechseln (Launch Phase 2, Schalter implementation.chapters.topic_shift) -------------
# TextTiling-artig (Hearst 1997) ohne Embeddings und ohne neue Abhängigkeit: Wortüberlappung benachbarter
# Zeitfenster plus Sprecherwechsel. Die Stammformen sind eine grobe Endungskürzung (wie story_graph._stem),
# kein Lemmatisierer; Funktionswörter fallen über eine feste Liste heraus. Alles deterministisch.

TOPIC_STOPWORDS = frozenset({
    "aber", "alle", "allem", "allen", "aller", "alles", "also", "andere", "anderen", "auch", "bevor", "beim", "bereits",
    "bist", "bitte", "damit", "dann", "darauf", "daran", "darum", "dass", "dein", "deine", "denn", "deren", "dessen",
    "dich", "diese", "diesem", "diesen", "dieser", "dieses", "doch", "dort", "durch", "eben", "eher", "eigentlich",
    "eine", "einem", "einen", "einer", "eines", "einfach", "einmal", "etwa", "etwas", "euch", "euer", "ganz", "gerade",
    "gibt", "haben", "habe", "halt", "hast", "hatte", "hatten", "heute", "hier", "ihre", "ihrem", "ihren", "ihrer",
    "immer", "jede", "jedem", "jeden", "jeder", "jedes", "jetzt", "kann", "kannst", "keine", "keinen", "können", "könnte",
    "machen", "macht", "mache", "mein", "meine", "meinem", "meinen", "meiner", "mich", "mehr", "muss", "müssen", "nach",
    "natürlich", "nicht", "nichts", "noch", "oder", "ohne", "schon", "sehr", "sein", "seine", "seinem", "seinen",
    "seiner", "selbst", "sich", "sind", "sollen", "sollte", "sondern", "über", "unser", "unsere", "unserem", "unseren",
    "unserer", "viel", "viele", "vielleicht", "voll", "vom", "vorher", "wäre", "waren", "warum", "weil", "welche",
    "wenn", "werden", "wieder", "wird", "wirklich", "wollen", "wurde", "wurden", "zwar", "zwischen", "genau", "okay",
    "sagen", "sagt", "sage", "gesagt", "ehrlich", "glaube", "denke", "finde", "wissen", "weiß", "irgendwie", "dabei",
})  # fmt: skip
_TOPIC_SUFFIXES = ("ungen", "heiten", "keiten", "lich", "isch", "ung", "heit", "keit", "en", "er", "es", "em", "e", "n", "s")


def _topic_stem(tok: str) -> str:
    for suf in _TOPIC_SUFFIXES:
        if tok.endswith(suf) and len(tok) - len(suf) >= 4:
            return tok[: -len(suf)]
    return tok


def topic_terms(text: str) -> Counter:
    """Inhaltswörter eines Textes als Zähler: klein geschrieben, länger als drei Zeichen, ohne Funktionswörter,
    mit gekürzter Endung. Grundlage der Wortüberlappung in ``topic_boundary_scores``."""
    return Counter(_topic_stem(t) for t in re.findall(r"[a-zäöüß]+", text.lower()) if len(t) > 3 and t not in TOPIC_STOPWORDS)


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def _turn_density(sents: list[Sentence], lo: int, hi: int) -> float:
    """Anteil der Satzübergänge mit Sprecherwechsel zwischen ``lo`` und ``hi`` (einschließlich)."""
    pairs = [(sents[k].speaker, sents[k + 1].speaker) for k in range(lo, hi)]
    return sum(1 for a, b in pairs if a and b and a != b) / len(pairs) if pairs else 0.0


def topic_boundary_scores(sents: list[Sentence], window_s: float = 60.0, speaker_weight: float = 0.25) -> list[dict]:
    """Je Lücke zwischen Satz ``g`` und ``g + 1`` eine Bewertung als Themengrenze, 0 bis 1.

    Wortüberlappung: Kosinus der Inhaltswörter (``topic_terms``) der Sätze im Fenster ``window_s`` vor und nach
    der Lücke. Daraus die Tiefe wie bei TextTiling: der Anstieg bis zum nächsten Gipfel links und rechts,
    bezogen auf die Summe der Gipfel (``lexical`` 1 heißt: an der Lücke keine Überlappung, beidseits viel).
    Sprecher: Wechsel genau an der Lücke (halb) und Unterschied der Wechseldichte beider Fenster (halb).
    ``score`` = (1 minus ``speaker_weight``) mal ``lexical`` plus ``speaker_weight`` mal ``speaker``."""
    n = len(sents)
    if n < 2:
        return []
    terms = [topic_terms(s.text) for s in sents]
    gaps: list[dict] = []
    lo, hi = 0, 1
    for g in range(n - 1):
        t = sents[g + 1].start
        while lo < g and sents[lo].start < t - window_s:
            lo += 1
        hi = max(hi, g + 1)
        while hi + 1 < n and sents[hi + 1].start < t + window_s:
            hi += 1
        left: Counter = Counter()
        for k in range(lo, g + 1):
            left.update(terms[k])
        right: Counter = Counter()
        for k in range(g + 1, hi + 1):
            right.update(terms[k])
        turn = 1.0 if sents[g].speaker and sents[g + 1].speaker and sents[g].speaker != sents[g + 1].speaker else 0.0
        density = abs(_turn_density(sents, lo, g) - _turn_density(sents, g + 1, hi))
        gaps.append({
            "after_sent": sents[g].idx, "time_s": round(t, 2), "cohesion": _cosine(left, right),
            "speaker": 0.5 * turn + 0.5 * min(1.0, density),
        })  # fmt: skip
    cohesion = [x["cohesion"] for x in gaps]
    for g, gap in enumerate(gaps):
        c = cohesion[g]
        lpeak = c
        for k in range(g - 1, -1, -1):
            if cohesion[k] < lpeak:
                break
            lpeak = cohesion[k]
        rpeak = c
        for k in range(g + 1, len(cohesion)):
            if cohesion[k] < rpeak:
                break
            rpeak = cohesion[k]
        peaks = lpeak + rpeak
        lexical = ((lpeak - c) + (rpeak - c)) / peaks if peaks > 0 else 0.0
        gap["lexical"] = round(lexical, 4)
        gap["cohesion"] = round(c, 4)
        gap["speaker"] = round(gap["speaker"], 4)
        gap["score"] = round((1.0 - speaker_weight) * lexical + speaker_weight * gap["speaker"], 4)
    return gaps


def chapterize_topic_shift(
    sents: list[Sentence],
    min_s: float = 120.0,
    max_s: float = 300.0,
    overlap_s: float = 0.0,
    window_s: float = 60.0,
    min_boundary_score: float = 0.5,
    speaker_weight: float = 0.25,
) -> tuple[list[list[Sentence]], list[dict]]:
    """Kapitel an Themenwechseln statt fester 240 s (Launch Phase 2, Master-Prompt Schwachstelle 4).

    Ab dem Beginn des Kapitels (ohne Überlappung gemessen) kommt jede Lücke in Frage, die mindestens ``min_s``
    danach liegt, höchstens ``max_s`` danach und so, dass der Rest mindestens ``min_s`` lang bleibt. Die Lücke
    mit der höchsten Bewertung (``topic_boundary_scores``; bei Gleichstand die spätere) wird Grenze, wenn sie
    ``min_boundary_score`` erreicht (``boundary`` ``topic_shift``). Sonst endet das Kapitel nur, wenn der Rest
    länger als ``max_s`` ist, und zwar an der besten Lücke (``max_length``). Ein kurzer Einschub erzeugt so nie
    ein eigenes Kapitel, und ein durchgehendes Thema bis ``max_s`` bleibt ganz.

    ``overlap_s`` wie in ``chapterize``: jedes folgende Kapitel beginnt zusätzlich mit den Sätzen des vorigen,
    die in dessen letzten ``overlap_s`` Sekunden beginnen. Rückgabe: Kapitel und je Kapitel ``{first_sent,
    last_sent, start_s, end_s, boundary, topic_boundary_score}``; ``topic_boundary_score`` ist die Bewertung der
    Grenze am Kapitelanfang (beim ersten Kapitel ``None``)."""
    if not sents:
        return [], []
    gaps = topic_boundary_scores(sents, window_s, speaker_weight)
    pos = {s.idx: n for n, s in enumerate(sents)}
    chapters: list[list[Sentence]] = []
    meta: list[dict] = []
    start = 0  # erster neuer Satz des aktuellen Kapitels
    boundary, score = "start", None
    end_t = sents[-1].end
    while True:
        t0 = sents[start].start
        window = [x for x in gaps[start:] if t0 + min_s <= x["time_s"] <= t0 + max_s and x["time_s"] <= end_t - min_s]
        best = max(window, key=lambda x: (x["score"], x["time_s"]), default=None)
        if best is not None and best["score"] >= min_boundary_score:
            cut, kind = pos[best["after_sent"]], "topic_shift"
        elif end_t - t0 > max_s:
            if best is None:  # kein Satzende im Fenster (sehr lange Sätze): das erste nach min_s
                best = next((x for x in gaps[start:] if x["time_s"] >= t0 + min_s), None)
            if best is None:
                cut, kind = len(sents) - 1, ""
            else:
                cut, kind = pos[best["after_sent"]], "max_length"
        else:
            cut, kind = len(sents) - 1, ""
        carry = [x for x in (chapters[-1] if chapters else []) if overlap_s > 0 and x.start >= chapters[-1][-1].end - overlap_s]
        if chapters and len(carry) == len(chapters[-1]):
            carry = carry[1:]
        chapter = [*carry, *sents[start : cut + 1]]
        chapters.append(chapter)
        meta.append({
            "first_sent": chapter[0].idx, "last_sent": chapter[-1].idx, "start_s": round(chapter[0].start, 2),
            "end_s": round(chapter[-1].end, 2), "boundary": boundary, "topic_boundary_score": score,
        })  # fmt: skip
        if not kind or cut >= len(sents) - 1:
            break
        boundary, score = kind, best["score"] if best is not None else None
        start = cut + 1
    return chapters, meta


def numbered(sents: list[Sentence]) -> str:
    """„[idx] (Sprecher) Text" pro Zeile, wie es die Prompts erwarten."""
    return "\n".join(f"[{s.idx}] ({s.speaker or '?'}) {s.text}" for s in sents)


__all__ = [
    "MIN_PAUSE_AS_BOUNDARY",
    "Candidate",
    "Sentence",
    "candidate_windows",
    "chapterize",
    "chapterize_topic_shift",
    "has_sentence_idx",
    "numbered",
    "sentences_from_annotated",
    "sentences_from_words",
    "silence_changes_boundaries",
    "snap_candidates",
    "topic_boundary_scores",
    "topic_terms",
]
