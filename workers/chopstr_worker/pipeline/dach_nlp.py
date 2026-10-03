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
    abbreviations = ABBREVIATIONS if rule == "v1" else ABBREVIATIONS_V2
    if base in abbreviations:
        return True
    # Kettenabkürzungen wie „z.B." oder „u.s.w."
    parts = [p for p in base.split(".") if p]
    if rule != "v1" and len(parts) < 2:
        return False
    return bool(parts) and all(p in abbreviations or len(p) == 1 for p in parts)


def is_ordinal(text: str) -> bool:
    return bool(_ORDINAL.match(_strip_trailing(text)))


def is_sentence_end(words: list[dict], i: int, min_pause_s: float = 0.7, rule: str = "v1") -> bool:
    """Endet Wort ``i`` einen Satz? Adapter auf ``sentence_end_kind``.

    ``rule="v1"`` (Standard) liefert exakt das Verhalten vor AP2: Satzzeichen, Abkürzungen,
    Ordinal- und Dezimalzahlen, jede lange Pause und jeder Sprecherwechsel. ``rule="v2"`` siehe
    ``sentence_end_kind``."""
    return sentence_end_kind(words, i, rule=rule, min_pause_s=min_pause_s) != "none"


# -- Satzende-Regel v2 (AP2) und Verbklammer-Heuristik (AP3) --------------------------------------
#
# Eine Funktion für Zerlegung, Satzgrenzen-Tor und Messung (RESEARCH-CLIPPING-KERN Abschnitt 2,
# Befund 1). Regel v2: Satzzeichen zuerst, ein Sprecherwechsel ist eine Grenze, eine lange Pause nur
# ein Grenzkandidat. Angenommen wird er, wenn das Folgewort großgeschrieben ist und im laufenden Satz
# keine Klammer offen ist. Der Port im Web (apps/web/lib/transcript/sentences.ts) muss gleich
# entscheiden; die gemeinsame Falldatei packages/editorial/parity/sentence_end_v1.json hält beide fest.

SENTENCE_RULES = ("v1", "v2")
# Rückgabewerte von ``sentence_end_kind``. ``end_of_text``: letztes Wort des Transkripts.
END_KINDS = ("punct", "speaker_change", "pause_candidate", "end_of_text", "none")

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
# Endet der laufende Satz vor der Pause auf einem dieser Wörter, ist er nicht zu Ende: unbestimmter
# Artikel, Präposition ohne Partikelgebrauch, Nebensatzkonnektor. Bewusst NICHT dabei: der bestimmte
# Artikel (auch Demonstrativpronomen, „Ich weiß das."), Präpositionen, die zugleich Verbpartikel sind
# („Wir fangen an."), und beiordnende Konjunktionen. Ein „aber" vor Pause und großgeschriebenem
# Neuanfang ist ein abgebrochener Satz, kein offener (transcript_fixtures.DEMO_SCRIPT, Satz 11).
PAUSE_OPEN_END_WORDS = frozenset(
    {"ein", "eine", "einen", "einem", "einer", "eines", "des"}
    | {
        "bei", "von", "zum", "zur", "für", "gegen", "ohne", "in", "im", "ins", "am", "ans", "beim", "vom",
        "seit", "zwischen", "hinter", "neben", "wegen", "trotz", "aufs", "fürs",
    }
    | set(SUBORDINATORS)
)  # fmt: skip

_LEADING = "\"'„»«“”‘’([{"
_TERMINAL = (".", "!", "?")
_CLAUSE_PUNCT = (".", "!", "?", ",", ";", ":")
_PARTICIPLE = re.compile(r"^(?:[a-zäöüß]*ge[a-zäöüß]{3,}(?:t|en)|(?:be|ver|er|ent|zer|emp|miss)[a-zäöüß]{3,}t|[a-zäöüß]{3,}iert)$")
_INFINITIVE = re.compile(r"^[a-zäöüß]{2,}(?:en|ern|eln)$")
_VERB_LIKE = re.compile(r"^[a-zäöüß]{2,}(?:e|st|t|en|ern|eln|te|ten)$")
_NOT_INFINITIVE = frozenset(
    {
        "einen", "keinen", "meinen", "deinen", "seinen", "ihren", "unseren", "euren", "diesen", "jenen",
        "welchen", "allen", "vielen", "wenigen", "anderen", "eben", "neben", "gegen", "wegen", "oben",
        "unten", "morgen", "denen", "deren", "ihnen", "seiten", "trotzdem", "zusammen", "dafür",
        "stattdessen", "indessen", "unterdessen", "währenddessen", "deswegen", "weswegen", "übrigen",
    }
)  # fmt: skip
# Begleiter auf -e, die keine Verbform sind („dass wir die | Kunden …").
_DETERMINERS_E = frozenset(
    {"die", "eine", "keine", "meine", "deine", "seine", "ihre", "unsere", "eure", "diese", "jene", "welche", "alle", "viele", "manche", "einige", "beide"}
)  # fmt: skip
_BRACKET_MAX_WORDS = 40
_RIGHT_SCAN_WORDS = 10


def _text(w: dict | str) -> str:
    return str(w.get("text", "") if isinstance(w, dict) else w).strip()


def _ends_with_ellipsis(text: str) -> bool:
    t = text.rstrip("\"'»«“”‘’)]}")
    return t.endswith(("…", "..."))


def _has_terminal_punct(text: str, rule: str = "v2") -> bool:
    """Steht am Wort ein echtes Satzzeichen (ohne Abkürzung, Ordinalzahl, Auslassungspunkte)?"""
    if _ends_with_ellipsis(text):
        return False
    stripped = _strip_trailing(text)
    if stripped.endswith(("!", "?")):
        return True
    return stripped.endswith(".") and not is_ordinal(stripped) and not is_abbreviation(stripped, rule)


def _is_lower(text: str) -> bool:
    t = text.lstrip(_LEADING)
    return bool(t[:1]) and t[:1].islower()


def _is_upper(text: str) -> bool:
    t = text.lstrip(_LEADING)
    return bool(t[:1]) and t[:1].isupper()


def is_participle(text: str) -> bool:
    """Partizip II, kleingeschrieben („gemacht", „angefangen", „verkauft")."""
    return _is_lower(text) and bool(_PARTICIPLE.match(core_token(text)))


def is_infinitive(text: str) -> bool:
    """Infinitiv, kleingeschrieben („machen", „ändern"); Artikel- und Adverbformen ausgenommen."""
    tok = core_token(text)
    return _is_lower(text) and tok not in _NOT_INFINITIVE and bool(_INFINITIVE.match(tok))


def _clause(words: list, seps: tuple[str, ...]) -> list:
    """Die Wörter nach dem letzten Trennzeichen vor dem letzten Wort (das letzte Wort gehört dazu)."""
    start = 0
    for j in range(len(words) - 1):
        if _strip_trailing(_text(words[j])).endswith(seps) or _text(words[j]).endswith(seps):
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
          („an."), links steht ein finites Verb;
      (b) Nebensatz: links steht im laufenden Teilsatz ein Konnektor („dass", „weil"), das letzte
          Wort vor dem Schnitt ist kein Verb;
      (c) Hilfs- oder Modalverb: links steht ein finites Hilfs- oder Modalverb ohne schließendes
          Partizip oder Infinitiv, rechts folgt im selben Satz kleingeschrieben ein Partizip oder ein
          Infinitiv am Satzende, bevor ein neues finites Hilfsverb kommt.
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

    def verb_like(w) -> bool:
        tok = core_token(_text(w))
        if tok in _DETERMINERS_E:
            return False
        return tok in auxiliaries or is_participle(_text(w)) or (_is_lower(_text(w)) and bool(_VERB_LIKE.match(tok)))

    # (a) trennbares Verb
    r0 = _text(rw)
    if _is_lower(r0) and core_token(r0) in particles and r0.rstrip("\"'»«“”‘’)]}").endswith(_CLAUSE_PUNCT):
        sentence = _clause(left, _TERMINAL)
        if any(verb_like(w) for w in sentence):
            return {
                "open": True,
                "signal": "separable_particle",
                "detail": f"Verbpartikel „{core_token(r0)}“ gehört zum Verb davor",
                "available": "heuristic",
            }

    # (b) Nebensatz ohne finites Verb am Ende
    if not _text(lw).endswith(","):
        part = _clause(left, _CLAUSE_PUNCT)
        conn = next((core_token(_text(w)) for w in part if core_token(_text(w)) in subordinators), None)
        if conn and not verb_like(lw):
            return {
                "open": True,
                "signal": "subordinate_clause",
                "detail": f"Nebensatz mit „{conn}“ ohne Verb am Ende",
                "available": "heuristic",
            }

    # (c) finites Hilfs- oder Modalverb ohne schließendes Partizip oder Infinitiv
    sentence = _clause(left, _TERMINAL)
    aux_at = max((k for k, w in enumerate(sentence) if core_token(_text(w)) in auxiliaries), default=None)
    if aux_at is not None:
        # Ein Partizip schließt überall, ein Infinitiv nur am Ende („haben dann stattdessen" bleibt offen).
        tail = sentence[aux_at + 1 :]
        closed = any(is_participle(_text(w)) for w in tail) or bool(tail and is_infinitive(_text(tail[-1])))
        if not closed:
            for w in right[:_RIGHT_SCAN_WORDS]:
                t = _text(w)
                if core_token(t) in auxiliaries:
                    break
                final = t.rstrip("\"'»«“”‘’)]}").endswith(_CLAUSE_PUNCT)
                if is_participle(t) or (is_infinitive(t) and final):
                    return {
                        "open": True,
                        "signal": "auxiliary_bracket",
                        "detail": f"„{_text(sentence[aux_at])}“ und „{core_token(t)}“ gehören zusammen",
                        "available": "heuristic",
                    }
                if t.rstrip("\"'»«“”‘’)]}").endswith(_TERMINAL):
                    break
    return out


def _running_sentence(words: list[dict], i: int, rule: str) -> list[dict]:
    """Die Wörter des laufenden Satzes bis einschließlich ``i`` (nach Satzzeichen, höchstens 40)."""
    a = i
    while a > 0 and i - a < _BRACKET_MAX_WORDS and not _has_terminal_punct(_text(words[a - 1]), rule):
        a -= 1
    return words[a : i + 1]


def _ends_open_clause(text: str) -> bool:
    """Komma, Semikolon oder Doppelpunkt am Wort: der Teilsatz geht weiter („Passen Sie auf, äh,")."""
    return text.rstrip("\"'»«“”‘’)]}").endswith((",", ";", ":"))


def _pause_boundary_accepted(words: list[dict], i: int, rule: str) -> bool:
    """Grenzkandidat aus einer Pause: angenommen nur mit großgeschriebenem Folgewort und ohne offene Klammer."""
    nxt = words[i + 1]
    if not _is_upper(_text(nxt)):
        return False
    if _ends_open_clause(_text(words[i])) or core_token(_text(words[i])) in PAUSE_OPEN_END_WORDS:
        return False
    left = _running_sentence(words, i, rule)
    right = words[i + 1 : i + 1 + _RIGHT_SCAN_WORDS]
    return not bracket_heuristic(left, right)["open"]


def sentence_end_kind(words: list[dict], i: int, rule: str = "v2", min_pause_s: float = 0.7) -> str:
    """Art des Satzendes nach Wort ``i``: ``punct``, ``speaker_change``, ``pause_candidate``,
    ``end_of_text`` oder ``none`` (kein Satzende).

    Regel ``v1``: das Verhalten vor AP2. Jede Pause ab ``min_pause_s`` gilt als ``pause_candidate`` und
    damit als Satzende; Abkürzungen nach ``ABBREVIATIONS``.

    Regel ``v2``: Satzzeichen zuerst (Abkürzung nach ``ABBREVIATIONS_V2``, Ordinal- und Dezimalzahl
    wie bisher; Auslassungspunkte sind kein Satzzeichen, sondern ein Abbruch). Ein Sprecherwechsel ist
    eine Grenze. Eine Pause ab ``min_pause_s`` ist nur ein Kandidat: ``pause_candidate`` nur, wenn das
    Folgewort großgeschrieben ist, der Satz nicht auf Artikel, Präposition oder Nebensatzkonnektor
    endet und ``bracket_heuristic`` keine offene Klammer findet. Sonst ``none``."""
    if rule not in SENTENCE_RULES:
        raise ValueError(f"unbekannte Satzende-Regel {rule!r} (erlaubt: v1, v2)")
    w = words[i]
    text = str(w.get("text", "")).strip()
    nxt = words[i + 1] if i + 1 < len(words) else None
    if nxt is None:
        return "end_of_text"
    pause = float(nxt.get("start", 0.0)) - float(w.get("end", 0.0))
    speaker_change = nxt.get("speaker") is not None and nxt.get("speaker") != w.get("speaker")

    stripped = _strip_trailing(text)
    if rule == "v2" and _ends_with_ellipsis(text):
        pass  # Abbruch, kein Satzzeichen: Sprecherwechsel und Pause entscheiden
    elif stripped.endswith(("!", "?", "…")):
        return "punct"
    elif stripped.endswith("."):
        nxt_text = str(nxt.get("text", "")).strip()
        # Dezimalzahl über Wortgrenze („2." + „4") oder Ordinal/Datum („3." + „Platz", „12." + „Oktober")
        if not (is_ordinal(stripped) or nxt_text[:1].isdigit() or is_abbreviation(stripped, rule)):
            return "punct"
    if speaker_change:
        return "speaker_change"
    if pause >= min_pause_s:
        if rule == "v1" or _pause_boundary_accepted(words, i, rule):
            return "pause_candidate"
    return "none"


def cut_boundary_kind(words: list[dict], i: int, rule: str = "v2", min_pause_s: float = 0.7) -> str:
    """Satzende-Art für einen Schnitt nach Wort ``i`` (Satzgrenzen-Tor, Messung, Anfang heilen).

    Wie ``sentence_end_kind``; unter ``v2`` gilt ein Sprecherwechsel nach Komma, Semikolon oder
    Doppelpunkt nicht als Satzende des Sprechers (Einwurf des Gegenübers mitten im Satz, „Ich bin da
    ganz ehrlich," | „Okay." | „ich hänge …"). Die Zerlegung trennt dort weiter nach Sprecher."""
    kind = sentence_end_kind(words, i, rule, min_pause_s)
    if rule != "v1" and kind == "speaker_change" and _ends_open_clause(_text(words[i])):
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
    return [i for i in range(len(words)) if is_sentence_end(words, i, min_pause_s, rule=rule)]


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
) -> list[dict]:
    """Fügt jedem Wort ``filler``, ``negation`` und ``sentence_idx`` hinzu (in-place, gibt Liste zurück).

    ``sentence_idx`` folgt der Satzende-Regel ``rule`` (``v1`` wie vor AP2, ``v2`` siehe ``sentence_end_kind``).

    ``dialect = "de-CH"`` (erkannt oder per ``asr_variant``) ergänzt ``text_norm`` bei sicherer Entsprechung
    (``normalize_ch``); ``text`` bleibt unverändert, geschützte Begriffe werden nie normalisiert."""
    classify_fillers(words)
    idx = 0
    for i, w in enumerate(words):
        w["sentence_idx"] = idx
        if is_sentence_end(words, i, min_pause_s, rule=rule):
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
    "SENTENCE_RULES",
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
