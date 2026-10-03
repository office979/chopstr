"""Eingefrorene Kopie von ``dach_nlp.is_sentence_end`` vor AP2 (Stand 35de380), Maßstab für Regel v1.

Nicht ändern. Weicht ``dach_nlp.sentence_end_kind(..., "v1")`` davon ab, hat sich Fassung 1 verändert.
Die Abkürzungsliste ist mit eingefroren, damit eine spätere Ergänzung der Liste hier auffällt.
"""

from __future__ import annotations

import re

ABBREVIATIONS_35DE380 = {
    "z", "b", "z.b", "zb", "bzw", "ca", "usw", "etc", "vgl", "dr", "prof", "nr", "st", "mio", "mrd", "tsd",
    "u", "a", "d", "h", "u.a", "d.h", "s", "o", "ä", "o.ä", "evtl", "ggf", "inkl", "exkl", "max", "min",
    "mind", "sog", "str", "tel", "hr", "fr", "ing", "mag", "dipl", "med", "jur", "phil", "abs", "art",
    "bsp", "geb", "gest", "jh", "jhd", "kap", "lt", "nachm", "vorm", "ugs", "urspr", "zzgl", "zw",
    "allg", "bes", "bzgl", "ehem", "einschl", "entspr", "erg", "gegr", "hrsg", "i", "e", "v", "chr",
    "mwst", "ust", "gmbh", "ag", "kg", "co", "sept", "okt", "nov", "dez", "jan", "feb", "mär", "apr",
    "jun", "jul", "aug", "mo", "di", "mi", "do", "sa", "so",
}  # fmt: skip
_TRAILING = "\"'»«“”‘’)]}…"
_ORDINAL = re.compile(r"^\d{1,3}\.$")


def _strip_trailing(text: str) -> str:
    return text.rstrip(_TRAILING)


def is_abbreviation(text: str) -> bool:
    t = _strip_trailing(text)
    if not t.endswith("."):
        return False
    base = t[:-1].lower().replace(" ", "")
    if not base:
        return False
    if base in ABBREVIATIONS_35DE380:
        return True
    parts = [p for p in base.split(".") if p]
    return bool(parts) and all(p in ABBREVIATIONS_35DE380 or len(p) == 1 for p in parts)


def is_ordinal(text: str) -> bool:
    return bool(_ORDINAL.match(_strip_trailing(text)))


def is_sentence_end(words: list[dict], i: int, min_pause_s: float = 0.7) -> bool:
    w = words[i]
    text = str(w.get("text", "")).strip()
    nxt = words[i + 1] if i + 1 < len(words) else None
    if nxt is None:
        return True
    pause = float(nxt.get("start", 0.0)) - float(w.get("end", 0.0))
    long_pause = pause >= min_pause_s
    speaker_change = nxt.get("speaker") is not None and nxt.get("speaker") != w.get("speaker")
    stripped = _strip_trailing(text)
    if stripped.endswith(("!", "?", "…")):
        return True
    if stripped.endswith("."):
        nxt_text = str(nxt.get("text", "")).strip()
        if is_ordinal(stripped) or nxt_text[:1].isdigit() or is_abbreviation(stripped):
            return long_pause or speaker_change
        return True
    return long_pause or speaker_change
