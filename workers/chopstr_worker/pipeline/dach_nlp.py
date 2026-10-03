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
        log.warning("spaCy nicht installiert, Verbklammer-Prüfung nur heuristisch")
        return None
    for model in ("de_core_news_lg", "de_core_news_md", "de_core_news_sm"):
        try:
            pipe = spacy.load(model)
            verb_bracket_available = True
            return pipe
        except OSError:
            continue
    verb_bracket_available = False
    log.warning("Kein spaCy-Modell de_core_news_* gefunden, Verbklammer-Prüfung nur heuristisch")
    return None


def _strip_trailing(text: str) -> str:
    return text.rstrip(_TRAILING)


def core_token(text: str) -> str:
    """Kleinbuchstaben ohne Satzzeichen (für Listen-Abgleich)."""
    return re.sub(r"[^\wäöüß]", "", text.lower())


def is_abbreviation(text: str, rule: str = "v1") -> bool:
    """„z.", „Dr.", „usw." und „z.B.".

    Regel ``v2`` nimmt ``ABBREVIATIONS_V2`` und lässt einen einzelnen Buchstaben nur dann als
    Abkürzung gelten, wenn er in der Liste steht oder Teil einer Kette ist („i." beendet unter v2
    einen Satz, „z. B." nicht)."""
    t = _strip_trailing(text)
    if not t.endswith("."):
        return False
    base = t[:-1].lower().replace(" ", "")
    if not base:
        return False
    abbreviations = ABBREVIATIONS_V2 if rule == "v2" else ABBREVIATIONS
    if base in abbreviations:
        return True
    # Kettenabkürzungen wie „z.B." oder „u.s.w."
    parts = [p for p in base.split(".") if p]
    if rule == "v2" and len(parts) < 2:
        return False
    return bool(parts) and all(p in abbreviations or len(p) == 1 for p in parts)


def is_ordinal(text: str) -> bool:
    return bool(_ORDINAL.match(_strip_trailing(text)))


def is_sentence_end(
    words: list[dict],
    i: int,
    min_pause_s: float = 0.7,
    rule: str = "v1",
    max_s: float | None = None,
    max_words: int | None = None,
) -> bool:
    """Endet Wort ``i`` einen Satz? Adapter auf ``sentence_end_kind``.

    ``rule="v1"`` (Standard) liefert exakt das Verhalten vor AP2: Satzzeichen, Abkürzungen,
    Ordinal- und Dezimalzahlen, jede lange Pause und jeder Sprecherwechsel. ``rule="v2"`` siehe
    ``sentence_end_kind``."""
    return sentence_end_kind(words, i, rule=rule, min_pause_s=min_pause_s, max_s=max_s, max_words=max_words) != "none"


# -- Satzende-Regel v2 (AP2) und Verbklammer-Heuristik (AP3) --------------------------------------
#
# Eine Funktion für Zerlegung, Satzgrenzen-Tor und Messung (RESEARCH-CLIPPING-KERN Abschnitt 2,
# Befund 1). Regel v2: Satzzeichen zuerst, ein Sprecherwechsel ist eine Grenze, eine lange Pause nur
# ein Grenzkandidat. Angenommen wird er, wenn das Folgewort großgeschrieben ist und im laufenden Satz
# keine Klammer offen ist. Wird ein Satz zu lang (``max_s``, ``max_words``), gilt die nächste Pause
# ohne offene Klammer auch ohne Großschreibung, sonst die längste Pause im Fenster. Hat ein Transkript
# kaum Satzzeichen, gilt Regel v1 (``resolve_sentence_rule``). Der Port im Web
# (apps/web/lib/transcript/sentences.ts) muss gleich entscheiden; die gemeinsame Falldatei
# packages/editorial/parity/sentence_end_v1.json hält beide fest.

# Regel v1 als Rückfall für ein Transkript mit kaum Satzzeichen (ausgewiesen in stats und Rubrik).
FALLBACK_NO_PUNCT = "v1_fallback_no_punct"
# Regel v2 für Transkripte mit Kommas, aber kaum Satzendezeichen (typisch für deutsche Whisper-Ausgaben:
# ein Punkt am Ende, sonst Kommas vor kleingeschriebenem Wort, lückenlose Wortzeiten).
COMMA_HEAVY = "v2_comma_heavy"
SENTENCE_RULES = ("v1", "v2", FALLBACK_NO_PUNCT, COMMA_HEAVY)
# In diesen Regeln ist ein Komma mit passender Syntax ein Grenzkandidat (``comma_candidate``).
COMMA_RULES = (COMMA_HEAVY, FALLBACK_NO_PUNCT)
# Mindestlänge des laufenden Satzes in Wörtern, bevor ein Komma ihn beenden darf.
COMMA_MIN_WORDS = 6
# Rückgabewerte von ``sentence_end_kind``. ``end_of_text``: letztes Wort des Transkripts.
# ``length_cap``: der Satz war zu lang und ohne passende Pause, getrennt an der längsten Pause.
END_KINDS = ("punct", "speaker_change", "pause_candidate", "comma_candidate", "length_cap", "end_of_text", "none")
# Obergrenze der Satzlänge unter v2 (segmentation.max_sentence_s und max_sentence_words in der Policy).
MAX_SENTENCE_S = 25.0
MAX_SENTENCE_WORDS = 40
# Unter einem Satzzeichen je so vielen Wörtern gilt Regel v1 (FALLBACK_NO_PUNCT).
WORDS_PER_PUNCT_MIN = 40

# Wörter, die im gesprochenen Deutsch häufiger einen Satz beenden als etwas abkürzen
# („Das ist so.", „mit a i.", „Ich mag.", „Das ist das Max.").
ABBREVIATIONS_V2 = ABBREVIATIONS - {"so", "i", "mag", "max", "art", "min"}

# Verbpartikeln trennbarer Verben („Wir fangen morgen | an.").
VERB_PARTICLES = (
    "an", "auf", "aus", "ein", "mit", "zu", "ab", "vor", "nach", "zurück", "weg", "her", "hin", "los",
    "fest", "vorbei", "weiter",
)  # fmt: skip
# Nebensatzkonnektoren: das finite Verb steht am Ende des Nebensatzes.
SUBORDINATORS = (
    "dass", "weil", "wenn", "ob", "obwohl", "damit", "nachdem", "bevor", "als", "während", "falls",
    "sofern", "sodass",
)  # fmt: skip
# Finite Formen von haben, sein, werden und den Modalverben (Präsens, Präteritum, Konjunktiv II).
AUXILIARY_FORMS = (
    "hab", "habe", "hast", "hat", "haben", "habt", "hatte", "hattest", "hatten", "hattet",
    "hätte", "hättest", "hätten", "hättet",
    "bin", "bist", "ist", "sind", "seid", "war", "warst", "waren", "wart", "wäre", "wärst", "wären", "wärt",
    "werde", "wirst", "wird", "werden", "werdet", "wurde", "wurdest", "wurden", "wurdet",
    "würde", "würdest", "würden", "würdet",
    "kann", "kannst", "können", "könnt", "konnte", "konntest", "konnten", "konntet",
    "könnte", "könntest", "könnten", "könntet",
    "muss", "musst", "müssen", "müsst", "musste", "musstest", "mussten", "musstet",
    "müsste", "müsstest", "müssten", "müsstet",
    "will", "willst", "wollen", "wollt", "wollte", "wolltest", "wollten", "wolltet",
    "soll", "sollst", "sollen", "sollt", "sollte", "solltest", "sollten", "solltet",
    "darf", "darfst", "dürfen", "dürft", "durfte", "durftest", "durften", "durftet",
    "dürfte", "dürftest", "dürften", "dürftet",
    "mag", "magst", "mögen", "mögt", "mochte", "mochtest", "mochten", "mochtet",
    "möchte", "möchtest", "möchten", "möchtet",
)  # fmt: skip
# Endet der laufende Satz vor der Pause auf einem dieser Wörter, ist er nicht zu Ende: Artikel,
# Präposition ohne Partikelgebrauch, Nebensatzkonnektor. „ein" nur, wenn im Satz kein Vollverb steht
# („Wir kaufen morgen ein" ist zu Ende). Bewusst NICHT dabei: „das" (auch Demonstrativpronomen, „Ich
# weiß das."), Präpositionen, die zugleich Verbpartikel sind („Wir fangen an."), und beiordnende
# Konjunktionen. Ein „aber" vor Pause und großgeschriebenem Neuanfang ist ein abgebrochener Satz, kein
# offener (transcript_fixtures.DEMO_SCRIPT, Satz 11).
PAUSE_OPEN_END_WORDS = frozenset(
    {"ein", "eine", "einen", "einem", "einer", "eines", "des", "der", "dem", "den"}
    | {
        "bei", "von", "zum", "zur", "für", "gegen", "ohne", "in", "im", "ins", "am", "ans", "beim", "vom",
        "seit", "zwischen", "hinter", "neben", "wegen", "trotz", "aufs", "fürs", "bis",
    }
    | set(SUBORDINATORS)
)  # fmt: skip

_LEADING = "\"'„»«“”‘’([{"
_CLOSERS = "\"'»«“”‘’)]}"
_PARTICIPLE = re.compile(
    r"^(?:"
    r"[a-zäöüß]*ge[a-zäöüß]{3,}(?:t|en)"
    r"|(?:vor|an|zu|auf|ab|aus|ein|nach|mit)?(?:be|ver|er|ent|zer|emp|miss)[a-zäöüß]{3,}(?:t|en)"
    r"|(?:über|unter|wider|hinter|voll)[a-zäöüß]{3,}(?:t|en)"
    r"|[a-zäöüß]{3,}iert"
    r"|getan"
    r")$"
)
_INFINITIVE = re.compile(r"^[a-zäöüß]{2,}(?:en|ern|eln)$")
_VERB_LIKE = re.compile(r"^[a-zäöüß]{2,}(?:e|st|t|en|ern|eln|te|ten)$")
# Wörter in Partizip-Gestalt, die als Adjektiv oder Adverb stehen.
_NOT_PARTICIPLE = frozenset(
    {"insgesamt", "bestimmt", "bereit", "bekannt", "gestern", "überhaupt", "derzeit", "beliebt", "verschieden"}
)  # fmt: skip
_NOT_INFINITIVE = frozenset(
    {
        "einen", "keinen", "meinen", "deinen", "seinen", "ihren", "unseren", "euren", "diesen", "jenen",
        "welchen", "allen", "vielen", "wenigen", "anderen", "eben", "neben", "gegen", "wegen", "oben",
        "unten", "morgen", "denen", "deren", "ihnen", "seiten", "trotzdem", "zusammen", "dafür",
        "stattdessen", "indessen", "unterdessen", "währenddessen", "deswegen", "weswegen", "übrigen",
        "gestern", "selten", "innen", "außen", "hinten", "vorn", "vorne", "drinnen", "draußen",
    }
)  # fmt: skip
# Begleiter auf -e, die keine Verbform sind („dass wir die | Kunden …").
_DETERMINERS_E = frozenset(
    {"die", "eine", "keine", "meine", "deine", "seine", "ihre", "unsere", "eure", "diese", "jene", "welche", "alle", "viele", "manche", "einige", "beide"}
)  # fmt: skip
# Großgeschrieben am Anfang des Folgeteils zeigen diese Wörter einen neuen Satz an (ein Nomen dagegen
# ist auch mitten im Satz groß): Artikel, Pronomen, Konjunktionen, Satzadverbien.
_NEW_SENTENCE_STARTERS = frozenset(
    {
        "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem", "einer", "und", "aber",
        "oder", "denn", "doch", "jetzt", "dann", "heute", "jeder", "jede", "jedes", "ich", "du", "er", "sie",
        "es", "wir", "man", "so", "also", "deshalb", "deswegen", "da", "hier", "dort", "was", "wer", "wie",
        "wo", "warum", "seitdem", "danach", "außerdem", "trotzdem", "allerdings", "wobei", "nein", "ja",
        "genau", "okay", "gut", "dieser", "diese", "dieses", "unser", "unsere", "mein", "meine", "kein",
        "keine", "niemand", "alle", "viele",
    }
)  # fmt: skip
# Personalpronomen; gefolgt von einem Verb beginnt rechts ein neuer Satz („… | Und wir wachsen.").
_PERSONAL_PRONOUNS = frozenset({"ich", "du", "er", "sie", "es", "wir", "ihr", "man"})
_BRACKET_MAX_WORDS = 40
_RIGHT_SCAN_WORDS = 10


def _text(w: dict | str) -> str:
    return str(w.get("text", "") if isinstance(w, dict) else w).strip()


def _base_rule(rule: str) -> str:
    """``v1`` oder ``v2``; ``v1_fallback_no_punct`` entscheidet wie ``v1``, ``v2_comma_heavy`` wie ``v2``."""
    if rule not in SENTENCE_RULES:
        raise ValueError(f"unbekannte Satzende-Regel {rule!r} (erlaubt: {', '.join(SENTENCE_RULES)})")
    return "v2" if rule in ("v2", COMMA_HEAVY) else "v1"


def _ends_with_ellipsis(text: str) -> bool:
    t = text.rstrip(_CLOSERS)
    return t.endswith(("…", "..."))


def _has_terminal_punct(text: str, rule: str = "v2") -> bool:
    """Steht am Wort ein echtes Satzzeichen (ohne Abkürzung, Ordinalzahl, Auslassungspunkte)?"""
    if _ends_with_ellipsis(text):
        return False
    stripped = _strip_trailing(text)
    if stripped.endswith(("!", "?")):
        return True
    return stripped.endswith(".") and not is_ordinal(stripped) and not is_abbreviation(stripped, _base_rule(rule))


def _ends_open_clause(text: str) -> bool:
    """Komma, Semikolon oder Doppelpunkt am Wort: der Teilsatz geht weiter („Passen Sie auf, äh,")."""
    return text.rstrip(_CLOSERS).endswith((",", ";", ":"))


def _ends_clause(text: str) -> bool:
    return text.rstrip(_CLOSERS).endswith((",", ";", ":", ".", "!", "?"))


def _is_lower(text: str) -> bool:
    t = text.lstrip(_LEADING)
    return bool(t[:1]) and t[:1].islower()


def _is_upper(text: str) -> bool:
    t = text.lstrip(_LEADING)
    return bool(t[:1]) and t[:1].isupper()


def _is_noun_like(w) -> bool:
    """Großgeschrieben und kein typischer Satzanfang: vermutlich ein Nomen."""
    t = _text(w)
    return _is_upper(t) and core_token(t) not in _NEW_SENTENCE_STARTERS


def is_participle(text: str) -> bool:
    """Partizip II, kleingeschrieben („gemacht", „angefangen", „vorbereitet", „verloren", „getan")."""
    tok = core_token(text)
    return _is_lower(text) and tok not in _NOT_PARTICIPLE and bool(_PARTICIPLE.match(tok))


def is_infinitive(text: str) -> bool:
    """Infinitiv, kleingeschrieben („machen", „ändern"); Artikel- und Adverbformen ausgenommen."""
    tok = core_token(text)
    return _is_lower(text) and tok not in _NOT_INFINITIVE and bool(_INFINITIVE.match(tok))


def _adjective_before_noun(seq: list, k: int) -> bool:
    """Steht ``seq[k]`` mit Adjektivendung direkt vor einem Nomen („einen großen | Fehler")?"""
    if k + 1 >= len(seq) or _ends_clause(_text(seq[k])):
        return False
    return core_token(_text(seq[k])).endswith(("e", "en", "er", "es", "em")) and _is_noun_like(seq[k + 1])


def _clause(words: list, clause_level: bool) -> list:
    """Die Wörter nach dem letzten Satzende (``clause_level``: auch nach Komma, Semikolon, Doppelpunkt)
    vor dem letzten Wort; das letzte Wort gehört dazu. Satzende heißt echtes Satzzeichen, also nicht
    nach Abkürzung oder Ordinalzahl („am 3. Oktober", „mit Dr. Müller", „z. B.")."""
    start = 0
    for j in range(len(words) - 1):
        t = _text(words[j])
        if _has_terminal_punct(t) or (clause_level and _ends_open_clause(t)):
            start = j + 1
    return list(words[start:])


def bracket_heuristic(
    left_words: list,
    right_words: list,
    particles: tuple[str, ...] | list[str] | None = None,
    subordinators: tuple[str, ...] | list[str] | None = None,
    auxiliaries: tuple[str, ...] | list[str] | None = None,
) -> dict:
    """Ist zwischen ``left_words`` und ``right_words`` eine Satzklammer offen? Ohne spaCy.

    Drei Signale, jedes nur bei eindeutiger Lage (Plan AP3):
      (a) trennbares Verb: rechts beginnt kleingeschrieben eine Verbpartikel mit Satzzeichen
          („an."), links steht ein Verb;
      (b) Nebensatz: links steht im laufenden Teilsatz ein Konnektor („dass", „weil") und danach kein
          verbähnliches Wort;
      (c) Hilfs- oder Modalverb: links steht ein finites Hilfs- oder Modalverb ohne schließendes
          Partizip oder Infinitiv, rechts folgt im selben Satz kleingeschrieben ein Partizip oder ein
          Infinitiv am Satzende, bevor ein neues finites Hilfsverb oder ein neuer Satz (großgeschriebener
          Satzanfang, Personalpronomen mit Verb) kommt.
    Adjektive vor einem Nomen („einen großen | Fehler") zählen weder als Partizip noch als Infinitiv.
    Rückgabe ``{open, signal, detail, available: "heuristic"}``."""
    particles = tuple(particles or VERB_PARTICLES)
    subordinators = tuple(subordinators or SUBORDINATORS)
    auxiliaries = frozenset(auxiliaries or AUXILIARY_FORMS)
    left = [w for w in left_words if _text(w)]
    right = [w for w in right_words if _text(w)]
    out = {"open": False, "signal": None, "detail": "keine offene Klammer erkannt", "available": "heuristic"}
    if not left or not right:
        return out
    lw, rw = left[-1], right[0]
    if isinstance(lw, dict) and isinstance(rw, dict):
        ls, rs = lw.get("speaker"), rw.get("speaker")
        if ls is not None and rs is not None and ls != rs:
            return out  # Eine Klammer reicht nicht über einen Sprecherwechsel.
    if _has_terminal_punct(_text(lw)):
        return out

    def verb_like(seq: list, k: int) -> bool:
        t = _text(seq[k])
        tok = core_token(t)
        if tok in _DETERMINERS_E or _adjective_before_noun(seq, k):
            return False
        return tok in auxiliaries or is_participle(t) or (_is_lower(t) and bool(_VERB_LIKE.match(tok)))

    # (a) trennbares Verb
    r0 = _text(rw)
    if _is_lower(r0) and core_token(r0) in particles and r0.rstrip(_CLOSERS).endswith((",", ";", ":", ".", "!", "?")):
        sentence = _clause(left, clause_level=False)
        if any(verb_like(sentence, k) for k in range(len(sentence))):
            return {
                "open": True,
                "signal": "separable_particle",
                "detail": f"Verbpartikel „{core_token(r0)}“ gehört zum Verb davor",
                "available": "heuristic",
            }

    # (b) Nebensatz ohne Verb nach dem Konnektor
    if not _ends_open_clause(_text(lw)):
        part = _clause(left, clause_level=True)
        at = next((k for k, w in enumerate(part) if core_token(_text(w)) in subordinators), None)
        if at is not None and not any(verb_like(part, k) for k in range(at + 1, len(part))):
            return {
                "open": True,
                "signal": "subordinate_clause",
                "detail": f"Nebensatz mit „{core_token(_text(part[at]))}“ ohne Verb am Ende",
                "available": "heuristic",
            }

    # (c) finites Hilfs- oder Modalverb ohne schließendes Partizip oder Infinitiv
    if _is_upper(r0) and core_token(r0) in _NEW_SENTENCE_STARTERS:
        return out  # rechts beginnt ein neuer Satz („Er hat recht | Die Kunden warten.")
    sentence = _clause(left, clause_level=False)
    aux_at = max((k for k, w in enumerate(sentence) if core_token(_text(w)) in auxiliaries), default=None)
    if aux_at is None:
        return out
    # Steht das Hilfsverb am Ende eines Nebensatzes („weil das Preismodell falsch war"), ist es verbletzt
    # und schließt den Nebensatz; es öffnet keine Klammer.
    part = _clause(left, clause_level=True)
    aux_in_part = next((k for k, w in enumerate(part) if w is sentence[aux_at]), None)
    if aux_in_part is not None and any(core_token(_text(w)) in subordinators for w in part[:aux_in_part]):
        return out
    # Ein Partizip schließt überall, ein Infinitiv nur am Ende („haben dann stattdessen" bleibt offen),
    # und keines von beiden, wenn es als Adjektiv vor einem Nomen steht.
    joined = sentence + right[:1]
    tail = range(aux_at + 1, len(sentence))
    closed = any(is_participle(_text(sentence[k])) and not _adjective_before_noun(joined, k) for k in tail)
    if len(sentence) > aux_at + 1 and is_infinitive(_text(sentence[-1])) and not _adjective_before_noun(joined, len(sentence) - 1):
        closed = True
    if closed:
        return out
    scan = right[:_RIGHT_SCAN_WORDS]
    for k, w in enumerate(scan):
        t = _text(w)
        tok = core_token(t)
        if tok in auxiliaries:
            break
        if tok in _PERSONAL_PRONOUNS and k + 1 < len(scan) and verb_like(scan, k + 1):
            break  # Personalpronomen mit Verb: neuer Satz
        if not _adjective_before_noun(scan, k):
            final = t.rstrip(_CLOSERS).endswith((",", ";", ":", ".", "!", "?"))
            if is_participle(t) or (is_infinitive(t) and final):
                return {
                    "open": True,
                    "signal": "auxiliary_bracket",
                    "detail": f"„{_text(sentence[aux_at])}“ und „{tok}“ gehören zusammen",
                    "available": "heuristic",
                }
        if _has_terminal_punct(t):
            break
    return out


def resolve_sentence_rule(words: list[dict], rule: str) -> str:
    """Die Regel, die für dieses Transkript gilt: unter ``v2`` mit weniger als einem Satzendezeichen
    (. ! ?) je ``WORDS_PER_PUNCT_MIN`` Wörtern ``v2_comma_heavy``, wenn wenigstens ebenso viele Kommas da
    sind (Kommas tragen die Zerlegung), sonst ``v1_fallback_no_punct`` (Zerlegung wie v1); sonst die
    Regel selbst."""
    _base_rule(rule)
    if rule != "v2" or not words:
        return rule
    punct = sum(1 for w in words if _has_terminal_punct(_text(w)))
    if punct * WORDS_PER_PUNCT_MIN >= len(words):
        return "v2"
    commas = sum(1 for w in words if _text(w).rstrip(_CLOSERS).endswith(","))
    return COMMA_HEAVY if commas * WORDS_PER_PUNCT_MIN >= len(words) else FALLBACK_NO_PUNCT


def _running_sentence(words: list[dict], i: int, rule: str) -> list[dict]:
    """Die Wörter des laufenden Satzes bis einschließlich ``i`` (nach Satzzeichen, höchstens 40)."""
    a = i
    while a > 0 and i - a < _BRACKET_MAX_WORDS and not _has_terminal_punct(_text(words[a - 1]), rule):
        a -= 1
    return words[a : i + 1]


def _ends_open(sentence: list[dict]) -> bool:
    """Endet der Satz auf Artikel, Präposition oder Konnektor (``PAUSE_OPEN_END_WORDS``)?"""
    tok = core_token(_text(sentence[-1]))
    if tok not in PAUSE_OPEN_END_WORDS:
        return False
    if tok == "ein":  # auch Verbpartikel („kaufen … ein"): nur offen, wenn im Satz kein Vollverb steht
        return not any(
            core_token(_text(w)) not in AUXILIARY_FORMS
            and core_token(_text(w)) not in _DETERMINERS_E
            and _is_lower(_text(w))
            and bool(_VERB_LIKE.match(core_token(_text(w))))
            for w in sentence[:-1]
        )
    return True


def _pause_boundary_accepted(words: list[dict], i: int, rule: str) -> bool:
    """Grenzkandidat aus einer Pause: angenommen nur mit großgeschriebenem Folgewort und ohne offene Klammer."""
    if not _is_upper(_text(words[i + 1])) or _ends_open_clause(_text(words[i])):
        return False
    left = _running_sentence(words, i, rule)
    if _ends_open(left):
        return False
    return not bracket_heuristic(left, words[i + 1 : i + 1 + _RIGHT_SCAN_WORDS])["open"]


def _gap(words: list[dict], j: int) -> float:
    return float(words[j + 1].get("start", 0.0)) - float(words[j].get("end", 0.0))


def _mag_title(words: list[dict], i: int, min_pause_s: float) -> bool:
    """Unter v2 ist „Mag." (Magister) nur Abkürzung, wenn das Folgewort großgeschrieben ist, am Wort kein
    weiteres Satzzeichen steht, weder Pause noch Sprecherwechsel folgt und davor kein Personalpronomen
    steht („Ich bin Mag. Huber" ja; „Ich mag." und „Das mag. | Aber" mit Pause nein)."""
    text = _text(words[i])
    if text.lstrip(_LEADING).lower() != "mag." or i + 1 >= len(words):
        return False
    nxt = words[i + 1]
    if not _is_upper(_text(nxt)) or _gap(words, i) >= min_pause_s:
        return False
    if nxt.get("speaker") is not None and nxt.get("speaker") != words[i].get("speaker"):
        return False
    return not (i > 0 and core_token(_text(words[i - 1])) in _PERSONAL_PRONOUNS)


def _base_kind(words: list[dict], i: int, rule: str, min_pause_s: float, relaxed: bool = False) -> str:
    """Satzende-Art ohne Längen- und Kommagrenze (Regel v1 oder v2). ``relaxed`` (``v2_comma_heavy``): eine
    Pause ohne offene Klammer gilt auch vor kleingeschriebenem Wort, weil die Großschreibung dort nichts
    über den Satzanfang sagt."""
    w = words[i]
    text = str(w.get("text", "")).strip()
    nxt = words[i + 1] if i + 1 < len(words) else None
    if nxt is None:
        return "end_of_text"
    speaker_change = nxt.get("speaker") is not None and nxt.get("speaker") != w.get("speaker")
    stripped = _strip_trailing(text)
    if rule == "v2" and _ends_with_ellipsis(text):
        pass  # Abbruch, kein Satzzeichen: Sprecherwechsel und Pause entscheiden
    elif stripped.endswith(("!", "?", "…")):
        return "punct"
    elif stripped.endswith("."):
        nxt_text = str(nxt.get("text", "")).strip()
        # Dezimalzahl über Wortgrenze („2." + „4") oder Ordinal/Datum („3." + „Platz", „12." + „Oktober")
        if not (
            is_ordinal(stripped)
            or nxt_text[:1].isdigit()
            or is_abbreviation(stripped, rule)
            or (rule == "v2" and _mag_title(words, i, min_pause_s))
        ):
            return "punct"
    if speaker_change:
        return "speaker_change"
    if _gap(words, i) >= min_pause_s:
        if rule == "v1" or _pause_boundary_accepted(words, i, rule):
            return "pause_candidate"
        if relaxed and _soft_candidate(words, i - len(_running_sentence(words, i, rule)) + 1, i, min_pause_s):
            return "pause_candidate"
    return "none"


def _too_long(words: list[dict], start: int, j: int, max_s: float, max_words: int) -> bool:
    return j - start + 1 >= max_words or float(words[j].get("end", 0.0)) - float(words[start].get("start", 0.0)) >= max_s


def _soft_candidate(words: list[dict], start: int, j: int, min_pause_s: float) -> bool:
    """Pause ohne offene Klammer, ohne Großschreibung des Folgeworts (nur bei zu langem Satz)."""
    if _gap(words, j) < min_pause_s:
        return False
    left = words[max(start, j - _BRACKET_MAX_WORDS + 1) : j + 1]
    if _ends_open(left):
        return False
    return not bracket_heuristic(left, words[j + 1 : j + 1 + _RIGHT_SCAN_WORDS])["open"]


# Relativpronomen und Fragewörter, mit denen nach einem Komma ein Nebensatz beginnt.
_RELATIVE_WORDS = frozenset(
    {"welcher", "welche", "welches", "welchen", "welchem", "wo", "was", "wobei", "denen", "deren", "dessen", "wie"}
)  # fmt: skip
# „der", „die", „das" … sind Relativpronomen, außer vor einem Nomen (Artikel) oder vor einem finiten Verb
# (Demonstrativpronomen als Subjekt eines Hauptsatzes: „das heisst", „das ist").
_D_WORDS = frozenset({"der", "die", "das", "dem", "den"})
# Kleingeschriebene Wörter in Verbgestalt (-t, -st, -e, -en), die kein Verb sind.
_NON_VERBS = frozenset(
    {
        "nicht", "jetzt", "erst", "zuerst", "selbst", "sonst", "meist", "meistens", "oft", "gut", "mit", "bitte",
        "heute", "gerade", "ganz", "ganze", "recht", "leicht", "schlecht", "echt", "vielleicht", "nachts",
        "längst", "fast", "jede", "jeden", "jedem", "letzte", "letzten", "erste", "ersten", "beste", "besten",
        "mehrere", "andere", "gleiche", "gleichen", "eigene", "eigenen", "neue", "neuen", "große", "großen",
        "kleine", "kleinen", "halbe", "zuletzt", "insgesamt", "bereits", "genau", "seit", "bisschen",
    }
)  # fmt: skip


def _is_finite_verb(seq: list, k: int) -> bool:
    """Grob: Hilfs- oder Modalverb, oder kleingeschriebenes Wort mit Verbendung, das kein Partizip,
    kein Begleiter, kein bekanntes Adverb und kein Adjektiv vor einem Nomen ist."""
    t = _text(seq[k])
    tok = core_token(t)
    if tok in AUXILIARY_FORMS:
        return True
    if not _is_lower(t) or tok in _NON_VERBS or tok in _DETERMINERS_E or tok in _NOT_INFINITIVE or tok in _NOT_PARTICIPLE:
        return False
    if is_participle(t) or _adjective_before_noun(seq, k):
        return False
    return bool(_VERB_LIKE.match(tok))


def _has_finite_verb(seq: list) -> bool:
    return any(_is_finite_verb(seq, k) for k in range(len(seq)))


def _next_clause(words: list[dict], j: int) -> list[dict]:
    """Die Wörter nach Wort ``j`` bis zum nächsten Komma oder Satzzeichen (höchstens 15)."""
    out = []
    for w in words[j + 1 : j + 16]:
        out.append(w)
        if _ends_clause(_text(w)):
            break
    return out


def _is_comma(w: dict) -> bool:
    return _text(w).rstrip(_CLOSERS).endswith(",")


def _comma_boundary(words: list[dict], start: int, j: int, min_words: int = COMMA_MIN_WORDS) -> bool:
    """Beendet das Komma an Wort ``j`` den Satz, der bei ``start`` beginnt (``v2_comma_heavy`` und Rückfall)?

    Ja, wenn der laufende Satz mindestens ``min_words`` Wörter hat, der Teilsatz davor und der danach je ein
    finites Verb haben (kein Nachtrag wie „dann der Preis."), keine Klammer offen ist, das Folgewort weder
    Nebensatzkonnektor noch Relativpronomen ist und keine Aufzählung vorliegt (zwei Nomen ohne Verb danach)."""
    if j + 1 >= len(words) or not _is_comma(words[j]) or j - start + 1 < min_words:
        return False
    nxt = words[j + 1]
    if nxt.get("speaker") is not None and nxt.get("speaker") != words[j].get("speaker"):
        return False
    tok = core_token(_text(nxt))
    if tok in SUBORDINATORS or tok in _RELATIVE_WORDS:
        return False
    after_verb = j + 2 < len(words) and _is_finite_verb(words, j + 2)
    if tok in _D_WORDS and not (after_verb or (j + 2 < len(words) and _is_noun_like(words[j + 2]))):
        return False
    if _is_noun_like(words[j]) and _is_noun_like(nxt) and not after_verb:
        return False  # Aufzählung („Brot, Butter und Milch")
    left = words[start : j + 1]
    if not _has_finite_verb(_clause(left, clause_level=True)):
        return False
    if not _has_finite_verb(_next_clause(words, j)):
        return False
    return not bracket_heuristic(left[-_BRACKET_MAX_WORDS:], words[j + 1 : j + 1 + _RIGHT_SCAN_WORDS])["open"]


def _length_breaks(words: list[dict], h: int, stop: int, min_pause_s: float, max_s: float, max_words: int) -> dict[int, str]:
    """Zusätzliche Satzenden in der Strecke ``h`` bis ``stop`` (``stop`` ist ein Satzende ohne
    Längengrenze). Ab ``max_s`` oder ``max_words`` gilt die nächste Pause ohne offene Klammer oder das
    nächste Komma mit passender Syntax. Gibt es keines, trennt das nächste Komma; ohne Komma bleibt ein
    Satz, der vor der doppelten Grenze endet, sonst trennt die längste Pause (bei lückenlosen Wortzeiten
    das Wort an der Grenze). Kein Satz wächst über die doppelte Grenze."""
    out: dict[int, str] = {}
    start = h
    while start < stop:
        cap = next((c for c in range(start, stop + 1) if _too_long(words, start, c, max_s, max_words)), None)
        if cap is None or cap >= stop:
            break
        window_end = next((e for e in range(cap, stop + 1) if _too_long(words, start, e, 2 * max_s, 2 * max_words)), stop)
        last = min(window_end, stop - 1)
        k = next(
            (j for j in range(cap, last + 1) if _soft_candidate(words, start, j, min_pause_s) or _comma_boundary(words, start, j, 0)),
            None,
        )
        if k is not None:
            out[k] = "pause_candidate" if _gap(words, k) >= min_pause_s else "comma_candidate"
        else:
            k = next((j for j in range(cap, last + 1) if _is_comma(words[j])), None)
            if k is None and window_end >= stop:
                break  # kein Komma, und der Satz endet ohnehin innerhalb der doppelten Grenze
            if k is None:
                k = max(range(cap, last + 1), key=lambda j: (round(_gap(words, j), 2), -j))
            out[k] = "length_cap"
        start = k + 1
    return out


def _stretch_breaks(
    words: list[dict], h: int, stop: int, rule: str, min_pause_s: float, max_s: float, max_words: int
) -> dict[int, str]:
    """Satzenden in der Strecke ``h`` bis ``stop`` aus Kommas (nur ``COMMA_RULES``) und der Längengrenze."""
    out: dict[int, str] = {}
    segments = []
    start = h
    if rule in COMMA_RULES:
        for j in range(h, stop):
            if _comma_boundary(words, start, j):
                out[j] = "comma_candidate"
                segments.append((start, j))
                start = j + 1
    segments.append((start, stop))
    for a, b in segments:
        out.update(_length_breaks(words, a, b, min_pause_s, max_s, max_words))
    return out


def sentence_end_kinds(
    words: list[dict],
    rule: str = "v2",
    min_pause_s: float = 0.7,
    max_s: float | None = None,
    max_words: int | None = None,
) -> list[str]:
    """``sentence_end_kind`` für alle Wörter in einem Durchgang (Zerlegung)."""
    base = _base_rule(rule)
    relaxed = rule == COMMA_HEAVY
    kinds = [_base_kind(words, i, base, min_pause_s, relaxed) for i in range(len(words))]
    if rule == "v1":
        return kinds
    max_s = MAX_SENTENCE_S if max_s is None else float(max_s)
    max_words = MAX_SENTENCE_WORDS if max_words is None else int(max_words)
    h = 0
    for i, k in enumerate(kinds):
        if k != "none":
            for j, kind in _stretch_breaks(words, h, i, rule, min_pause_s, max_s, max_words).items():
                kinds[j] = kind
            h = i + 1
    return kinds


def sentence_end_kind(
    words: list[dict],
    i: int,
    rule: str = "v2",
    min_pause_s: float = 0.7,
    max_s: float | None = None,
    max_words: int | None = None,
) -> str:
    """Art des Satzendes nach Wort ``i``: ``punct``, ``speaker_change``, ``pause_candidate``,
    ``length_cap``, ``end_of_text`` oder ``none`` (kein Satzende).

    Regel ``v1``: das Verhalten vor AP2. Jede Pause ab ``min_pause_s`` gilt als ``pause_candidate`` und
    damit als Satzende; Abkürzungen nach ``ABBREVIATIONS``. ``v1_fallback_no_punct`` (Regel v2 bei
    kaum Satzzeichen) entscheidet wie v1, mit der Längengrenze von v2.

    Regel ``v2``: Satzzeichen zuerst (Abkürzung nach ``ABBREVIATIONS_V2``, Ordinal- und Dezimalzahl
    wie bisher; Auslassungspunkte sind kein Satzzeichen, sondern ein Abbruch). Ein Sprecherwechsel ist
    eine Grenze. Eine Pause ab ``min_pause_s`` ist nur ein Kandidat: ``pause_candidate`` nur, wenn das
    Folgewort großgeschrieben ist, der Satz nicht auf Artikel, Präposition oder Nebensatzkonnektor
    endet und ``bracket_heuristic`` keine offene Klammer findet. Wird der Satz länger als ``max_s``
    Sekunden oder ``max_words`` Wörter (Standard 25 und 40), gilt die nächste Pause ohne offene Klammer
    auch vor kleingeschriebenem Wort, sonst bis zur doppelten Grenze die längste Pause (``length_cap``)."""
    base = _base_rule(rule)
    relaxed = rule == COMMA_HEAVY
    kind = _base_kind(words, i, base, min_pause_s, relaxed)
    if rule == "v1" or kind != "none":
        return kind
    h = i
    while h > 0 and _base_kind(words, h - 1, base, min_pause_s, relaxed) == "none":
        h -= 1
    stop = i + 1
    while _base_kind(words, stop, base, min_pause_s, relaxed) == "none":
        stop += 1
    max_s = MAX_SENTENCE_S if max_s is None else float(max_s)
    max_words = MAX_SENTENCE_WORDS if max_words is None else int(max_words)
    return _stretch_breaks(words, h, stop, rule, min_pause_s, max_s, max_words).get(i, "none")


def cut_boundary_kind(
    words: list[dict],
    i: int,
    rule: str = "v2",
    min_pause_s: float = 0.7,
    max_s: float | None = None,
    max_words: int | None = None,
) -> str:
    """Satzende-Art für einen Schnitt nach Wort ``i`` (Satzgrenzen-Tor, Messung, Anfang heilen).

    Wie ``sentence_end_kind``; unter ``v2`` gilt ein Sprecherwechsel nach Komma, Semikolon oder
    Doppelpunkt nicht als Satzende des Sprechers (Einwurf des Gegenübers mitten im Satz, „Ich bin da
    ganz ehrlich," | „Okay." | „ich hänge …"). Die Zerlegung trennt dort weiter nach Sprecher."""
    kind = sentence_end_kind(words, i, rule, min_pause_s, max_s, max_words)
    if _base_rule(rule) == "v2" and kind == "speaker_change" and _ends_open_clause(_text(words[i])):
        return "none"
    return kind


def bracket_open_at_cut(
    words: list[dict],
    cut_word_idx: int,
    rule: str = "v2",
    fallback: str = "heuristic",
    lists: dict | None = None,
) -> dict:
    """Ist an einem Schnitt vor Wort ``cut_word_idx`` eine Verbklammer offen?

    Geprüft wird der Text aus Vorsatz und Folgesatz zusammen, nicht ein Satz für sich (Befund 2: so
    war das Tor per Konstruktion immer legal). Mit spaCy über ``forbidden_cut_ranges`` auf dem
    verbundenen Text, ohne spaCy über ``bracket_heuristic`` (``fallback="heuristic"``); mit
    ``fallback="off"`` und ohne spaCy wird nichts geprüft und das auch so gemeldet.
    Rückgabe ``{open, signal, detail, available: "spacy" | "heuristic" | "off"}``."""
    if cut_word_idx <= 0 or cut_word_idx >= len(words):
        return {"open": False, "signal": None, "detail": "Schnitt am Rand des Transkripts", "available": "none"}
    left = _running_sentence(words, cut_word_idx - 1, rule)
    right = words[cut_word_idx : cut_word_idx + _BRACKET_MAX_WORDS]
    pipe = nlp()
    if pipe is not None:
        joined = left + right
        ranges = forbidden_cut_ranges(" ".join(_text(x) for x in joined), joined)
        t = (float(left[-1].get("end", 0.0)) + float(right[0].get("start", 0.0))) / 2.0
        if not cut_is_legal(t, ranges):
            return {"open": True, "signal": "spacy", "detail": "Schnitt in einer Verbklammer", "available": "spacy"}
        return {"open": False, "signal": None, "detail": "keine offene Klammer", "available": "spacy"}
    if fallback != "heuristic":
        return {"open": False, "signal": None, "detail": "nicht geprüft", "available": "off"}
    lists = lists or {}
    return bracket_heuristic(
        left,
        right,
        particles=lists.get("particles"),
        subordinators=lists.get("subordinators"),
        auxiliaries=lists.get("auxiliaries"),
    )


def sentence_boundaries(words: list[dict], min_pause_s: float = 0.7, rule: str = "v1") -> list[int]:
    """Indizes der Wörter, die einen Satz beenden (inklusive)."""
    return [i for i, k in enumerate(sentence_end_kinds(words, rule, min_pause_s)) if k != "none"]


def nlp_status() -> str:
    """``spacy``, wenn ein deutsches spaCy-Modell geladen ist, sonst ``heuristic`` (Verbklammer-Rückfall)."""
    return "spacy" if nlp() is not None else "heuristic"


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
    rule: str = "v1",
    max_s: float | None = None,
    max_words: int | None = None,
) -> list[dict]:
    """Fügt jedem Wort ``filler``, ``negation`` und ``sentence_idx`` hinzu (in-place, gibt Liste zurück).

    ``sentence_idx`` folgt der Satzende-Regel ``rule`` (``v1`` wie vor AP2, ``v2`` siehe ``sentence_end_kind``).

    ``dialect = "de-CH"`` (erkannt oder per ``asr_variant``) ergänzt ``text_norm`` bei sicherer Entsprechung
    (``normalize_ch``); ``text`` bleibt unverändert, geschützte Begriffe werden nie normalisiert."""
    classify_fillers(words)
    idx = 0
    kinds = sentence_end_kinds(words, rule, min_pause_s, max_s, max_words)
    for w, kind in zip(words, kinds, strict=True):
        w["sentence_idx"] = idx
        if kind != "none":
            idx += 1
    if dialect == "de-CH":
        for w in words:
            norm = normalize_ch(str(w.get("text", "")), protected_terms)
            if norm is not None:
                w["text_norm"] = norm
    return words


__all__ = [
    "ABBREVIATIONS",
    "ABBREVIATIONS_V2",
    "AUXILIARY_FORMS",
    "END_KINDS",
    "PAUSE_OPEN_END_WORDS",
    "COMMA_HEAVY",
    "COMMA_MIN_WORDS",
    "COMMA_RULES",
    "FALLBACK_NO_PUNCT",
    "MAX_SENTENCE_S",
    "MAX_SENTENCE_WORDS",
    "SENTENCE_RULES",
    "WORDS_PER_PUNCT_MIN",
    "resolve_sentence_rule",
    "sentence_end_kinds",
    "SUBORDINATORS",
    "VERB_PARTICLES",
    "bracket_heuristic",
    "bracket_open_at_cut",
    "cut_boundary_kind",
    "is_infinitive",
    "is_participle",
    "nlp_status",
    "sentence_end_kind",
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
