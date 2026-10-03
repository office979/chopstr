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
from dataclasses import dataclass

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


# -- Claim-Check v2 (AP6a, Policy-Fassung 2) ---------------------------------------------------------
# ``hook_claim_check`` vergleicht Zahlen als Teilstring: „40 Euro“ gilt durch „400.000 Euro“ als gedeckt,
# „4 Tipps“ durch „2024“ (RESEARCH-CLIPPING-KERN Abschnitt 2 Nr. 7). v2 vergleicht normalisierte Zahlen als
# Menge von (Wert, Einheit), prüft den Geltungsbereich und lässt unsicher erkannte Zahlen nicht in den Hook.
# Der Web-Port steht in apps/web/lib/copy/claims.ts, beide prüfen gegen packages/editorial/parity/.

# Zahlwörter: Einer, Zehner bis neunzehn, Zehner; zusammengesetzt mit „und“, „hundert“, „tausend“.
UNIT_NUMBER_WORDS = {
    "eins": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9,
}  # fmt: skip
UNIT_PREFIXES = {**{k: v for k, v in UNIT_NUMBER_WORDS.items() if k != "eins"}, "ein": 1}
TEEN_NUMBER_WORDS = {
    "zehn": 10, "elf": 11, "zwölf": 12, "dreizehn": 13, "vierzehn": 14, "fünfzehn": 15, "sechzehn": 16,
    "siebzehn": 17, "achtzehn": 18, "neunzehn": 19,
}  # fmt: skip
TEN_NUMBER_WORDS = {
    "zwanzig": 20, "dreißig": 30, "dreissig": 30, "vierzig": 40, "fünfzig": 50, "sechzig": 60, "siebzig": 70,
    "achtzig": 80, "neunzig": 90,
}  # fmt: skip
# Zahl nur vor einem Nomen, einer Einheit oder einem Multiplikator („acht Leute“, nicht „gib acht“).
AMBIGUOUS_NUMBER_WORDS = frozenset({"null", "eins", "acht", "elf"})
# Unbestimmter Artikel als Zahl nur vor einem Multiplikator („eine Million Euro“).
ARTICLE_ONE = frozenset({"ein", "eine", "einen", "einem", "einer"})
# Wortanfänge und Bestandteile, an denen ein nicht erkanntes Zahlwort im Hook auffällt.
NUMBER_WORD_STEMS = (
    "ein", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun", "zehn", "elf", "zwölf",
    "zwanzig", "hundert", "tausend",
)  # fmt: skip
NUMBER_WORD_PARTS = ("zig", "ßig", "ssig", "hundert", "tausend", "zehn")
MULTIPLIERS = {
    "hundert": 1e2, "tausend": 1e3, "tsd": 1e3, "tsd.": 1e3, "mio": 1e6, "mio.": 1e6, "million": 1e6,
    "millionen": 1e6, "mrd": 1e9, "mrd.": 1e9, "milliarde": 1e9, "milliarden": 1e9,
}  # fmt: skip
UNIT_WORDS = {
    "%": "%", "prozent": "%", "euro": "EUR", "eur": "EUR", "€": "EUR", "franken": "CHF", "chf": "CHF",
}  # fmt: skip
UNIT_LABELS = {"%": "Prozent", "EUR": "Euro", "CHF": "Franken", "time": "Uhr"}
# Verallgemeinerer im Hook gegen Einschränker im Clip (Master-Prompt 8: „bei einem Kunden“ wird nicht
# „für jedes Unternehmen“). Wortgrenzen, kleingeschrieben.
GENERALIZERS = (
    "jedes unternehmen", "jede firma", "jeder betrieb", "für jeden", "für jede", "für alle", "alle", "immer",
    "grundsätzlich", "überall", "jeder", "jede", "jedes",
)  # fmt: skip
RESTRICTORS = (
    "bei uns", "bei mir", "bei einem kunden", "bei einer kundin", "in unserem fall", "in meinem fall",
    "in unserem betrieb", "für uns", "damals",
)  # fmt: skip

_MENTION = re.compile(
    r"(?<![\w.,:])(?P<time>\d{1,2}[:.]\d{2})(?=\s*Uhr(?!\w))"
    r"|(?<![\w.,])(?P<num>\d{1,3}(?:[.'   ]\d{3})+(?:,\d+)?(?!\d)|\d+(?:[.,]\d+)?)"
    r"|(?<!\w)(?P<word>[^\W\d_]+)(?!\w)"
)
_NEXT_TOKEN = re.compile(r"\s*(%|€|[^\s,;:!?()]+)")
_THOUSANDS = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?")
_CLIP_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class NumberMention:
    """Eine Zahl im Text: Rohform, normalisierter Wert, Einheit (``%``, ``EUR``, ``CHF``, ``time``,
    ``noun:<wort>`` oder None)."""

    raw: str
    value: float
    unit: str | None


def _number_value(raw: str) -> float:
    s = raw.replace(" ", "").replace(" ", "").replace("'", "").replace(" ", "")
    if _THOUSANDS.fullmatch(s):
        s = s.replace(".", "")
    return round(float(s.replace(",", ".")), 6)


def _word_key(token: str) -> str:
    return token.lower().strip(".,;:!?\"'»«“”‘’()")


def _below_hundred(s: str) -> int | None:
    if s in TEEN_NUMBER_WORDS:
        return TEEN_NUMBER_WORDS[s]
    if s in TEN_NUMBER_WORDS:
        return TEN_NUMBER_WORDS[s]
    if s in UNIT_NUMBER_WORDS:
        return UNIT_NUMBER_WORDS[s]
    for ten, value in TEN_NUMBER_WORDS.items():
        if s.endswith("und" + ten) and s[: -len("und" + ten)] in UNIT_PREFIXES:
            return UNIT_PREFIXES[s[: -len("und" + ten)]] + value
    return None


def _below_thousand(s: str) -> int | None:
    if "hundert" not in s:
        return _below_hundred(s)
    head, _, tail = s.partition("hundert")
    hundreds = 1 if head == "" else UNIT_PREFIXES.get(head)
    if hundreds is None:
        return None
    tail = tail.removeprefix("und")
    rest = 0 if tail == "" else _below_hundred(tail)
    return None if rest is None else hundreds * 100 + rest


def parse_number_word(word: str) -> int | None:
    """Zahlwort bis 999.999 („einundzwanzig“, „vierzigtausend“, „zweihundertfünfzig“), sonst None."""
    s = word.lower()
    if s == "null":
        return 0
    if "tausend" not in s:
        return _below_thousand(s)
    head, _, tail = s.partition("tausend")
    thousands = 1 if head == "" else UNIT_PREFIXES.get(head) or _below_thousand(head)
    if thousands is None:
        return None
    tail = tail.removeprefix("und")
    rest = 0 if tail == "" else _below_thousand(tail)
    return None if rest is None else thousands * 1000 + rest


def _unit_of(token: str) -> str | None:
    key = token if token in ("%", "€") else _word_key(token)
    if key in UNIT_WORDS:
        return UNIT_WORDS[key]
    if token[:1].isupper() and _word_key(token).isalpha():
        return f"noun:{_word_key(token)}"
    return None


def number_mentions(text: str) -> list[NumberMention]:
    """Alle Zahlen eines Textes: Ziffern (Tausenderpunkt, Leerzeichen, geschütztes Leerzeichen,
    Dezimalkomma), Uhrzeiten („9.30 Uhr“ gleich „9:30 Uhr“) und Zahlwörter („vier“, „einundzwanzig“,
    „vierzigtausend“).

    Die Einheit ist das folgende Wort: Prozent und Währung normalisiert, ein großgeschriebenes Nomen als
    ``noun:<wort>``, sonst None. „Mio.“, „Tausend“ und „hundert“ danach multiplizieren den Wert. „null“,
    „eins“, „acht“, „elf“ zählen nur vor Nomen, Einheit oder Multiplikator, „ein“ und „eine“ nur vor einem
    Multiplikator."""
    out: list[NumberMention] = []
    consumed = 0
    for m in _MENTION.finditer(text):
        if m.start() < consumed:
            continue
        pos = m.end()
        if m.group("time"):
            hours, minutes = re.split(r"[:.]", m.group("time"))
            out.append(NumberMention(m.group("time"), float(int(hours) * 60 + int(minutes)), "time"))
            consumed = pos
            continue
        nxt = _NEXT_TOKEN.match(text, pos)
        nxt_key = _word_key(nxt.group(1)) if nxt else ""
        if m.group("num"):
            raw = m.group("num").strip()
            value = _number_value(raw)
        else:
            raw = m.group("word")
            low = raw.lower()
            parsed = parse_number_word(low)
            if parsed is None:
                if not (low in ARTICLE_ONE and nxt_key in MULTIPLIERS):
                    continue
                parsed = 1
            elif low in AMBIGUOUS_NUMBER_WORDS and not (nxt and (nxt_key in MULTIPLIERS or _unit_of(nxt.group(1)))):
                continue
            value = float(parsed)
        if nxt and nxt_key in MULTIPLIERS:
            value = round(value * MULTIPLIERS[nxt_key], 6)
            pos = nxt.end()
            nxt = _NEXT_TOKEN.match(text, pos)
        unit = _unit_of(nxt.group(1)) if nxt else None
        if unit is None:
            before = text[: m.start()].rstrip()
            if before.endswith("€"):
                unit = "EUR"
            elif before.lower().endswith("chf"):
                unit = "CHF"
        out.append(NumberMention(raw, value, unit))
        consumed = pos
    return out


def unrecognized_number_words(text: str) -> list[str]:
    """Wörter, die wie ein Zahlwort gebaut sind, aber nicht gelesen werden können („zehntausende“)."""
    out = []
    for m in re.finditer(r"(?<!\w)[^\W\d_]+(?!\w)", text):
        low = m.group(0).lower()
        if parse_number_word(low) is not None or low.startswith("einzig"):
            continue
        if low.startswith(NUMBER_WORD_STEMS) and any(part in low for part in NUMBER_WORD_PARTS):
            out.append(m.group(0))
    return out


def _same_stem(a: str, b: str) -> bool:
    """Gleiches Nomen bis auf die Endung („Woche“ und „Wochen“, „Kunden“ und „Kundinnen“): gemeinsamer
    Anfang von mindestens vier Zeichen, dem kürzeren Wort fehlen höchstens zwei."""
    common = 0
    for x, y in zip(a, b):
        if x != y:
            break
        common += 1
    return a == b or (common >= 4 and common >= min(len(a), len(b)) - 2)


def _covered(h: NumberMention, clip: list[NumberMention], low_words: set[str]) -> bool:
    same = [c for c in clip if c.value == h.value]
    if h.unit is None:
        return bool(same)
    if not h.unit.startswith("noun:"):
        return any(c.unit == h.unit for c in same)
    noun = h.unit[len("noun:") :]
    return any(
        (c.unit is not None and c.unit.startswith("noun:") and _same_stem(c.unit[len("noun:") :], noun))
        or (c.unit is None and any(_same_stem(w, noun) for w in low_words))
        for c in same
    )


def phrase_hits(phrases: tuple[str, ...] | list[str], low: str) -> list[str]:
    """Phrasen, die im kleingeschriebenen Text an Wortgrenzen stehen."""
    return [p for p in phrases if re.search(rf"(?<!\w){re.escape(p)}(?!\w)", low)]


def _unit_label(unit: str | None) -> str:
    if unit is None:
        return ""
    return f" ({UNIT_LABELS.get(unit, unit.removeprefix('noun:').capitalize())})"


def _scope_issues(low_hook: str, clip_text: str) -> list[tuple[str, str]]:
    """(Verallgemeinerer, Einschränker) für Befunde zum Geltungsbereich.

    Kein Befund, wenn der Hook selbst einschränkt oder wenn der Clip den Verallgemeinerer in einem Satz
    ohne Einschränker selbst sagt."""
    restrictors = phrase_hits(RESTRICTORS, clip_text.lower())
    if not restrictors or phrase_hits(RESTRICTORS, low_hook):
        return []
    sentences = [x.lower() for x in _CLIP_SENTENCE.split(" ".join(clip_text.split())) if x.strip()]
    hits = phrase_hits(GENERALIZERS, low_hook)
    out = []
    for gen in [g for g in hits if not any(g != o and g in o for o in hits)]:
        if any(phrase_hits([gen], x) and not phrase_hits(RESTRICTORS, x) for x in sentences):
            continue
        out.append((gen, restrictors[0]))
    return out


def hook_claim_check_v2(
    hook_text: str, clip_text: str, uncertain_tokens: list[str] | tuple[str, ...] = ()
) -> list[str]:
    """Hook darf nicht mehr behaupten als der Clip (Policy-Fassung 2; ``hook_claim_check`` bleibt für v1).

    * Zahlen als Menge von (Wert, Einheit): „40 Euro“ ist nicht „40.000 Euro“, „4“ steckt nicht in „2024“,
      „40 %“ und „40 Prozent“ sind dasselbe, „vier“ ist 4. Ein Nomen als Einheit deckt nur dasselbe Nomen.
    * Zahlwörter, die nicht gelesen werden können, sind ein Befund.
    * Zahlen, die im Clip unsicher erkannt sind (``uncertain_tokens``), dürfen im Hook nicht stehen.
    * Geltungsbereich: ein Verallgemeinerer im Hook gegen einen Einschränker im Clip ist ein Befund.
    * Zuspitzungen wie in v1, aber an Wortgrenzen und ohne Doppelbefund mit dem Geltungsbereich."""
    issues: list[str] = []
    clip_mentions = number_mentions(clip_text)
    low_words = {_word_key(t) for t in clip_text.split()}
    uncertain_values = {m.value for tok in uncertain_tokens for m in number_mentions(str(tok))}
    for h in number_mentions(hook_text):
        if h.value in uncertain_values:
            issues.append(f"Zahl '{h.raw}' ist im Clip unsicher erkannt und darf nicht in den Hook (am Audio prüfen)")
        elif not _covered(h, clip_mentions, low_words):
            issues.append(f"Zahl '{h.raw}'{_unit_label(h.unit)} steht so nicht im Clip")
    for word in unrecognized_number_words(hook_text):
        issues.append(f"Zahlwort '{word}' nicht erkannt, am Clip prüfen")
    low_hook, low_clip = hook_text.lower(), clip_text.lower()
    scope = _scope_issues(low_hook, clip_text)
    scoped = {gen for gen, _ in scope}
    for sup in SUPERLATIVES:
        if sup not in scoped and phrase_hits([sup], low_hook) and not phrase_hits([sup], low_clip):
            issues.append(f"Zuspitzung '{sup}' nicht durch Clip gedeckt")
    for gen, restrictor in scope:
        issues.append(f"Geltungsbereich: '{gen}' im Hook, der Clip schränkt ein ('{restrictor}')")
    return issues


UNCERTAIN_CONTEXT_WORDS = 3  # Zahl, Multiplikator, Einheit


def uncertain_number_tokens(words: list[dict], threshold: float | None = None) -> list[str]:
    """Zahlen, deren ASR-Sicherheit (``prob``) unter der Schwelle liegt: je Wort die Wortfolge ab der Zahl
    (damit „40 Tausend Euro“ als 40.000 gelesen wird) und die Rohform allein.

    Schwelle ist ``transcribe.LOW_CONF_THRESHOLD`` (dieselbe, die ``confidence_stats`` zählt). Wörter ohne
    ``prob`` gelten als sicher."""
    if threshold is None:
        from .transcribe import LOW_CONF_THRESHOLD

        threshold = LOW_CONF_THRESHOLD
    out: list[str] = []
    for i, w in enumerate(words):
        prob = w.get("prob")
        if prob is None or float(prob) >= threshold:
            continue
        context = " ".join(str(x.get("text", "")) for x in words[i : i + UNCERTAIN_CONTEXT_WORDS])
        mentions = number_mentions(context)
        if not mentions or not context.startswith(mentions[0].raw):
            continue
        for tok in (context, str(w.get("text", ""))):
            if tok not in out and number_mentions(tok):
                out.append(tok)
    return out


def number_values(texts: list[str] | tuple[str, ...]) -> set[float]:
    """Werte aller Zahlen in den Texten (für den Abgleich mit unsicheren Zahlen)."""
    return {m.value for t in texts for m in number_mentions(str(t))}


__all__ = [
    "CONTRAST_STARTS",
    "GENERALIZERS",
    "MAX_JOIN_GAP_S",
    "QUALIFIERS",
    "RESTRICTORS",
    "SUPERLATIVES",
    "NumberMention",
    "check_cut",
    "hook_claim_check",
    "hook_claim_check_v2",
    "number_mentions",
    "number_values",
    "parse_number_word",
    "phrase_hits",
    "uncertain_number_tokens",
    "unrecognized_number_words",
]
