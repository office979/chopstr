"""Compose: ein Clip ist eine LISTE von Quell-Segmenten mit eigener Abspielreihenfolge.

Ermöglicht Füller-Schnitte (viele kleine Segmente) und Cold Open (stärkster Satz vorne als Teaser).

DACH-Trust-Regeln:
- Teaser muss vom selben Sprecher stammen und als Teaser markiert werden.
- Teaser-Satz kommt im Clip-Verlauf noch einmal vollständig vor.
- Segmente aus weit auseinanderliegenden Stellen ohne Teaser-Markierung: Sinntreue-Warnung (fidelity.py).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

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

    def validate(self, words: list[dict]) -> list[str]:
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


def remap_words(words: list[dict], comp: Composition) -> list[dict]:
    """Wortzeiten von Quell- auf Ausgabe-Timeline (für Captions). Wörter können doppelt vorkommen
    (Teaser + Body), deshalb wird pro Segment kopiert."""
    out, offset = [], 0.0
    for seg in comp.segments:
        for w in words:
            if seg.start <= float(w["start"]) and float(w["end"]) <= seg.end:
                nw = dict(w)
                nw["start"] = round(float(w["start"]) - seg.start + offset, 3)
                nw["end"] = round(float(w["end"]) - seg.start + offset, 3)
                nw["segment_role"] = seg.role
                out.append(nw)
        offset += seg.end - seg.start
    return out


__all__ = ["MAX_TEASER_S", "MICRO_FADE_S", "Composition", "Segment", "from_keep_ranges", "remap_words", "with_teaser"]
