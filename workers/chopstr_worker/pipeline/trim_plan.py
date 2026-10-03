"""Remove- und Keep-Logik mit Mehrsegment-Komposition (AP7, Policy v2, Abschnitt ``trim``).

Ballast raus, Bedeutung bleibt (Master-Prompt Abschnitte 12, 13, 15, 16, 18). Die Werte kommen aus
``editorial.trim_settings``; wirksam in der Kandidatensuche erst, wenn die Regel ``trim.enabled`` und
der Schalter ``implementation.trim.enabled`` beide an sind.

* ``protected_spans``: Schutzbereiche (Negation, Bedingung, Einschränkung, Vergleichsmaßstab, zeitliche
  Einordnung, Unsicherheit, Definition, Sprecherzuordnung, Korrektur). ``lock_range`` ist Auslöser plus
  je ein Wort Rand, nie über den eigenen Satz und Sprecherbeitrag hinaus: darin wird kein Füllwort
  entfernt. ``word_range`` reicht bei Bedingung, Vergleich, Definition, Zuordnung und Korrektur bis
  zum Satzende: das gilt für Pausen, semantische Schnitte und ``fidelity.check_cut``.
* ``protected_cut_findings``: was ein Schnitt an Schutzbereichen anrichtet. Teilweise entfernt (hoch),
  ganzer Satz weggelassen, der sich auf das Behaltene bezieht (hoch), ganzer Satz ohne Bezug (mittel,
  Prüfhinweis). Füll- und Rückmeldewörter zählen dabei nicht als Inhalt.
* ``classify_pauses``: Pausenklassen ``technical``, ``orientation``, ``dramatic``, ``reaction``,
  ``demonstration``. Nur ``technical`` wird gekürzt, und nie auf null (``trim.pause_target_s``).
* ``removal_candidates``: harte Füllwörter (P3), Einwürfe des Gegenübers, abgebrochene Ansätze mit
  Neustart, Begrüßung und Organisatorisches am Rand. Modalpartikeln im Satz nie.
* ``reward_end``: kappt den Nachlauf nach dem Payoff, nie eine Einschränkung oder Bedingung.
* ``build_composition``: baut über ``compose.from_keep_ranges`` die Komposition, zählt semantische
  Splices und lokale Schnitte getrennt, prüft E6 und ``zusammenhang.mindest_dichte`` und listet die
  entfernten Stellen im ``ClipCandidate``-Format (``removed_spans``, Master-Prompt Abschnitt 21).

Verdrahtung (``story_engine``), in dieser Reihenfolge:

1. ``new_last, gekappt = reward_end(sents, first, last, payoff_idx, policy)``.
2. ``a, b = sents[first].word_range[0], sents[new_last].word_range[1]``;
   ``res = build_composition(words, a, b, None, policy, heat_payload=...)`` mit dem neuen Ende.
3. ``fidelity.check_cut(words[a:last_word + 1], [(x - a, y - a) for x, y in res["kept_word_ranges"]],
   rule="v2", policy=policy)``; ``last_word`` ist das alte Ende, damit der gekappte Nachlauf mitgeprüft
   wird (ganz weggelassene Sätze ohne Bezug sind nur ein Prüfhinweis).
4. Ein Befund hoher Schwere oder ``res["valid"]`` false: ungekürzte Fassung behalten, Grund protokollieren.
5. Einen Teaser nur, wenn ``res["is_debate"]`` false ist (E6).

Wortlisten: Einträge mit ``text``, ``start``, ``end`` und ``speaker``; die Funktionen ändern sie nicht.
Alle Wortbereiche sind inklusiv.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from .. import editorial
from . import compose, dach_nlp, fidelity

PROTECTED_TYPES = (
    "negation", "condition", "qualifier", "comparison_baseline", "temporal", "uncertainty", "definition",
    "attribution", "correction",
)  # fmt: skip
PAUSE_CLASSES = ("technical", "orientation", "dramatic", "reaction", "demonstration")

# Auslöser je Schutztyp, kleingeschrieben, mehrteilige Wendungen mit Leerzeichen. „noch“ ist im
# Trim-Pfad keine Negation („Ich hole mir noch einen Kaffee“); „weder … noch“ trägt „weder“.
NEGATION_TRIGGERS = (frozenset(dach_nlp.NEGATIONS) - {"noch"}) | {"nein"}
CONDITION_TRIGGERS = (
    "wenn", "falls", "sofern", "solange", "vorausgesetzt", "es sei denn", "unter der bedingung", "nur dann",
)  # fmt: skip
QUALIFIER_TRIGGERS = tuple(sorted(fidelity.QUALIFIERS)) + (
    "wobei", "allerdings", "jedoch", "abgesehen davon", "bloß", "lediglich", "ausschließlich", "allein",
    "erst", "zwar", "trotzdem", "dennoch", "aber",
)  # fmt: skip
COMPARISON_TRIGGERS = (
    "im vergleich", "verglichen mit", "gegenüber", "im gegensatz zu", "statt", "anstatt", "mehr als",
    "weniger als", "doppelt so", "halb so", "als früher", "als vorher",
)  # fmt: skip
TEMPORAL_TRIGGERS = (
    "damals", "früher", "heute", "inzwischen", "mittlerweile", "seitdem", "seit", "vorher", "bisher",
    "anfangs", "zurzeit", "aktuell", "derzeit", "momentan", "gestern", "vorgestern", "letztes jahr",
    "letzten jahr", "letzte woche", "letzten monat", "letzten sommer", "letzten winter", "dieses jahr",
    "diese woche", "nächstes jahr", "nächste woche", "nächsten monat", "im ersten quartal", "am anfang",
    "bis jetzt", "im moment",
)  # fmt: skip
# „vor zwei Jahren“, „vor 3 Monaten“: Zahl oder Zahlwort zwischen „vor“ und der Zeiteinheit.
TEMPORAL_UNITS = frozenset({"jahren", "jahr", "monaten", "wochen", "tagen", "jahrzehnten"})
UNCERTAINTY_TRIGGERS = (
    "wahrscheinlich", "vielleicht", "vermutlich", "eventuell", "möglicherweise", "ich glaube", "ich glaub",
    "ich denke", "ich schätze", "ungefähr", "etwa", "circa", "ca", "schätzungsweise", "angeblich",
    "anscheinend", "keine ahnung", "weiß nicht", "nicht sicher",
)  # fmt: skip
# „heißt“ allein ist ein Name („Mein Hund heißt Bello“), nur „das heißt“ und „heißt, dass“ definieren.
DEFINITION_TRIGGERS = (
    "das heißt", "heißt dass", "bedeutet", "damit meine ich", "gemeint ist", "verstehe ich unter",
    "versteht man", "nennt man", "nennen wir", "definiert", "im sinne von", "sprich",
)  # fmt: skip
ATTRIBUTION_TRIGGERS = (
    "sagt", "sagte", "sagten", "gesagt", "meint", "meinte", "meinten", "laut", "zufolge", "behauptet",
    "behauptete", "erzählt", "erzählte", "findet", "fand", "fragt", "fragte", "schreibt", "schrieb",
)  # fmt: skip
CORRECTION_TRIGGERS = (
    "ich meine", "beziehungsweise", "bzw", "besser gesagt", "genauer gesagt", "korrektur", "vielmehr",
    "sondern", "korrigiere", "korrigieren", "stimmt nicht", "stimmt so nicht", "falsch",
)  # fmt: skip
TRIGGERS: dict[str, tuple[str, ...]] = {
    "negation": tuple(sorted(NEGATION_TRIGGERS)),
    "condition": CONDITION_TRIGGERS,
    "qualifier": QUALIFIER_TRIGGERS,
    "comparison_baseline": COMPARISON_TRIGGERS,
    "temporal": TEMPORAL_TRIGGERS,
    "uncertainty": UNCERTAINTY_TRIGGERS,
    "definition": DEFINITION_TRIGGERS,
    "attribution": ATTRIBUTION_TRIGGERS,
    "correction": CORRECTION_TRIGGERS,
}
# Diese Typen gelten bis zum Ende ihres Satzes (höchstens ``CLAUSE_MAX_WORDS``): eine Bedingung, eine
# fremde Position oder eine Korrektur ist mehr als ihr Auslösewort.
CLAUSE_TYPES = frozenset({"condition", "comparison_baseline", "definition", "attribution", "correction"})
CLAUSE_MAX_WORDS = 20
MARGIN_WORDS = 1  # „je ein Wort Rand“
# Typen, die eine Aussage daneben verändern. Fehlt ein ganzer Satz mit einem davon, der sich auf das
# Behaltene bezieht, ist das ein Befund hoher Schwere; sonst nur ein Prüfhinweis.
MODIFYING_TYPES = frozenset({"negation", "condition", "qualifier", "correction", "comparison_baseline"})
# Satzanfänge, mit denen ein Satz an den Satz davor anschließt.
RELATION_STARTS = frozenset(
    {"das", "dies", "diese", "dieser", "dieses", "dabei", "damit", "davon", "dafür", "dann", "danach", "es",
     "doch", "nur", "bloß", "zwar", "außer", "sondern", "wenn", "falls", "sofern", "aber", "allerdings",
     "jedoch", "wobei", "trotzdem", "dennoch", "andererseits", "nicht", "kein", "keine"}
)  # fmt: skip

# Stellen, vor denen eine Pause dramaturgisch ist (RK 7, Zeile „Pausen“).
CONTRAST_WORDS = tuple(fidelity.CONTRAST_STARTS) + ("sondern", "dennoch", "stattdessen", "zwar")
# Nur am Satzanfang Kontrast („Doch dann kam der Anruf“, „Nur der Kunde hat nicht bezahlt“).
CONTRAST_SENTENCE_START = frozenset({"doch", "nur", "bloß"})
# Rückmeldewörter des Gegenübers (``dach_nlp.BACKCHANNEL``) und Zögerlaute.
BACKCHANNEL_TOKENS = frozenset(dach_nlp.BACKCHANNEL) | frozenset(dach_nlp.HARD_FILLERS) | {"aha", "ah", "oh"}
RESTART_MAX_WORDS = 3
RESTART_BROKEN_SCAN = 5
# Ein einzelnes Wort ist kein Neustart, wenn es Artikel, Relativ- oder Fragepronomen ist („Die, die
# das gemacht haben“, „Wer, wer hat das entschieden?“).
NOT_A_RESTART_WORD = frozenset(
    {"der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem", "einer", "eines", "wer",
     "wen", "wem", "wessen", "was", "warum", "wieso", "weshalb", "wie", "wo", "wann", "woher", "wohin",
     "welche", "welcher", "welches", "welchen", "welchem"}
)  # fmt: skip
# Folgt auf die Wiederholung ein Verstärker, ist es Betonung („Wir haben, wir haben wirklich …“).
INTENSIFIERS = frozenset({"wirklich", "so", "total", "echt", "ganz", "sehr", "absolut", "richtig", "extrem"})
# Funktionale Wiederholung („Nein, nein.“, „Viel, viel besser“) ist kein abgebrochener Ansatz.
FUNCTIONAL_REPEAT = NEGATION_TRIGGERS | {"ja", "doch", "sehr", "ganz", "viel", "immer", "wirklich", "so"}
# Einschränkungstypen, die ``reward_end`` nie kappt.
QUALIFYING_TYPES = frozenset({"negation", "condition", "qualifier", "uncertainty", "correction", "comparison_baseline"})
# Verkaufsaufruf: Imperativ in der zweiten Person oder Anrede in der zweiten Person.
SECOND_PERSON = frozenset(
    {"ihr", "euch", "euer", "eure", "euren", "eurem", "du", "dir", "dich", "dein", "deine", "deinen", "deinem"}
)  # fmt: skip
IMPERATIVE_PARTNERS = frozenset({"mir", "uns", "euch", "jetzt", "doch", "gerne", "gern", "direkt", "sofort"})
REPEAT_MIN_TOKEN_LEN = 4
VISUAL_MIN_OVERLAP_S = 0.5
EPS = 1e-6

_CLOSERS = "\"'»«“”‘’)]}"


# -- Hilfen ----------------------------------------------------------------------------------------


def _policy_settings(policy: editorial.Policy | None) -> tuple[editorial.Policy, dict[str, Any]]:
    pol = policy if policy is not None else editorial.load()
    cfg = editorial.trim_settings(pol)
    if cfg is None:
        raise editorial.PolicyError(f"clip_policy_v{pol.version}: trim_plan braucht Fassung 2 mit Abschnitt trim.")
    return pol, cfg


def _text(w: Mapping[str, Any]) -> str:
    return str(w.get("text", "")).strip()


def _tok(w: Mapping[str, Any]) -> str:
    return dach_nlp.core_token(_text(w))


def _norm(text: str) -> str:
    """Kleingeschrieben, Satzzeichen zu Leerzeichen, einfache Leerzeichen (für Wendungen)."""
    return " ".join(re.sub(r"[^\wäöüß ]", " ", str(text).lower()).split())


def _gap(words: Sequence[Mapping[str, Any]], i: int) -> float:
    return float(words[i + 1]["start"]) - float(words[i]["end"])


def _ends_sentence(text: str) -> bool:
    t = str(text).strip().rstrip(_CLOSERS)
    if t.endswith(("…", "...")):
        return False
    if t.endswith(("!", "?")):
        return True
    return t.endswith(".") and not dach_nlp.is_ordinal(t) and not dach_nlp.is_abbreviation(t, "v2")


def _is_question(text: str) -> bool:
    return str(text).strip().rstrip(_CLOSERS).endswith("?")


def is_hard_filler(w: Mapping[str, Any]) -> bool:
    """Hartes Füllwort nach P3, am Rohtext geprüft: eine Abkürzung in Großbuchstaben („EM“, „KI“) ist
    nie eins, und ein Zögerlaut mit Fragezeichen („Hm?“) ist eine Rückfrage."""
    text = _text(w)
    letters = re.sub(r"[^\wäöüÄÖÜß]", "", text)
    if len(letters) >= 2 and letters.isupper():
        return False
    if _is_question(text):
        return False
    return dach_nlp.core_token(text) in dach_nlp.HARD_FILLERS


def _is_contentless(w: Mapping[str, Any]) -> bool:
    """Füll- oder Rückmeldewort ohne Inhalt („äh“, „okay“, „genau“)."""
    return is_hard_filler(w) or (_tok(w) in BACKCHANNEL_TOKENS and not _is_question(_text(w)))


def _phrase_positions(tokens: Sequence[str], phrase: str) -> list[tuple[int, int]]:
    parts = [dach_nlp.core_token(p) for p in phrase.split()]
    parts = [p for p in parts if p]
    n = len(parts)
    if not n:
        return []
    return [(i, i + n - 1) for i in range(len(tokens) - n + 1) if list(tokens[i : i + n]) == parts]


def _sentence_ranges(words: Sequence[Mapping[str, Any]], pol: editorial.Policy) -> list[tuple[int, int]]:
    """Sätze nach der Satzende-Regel der Policy (``dach_nlp.sentence_boundaries``)."""
    if not words:
        return []
    ends = dach_nlp.sentence_boundaries(list(words), rule=editorial.sentence_rule(pol))
    out, start = [], 0
    for e in ends:
        out.append((start, e))
        start = e + 1
    if start < len(words):
        out.append((start, len(words) - 1))
    return out


def _unit_bounds(words: Sequence[Mapping[str, Any]], sentences: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Je Wort der eigene Satz, geschnitten mit dem eigenen Sprecherbeitrag."""
    out: list[tuple[int, int]] = [(0, 0)] * len(words)
    for a, b in sentences:
        for i in range(a, b + 1):
            lo = i
            while lo > a and words[lo - 1].get("speaker") == words[i].get("speaker"):
                lo -= 1
            hi = i
            while hi < b and words[hi + 1].get("speaker") == words[i].get("speaker"):
                hi += 1
            out[i] = (lo, hi)
    return out


def _clause_end(words: Sequence[Mapping[str, Any]], b: int, hi: int) -> int:
    """Letztes Wort des Satzes ab ``b``: Satzzeichen, Satz- oder Beitragsende, höchstens ``CLAUSE_MAX_WORDS``."""
    k = b
    limit = min(hi, b + CLAUSE_MAX_WORDS)
    while k < limit and not _ends_sentence(_text(words[k])):
        k += 1
    return k


def _overlaps(a: Sequence[int], b: Sequence[int]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def _is_number_token(text: str) -> bool:
    return any(ch.isdigit() for ch in text) or fidelity.parse_number_word(dach_nlp.core_token(text)) is not None


# -- Schutzbereiche --------------------------------------------------------------------------------


def _trigger_hits(tokens: Sequence[str], words: Sequence[Mapping[str, Any]]) -> list[tuple[str, int, int]]:
    """Auslöser je Typ; Wendungen werden über harte Füllwörter hinweg erkannt („heißt äh dass“)."""
    hits: list[tuple[str, int, int]] = []
    keep = [i for i, w in enumerate(words) if not is_hard_filler(w)]
    dense = [tokens[i] for i in keep]
    for kind in PROTECTED_TYPES:
        for phrase in TRIGGERS[kind]:
            hits += [(kind, keep[a], keep[b]) for a, b in _phrase_positions(dense, phrase)]
    for i in range(len(tokens) - 2):  # „vor zwei Jahren“
        if tokens[i] == "vor" and _is_number_token(_text(words[i + 1])) and tokens[i + 2] in TEMPORAL_UNITS:
            hits.append(("temporal", i, i + 2))
    return hits


def protected_spans(words: Sequence[Mapping[str, Any]], policy: editorial.Policy | None = None) -> list[dict]:
    """Schutzbereiche je Typ aus ``PROTECTED_TYPES``.

    Rückgabe sortiert: ``{type, word_range: [a, b], lock_range: [a, b], trigger: [a, b], text}``.
    ``lock_range`` ist der Auslöser mit je einem Wort Rand, ``word_range`` reicht bei Bedingung,
    Vergleichsmaßstab, Definition, Sprecherzuordnung und Korrektur bis zum Satzende. Beide bleiben im
    eigenen Satz und im eigenen Sprecherbeitrag. Einschränkungen kommen aus ``fidelity.QUALIFIERS``
    plus den einschränkenden Anschlüssen (wobei, bloß, lediglich, zwar, trotzdem, aber, …)."""
    pol, _cfg = _policy_settings(policy)
    tokens = [_tok(w) for w in words]
    bounds = _unit_bounds(words, _sentence_ranges(words, pol))
    seen: set[tuple[str, int, int]] = set()
    out: list[dict] = []
    for kind, ta, tb in _trigger_hits(tokens, words):
        lo, hi = bounds[ta][0], bounds[tb][1]
        end = _clause_end(words, tb, hi) if kind in CLAUSE_TYPES else tb
        a, b = max(lo, ta - MARGIN_WORDS), min(hi, end + MARGIN_WORDS)
        if (kind, a, b) in seen:
            continue
        seen.add((kind, a, b))
        out.append({
            "type": kind, "word_range": [a, b],
            "lock_range": [max(lo, ta - MARGIN_WORDS), min(hi, tb + MARGIN_WORDS)], "trigger": [ta, tb],
            "text": " ".join(_text(w) for w in words[ta : tb + 1]),
        })  # fmt: skip
    return sorted(out, key=lambda p: (p["word_range"][0], p["word_range"][1], PROTECTED_TYPES.index(p["type"])))


def _relates(words: Sequence[Mapping[str, Any]], sent: tuple[int, int], kept: set[int], sentences: list[tuple[int, int]]) -> bool:
    """Bezieht sich ein ganz weggelassener Satz auf das Behaltene? Er grenzt an einen behaltenen Satz und
    beginnt mit einem Anschluss („Das“, „Aber“, „Trotzdem“, „Wenn“) oder teilt ein Inhaltswort mit ihm."""
    k = sentences.index(sent)
    neighbours = [sentences[j] for j in (k - 1, k + 1) if 0 <= j < len(sentences)]
    kept_neighbours = [s for s in neighbours if any(i in kept for i in range(s[0], s[1] + 1))]
    if not kept_neighbours:
        return False
    if _tok(words[sent[0]]) in RELATION_STARTS:
        return True
    mine = {_tok(words[i]) for i in range(sent[0], sent[1] + 1) if len(_tok(words[i])) >= REPEAT_MIN_TOKEN_LEN}
    return any(
        mine & {_tok(words[i]) for i in range(s[0], s[1] + 1) if len(_tok(words[i])) >= REPEAT_MIN_TOKEN_LEN}
        for s in kept_neighbours
    )


def protected_cut_findings(
    words: Sequence[Mapping[str, Any]], kept: set[int], policy: editorial.Policy | None = None
) -> list[dict]:
    """Was ein Schnitt (behaltene Wortindizes ``kept``) an Schutzbereichen anrichtet.

    Je betroffenem Schutzbereich ``{type, word_range, text, severity, mode}``:

    * ``partial`` (hoch): Inhaltswörter des Bereichs fehlen, andere oder der Rest seines Satzes bleiben;
    * ``omitted_related`` (hoch): der ganze Satz fehlt, der Typ verändert eine Aussage (Negation,
      Bedingung, Einschränkung, Korrektur, Vergleich) und der Satz bezieht sich auf das Behaltene;
    * ``omitted`` (mittel): der ganze Satz fehlt ohne erkennbaren Bezug, ein Prüfhinweis.

    Füll- und Rückmeldewörter zählen nicht als Inhalt; ihr Fehlen berührt keinen Schutzbereich."""
    pol, _cfg = _policy_settings(policy)
    sentences = _sentence_ranges(words, pol)
    sent_of = {i: s for s in sentences for i in range(s[0], s[1] + 1)}
    out: list[dict] = []
    for p in protected_spans(words, pol):
        a, b = p["word_range"]
        content = [i for i in range(a, b + 1) if not _is_contentless(words[i])]
        removed = [i for i in content if i not in kept]
        if not removed:
            continue
        sent = sent_of[p["trigger"][0]]
        sentence_content = [i for i in range(sent[0], sent[1] + 1) if not _is_contentless(words[i])]
        if any(i in kept for i in content) or any(i in kept for i in sentence_content):
            severity, mode = "high", "partial"
        elif p["type"] in MODIFYING_TYPES and _relates(words, sent, kept, sentences):
            severity, mode = "high", "omitted_related"
        else:
            severity, mode = "medium", "omitted"
        out.append({"type": p["type"], "word_range": [a, b], "text": p["text"], "severity": severity, "mode": mode})
    return out


# -- Pausenklassen ---------------------------------------------------------------------------------


def _laughter_in(heat_payload: Mapping[str, Any] | None, t0: float, t1: float) -> bool:
    """Lachen in ``[t0, t1]`` laut ``heat_payload["laughter_values"]`` (je Bin, größer null heißt Lachen).

    Die heutige Heatmap (``signals.to_payload``) trägt das Lachen nicht getrennt; ohne den Schlüssel
    zählt nur das Transkript (Reaktionswörter)."""
    if not heat_payload:
        return False
    values = heat_payload.get("laughter_values")
    if not values:
        return False
    bin_s = float(heat_payload.get("bin_s") or 1.0) or 1.0
    lo, hi = max(0, int(t0 / bin_s)), int(t1 / bin_s)
    return any(float(v) > 0 for v in values[lo : hi + 1])


def _is_reaction_word(words: Sequence[Mapping[str, Any]], k: int, speaker: Any, cfg: Mapping[str, Any]) -> bool:
    text = _text(words[k])
    if _tok(words[k]) not in cfg["reaction_words"]:
        return False
    marked = text.startswith(("(", "[", "*"))
    return marked or words[k].get("speaker") != speaker


def _punchlines(
    words: Sequence[Mapping[str, Any]],
    sentences: list[tuple[int, int]],
    heat_payload: Mapping[str, Any] | None,
    cfg: Mapping[str, Any],
) -> list[tuple[int, int, str]]:
    """Sätze, nach denen innerhalb von ``punchline_window_s`` gelacht oder reagiert wird."""
    out = []
    window = float(cfg["punchline_window_s"])
    for a, b in sentences:
        t_end = float(words[b]["end"])
        speaker = words[b].get("speaker")
        cue = None
        k = b + 1
        while k < len(words) and k <= b + 3 and float(words[k]["start"]) <= t_end + window:
            if _is_reaction_word(words, k, speaker, cfg):
                cue = f"Reaktionswort „{_text(words[k])}“"
                break
            k += 1
        if cue is None and _laughter_in(heat_payload, t_end, t_end + window):
            cue = "Lachen"
        if cue is not None:
            out.append((a, b, cue))
    return out


def classify_pauses(
    words: Sequence[Mapping[str, Any]],
    heat_payload: Mapping[str, Any] | None = None,
    policy: editorial.Policy | None = None,
    visual_events: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict]:
    """Jede Lücke zwischen zwei Wörtern über ``trim.pause_target_s`` mit Klasse und Grund.

    Reihenfolge der Prüfung (die erste passende gilt):

    * ``demonstration``: ein Bildereignis (``visual_events``, wie in den Fixtures) fällt in die Lücke;
    * ``dramatic``: Pause vor oder in einer Pointe (Satz, nach dem gelacht oder reagiert wird);
    * ``reaction``: Pause nach der Pointe, nach einer Frage, vor einem Reaktionswort oder mit Lachen;
    * ``dramatic``: Pause vor einer Zahl, einer Negation oder einem Kontrastwort („Doch“, „Nur“ und
      „Bloß“ am Satzanfang);
    * lange Stille ab ``trim.long_silence_s``: im laufenden Satz ``dramatic`` (Innehalten), sonst
      ``demonstration`` (mögliche Demonstration ohne Sprache);
    * Pause im Satz ab ``orientation_min_s``: ``dramatic`` (Innehalten, nie technisch);
    * ``orientation``: an einer Satzgrenze ab ``orientation_min_s`` oder vor einem Gliederungswort;
    * sonst ``technical``. Nur diese Klasse wird gekürzt.

    Rückgabe je Lücke: ``{after_word, start, end, duration, class, reason}``."""
    pol, cfg = _policy_settings(policy)
    if len(words) < 2:
        return []
    sentences = _sentence_ranges(words, pol)
    ends = {b for _a, b in sentences}
    punch = _punchlines(words, sentences, heat_payload, cfg)
    punch_inner = {i: cue for a, b, cue in punch for i in range(a - 1, b)}  # Lücke nach Wort i
    punch_after = {b: cue for _a, b, cue in punch}
    events = [e for e in (visual_events or []) if e.get("start") is not None and e.get("end") is not None]
    ctx = {"ends": ends, "punch_inner": punch_inner, "punch_after": punch_after, "events": events, "heat": heat_payload}
    out: list[dict] = []
    for i in range(len(words) - 1):
        g = _gap(words, i)
        if g <= float(cfg["pause_target_s"]) + EPS:
            continue
        t0, t1 = float(words[i]["end"]), float(words[i + 1]["start"])
        cls, reason = _pause_class(words, i, g, t0, t1, ctx, cfg)
        out.append({
            "after_word": i, "start": round(t0, 3), "end": round(t1, 3), "duration": round(g, 3),
            "class": cls, "reason": reason,
        })  # fmt: skip
    return out


def _pause_class(
    words: Sequence[Mapping[str, Any]],
    i: int,
    g: float,
    t0: float,
    t1: float,
    ctx: Mapping[str, Any],
    cfg: Mapping[str, Any],
) -> tuple[str, str]:
    prev, nxt = words[i], words[i + 1]
    dramatic_before, reaction_after = set(cfg["dramatic_before"]), set(cfg["reaction_after"])
    ends = ctx["ends"]
    for e in ctx["events"]:
        overlap = min(t1, float(e["end"])) - max(t0, float(e["start"]))
        if overlap >= min(VISUAL_MIN_OVERLAP_S, 0.5 * g):
            return "demonstration", f"Bildereignis ohne Sprache ({e.get('type') or 'visual'})"
    if "punchline" in dramatic_before and i in ctx["punch_inner"]:
        return "dramatic", f"Pause vor der Pointe ({ctx['punch_inner'][i]} danach)"
    if i in ctx["punch_after"] and ({"laughter", "reaction_word"} & reaction_after):
        return "reaction", f"Reaktion auf die Pointe ({ctx['punch_after'][i]})"
    if "question" in reaction_after and _is_question(_text(prev)):
        return "reaction", "Pause nach einer Frage"
    if "reaction_word" in reaction_after and _is_reaction_word(words, i + 1, prev.get("speaker"), cfg):
        return "reaction", f"Pause vor dem Reaktionswort „{_text(nxt)}“"
    if "laughter" in reaction_after and _laughter_in(ctx["heat"], t0, t1):
        return "reaction", "Lachen in der Pause"
    tok = _tok(nxt)
    if "number" in dramatic_before and _is_number_token(_text(nxt)):
        return "dramatic", f"Pause vor der Zahl „{_text(nxt)}“"
    if "negation" in dramatic_before and tok in NEGATION_TRIGGERS:
        return "dramatic", f"Pause vor der Negation „{_text(nxt)}“"
    if "contrast" in dramatic_before and (tok in CONTRAST_WORDS or (i in ends and tok in CONTRAST_SENTENCE_START)):
        return "dramatic", f"Pause vor dem Kontrastwort „{_text(nxt)}“"
    in_sentence = i not in ends and nxt.get("speaker") == prev.get("speaker")
    if g >= float(cfg["long_silence_s"]):
        if in_sentence:
            return "dramatic", f"lange Stille im Satz ({g:.1f} s), Innehalten"
        return "demonstration", f"lange Stille ohne Sprache ({g:.1f} s), mögliche Demonstration"
    if in_sentence and g >= float(cfg["orientation_min_s"]):
        return "dramatic", f"Pause im Satz ({g:.1f} s), Innehalten"
    if i in ends:
        head = _norm(" ".join(_text(w) for w in words[i + 1 : i + 5]))
        if g >= float(cfg["orientation_min_s"]):
            return "orientation", f"Satzgrenze mit {g:.1f} s Pause"
        if any(head == m or head.startswith(m + " ") for m in cfg["orientation_markers"]):
            return "orientation", f"Pause vor dem Gliederungswort „{_text(nxt)}“"
    return "technical", "technische Leerstelle"


# -- Entfernungskandidaten -------------------------------------------------------------------------


def _speaker_runs(words: Sequence[Mapping[str, Any]]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    for i, w in enumerate(words):
        if runs and words[runs[-1][1]].get("speaker") == w.get("speaker"):
            runs[-1] = (runs[-1][0], i)
        else:
            runs.append((i, i))
    return runs


def _backchannels(words: Sequence[Mapping[str, Any]]) -> list[tuple[int, int]]:
    """Kurzer Einwurf (höchstens ``compose.BACKCHANNEL_MAX_WORDS`` Rückmeldewörter) eines Sprechers
    mitten im Beitrag eines anderen. Keiner, wenn der Beitrag davor mit einem Satzende schließt: nach
    einer Frage ist es eine Antwort (auch einsilbig, „Klar.“ zwischen zwei Fragen), nach einer Aussage
    eine Bestätigung („Genau.“ nach „Du meinst also, …“). Eine Rückfrage („Hm?“) bleibt immer."""
    runs = _speaker_runs(words)
    out = []
    for k in range(1, len(runs) - 1):
        a, b = runs[k]
        _prev_a, prev_b = runs[k - 1]
        nxt_a, _nxt_b = runs[k + 1]
        spk, other = words[a].get("speaker"), words[prev_b].get("speaker")
        if spk is None or other is None or words[nxt_a].get("speaker") != other:
            continue
        if b - a + 1 > compose.BACKCHANNEL_MAX_WORDS:
            continue
        if not all(_tok(words[i]) in BACKCHANNEL_TOKENS and not _is_question(_text(words[i])) for i in range(a, b + 1)):
            continue
        if _ends_sentence(_text(words[prev_b])):
            continue  # Antwort oder Bestätigung
        out.append((a, b))
    return out


def _restarts(
    words: Sequence[Mapping[str, Any]], sentences: list[tuple[int, int]], cfg: Mapping[str, Any]
) -> list[tuple[int, int]]:
    """Abgebrochener Ansatz mit Neustart am Satzanfang. Entfernt wird der erste Ansatz samt Zögerlauten.

    Neustart nur mit Trennung zwischen den Ansätzen: hartes Füllwort, abgebrochenes Wort („hab-“) oder
    Pause über ``trim.pause_target_s``; Auslassungspunkte nur, wenn mindestens zwei Wörter des Ansatzes
    wiederkehren („Der Grund war… der Preis.“ ist eine Pointe). Kein Neustart: ein einzelnes Wort, das
    Artikel, Relativ- oder Fragepronomen ist („Die, die …“, „Wer, wer …“); funktionale Wiederholung
    („Viel, viel besser“); Wiederholung mit Verstärker danach („Wir haben, wir haben wirklich …“)."""
    out = []
    toks = [_tok(w) for w in words]
    n = len(words)
    target = float(cfg["pause_target_s"])
    for i in sorted({a for a, _b in sentences}):
        found = None
        for k in range(RESTART_MAX_WORDS, 0, -1):
            first = list(range(i, i + k))
            if first[-1] >= n or any(not toks[j] or is_hard_filler(words[j]) for j in first):
                continue
            if any(_ends_sentence(_text(words[j])) for j in first):
                continue
            if all(toks[j] in FUNCTIONAL_REPEAT for j in first) or (k == 1 and toks[i] in NOT_A_RESTART_WORD):
                continue
            j = i + k
            while j < n and is_hard_filler(words[j]):
                j += 1
            second = list(range(j, j + k))
            if second[-1] >= n or [toks[x] for x in first] != [toks[x] for x in second]:
                continue
            if len({words[x].get("speaker") for x in first + second}) != 1:
                continue
            if second[-1] + 1 < n and toks[second[-1] + 1] in INTENSIFIERS:
                continue  # Betonung
            last = _text(words[first[-1]]).rstrip(_CLOSERS)
            separated = (
                j > i + k
                or last.endswith("-")
                or _gap(words, first[-1]) > target + EPS
                or (k >= 2 and last.endswith(("…", "...")))
            )
            if separated:
                found = (i, j - 1)
                break
        if found is None:
            for j in range(i, min(n - 1, i + RESTART_BROKEN_SCAN)):
                t = _text(words[j]).rstrip(_CLOSERS)
                same_spk = words[j + 1].get("speaker") == words[i].get("speaker")
                if t.endswith("-") and toks[j + 1] == toks[i] and same_spk:
                    found = (i, j)
                    break
                if t.endswith(("…", "...")) and same_spk and j > i and toks[j + 1 : j + 3] == toks[i : i + 2]:
                    found = (i, j)
                    break
                if _ends_sentence(t):
                    break
        if found is not None:
            out.append(found)
    return out


def _edge_removals(
    words: Sequence[Mapping[str, Any]], sentences: list[tuple[int, int]], cfg: Mapping[str, Any]
) -> list[tuple[int, int, str, bool]]:
    """Begrüßung, Dank, Abschied und Organisatorisches am Anfang oder Ende: ``(a, b, reason, whole)``.

    Ein Randsatz fällt ganz weg, wenn er überwiegend aus Wendungen besteht (höchstens drei weitere
    Wörter); sonst nur die Wendung selbst, wenn sie den Satz am Anfang eröffnet oder am Ende schließt
    („Hallo zusammen, unser größter Kunde hat gekündigt.“ verliert nur „Hallo zusammen,“). Der letzte
    verbleibende Satz bleibt immer."""
    tokens = [_tok(w) for w in words]
    org = [(m, "organisational") for m in (*cfg["organisation_markers"], *cfg["organisation_markers_trim"])]
    markers = sorted(org + [(m, "greeting") for m in cfg["edge_markers"]], key=lambda x: -len(x[0].split()))

    def matches(a: int, b: int) -> list[tuple[int, int, str]]:
        taken: set[int] = set()
        hits = []
        for phrase, kind in markers:
            for x, y in _phrase_positions(tokens[a : b + 1], phrase):
                x, y = x + a, y + a
                if not taken & set(range(x, y + 1)):
                    taken |= set(range(x, y + 1))
                    hits.append((x, y, kind))
        return sorted(hits)

    def whole(a: int, b: int, hits: list[tuple[int, int, str]]) -> str | None:
        covered = {i for x, y, _k in hits for i in range(x, y + 1)}
        others = [i for i in range(a, b + 1) if i not in covered and not is_hard_filler(words[i])]
        if hits and len(others) <= 3:
            return "organisational" if any(k == "organisational" for *_r, k in hits) else "greeting"
        return None

    out: list[tuple[int, int, str, bool]] = []
    lo, hi = 0, len(sentences) - 1
    while lo < hi:
        a, b = sentences[lo]
        hits = matches(a, b)
        reason = whole(a, b, hits)
        if reason is not None:
            out.append((a, b, reason, True))
            lo += 1
            continue
        if hits and hits[0][0] == a:
            out.append((a, hits[0][1], hits[0][2], False))
        break
    while hi > lo:
        a, b = sentences[hi]
        hits = matches(a, b)
        reason = whole(a, b, hits)
        if reason is not None:
            out.append((a, b, reason, True))
            hi -= 1
            continue
        if hits and hits[-1][1] == b:
            out.append((hits[-1][0], b, hits[-1][2], False))
        break
    return out


def removal_candidates(words: Sequence[Mapping[str, Any]], policy: editorial.Policy | None = None) -> list[dict]:
    """Was entfernt werden darf, je ``{word_range: [a, b], reason, text}``, sortiert.

    Gründe: ``hard_filler`` (äh, ähm; P3, am Rohtext: „EM“ ist keins, „Hm?“ ist eine Rückfrage),
    ``backchannel`` (Einwurf des Gegenübers mitten im Beitrag, nie nach einem Satzende), ``restart``
    (abgebrochener Ansatz mit Neustart), ``greeting`` und ``organisational`` (nur am Rand,
    ``trim.removal.edge_markers``, ``trim.removal.organisation_markers`` und
    ``ausschluss.organisations_marker``). Ausgeschlossen sind:

    * Kandidaten mit einem Wort aus ``trim.removal.never_remove`` (Modalpartikeln im Satz); ein
      Einwurf („Ja.“ des Gegenübers) und ein ganzer Begrüßungssatz sind keine Modalpartikel im Satz;
    * Kandidaten im Auslöser oder Rand eines Schutzbereichs (``lock_range``);
    * Kandidaten neben einer Stille ab ``trim.long_silence_s`` (das Zögern davor gehört zur Szene)."""
    pol, cfg = _policy_settings(policy)
    if not words:
        return []
    sentences = _sentence_ranges(words, pol)
    raw: list[tuple[int, int, str, bool]] = []
    if cfg["fillers"] == "hard":
        raw += [(i, i, "hard_filler", False) for i, w in enumerate(words) if is_hard_filler(w)]
    if cfg["backchannel"]:
        raw += [(a, b, "backchannel", True) for a, b in _backchannels(words)]
    if cfg["restarts"]:
        raw += [(a, b, "restart", False) for a, b in _restarts(words, sentences, cfg)]
    raw += _edge_removals(words, sentences, cfg)

    locked = [p["lock_range"] for p in protected_spans(words, pol)]
    never = set(cfg["never_remove"])
    long_s = float(cfg["long_silence_s"])
    out, seen = [], set()
    for a, b, reason, no_particle in sorted(raw):
        if (a, b, reason) in seen:
            continue
        seen.add((a, b, reason))
        if not no_particle and any(_tok(words[i]) in never for i in range(a, b + 1)):
            continue
        if any(_overlaps((a, b), p) for p in locked):
            continue
        if (a > 0 and _gap(words, a - 1) >= long_s) or (b + 1 < len(words) and _gap(words, b) >= long_s):
            continue
        out.append({"word_range": [a, b], "reason": reason, "text": " ".join(_text(w) for w in words[a : b + 1])})
    return out


# -- Ende nach dem Payoff --------------------------------------------------------------------------


def _sentence_text(s: Any) -> str:
    return str(s.get("text", "") if isinstance(s, Mapping) else getattr(s, "text", ""))


def _content_tokens(text: str) -> set[str]:
    """Inhaltswörter ab vier Zeichen und jede Zahl oder jedes Zahlwort."""
    return {t for t in _norm(text).split() if len(t) >= REPEAT_MIN_TOKEN_LEN or _is_number_token(t)}


def _is_qualifying(text: str, pol: editorial.Policy) -> bool:
    """Trägt der Satz eine Einschränkung, Bedingung, Negation, Unsicherheit oder Korrektur? Kontrastwörter
    zählen an jeder Stelle im Satz, „doch“, „nur“, „bloß“ am Satzanfang."""
    low = _norm(text)
    tokens = low.split()
    markers = tuple(_norm(m) for m in pol.ausstieg.get("abschwaechung_marker") or ())
    if any(low == m or low.startswith(m + " ") for m in markers if m):
        return True
    if any(t in CONTRAST_WORDS for t in tokens) or (tokens and tokens[0] in CONTRAST_SENTENCE_START):
        return True
    pseudo = [{"text": t, "start": 0.0, "end": 0.0} for t in str(text).split()]
    return any(p["type"] in QUALIFYING_TYPES for p in protected_spans(pseudo, pol))


def _is_sales_call(text: str, cfg: Mapping[str, Any]) -> bool:
    """Verkaufsaufruf: eine Wendung aus ``reward_end.sales_call`` und ein Imperativ oder eine Anrede in
    der zweiten Person („Schreibt mir für ein Erstgespräch.“, nicht „… haben abonniert.“)."""
    low = f" {_norm(text)} "
    if not any(f" {_norm(m)} " in low for m in cfg["sales_call"]):
        return False
    tokens = low.split()
    imperative = len(tokens) >= 2 and tokens[0].endswith(("t", "e")) and tokens[1] in IMPERATIVE_PARTNERS
    return imperative or bool(SECOND_PERSON & set(tokens)) or " jetzt buchen " in low


def _tail_reason(text: str, payoff_text: str, cfg: Mapping[str, Any]) -> str | None:
    low = f" {_norm(text)} "
    head = _norm(text)
    if any(head.startswith(_norm(m)) for m in cfg["weak_summary"]):
        return "weak_summary"
    if _is_sales_call(text, cfg):
        return "sales_call"
    if any(f" {_norm(m)} " in low for m in cfg["farewell"]):
        return "farewell"
    mine, payoff = _content_tokens(text), _content_tokens(payoff_text)
    if any(_is_number_token(t) for t in mine - payoff):
        return None  # eine neue Zahl ist neue Information
    if len(mine) >= 2 and len(mine & payoff) / len(mine) >= float(cfg["repeat_overlap"]):
        return "repeated_payoff"
    return None


def reward_end(
    sents: Sequence[Any],
    first: int,
    last: int,
    payoff_idx: int | None,
    policy: editorial.Policy | None = None,
) -> tuple[int, list[dict]]:
    """Neuer letzter Satzindex und die gekappten Sätze ``{sentence, reason, text}``.

    Gekappt wird von hinten, solange jeder Satz nach dem Payoff Nachlauf ist: wiederholte Pointe
    (``repeated_payoff``, ohne neue Zahl), schwache Zusammenfassung (``weak_summary``), Verkaufsaufruf
    (``sales_call``, Imperativ oder zweite Person) oder Verabschiedung (``farewell``). Ein Satz mit
    Einschränkung, Bedingung, Negation, Unsicherheit, Korrektur oder Kontrastwort wird nie gekappt und
    hält alles davor fest. Ohne Payoff (``None``) oder mit Payoff am Ende bleibt das Ende."""
    pol, cfg = _policy_settings(policy)
    if payoff_idx is None or not first <= payoff_idx < last:
        return last, []
    payoff_text = _sentence_text(sents[payoff_idx])
    cut: list[dict] = []
    k = last
    while k > payoff_idx:
        text = _sentence_text(sents[k])
        if _is_qualifying(text, pol):
            break
        reason = _tail_reason(text, payoff_text, cfg)
        if reason is None:
            break
        cut.insert(0, {"sentence": k, "reason": reason, "text": text})
        k -= 1
    return k, cut


# -- Komposition -----------------------------------------------------------------------------------


def _keep_ranges(keep_decisions: Sequence[Sequence[int]] | None, first: int, last: int) -> list[tuple[int, int]]:
    if not keep_decisions:
        return [(first, last)]
    ranges = [(int(a), int(b)) for a, b in keep_decisions]
    prev = first - 1
    for a, b in ranges:
        if not (first <= a <= b <= last) or a <= prev:
            raise ValueError(f"keep_decisions {ranges} liegen nicht aufsteigend und überlappungsfrei in {first} bis {last}")
        prev = b
    return ranges


def _pieces(ranges: list[tuple[int, int]], removed: set[int], split_after: set[int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for a, b in ranges:
        cur: list[int] | None = None
        for i in range(a, b + 1):
            if i in removed:
                if cur is not None:
                    out.append((cur[0], cur[1]))
                    cur = None
                continue
            if cur is None:
                cur = [i, i]
            else:
                cur[1] = i
            if i in split_after:
                out.append((cur[0], cur[1]))
                cur = None
        if cur is not None:
            out.append((cur[0], cur[1]))
    return out


def _mid(w: Mapping[str, Any]) -> float:
    return (float(w["start"]) + float(w["end"])) / 2.0


def _kept_ids(words: Sequence[Mapping[str, Any]], seg: compose.Segment, lo: int, hi: int) -> list[int]:
    return [i for i in range(lo, hi + 1) if seg.start <= _mid(words[i]) <= seg.end]


def _group(ids: list[int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for i in ids:
        if out and out[-1][1] == i - 1:
            out[-1] = (out[-1][0], i)
        else:
            out.append((i, i))
    return out


def build_composition(
    words: Sequence[Mapping[str, Any]],
    first_word: int,
    last_word: int,
    keep_decisions: Sequence[Sequence[int]] | None = None,
    policy: editorial.Policy | None = None,
    *,
    heat_payload: Mapping[str, Any] | None = None,
    visual_events: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Komposition für die Wörter ``first_word`` bis ``last_word``.

    ``keep_decisions`` sind die redaktionell behaltenen Wortbereiche (aufsteigend, ohne Überlappung;
    ``None`` heißt die ganze Spanne); jede Naht dazwischen ist semantisch. Innerhalb davon werden
    lokale Schnitte gesetzt: Kandidaten aus ``removal_candidates`` (nicht neben einer Pause, die keine
    technische ist) und technische Pausen (``classify_pauses``) mit mindestens ``trim.min_trim_gain_s``
    Gewinn, nie in einem Schutzbereich. Pausen werden auf ``trim.pause_target_s`` gekürzt, je zur
    Hälfte vor und nach der Naht. An entfernten Wörtern endet das Segment spätestens am Beginn des
    ersten entfernten Wortes und beginnt frühestens am Ende des letzten (kein hörbarer Rest). Ein
    lokaler Schnitt, der ein Segment unter ``trim.min_segment_s`` erzeugen würde, entfällt.

    Gezählt wird getrennt (``compose.splice_kinds``): ``semantic_splices`` (Verbindung nicht
    benachbarter Sätze, höchstens ``trim.max_semantic_splices``) und ``local_cuts``. ``density`` ist der
    Anteil der Spanne, der nicht durch semantische Schnitte wegfällt; lokale Schnitte und Ränder zählen
    nicht mit. Unter ``zusammenhang.mindest_dichte`` ist es eine Collage. Verstöße und Schutzbereich-
    Befunde hoher Schwere stehen in ``issues``, ``valid`` ist dann false; Prüfhinweise mittlerer Schwere
    in ``review_findings``.

    ``removed_spans`` im ``ClipCandidate``-Format (genau ``source_in``, ``source_out``,
    ``removal_reason``, ``protected_context_check``); ``protected_context_check`` trägt ``passed``,
    ``touched_types``, ``review_types``, ``checked_spans`` und unter ``detail`` die Art der Naht
    (``kind``: ``local``, ``semantic``, ``edge``), ``word_ids`` und ``text``."""
    pol, cfg = _policy_settings(policy)
    n = len(words)
    if not 0 <= first_word <= last_word < n:
        raise ValueError(f"Wortbereich {first_word} bis {last_word} liegt nicht in 0 bis {n - 1}")
    ranges = _keep_ranges(keep_decisions, first_word, last_word)
    span = list(words[first_word : last_word + 1])
    off = first_word

    def shift(r: Sequence[int]) -> tuple[int, int]:
        return int(r[0]) + off, int(r[1]) + off

    protected = [
        {**p, "word_range": list(shift(p["word_range"])), "lock_range": list(shift(p["lock_range"]))}
        for p in protected_spans(span, pol)
    ]
    prot_ranges = [tuple(p["word_range"]) for p in protected]
    pauses = [{**p, "after_word": p["after_word"] + off} for p in classify_pauses(span, heat_payload, pol, visual_events)]
    pause_at = {p["after_word"]: p for p in pauses}
    range_of = {i: k for k, (a, b) in enumerate(ranges) for i in range(a, b + 1)}
    forced = {i for i in range(first_word, last_word + 1) if i not in range_of and ranges[0][0] <= i <= ranges[-1][1]}

    # Lokale Schnitte: Wortgruppen und Pausen, jeweils mit Grund.
    cuts: list[dict] = []
    skipped: list[dict] = []
    for c in removal_candidates(span, pol):
        a, b = shift(c["word_range"])
        k = range_of.get(a)
        if k is None or range_of.get(b) != k or (a, b) == ranges[k]:
            skipped.append({**c, "word_range": [a, b], "skipped": "liegt nicht innerhalb einer behaltenen Passage"})
            continue
        # Am Rand des Clips fällt die Pause nach innen mit weg; das ist nur bei Innehalten oder stillem
        # Zeigen ein Verlust. Innen bleibt jede Pause, die keine technische ist, samt Nachbarwort stehen.
        edge = a == ranges[0][0] or b == ranges[-1][1]
        blocking = {"dramatic", "demonstration"} if edge else set(PAUSE_CLASSES) - {"technical"}
        if any(p is not None and p["class"] in blocking for p in (pause_at.get(a - 1), pause_at.get(b))):
            skipped.append({**c, "word_range": [a, b], "skipped": "neben einer Pause, die keine technische ist"})
            continue
        cuts.append({"kind": "words", "word_range": (a, b), "reason": c["reason"], "active": True})
    target = float(cfg["pause_target_s"])
    for p in pauses:
        i = p["after_word"]
        if p["class"] != "technical" or p["duration"] - target < float(cfg["min_trim_gain_s"]) - EPS:
            continue
        if range_of.get(i) is None or range_of.get(i) != range_of.get(i + 1):
            continue
        if any(a <= i and i + 1 <= b for a, b in prot_ranges):
            continue  # nie in einem Schutzbereich
        cuts.append({"kind": "pause", "after_word": i, "reason": "technical_pause", "active": True})

    # Überlappende Wortgruppen (Neustart samt „äh“) zu einer Stelle zusammenfassen.
    cuts.sort(key=lambda c: c["word_range"] if c["kind"] == "words" else (c["after_word"] + 0.5, c["after_word"] + 0.5))
    merged: list[dict] = []
    for c in cuts:
        if c["kind"] == "words" and merged and merged[-1]["kind"] == "words" and c["word_range"][0] <= merged[-1]["word_range"][1] + 1:
            a0, b0 = merged[-1]["word_range"]
            merged[-1]["word_range"] = (a0, max(b0, c["word_range"][1]))
            merged[-1]["reason"] = ",".join(dict.fromkeys(merged[-1]["reason"].split(",") + [c["reason"]]))
            continue
        merged.append(c)
    cuts = merged
    # Eine Pause neben entfernten Wörtern fällt mit der Wortgruppe weg; kein eigener Schnitt.
    for c in cuts:
        if c["kind"] == "pause" and any(
            d["kind"] == "words" and d["word_range"][0] - 1 <= c["after_word"] <= d["word_range"][1] for d in cuts
        ):
            c["active"] = False

    def state() -> tuple[set[int], set[int]]:
        removed = {i for c in cuts if c["active"] and c["kind"] == "words" for i in range(c["word_range"][0], c["word_range"][1] + 1)}
        split_after = {c["after_word"] for c in cuts if c["active"] and c["kind"] == "pause"}
        return removed, split_after

    def cut_between(p: tuple[int, int], q: tuple[int, int]) -> dict | None:
        for c in cuts:
            if not c["active"]:
                continue
            if c["kind"] == "pause" and c["after_word"] == p[1] and q[0] == p[1] + 1:
                return c
            if c["kind"] == "words" and p[1] < c["word_range"][0] and c["word_range"][1] < q[0]:
                return c
        return None

    min_seg = float(cfg["min_segment_s"])
    for _round in range(len(cuts) + 1):
        removed, split_after = state()
        pieces = _pieces(ranges, removed, split_after)
        changed = False
        for k, (a, b) in enumerate(pieces):
            nxt = pieces[k + 1] if k + 1 < len(pieces) else None
            # Würde ``from_keep_ranges`` die Naht ohnehin schließen, ist der Schnitt keiner.
            if nxt is not None:
                c = cut_between((a, b), nxt)
                gap = (float(words[nxt[0]]["start"]) - compose.LEAD_IN_S) - (float(words[b]["end"]) + compose.LEAD_OUT_S)
                if c is not None and c["kind"] == "words" and gap < compose.MERGE_GAP_S:
                    c["active"], c["dropped"] = False, "Naht zu kurz, wird verschmolzen"
                    changed = True
                    break
            if float(words[b]["end"]) - float(words[a]["start"]) >= min_seg:
                continue
            prv = pieces[k - 1] if k > 0 else None
            c = (cut_between((a, b), nxt) if nxt else None) or (cut_between(prv, (a, b)) if prv else None)
            if c is not None:
                c["active"], c["dropped"] = False, f"Segment kürzer als {min_seg:.2f} s"
                changed = True
                break
        if not changed:
            break
    removed, split_after = state()
    pieces = _pieces(ranges, removed, split_after)
    comp = compose.from_keep_ranges(list(words), pieces)
    segs = comp.segments

    # Ränder an entfernten Wörtern: kein hörbarer Rest; technische Pause: je die halbe Zielpause.
    gone = {i for i in range(first_word, last_word + 1)} - {i for a, b in pieces for i in range(a, b + 1)}
    for k, seg in enumerate(segs):
        ids = _kept_ids(words, seg, first_word, last_word)
        if not ids:
            continue
        if ids[0] - 1 in gone:
            seg.start = max(seg.start, round(float(words[ids[0] - 1]["end"]), 3))
        if ids[-1] + 1 in gone:
            seg.end = min(seg.end, round(float(words[ids[-1] + 1]["start"]), 3))
        if k + 1 < len(segs) and ids[-1] in split_after:
            nxt_ids = _kept_ids(words, segs[k + 1], first_word, last_word)
            if nxt_ids and nxt_ids[0] == ids[-1] + 1:
                i = ids[-1]
                seg.end = max(seg.end, round(float(words[i]["end"]) + target / 2.0, 3))
                segs[k + 1].start = min(segs[k + 1].start, round(float(words[i + 1]["start"]) - target / 2.0, 3))

    kinds = compose.splice_kinds(comp, list(words), forced)
    kept_ids = sorted({i for s in segs for i in _kept_ids(words, s, first_word, last_word)})
    findings = [
        {**f, "word_range": list(shift(f["word_range"]))}
        for f in protected_cut_findings(span, {i - off for i in kept_ids}, pol)
    ]
    reason_of: dict[int, str] = {}
    for c in cuts:
        if c["active"] and c["kind"] == "words":
            for i in range(c["word_range"][0], c["word_range"][1] + 1):
                reason_of[i] = c["reason"]

    def removed_entry(t0: float, t1: float, ids: list[int], kind: str) -> dict:
        reasons = list(dict.fromkeys(r for i in ids for r in reason_of.get(i, "keep_decision").split(","))) or ["technical_pause"]
        hits = [f for f in findings if any(f["word_range"][0] <= i <= f["word_range"][1] for i in ids)]
        touched = sorted({f["type"] for f in hits if f["severity"] == "high"})
        return {
            "source_in": round(t0, 3), "source_out": round(t1, 3), "removal_reason": "+".join(reasons),
            "protected_context_check": {
                "passed": not touched, "touched_types": touched,
                "review_types": sorted({f["type"] for f in hits if f["severity"] != "high"}),
                "checked_spans": len(protected),
                "detail": {"kind": kind, "word_ids": ids, "text": " ".join(_text(words[i]) for i in ids)},
            },
        }  # fmt: skip

    removed_spans: list[dict] = []
    if kept_ids and kept_ids[0] > first_word:
        ids = list(range(first_word, kept_ids[0]))
        removed_spans.append(removed_entry(float(words[first_word]["start"]), segs[0].start, ids, "edge"))
    for (seg, nxt_seg), kind in zip(zip(segs, segs[1:]), kinds):
        ids = [i for i in range(first_word, last_word + 1) if i not in kept_ids and seg.end < _mid(words[i]) < nxt_seg.start]
        if nxt_seg.start - seg.end > EPS:
            removed_spans.append(removed_entry(seg.end, nxt_seg.start, ids, kind))
    if kept_ids and kept_ids[-1] < last_word:
        ids = list(range(kept_ids[-1] + 1, last_word + 1))
        removed_spans.append(removed_entry(segs[-1].end, float(words[last_word]["end"]), ids, "edge"))

    total = float(words[last_word]["end"]) - float(words[first_word]["start"])
    by_kind = {k: sum(r["source_out"] - r["source_in"] for r in removed_spans if r["protected_context_check"]["detail"]["kind"] == k) for k in ("local", "semantic", "edge")}
    base = total - by_kind["local"] - by_kind["edge"]
    density = round(max(0.0, 1.0 - by_kind["semantic"] / base), 3) if base > EPS else 1.0
    issues = comp.validate(
        list(words), max_splices=int(cfg["max_semantic_splices"]), debate_no_reorder=bool(cfg["debate_no_reorder"]),
        forced_semantic=forced,
    )  # fmt: skip
    if density < float(cfg["min_density"]):
        issues.append(f"Dichte {density:.2f} unter zusammenhang.mindest_dichte {float(cfg['min_density']):.2f}: eher Collage als Passage")
    high = sorted({f["type"] for f in findings if f["severity"] == "high"})
    if high:
        issues.append(f"Schutzbereich berührt: {', '.join(high)}")
    for p in pauses:
        p["action"] = "trimmed" if p["after_word"] in split_after else "kept"
    return {
        "segments": comp.to_json(),
        "timeline": compose.output_timeline(comp),
        "duration_s": round(comp.duration, 3),
        "kept_word_ranges": [list(r) for r in _group(kept_ids)],
        "removed_spans": removed_spans,
        "semantic_splices": kinds.count("semantic"),
        "local_cuts": kinds.count("local"),
        "density": density,
        "is_debate": compose.is_debate(list(words), first_word, last_word),
        "pauses": pauses,
        "protected_spans": protected,
        "review_findings": [f for f in findings if f["severity"] != "high"],
        "skipped_candidates": skipped + [
            {"word_range": list(c["word_range"]), "reason": c["reason"], "skipped": c["dropped"]}
            for c in cuts if c["kind"] == "words" and c.get("dropped")
        ],  # fmt: skip
        "issues": issues,
        "valid": not issues,
        "policy_version": editorial.policy_version(pol.version),
    }


__all__ = [
    "PAUSE_CLASSES",
    "PROTECTED_TYPES",
    "build_composition",
    "classify_pauses",
    "is_hard_filler",
    "protected_cut_findings",
    "protected_spans",
    "removal_candidates",
    "reward_end",
]
