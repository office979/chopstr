"""Sinntreue-Wächter (regelbasiert, läuft nach jedem Schnitt, Trim oder Füller-Cut).

Erkennt, wenn ein Schnitt die Aussage verändert:
- entfernte Verneinungen („nicht", „kein", „nie")
- entfernte Einschränkungen („nur", „außer", „bei uns", „in unserem Fall", „meistens")
- Clip endet direkt vor „aber"/„allerdings" (Relativierung abgeschnitten)
- zusammengesetzte Aussagen (Segmente aus weit auseinanderliegenden Stellen)
Ergebnis: Warnungen für die UI. Kein Auto-Fix, der Mensch entscheidet.
"""

from __future__ import annotations

import re

from .dach_nlp import NEGATIONS

QUALIFIERS = {
    "nur", "außer", "ausser", "meistens", "oft", "manchmal", "teilweise", "eventuell", "vielleicht",
    "bei uns", "in unserem fall", "für uns", "in der regel", "unter umständen", "grundsätzlich",
    "eigentlich", "zumindest", "höchstens", "mindestens",
}  # fmt: skip
CONTRAST_STARTS = ("aber", "allerdings", "jedoch", "wobei", "trotzdem", "andererseits", "außer")
MAX_JOIN_GAP_S = 20.0  # Segmente mit größerem Abstand im Original = „zusammengesetzte Aussage"


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-zäöüß]+", text.lower())


def check_cut(original_words: list[dict], kept_ranges: list[tuple[int, int]]) -> list[dict]:
    """original_words: Wortliste des Kandidaten; kept_ranges: behaltene Wortindex-Bereiche (inklusiv)."""
    warnings = []
    kept: set[int] = set()
    for a, b in kept_ranges:
        kept.update(range(a, b + 1))
    removed = [w for i, w in enumerate(original_words) if i not in kept]
    removed_text = " ".join(str(w["text"]) for w in removed).lower()
    removed_tokens = set(_tokens(removed_text))

    if removed_tokens & NEGATIONS:
        warnings.append({"type": "negation_removed", "severity": "high", "detail": sorted(removed_tokens & NEGATIONS)})
    hits = [q for q in sorted(QUALIFIERS) if f" {q} " in f" {removed_text} "]
    if hits:
        warnings.append({"type": "qualifier_removed", "severity": "medium", "detail": hits})

    last_kept = max(kept) if kept else -1
    tail = " ".join(str(w["text"]) for w in original_words[last_kept + 1 : last_kept + 4]).lower()
    if tail.startswith(CONTRAST_STARTS):
        warnings.append({"type": "ends_before_contrast", "severity": "high", "detail": tail})

    for (_a1, b1), (a2, _b2) in zip(kept_ranges, kept_ranges[1:]):
        gap = float(original_words[a2]["start"]) - float(original_words[b1]["end"])
        if gap > MAX_JOIN_GAP_S:
            warnings.append({"type": "joined_statements", "severity": "high", "detail": f"{gap:.0f}s Abstand im Original"})
    return warnings


SUPERLATIVES = ("beste", "einzige", "garantiert", "immer", "100 %", "100%", "sofort", "heilt", "nie wieder", "jeder")


def hook_claim_check(hook_text: str, clip_text: str) -> list[str]:
    """Hook darf keine Zahlen/Superlative enthalten, die im Clip nicht vorkommen (UWG: Irreführung)."""
    issues = []
    for num in re.findall(r"\d[\d.,]*", hook_text):
        if num not in clip_text:
            issues.append(f"Zahl '{num}' steht nicht im Clip")
    low_hook, low_clip = hook_text.lower(), clip_text.lower()
    for sup in SUPERLATIVES:
        if sup in low_hook and sup not in low_clip:
            issues.append(f"Zuspitzung '{sup}' nicht durch Clip gedeckt")
    return issues


__all__ = ["CONTRAST_STARTS", "MAX_JOIN_GAP_S", "QUALIFIERS", "SUPERLATIVES", "check_cut", "hook_claim_check"]
