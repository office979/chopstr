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
from typing import TYPE_CHECKING, Any

from . import dach_nlp
from .dach_nlp import NEGATIONS

if TYPE_CHECKING:
    from ..editorial import Policy

QUALIFIERS = {
    "nur", "außer", "ausser", "meistens", "oft", "manchmal", "teilweise", "eventuell", "vielleicht",
    "bei uns", "in unserem fall", "für uns", "in der regel", "unter umständen", "grundsätzlich",
    "eigentlich", "zumindest", "höchstens", "mindestens",
}  # fmt: skip
CONTRAST_STARTS = ("aber", "allerdings", "jedoch", "wobei", "trotzdem", "andererseits", "außer")
# Regel v2 (AP4): zusätzlich die Schreibung ohne ß (Schweiz).
CONTRAST_STARTS_V2 = (*CONTRAST_STARTS, "ausser")
MAX_JOIN_GAP_S = 20.0  # Segmente mit größerem Abstand im Original = „zusammengesetzte Aussage"


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-zäöüß]+", text.lower())


def starts_with_contrast(tail: str, rule: str = "v1") -> bool:
    """Beginnt ``tail`` (kleingeschrieben) mit einem Kontrastwort? ``v1`` vergleicht den Textanfang (vor AP4,
    „außerdem“ gilt als „außer“), ``v2`` das erste ganze Wort (RESEARCH-CLIPPING-KERN Abschnitt 2 Nr. 6)."""
    if rule != "v2":
        return tail.startswith(CONTRAST_STARTS)
    first = next((t for t in (dach_nlp.core_token(x) for x in tail.split()) if t), "")
    return first in CONTRAST_STARTS_V2


def check_cut(
    original_words: list[dict], kept_ranges: list[tuple[int, int]], rule: str = "v1", policy: Policy | None = None
) -> list[dict]:
    """original_words: Wortliste des Kandidaten; kept_ranges: behaltene Wortindex-Bereiche (inklusiv).

    ``rule`` betrifft nur ``ends_before_contrast``: ``v2`` gleicht ``CONTRAST_STARTS`` an Wortgrenzen ab.

    Mit ``policy`` der Fassung 2 (Abschnitt ``trim``, AP7) zusätzlich aus
    ``trim_plan.protected_cut_findings``: ``protected_removed`` (hoch), wenn ein Schutzbereich teilweise
    fehlt oder ein ganzer Satz mit Negation, Bedingung, Einschränkung, Korrektur oder Vergleich wegfällt,
    der sich auf das Behaltene bezieht; ``protected_omitted`` (mittel, Prüfhinweis), wenn ein ganzer Satz
    ohne erkennbaren Bezug wegfällt. Ohne ``policy`` oder unter Fassung 1 bleibt die Prüfung wie vorher."""
    warnings = []
    kept: set[int] = set()
    for a, b in kept_ranges:
        kept.update(range(a, b + 1))
    removed = [w for i, w in enumerate(original_words) if i not in kept]
    removed_text = " ".join(str(w["text"]) for w in removed).lower()
    removed_tokens = set(_tokens(removed_text))

    negations = NEGATIONS
    if rule == "v2":
        # Unter Regel v2 dieselbe Liste wie die Schutzbereiche (AP7): „noch“ ist keine Negation
        # („Wir rechnen alles noch zweimal durch“), „nein“ ist eine.
        from .trim_plan import NEGATION_TRIGGERS as negations
    if removed_tokens & negations:
        warnings.append({"type": "negation_removed", "severity": "high", "detail": sorted(removed_tokens & negations)})
    hits = [q for q in sorted(QUALIFIERS) if f" {q} " in f" {removed_text} "]
    if hits:
        warnings.append({"type": "qualifier_removed", "severity": "medium", "detail": hits})

    last_kept = max(kept) if kept else -1
    tail = " ".join(str(w["text"]) for w in original_words[last_kept + 1 : last_kept + 4]).lower()
    if starts_with_contrast(tail, rule):
        warnings.append({"type": "ends_before_contrast", "severity": "high", "detail": tail})

    for (_a1, b1), (a2, _b2) in zip(kept_ranges, kept_ranges[1:]):
        gap = float(original_words[a2]["start"]) - float(original_words[b1]["end"])
        if gap > MAX_JOIN_GAP_S:
            warnings.append({"type": "joined_statements", "severity": "high", "detail": f"{gap:.0f}s Abstand im Original"})
    if policy is not None and policy.version >= 2:
        from .. import editorial
        from . import trim_plan

        if editorial.trim_settings(policy) is not None:
            found = trim_plan.protected_cut_findings(original_words, kept, policy)
            for kind, severity in (("protected_removed", "high"), ("protected_omitted", "medium")):
                hit = [
                    {"type": f["type"], "word_range": f["word_range"], "text": f["text"], "mode": f["mode"]}
                    for f in found
                    if f["severity"] == severity
                ]
                if hit:
                    warnings.append({"type": kind, "severity": severity, "detail": hit})
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
# Wendungen mit „immer“, die nichts verallgemeinern („immer mehr“, „wie immer“).
IMMER_IDIOMS = ("immer mehr", "immer wieder", "immer noch", "wie immer")
# Mengenwörter ohne Ziffer („Millionen Kunden“): im Hook nur, wenn der Clip dasselbe Wort sagt.
QUANTITY_STEMS = ("million", "milliard", "dutzend")
# Richtung einer Zahl: „über 40 Prozent“ ist nicht „fast 40 %“.
DIRECTION_UP = ("über", "mehr als", "mindestens", "ab")
DIRECTION_DOWN = ("fast", "knapp", "unter", "höchstens", "weniger als", "beinahe")

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
    direction: str | None = None  # "up" (über, mehr als, mindestens) oder "down" (fast, knapp, unter)


def _direction_before(text: str, start: int) -> str | None:
    before = " ".join(text[:start].lower().split()[-2:])
    for word in DIRECTION_UP:
        if re.search(rf"(?<!\w){re.escape(word)}$", before):
            return "up"
    for word in DIRECTION_DOWN:
        if re.search(rf"(?<!\w){re.escape(word)}$", before):
            return "down"
    return None


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
        out.append(NumberMention(raw, value, unit, _direction_before(text, m.start())))
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


def quantity_words(text: str) -> list[str]:
    """Mengenwörter ohne vorangehende Zahl („Millionen Kunden“, „Dutzende Anfragen“)."""
    out = []
    prev = ""
    for m in re.finditer(r"(?<!\w)[^\W_]+(?!\w)", text):
        word = m.group(0)
        low = word.lower()
        is_number = any(ch.isdigit() for ch in prev) or parse_number_word(prev) is not None or prev in ARTICLE_ONE
        if low.startswith(QUANTITY_STEMS) and not is_number:
            out.append(word)
        prev = low
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


def _direction_conflict(h: NumberMention, clip: list[NumberMention]) -> bool:
    """Hook „über 40 Prozent“, Clip nur „fast 40 %“ (oder umgekehrt): jede passende Stelle zeigt in die
    andere Richtung."""
    if h.direction is None:
        return False
    same = [c for c in clip if c.value == h.value and (h.unit is None or c.unit == h.unit or c.unit is None)]
    return bool(same) and all(c.direction is not None and c.direction != h.direction for c in same)


def phrase_hits(phrases: tuple[str, ...] | list[str], low: str) -> list[str]:
    """Phrasen, die im kleingeschriebenen Text an Wortgrenzen stehen."""
    return [p for p in phrases if re.search(rf"(?<!\w){re.escape(p)}(?!\w)", low)]


def _phrase_spans(phrases: tuple[str, ...] | list[str], low: str) -> list[str]:
    """Wie ``phrase_hits``, aber überlappende Treffer zählen einmal, der längste gewinnt
    („für jede firma“ ist ein Befund, nicht „jede firma“ und „für jede“)."""
    taken: list[tuple[int, int]] = []
    out: list[str] = []
    for p in sorted(phrases, key=len, reverse=True):
        for m in re.finditer(rf"(?<!\w){re.escape(p)}(?!\w)", low):
            if any(m.start() < e and s0 < m.end() for s0, e in taken):
                continue
            taken.append((m.start(), m.end()))
            if p not in out:
                out.append(p)
    return [p for p in phrases if p in out]


def _without_idioms(low: str) -> str:
    for idiom in IMMER_IDIOMS:
        low = re.sub(rf"(?<!\w){re.escape(idiom)}(?!\w)", " ", low)
    return low


def text_sentences(text: str) -> list[str]:
    """Sätze nach ``dach_nlp.sentence_end_kind`` (Regel v2, nur Satzzeichen): „z. B.“ und „am 3. Mai“ trennen
    nicht. Der Web-Port nutzt ``sentenceEndKind`` aus apps/web/lib/transcript/sentences.ts."""
    toks = text.split()
    words = [{"text": t, "start": 0.0, "end": 0.0} for t in toks]
    out, cur = [], []
    for i, t in enumerate(toks):
        cur.append(t)
        if dach_nlp.sentence_end_kind(words, i, rule="v2") != "none":
            out.append(" ".join(cur))
            cur = []
    if cur:
        out.append(" ".join(cur))
    return out


def _unit_label(unit: str | None) -> str:
    if unit is None:
        return ""
    return f" ({UNIT_LABELS.get(unit, unit.removeprefix('noun:').capitalize())})"


def _scope_issues(low_hook: str, clip_text: str) -> list[tuple[str, str]]:
    """(Verallgemeinerer, Einschränker) für Befunde zum Geltungsbereich.

    Kein Befund, wenn der Hook selbst einschränkt oder wenn der Clip den Verallgemeinerer in einem Satz
    ohne Einschränker selbst sagt. „immer mehr“, „immer wieder“, „immer noch“, „wie immer“ verallgemeinern
    nicht."""
    restrictors = phrase_hits(RESTRICTORS, clip_text.lower())
    if not restrictors or phrase_hits(RESTRICTORS, low_hook):
        return []
    sentences = [_without_idioms(x.lower()) for x in text_sentences(clip_text)]
    out = []
    for gen in _phrase_spans(GENERALIZERS, _without_idioms(low_hook)):
        if any(phrase_hits([gen], x) and not phrase_hits(RESTRICTORS, x) for x in sentences):
            continue
        out.append((gen, restrictors[0]))
    return out


def hook_claim_check_v2(
    hook_text: str, clip_text: str, uncertain_tokens: list[str] | tuple[str, ...] = (), meaning: bool | None = None
) -> list[str]:
    """Hook darf nicht mehr behaupten als der Clip (Policy-Fassung 2; ``hook_claim_check`` bleibt für v1).

    * Zahlen als Menge von (Wert, Einheit): „40 Euro“ ist nicht „40.000 Euro“, „4“ steckt nicht in „2024“,
      „40 %“ und „40 Prozent“ sind dasselbe, „vier“ ist 4. Ein Nomen als Einheit deckt nur dasselbe Nomen.
    * Zahlwörter, die nicht gelesen werden können, sind ein Befund.
    * Zahlen, die im Clip unsicher erkannt sind (``uncertain_tokens``), dürfen im Hook nicht stehen.
    * Geltungsbereich: ein Verallgemeinerer im Hook gegen einen Einschränker im Clip ist ein Befund.
    * Zuspitzungen wie in v1, aber an Wortgrenzen und ohne Doppelbefund mit dem Geltungsbereich.
    * Regel 6 (Lane P3, ``meaning``): Zuschreibung, Sicherheit, Zeitraum, Größenordnung und Kausalität bleiben
      erhalten (``hook_meaning_issues``). Ohne Angabe gilt der Gegenleser der aktiven Fassung
      (``counter_reader_settings``); unter Fassung 1 und ohne Schalter bleibt die Prüfung wie vorher."""
    issues: list[str] = []
    clip_mentions = number_mentions(clip_text)
    low_words = {_word_key(t) for t in clip_text.split()}
    uncertain_values = {m.value for tok in uncertain_tokens for m in number_mentions(str(tok))}
    for h in number_mentions(hook_text):
        if h.value in uncertain_values:
            issues.append(f"Zahl '{h.raw}' ist im Clip unsicher erkannt und darf nicht in den Hook (am Audio prüfen)")
        elif not _covered(h, clip_mentions, low_words):
            issues.append(f"Zahl '{h.raw}'{_unit_label(h.unit)} steht so nicht im Clip")
        elif _direction_conflict(h, clip_mentions):
            issues.append(f"Zahl '{h.raw}': der Hook sagt mehr, als der Clip trägt (Richtung umgekehrt)")
    for word in unrecognized_number_words(hook_text):
        issues.append(f"Zahlwort '{word}' nicht erkannt, am Clip prüfen")
    for word in quantity_words(hook_text):
        if not any(_same_stem(word.lower(), w) for w in low_words):
            issues.append(f"Mengenwort '{word}' steht so nicht im Clip")
    low_hook, low_clip = _without_idioms(hook_text.lower()), _without_idioms(clip_text.lower())
    scope = _scope_issues(hook_text.lower(), clip_text)
    scoped = {gen for gen, _ in scope}
    for sup in SUPERLATIVES:
        if sup not in scoped and phrase_hits([sup], low_hook) and not phrase_hits([sup], low_clip):
            issues.append(f"Zuspitzung '{sup}' nicht durch Clip gedeckt")
    for gen, restrictor in scope:
        issues.append(f"Geltungsbereich: '{gen}' im Hook, der Clip schränkt ein ('{restrictor}')")
    if meaning is None:
        meaning = counter_reader_settings(_active_policy()) is not None
    if meaning:
        known = " ".join(issues)
        issues.extend(i["detail"] for i in hook_meaning_issues(hook_text, clip_text) if f"'{i['hook_quote']}'" not in known)
    return issues


UNCERTAIN_CONTEXT_WORDS = 3  # Zahl, Multiplikator, Einheit
UNCERTAIN_WINDOW = 2  # unsicherer Multiplikator oder unsichere Einheit macht die Zahl bis zwei Wörter davor unsicher


def _is_number_word(text: str) -> bool:
    mentions = number_mentions(text)
    return bool(mentions) and text.strip().startswith(mentions[0].raw)


def uncertain_number_tokens(words: list[dict], threshold: float | None = None) -> list[str]:
    """Zahlen, deren ASR-Sicherheit (``prob``) unter der Schwelle liegt: je Zahl die Wortfolge ab der Zahl
    (damit „40 Tausend Euro“ als 40.000 gelesen wird) und die Rohform allein.

    Unsicher ist eine Zahl auch, wenn ihr Multiplikator oder ihre Einheit im Fenster von zwei Wörtern
    unsicher erkannt ist („40 Tausend“ mit unsicherem „Tausend“). Schwelle ist
    ``transcribe.LOW_CONF_THRESHOLD``. Wörter ohne ``prob`` gelten als sicher."""
    if threshold is None:
        from .transcribe import LOW_CONF_THRESHOLD

        threshold = LOW_CONF_THRESHOLD
    texts = [str(w.get("text", "")) for w in words]
    numbers: list[int] = []
    for i, w in enumerate(words):
        prob = w.get("prob")
        if prob is None or float(prob) >= threshold:
            continue
        key = _word_key(texts[i])
        if key in MULTIPLIERS or key in UNIT_WORDS or texts[i] in ("%", "€"):
            for j in range(max(0, i - UNCERTAIN_WINDOW), min(len(words), i + UNCERTAIN_WINDOW + 1)):
                if j != i and _word_key(texts[j]) not in MULTIPLIERS and _is_number_word(" ".join(texts[j : j + UNCERTAIN_CONTEXT_WORDS])):
                    numbers.append(j)
        elif _is_number_word(" ".join(texts[i : i + UNCERTAIN_CONTEXT_WORDS])):
            numbers.append(i)
    out: list[str] = []
    for j in sorted(set(numbers)):
        for tok in (" ".join(texts[j : j + UNCERTAIN_CONTEXT_WORDS]), texts[j]):
            if tok not in out and number_mentions(tok):
                out.append(tok)
    return out


def number_values(texts: list[str] | tuple[str, ...]) -> set[float]:
    """Werte aller Zahlen in den Texten (für den Abgleich mit unsicheren Zahlen)."""
    return {m.value for t in texts for m in number_mentions(str(t))}


# -- Gegenleser und Hook-Verdichtung (Lane P3, Launch-Auftrag Phase 3, Regeln 2 und 6) -------------------------
# Deterministischer Vergleich nach sechs Dimensionen (Review 8: eine Ein-Satz-Paraphrase kann gerade die
# entscheidende Bedingung weglassen). Jede Dimension ist ein Befund mit Zitat aus Clip und Quelle. Die Wortlisten
# sind Übertragungshypothesen ohne Messung (Herkunft H in ``origins.context.counter_reader.*``). Ein Befund ist ein
# regelbasierter Hinweis, kein bestätigter Fehler; bestätigt wird nur über den Modellprompt ``counter_reader_v1``
# (``critic.counter_read_model``).
COUNTER_READER_SWITCH = "context.counter_reader"
TITLE_CARD_SWITCH = "context.title_card"
COUNTER_DIMENSIONS = ("attribution", "negation", "certainty", "condition", "number", "time")
ATTRIBUTION_MARKERS = (
    "laut", "zufolge", "sagt", "sagte", "meint", "meinte", "behauptet", "behauptete", "angeblich", "heißt es",
    "hieß es", "schreibt", "schrieb",
)  # fmt: skip
NEGATION_MARKERS = (
    "nicht", "kein", "keine", "keinen", "keinem", "keiner", "keines", "nie", "niemals", "nichts", "niemand",
    "ned", "nöd", "nid", "nit", "net",
)  # fmt: skip
HEDGES = (
    "ich glaube", "glaube ich", "ich denke", "denke ich", "vielleicht", "wahrscheinlich", "vermutlich",
    "eventuell", "möglicherweise", "soweit ich weiß", "ich bin nicht sicher", "keine ahnung", "ich schätze",
    "schätze ich", "unter umständen",
)  # fmt: skip
ABSOLUTES = ("garantiert", "sicher", "definitiv", "bewiesen", "immer", "nie", "niemals", "100 prozent", "auf jeden fall")
CONDITION_MARKERS = (
    "nur wenn", "es sei denn", "vorausgesetzt", "wenn", "falls", "sofern", "außer", "ausser", "nur", "bei uns",
    "bei mir", "in unserem fall", "in meinem fall", "meistens", "manchmal", "teilweise", "in der regel",
)  # fmt: skip
TIME_MARKERS = (
    "damals", "früher", "heute", "inzwischen", "mittlerweile", "seit", "letztes jahr", "letzte woche",
    "letzten monat", "dieses jahr", "in einer woche", "in einem monat", "in einem jahr", "pro tag", "pro woche",
    "pro monat", "pro jahr", "täglich", "wöchentlich", "monatlich", "jährlich", "im jahr",
)  # fmt: skip
APPROXIMATORS = ("rund", "etwa", "ungefähr", "circa", "ca", "gut", "bis zu", "knapp", "fast", "über", "mehr als")
CAUSAL_MARKERS = (
    "weil", "deshalb", "deswegen", "dadurch", "darum", "führt zu", "sorgt für", "verursacht", "kostet", "kosten",
    "bringt", "bringen", "wegen", "schuld", "macht dich", "macht euch", "macht sie",
)  # fmt: skip
FIRST_PERSON = frozenset({"ich", "wir", "mir", "mich", "uns", "mein", "meine", "meinen", "meinem", "meiner", "unser", "unsere", "unseren", "unserem"})
SECOND_PERSON = frozenset({"du", "dich", "dir", "dein", "deine", "deinen", "deinem", "deiner", "euch", "euer", "eure", "ihr"})
GENERIC_SUBJECTS = ("man", "jeder", "jede", "alle", "diese methode", "die methode", "dieser trick")
_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d\d(?!\d)")
RELATED_OVERLAP = 0.15
ELLIPTIC_WORDS = 5
CONNECTOR_STARTS = ("und", "aber", "also", "dann", "deshalb", "deswegen", "sondern", "doch", "trotzdem", "darum", "allerdings", "jedoch", "wobei", "außer", "ausser", "nur")


def _setting(policy: Policy | None, switch: str, section: str) -> dict | None:
    """Abschnitt ``context.<section>`` der Fassung 2, wenn Schalter ``implementation.<switch>`` und Regel
    ``context.<section>.enabled`` beide an sind, sonst ``None``."""
    from .. import editorial

    if policy is None or getattr(policy, "version", 1) < 2:
        return None
    roh = policy.roh
    if editorial._switch_value(roh.get("implementation") or {}, switch) is not True:
        return None
    raw = ((roh.get("context") or {}).get(section)) or {}
    if not isinstance(raw, dict) or raw.get("enabled") is not True:
        return None
    return raw


def counter_reader_settings(policy: Policy | None) -> dict | None:
    """Gegenleser (``context.counter_reader``): ``None`` ohne Schalter oder Regel. ``model`` sagt, ob der
    Modellprompt ``counter_reader_v1`` im Kritikerschritt läuft (nur mit ``roles.critic``)."""
    raw = _setting(policy, COUNTER_READER_SWITCH, "counter_reader")
    if raw is None:
        return None
    model = raw.get("model", False)
    if not isinstance(model, bool):
        from ..editorial import PolicyError

        raise PolicyError("context.counter_reader.model ist true oder false.")
    return {"model": model}


def title_card_settings(policy: Policy | None) -> dict | None:
    """Titelkarte als Kontextreparatur (``context.title_card``): ``None`` ohne Schalter oder Regel, sonst
    ``max_words`` (höchstens so viele Wörter hat der wörtliche Quellsatz auf der Karte)."""
    raw = _setting(policy, TITLE_CARD_SWITCH, "title_card")
    if raw is None:
        return None
    try:
        max_words = int(raw.get("max_words", 20))
    except (TypeError, ValueError):
        max_words = 0
    if max_words < 1:
        from ..editorial import PolicyError

        raise PolicyError("context.title_card.max_words ist eine ganze Zahl ab 1.")
    return {"max_words": max_words}


def _active_policy() -> Policy | None:
    from .. import editorial

    try:
        return editorial.load()
    except editorial.PolicyError:
        return None


def _core_seq(text: str) -> list[str]:
    return [t for t in (dach_nlp.core_token(x) for x in str(text or "").split()) if t]


def _markers(text: str, phrases: tuple[str, ...]) -> list[str]:
    seq = _core_seq(text)
    out = []
    for p in phrases:
        pt = tuple(t for t in (dach_nlp.core_token(x) for x in p.split()) if t)
        if pt and any(tuple(seq[k : k + len(pt)]) == pt for k in range(len(seq) - len(pt) + 1)):
            out.append(p)
    return out


def dimension_markers(text: str) -> dict[str, list[str]]:
    """Marker je Dimension in ``text``: Zuschreibung, Verneinung, Sicherheit (Abschwächung), Bedingung und
    Einschränkung, Zahl (Rohform mit Einheit), Zeitbezug (Wendung oder Jahreszahl)."""
    numbers = [f"{m.raw}{_unit_label(m.unit)}" for m in number_mentions(text)]
    time = _markers(text, TIME_MARKERS) + _YEAR_RE.findall(text)
    return {
        "attribution": _markers(text, ATTRIBUTION_MARKERS),
        "negation": _markers(text, NEGATION_MARKERS),
        "certainty": _markers(text, HEDGES),
        "condition": _markers(text, CONDITION_MARKERS),
        "number": numbers,
        "time": time,
    }


def _content(text: str) -> set[str]:
    return {t for t in _core_seq(text) if len(t) > 3}


def _overlap(a: str, b: str) -> float:
    ca, cb = _content(a), _content(b)
    return len(ca & cb) / max(len(cb), 1)


def related_to_clip(source: str, clip_side: str) -> bool:
    """Bezieht sich ein Nachbarsatz auf den Clip? Kurz und elliptisch, mit Anschlusswort am Anfang oder mit
    lexikalischer Überlappung ab ``RELATED_OVERLAP`` (wie der Story-Graph)."""
    seq = _core_seq(source)
    if not seq:
        return False
    return len(seq) <= ELLIPTIC_WORDS or seq[0] in CONNECTOR_STARTS or _overlap(clip_side, source) >= RELATED_OVERLAP


def _number_differs(source: str, clip: str) -> list[str]:
    src, cl = number_mentions(source), number_mentions(clip)
    clip_units = {m.unit for m in cl}
    clip_values = {(m.value, m.unit) for m in cl}
    return [m.raw for m in src if m.unit in clip_units and (m.value, m.unit) not in clip_values]


def _finding(dimension: str, verdict: str, source: str | None = None, clip_quote: str | None = None,
             source_quote: str | None = None, span: dict | None = None, detail: str = "") -> dict:  # fmt: skip
    return {
        "dimension": dimension, "verdict": verdict, "source": source, "clip_quote": clip_quote,
        "source_quote": source_quote, "source_span": span, "detail": detail,
    }  # fmt: skip


DIMENSION_LABELS = {
    "attribution": "Zuschreibung", "negation": "Verneinung", "certainty": "Sicherheit", "condition": "Bedingung",
    "number": "Zahl", "time": "Zeitbezug", "causality": "Kausalität", "magnitude": "Größenordnung",
}  # fmt: skip


def context_findings(clip_first: str, clip_last: str, before: dict | None, after: dict | None) -> dict[str, dict]:
    """Je Dimension ein Befund aus dem Vergleich des Clips mit dem direkt angrenzenden Kontext desselben
    Sprechers (``before`` und ``after`` als ``{"text", "start_s", "end_s"}``): ``differs``, wenn der Nachbarsatz
    sich auf den Clip bezieht und einen Marker dieser Dimension trägt, den der Clip nicht hat (bei Zahlen: eine
    andere Zahl derselben Einheit)."""
    clip_all = f"{clip_first} {clip_last}"
    clip_marks = dimension_markers(clip_all)
    out: dict[str, dict] = {}
    for side, ctx, clip_side in (("context_before", before, clip_first), ("context_after", after, clip_last)):
        if not ctx or not related_to_clip(ctx["text"], clip_side):
            continue
        marks = dimension_markers(ctx["text"])
        span = {"start_s": ctx["start_s"], "end_s": ctx["end_s"]}
        for dim in COUNTER_DIMENSIONS:
            if dim in out:
                continue
            if dim == "number":
                extra = _number_differs(ctx["text"], clip_all)
            else:
                extra = [m for m in marks[dim] if m not in clip_marks[dim]]
            if extra:
                where = "davor" if side == "context_before" else "danach"
                out[dim] = _finding(
                    dim, "differs", side, clip_side, ctx["text"], span,
                    f"{DIMENSION_LABELS[dim]}: der Satz direkt {where} sagt „{extra[0]}“, der Clip nicht",
                )  # fmt: skip
    return out


def _best_sentence(hook: str, clip_text: str) -> str:
    sents = text_sentences(clip_text) or [clip_text]
    return max(sents, key=lambda s: (len(_content(hook) & _content(s)), -len(s)))


def hook_meaning_issues(hook_text: str, clip_text: str) -> list[dict]:
    """Regel 6: Ein Hook darf verdichten und gewichten, Zuschreibung, Sicherheit, Zeitraum, Größenordnung und
    Kausalität bleiben erhalten. Je Befund ``dimension``, ``hook_quote``, ``clip_quote`` und ``detail``.

    * Zuschreibung: der Hook spricht das Publikum an („du“, „dich“) oder verallgemeinert („man“, „diese
      Methode“), der Clip spricht von sich („ich“, „wir“) ohne diese Form; oder der Hook nennt eine Quelle
      („laut“), die der Clip nicht nennt.
    * Sicherheit: der Hook sagt absolut („garantiert“, „immer“), was der Clip nicht sagt, oder der passende
      Clipsatz schwächt ab („ich glaube“, „vielleicht“) und der Hook nicht.
    * Zeitraum: der Hook nennt einen Zeitbezug, den der Clip nicht nennt, oder lässt den Zeitbezug des passenden
      Clipsatzes weg, obwohl er dessen Zahl übernimmt.
    * Größenordnung: der passende Clipsatz nähert an („rund“, „etwa“, „fast“), der Hook nennt die Zahl ohne.
    * Kausalität: der Hook behauptet eine Ursache („kostet dich“, „weil“, „führt zu“), die der Clip nicht nennt.
    Das Beispiel aus Regel 6: „Rund 40.000 Euro Verlust in einer Woche“ ist zulässig, „Diese Methode kostet dich
    40.000 Euro“ verletzt Zuschreibung und Kausalität."""
    hook, clip = str(hook_text or ""), str(clip_text or "")
    if not hook.strip() or not clip.strip():
        return []
    best = _best_sentence(hook, clip)
    hook_seq, clip_seq = set(_core_seq(hook)), set(_core_seq(clip))
    issues: list[dict] = []

    def add(dim: str, quote: str, clip_quote: str, detail: str) -> None:
        issues.append({"dimension": dim, "hook_quote": quote, "clip_quote": clip_quote, "detail": detail})

    addressed = sorted((hook_seq & SECOND_PERSON) - clip_seq)
    generic = [g for g in _markers(hook, GENERIC_SUBJECTS) if g not in _markers(clip, GENERIC_SUBJECTS)]
    if (addressed or generic) and clip_seq & FIRST_PERSON:
        word = (addressed or generic)[0]
        add("attribution", word, best, f"Zuschreibung: der Hook macht mit „{word}“ eine allgemeine Aussage, der Clip spricht vom eigenen Fall")
    for m in _markers(hook, ATTRIBUTION_MARKERS):
        if m not in _markers(clip, ATTRIBUTION_MARKERS):
            add("attribution", m, best, f"Zuschreibung: „{m}“ steht so nicht im Clip")
    for m in _markers(hook, ABSOLUTES):
        if m not in _markers(clip, ABSOLUTES):
            add("certainty", m, best, f"Sicherheit: „{m}“ im Hook ist im Clip nicht gedeckt")
    hedges = _markers(best, HEDGES)
    if hedges and not _markers(hook, HEDGES):
        add("certainty", hook, hedges[0], f"Sicherheit: der Clip schwächt mit „{hedges[0]}“ ab, der Hook nicht")
    hook_time = _markers(hook, TIME_MARKERS) + _YEAR_RE.findall(hook)
    clip_time = _markers(clip, TIME_MARKERS) + _YEAR_RE.findall(clip)
    for t in hook_time:
        if t not in clip_time:
            add("time", t, best, f"Zeitraum: „{t}“ steht so nicht im Clip")
    best_time = _markers(best, TIME_MARKERS) + _YEAR_RE.findall(best)
    hook_numbers = {(m.value, m.unit) for m in number_mentions(hook)}
    best_numbers = {(m.value, m.unit) for m in number_mentions(best)}
    if best_time and not hook_time and hook_numbers & best_numbers:
        add("time", hook, best_time[0], f"Zeitraum: der Clip nennt „{best_time[0]}“, der Hook lässt ihn weg")
    approx = _markers(best, APPROXIMATORS)
    if approx and hook_numbers & best_numbers and not _markers(hook, APPROXIMATORS):
        add("magnitude", hook, approx[0], f"Größenordnung: der Clip sagt „{approx[0]}“, der Hook nennt die Zahl ohne")
    for c in _markers(hook, CAUSAL_MARKERS):
        if c not in _markers(clip, CAUSAL_MARKERS):
            add("causality", c, best, f"Kausalität: „{c}“ behauptet eine Ursache, die der Clip nicht nennt")
    return issues


def hook_findings(hook_text: str, clip_text: str) -> dict[str, dict]:
    """Je Dimension des Gegenlesers ein Befund aus ``hook_meaning_issues`` und dem Abgleich der Verneinung und
    Bedingung im passenden Clipsatz. Größenordnung zählt als ``number``, Kausalität steht nur in den Hinweisen
    zu Regel 6."""
    out: dict[str, dict] = {}
    if not str(hook_text or "").strip():
        return out
    for issue in hook_meaning_issues(hook_text, clip_text):
        dim = "number" if issue["dimension"] == "magnitude" else issue["dimension"]
        if dim in COUNTER_DIMENSIONS and dim not in out:
            out[dim] = _finding(dim, "differs", "hook", issue["clip_quote"], issue["hook_quote"], None, issue["detail"])
    best = _best_sentence(hook_text, clip_text)
    hook_m, best_m = dimension_markers(hook_text), dimension_markers(best)
    if "negation" not in out and bool(hook_m["negation"]) != bool(best_m["negation"]):
        out["negation"] = _finding("negation", "differs", "hook", best, hook_text, None, "Verneinung: Hook und Clipsatz unterscheiden sich in der Verneinung")
    if "condition" not in out and best_m["condition"] and not hook_m["condition"] and _overlap(best, hook_text) > 0:
        out["condition"] = _finding(
            "condition", "differs", "hook", best, hook_text, None,
            f"Bedingung: der Clipsatz schränkt mit „{best_m['condition'][0]}“ ein, der Hook nicht",
        )  # fmt: skip
    if "number" not in out:
        for issue in hook_claim_check_v2(hook_text, clip_text, meaning=False):
            if issue.startswith(("Zahl", "Mengenwort")):
                out["number"] = _finding("number", "differs", "hook", best, hook_text, None, issue)
                break
    return out


def counter_read(clip_sentences: list[dict], before: dict | None, after: dict | None, hook: str = "") -> dict[str, Any]:
    """Deterministischer Gegenleser (Regel 2 und 6): Clip gegen den angrenzenden Kontext und gegen den Hook.

    ``clip_sentences`` sind ``{"text", "start_s", "end_s"}``. Zurück ``findings`` (genau eine je Dimension aus
    ``COUNTER_DIMENSIONS``, ``verdict`` ``same`` oder ``differs``, Zitat aus Clip und Quelle, Quelle
    ``context_before``, ``context_after`` oder ``hook``), ``hook_meaning`` (Befunde zu Regel 6, auch Kausalität)
    und ``differs`` (die Dimensionen mit Befund). Gleich heißt nur: diese Regeln fanden nichts."""
    if not clip_sentences:
        return {"findings": [], "hook_meaning": [], "differs": []}
    first, last = clip_sentences[0]["text"], clip_sentences[-1]["text"]
    clip_text = " ".join(s["text"] for s in clip_sentences)
    ctx = context_findings(first, last, before, after)
    hk = hook_findings(hook, clip_text) if hook else {}
    findings = []
    for dim in COUNTER_DIMENSIONS:
        f = ctx.get(dim) or hk.get(dim)
        findings.append(f or _finding(dim, "same", detail=f"{DIMENSION_LABELS[dim]}: kein Unterschied nach den Regeln gefunden"))
    return {
        "findings": findings,
        "hook_meaning": hook_meaning_issues(hook, clip_text) if hook else [],
        "differs": [f["dimension"] for f in findings if f["verdict"] == "differs"],
    }


__all__ = [
    "COUNTER_DIMENSIONS",
    "COUNTER_READER_SWITCH",
    "TITLE_CARD_SWITCH",
    "CONTRAST_STARTS",
    "CONTRAST_STARTS_V2",
    "GENERALIZERS",
    "MAX_JOIN_GAP_S",
    "QUALIFIERS",
    "RESTRICTORS",
    "SUPERLATIVES",
    "NumberMention",
    "check_cut",
    "context_findings",
    "counter_read",
    "counter_reader_settings",
    "dimension_markers",
    "hook_findings",
    "hook_meaning_issues",
    "related_to_clip",
    "title_card_settings",
    "hook_claim_check",
    "hook_claim_check_v2",
    "number_mentions",
    "number_values",
    "parse_number_word",
    "phrase_hits",
    "quantity_words",
    "starts_with_contrast",
    "text_sentences",
    "uncertain_number_tokens",
    "unrecognized_number_words",
]
