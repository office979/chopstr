"""dach_nlp: der deutsche Sprach-Moat (aus dem Gerüst, erweitert).

1) Satzgrenzen mit Abkürzungsliste (z. B., Dr., usw., bzw., ca., Nr., Mio. ...), Ordinalzahlen
   („3. Platz" ist keine Grenze) und Dezimalzahlen.
2) Verbklammer-Schutz (spaCy, optional): kein Schnitt zwischen finitem Hilfs-/Modalverb und
   Vollverb/Partikel. Fehlt spaCy oder das Modell, liefert ``forbidden_cut_ranges`` ``[]`` und
   setzt ``verb_bracket_available = False``.
3) Verbotene Clip-Enden: letzter Satz endet auf Open-Loop-Konnektor („aber", „deshalb", „nämlich").
4) Füllwörter: äh/ähm raus; Modalpartikeln (halt, eigentlich, mal, ja, doch) BEHALTEN. Nur Vorschläge.
5) Negations-Flags pro Wort (Caption-QA, Sinntreue, „nicht" nie allein in neue Zeile).
6) Dezimalkomma für Zahlen in Captions („2.4" wird „2,4").
7) Dialekterkennung (Phase 5c, Beta): ``detect_dialect`` zählt Lexikon-Marker für Schweizerdeutsch (CH) und
   Österreichisch (AT) und liefert ``{variant, confidence, markers}``. Schwellen: mindestens
   ``DIALECT_MIN_HITS`` gewichtete Treffer und ein Anteil von ``DIALECT_MIN_RATIO`` an den Wörtern; die
   Sicherheit steigt linear bis ``DIALECT_FULL_RATIO`` (dann 1,0). Schwache Marker (auch im Standarddeutschen
   üblich, z. B. „eh", „passt") zählen halb.
8) Getrennte Dialektausgabe (Entscheidung P2): ``normalize_ch`` liefert nur bei sicherer Entsprechung aus
   ``CH_NORMALIZATION`` eine Standardform, nie für ``protected_terms``; ``annotate`` schreibt sie nach
   ``text_norm``, ``text`` bleibt das Original. Regionale Wörter ohne sichere Entsprechung werden nie umgeschrieben.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

log = logging.getLogger("chopstr.nlp")

HARD_FILLERS = {"äh", "ähm", "öhm", "hm", "hmm", "mhm", "ähh", "ähmm", "em", "ehm"}
SOFT_FILLERS = {"quasi", "sozusagen", "irgendwie", "letztendlich", "im prinzip", "gewissermaßen"}
MODAL_PARTICLES = {"halt", "eigentlich", "mal", "ja", "doch", "eben", "schon", "wohl", "ned", "eh", "fei"}
BACKCHANNEL = {"genau", "ja", "okay", "ok", "mhm", "stimmt", "richtig", "klar"}
NEGATIONS = {
    "nicht", "kein", "keine", "keinen", "keinem", "keiner", "keins", "keines", "nie", "niemals",
    "nichts", "niemand", "nirgends", "ohne", "ned", "nöd", "nid", "nit", "net", "weder", "noch",
}  # fmt: skip
OPEN_LOOP_END = {
    "aber", "deshalb", "deswegen", "nämlich", "und", "weil", "denn", "sondern", "also", "dass",
    "wobei", "trotzdem", "und zwar", "obwohl", "oder", "das heißt", "beziehungsweise", "bzw.",
}  # fmt: skip

# Dialektlexika (Phase 5c). Kleingeschrieben, ohne Satzzeichen; Abgleich über ``core_token``.
CH_MARKERS = {"nöd", "isch", "chli", "gsi", "öppis", "hoi", "merci", "velo", "gäll", "jetz", "chum", "mer", "hät", "wänn"}
AT_MARKERS = {"heuer", "jänner", "leiwand", "eh", "sackerl", "paradeiser", "semmel", "marille", "oida", "passt"}
WEAK_MARKERS = {"eh", "passt", "mer", "jetz"}  # auch im Standarddeutschen oder als Verschleifung üblich: halbes Gewicht
DIALECT_MIN_HITS = 2.0  # gewichtete Treffer
DIALECT_MIN_RATIO = 0.02  # Anteil Marker an allen Wörtern (2 %)
DIALECT_FULL_RATIO = 0.10  # ab 10 % Markeranteil Sicherheit 1,0
DIALECT_VARIANTS = ("de", "de-AT", "de-CH")
# Sichere Entsprechungen Schweizerdeutsch zu Standarddeutsch; nur diese werden nach ``text_norm`` geschrieben.
CH_NORMALIZATION = {
    "nöd": "nicht", "isch": "ist", "chli": "ein wenig", "gsi": "gewesen", "öppis": "etwas", "jetz": "jetzt",
    "hät": "hat", "wänn": "wenn",
}  # fmt: skip

# Abkürzungen ohne Punkt, kleingeschrieben. Mehrteilige („z. B.") entstehen aus Einzelteilen.
ABBREVIATIONS = {
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
_SENT_PUNCT = (".", "!", "?", "…")

verb_bracket_available: bool | None = None  # None = noch nicht geprüft


@lru_cache(maxsize=1)
def nlp():
    """spaCy-Pipeline oder ``None``, wenn spaCy/Modell fehlt. Setzt ``verb_bracket_available``."""
    global verb_bracket_available
    try:
        import spacy
    except ImportError:
        verb_bracket_available = False
        log.info("spaCy nicht installiert, Verbklammer-Schutz deaktiviert")
        return None
    for model in ("de_core_news_lg", "de_core_news_md", "de_core_news_sm"):
        try:
            pipe = spacy.load(model)
            verb_bracket_available = True
            return pipe
        except OSError:
            continue
    verb_bracket_available = False
    log.info("Kein spaCy-Modell de_core_news_* gefunden, Verbklammer-Schutz deaktiviert")
    return None


def _strip_trailing(text: str) -> str:
    return text.rstrip(_TRAILING)


def core_token(text: str) -> str:
    """Kleinbuchstaben ohne Satzzeichen (für Listen-Abgleich)."""
    return re.sub(r"[^\wäöüß]", "", text.lower())


def is_abbreviation(text: str) -> bool:
    """„z.", „Dr.", „usw." und „z.B."."""
    t = _strip_trailing(text)
    if not t.endswith("."):
        return False
    base = t[:-1].lower().replace(" ", "")
    if not base:
        return False
    if base in ABBREVIATIONS:
        return True
    # Kettenabkürzungen wie „z.B." oder „u.s.w."
    parts = [p for p in base.split(".") if p]
    return bool(parts) and all(p in ABBREVIATIONS or len(p) == 1 for p in parts)


def is_ordinal(text: str) -> bool:
    return bool(_ORDINAL.match(_strip_trailing(text)))


def is_sentence_end(words: list[dict], i: int, min_pause_s: float = 0.7) -> bool:
    """Endet Wort ``i`` einen Satz? Berücksichtigt Satzzeichen, Abkürzungen, Ordinal- und
    Dezimalzahlen, lange Pausen und Sprecherwechsel."""
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
        # Dezimalzahl über Wortgrenze („2." + „4") oder Ordinal/Datum („3." + „Platz", „12." + „Oktober")
        if is_ordinal(stripped) or nxt_text[:1].isdigit() or is_abbreviation(stripped):
            return long_pause or speaker_change
        return True
    return long_pause or speaker_change


def sentence_boundaries(words: list[dict], min_pause_s: float = 0.7) -> list[int]:
    """Indizes der Wörter, die einen Satz beenden (inklusive)."""
    return [i for i in range(len(words)) if is_sentence_end(words, i, min_pause_s)]


def forbidden_cut_ranges(sentence_text: str, word_times: list[dict]) -> list[tuple[float, float]]:
    """Zeitbereiche innerhalb eines Satzes, in denen NICHT geschnitten werden darf (Verbklammer).
    Ohne spaCy: leere Liste (siehe ``verb_bracket_available``)."""
    pipe = nlp()
    if pipe is None:
        return []
    doc = pipe(sentence_text)
    offsets, pos = [], 0
    for i, w in enumerate(word_times):
        start = sentence_text.find(w["text"], pos)
        if start < 0:
            continue
        offsets.append((start, start + len(w["text"]), i))
        pos = max(pos, start + len(w["text"]))

    def widx(tok):
        for s, e, i in offsets:
            if s <= tok.idx < e or (tok.idx <= s < tok.idx + len(tok)):
                return i
        return None

    ranges = []
    for tok in doc:
        if tok.pos_ in ("AUX", "VERB") and tok.morph.get("VerbForm") == ["Fin"]:
            right = None
            for t in doc[tok.i + 1 :]:
                is_particle = t.dep_ == "svp" and t.head == tok  # „fangen ... an"
                is_nonfinite = t.pos_ in ("VERB", "AUX") and t.head == tok and t.morph.get("VerbForm") in (["Inf"], ["Part"])
                is_aux_head = tok.dep_ in ("aux", "aux:pass") and t == tok.head  # „habe ... gemacht"
                if is_particle or is_nonfinite or is_aux_head:
                    right = t
            if right is not None and right.i > tok.i + 1:
                a, b = widx(tok), widx(right)
                if a is not None and b is not None:
                    ranges.append((word_times[a]["end"], word_times[b]["start"]))
    return ranges


def cut_is_legal(t: float, forbidden: list[tuple[float, float]]) -> bool:
    return not any(a < t < b for a, b in forbidden)


def ends_with_open_loop(last_sentence: str) -> bool:
    tail = re.sub(r"[^\wäöüß. ]", "", last_sentence.lower()).replace(".", "").split()
    if not tail:
        return False
    return tail[-1] in OPEN_LOOP_END or " ".join(tail[-2:]) in OPEN_LOOP_END


def classify_fillers(words: list[dict]) -> list[dict]:
    """Markiert Wörter mit filler: 'hard' | 'soft' | 'modal_keep' | 'backchannel' | None und negation."""
    for i, w in enumerate(words):
        tok = core_token(str(w.get("text", "")))
        prev_spk = words[i - 1].get("speaker") if i else None
        nxt_spk = words[i + 1].get("speaker") if i + 1 < len(words) else None
        spk = w.get("speaker")
        if tok in HARD_FILLERS:
            w["filler"] = "hard"
        elif tok in SOFT_FILLERS:
            w["filler"] = "soft"
        elif tok in BACKCHANNEL and spk is not None and spk not in (prev_spk, nxt_spk) and (i > 0 and i + 1 < len(words)):
            w["filler"] = "backchannel"  # „genau." des Gegenübers mitten im Monolog
        elif tok in MODAL_PARTICLES:
            w["filler"] = "modal_keep"
        else:
            w["filler"] = None
        w["negation"] = tok in NEGATIONS
    return words


def auto_remove_ranges(words: list[dict], aggressive: bool = False) -> list[tuple[int, int]]:
    """Wortindex-Bereiche, die BEHALTEN werden (Inverse der entfernten Füller)."""
    drop = {"hard", "backchannel"} | ({"soft"} if aggressive else set())
    keep, start = [], None
    for i, w in enumerate(words):
        if w.get("filler") in drop:
            if start is not None:
                keep.append((start, i - 1))
                start = None
        elif start is None:
            start = i
    if start is not None:
        keep.append((start, len(words) - 1))
    return keep


def de_number(text: str) -> str:
    """„2.4 Prozent" wird „2,4 %"; Tausenderpunkt bleibt („40.000"). Ordinalzahlen („3.") bleiben."""
    text = re.sub(r"(?<![\d.])(\d+)\.(\d{1,2})(?![\d.])", r"\1,\2", text)
    return re.sub(r"(\d)\s?(Prozent|%)", r"\1 %", text)


def detect_dialect(words: list[dict]) -> dict:
    """Dialektvariante aus Lexikon-Markern: ``{variant, confidence, markers, ratios, word_count}``.

    ``variant`` ist ``de``, ``de-AT`` oder ``de-CH``; ``markers`` die gefundenen Markerwörter (nach Häufigkeit).
    Beta: ein Lexikon erkennt nur, was drinsteht; die Abnahme ist ``eval/wer_eval.py`` je Dialekt."""
    n = len(words)
    hits: dict[str, dict[str, int]] = {"de-CH": {}, "de-AT": {}}
    for w in words:
        tok = core_token(str(w.get("text", "")))
        if not tok:
            continue
        if tok in CH_MARKERS:
            hits["de-CH"][tok] = hits["de-CH"].get(tok, 0) + 1
        if tok in AT_MARKERS:
            hits["de-AT"][tok] = hits["de-AT"].get(tok, 0) + 1

    def weighted(counts: dict[str, int]) -> float:
        return sum(c * (0.5 if tok in WEAK_MARKERS else 1.0) for tok, c in counts.items())

    scores = {v: weighted(c) for v, c in hits.items()}
    ratios = {v: round(sc / n, 4) if n else 0.0 for v, sc in scores.items()}
    variant, confidence = "de", 0.0
    if n:
        best = max(scores, key=lambda v: (scores[v], v))
        if scores[best] >= DIALECT_MIN_HITS and ratios[best] >= DIALECT_MIN_RATIO:
            variant = best
            confidence = round(min(1.0, ratios[best] / DIALECT_FULL_RATIO), 3)
    markers = sorted(hits[variant], key=lambda t: (-hits[variant][t], t)) if variant != "de" else []
    return {"variant": variant, "confidence": confidence, "markers": markers, "ratios": ratios, "word_count": n}


def _is_protected(token: str, protected: set[str]) -> bool:
    return bool(token) and token in protected


def normalize_ch(word: str, protected_terms: list[str] | None = None) -> str | None:
    """Standarddeutsche Form eines Schweizerdeutsch-Wortes, nur bei sicherer Entsprechung (``CH_NORMALIZATION``).
    Geschützte Begriffe (``protected_terms``) werden nie umgeschrieben. Großschreibung am Wortanfang und
    anhängende Satzzeichen bleiben erhalten. ``None`` heißt: nicht normalisieren."""
    raw = str(word or "").strip()
    tok = core_token(raw)
    if not tok:
        return None
    protected = {core_token(t) for t in (protected_terms or []) if t}
    if _is_protected(tok, protected):
        return None
    target = CH_NORMALIZATION.get(tok)
    if target is None:
        return None
    if raw[:1].isupper():
        target = target[:1].upper() + target[1:]
    trailing = re.findall(r"[.,!?;:…]+$", raw)
    return target + (trailing[0] if trailing else "")


def annotate(
    words: list[dict],
    min_pause_s: float = 0.7,
    protected_terms: list[str] | None = None,
    dialect: str | None = None,
) -> list[dict]:
    """Fügt jedem Wort ``filler``, ``negation`` und ``sentence_idx`` hinzu (in-place, gibt Liste zurück).

    ``dialect = "de-CH"`` (erkannt oder per ``asr_variant``) ergänzt ``text_norm`` bei sicherer Entsprechung
    (``normalize_ch``); ``text`` bleibt unverändert, geschützte Begriffe werden nie normalisiert."""
    classify_fillers(words)
    idx = 0
    for i, w in enumerate(words):
        w["sentence_idx"] = idx
        if is_sentence_end(words, i, min_pause_s):
            idx += 1
    if dialect == "de-CH":
        for w in words:
            norm = normalize_ch(str(w.get("text", "")), protected_terms)
            if norm is not None:
                w["text_norm"] = norm
    return words


__all__ = [
    "ABBREVIATIONS",
    "AT_MARKERS",
    "BACKCHANNEL",
    "CH_MARKERS",
    "CH_NORMALIZATION",
    "DIALECT_FULL_RATIO",
    "DIALECT_MIN_HITS",
    "DIALECT_MIN_RATIO",
    "DIALECT_VARIANTS",
    "HARD_FILLERS",
    "MODAL_PARTICLES",
    "NEGATIONS",
    "OPEN_LOOP_END",
    "SOFT_FILLERS",
    "WEAK_MARKERS",
    "annotate",
    "auto_remove_ranges",
    "classify_fillers",
    "core_token",
    "cut_is_legal",
    "de_number",
    "detect_dialect",
    "ends_with_open_loop",
    "forbidden_cut_ranges",
    "is_abbreviation",
    "is_ordinal",
    "is_sentence_end",
    "nlp",
    "normalize_ch",
    "sentence_boundaries",
    "verb_bracket_available",
]
