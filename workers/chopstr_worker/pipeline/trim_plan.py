"""Remove- und Keep-Logik mit Mehrsegment-Komposition (AP7, Policy v2, Abschnitt ``trim``).

Ballast raus, Bedeutung bleibt (Master-Prompt Abschnitte 12, 13, 15, 16, 18). Der Baustein ist noch
nicht in ``story_engine`` verdrahtet; er liest seine Werte über ``editorial.trim_settings`` auch bei
ausgeschaltetem Schalter ``implementation.trim.enabled``.

* ``protected_spans``: Schutzbereiche (Negation, Bedingung, Einschränkung, Vergleichsmaßstab, zeitliche
  Einordnung, Unsicherheit, Definition, Sprecherzuordnung, Korrektur), je ein Wort Rand. In einem
  Schutzbereich wird nichts entfernt und keine Pause gekürzt.
* ``classify_pauses``: Pausenklassen ``technical``, ``orientation``, ``dramatic``, ``reaction``,
  ``demonstration``. Nur ``technical`` wird gekürzt, und nie auf null (``trim.pause_target_s``).
* ``removal_candidates``: harte Füllwörter (P3), Einwürfe des Gegenübers, abgebrochene Ansätze mit
  Neustart, Begrüßung und Organisatorisches am Rand. Modalpartikeln nie.
* ``reward_end``: kappt den Nachlauf nach dem Payoff, nie eine Einschränkung oder Bedingung.
* ``build_composition``: baut über ``compose.from_keep_ranges`` die Komposition, zählt semantische
  Splices und lokale Schnitte getrennt, prüft E6 und ``zusammenhang.mindest_dichte`` und listet die
  entfernten Stellen im Format aus Master-Prompt Abschnitt 21 (``removed_spans``).

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

# Auslöser je Schutztyp, kleingeschrieben, mehrteilige Wendungen mit Leerzeichen. ``qualifier`` kommt
# aus ``fidelity.QUALIFIERS`` plus den einschränkenden Anschlüssen.
NEGATION_TRIGGERS = frozenset(dach_nlp.NEGATIONS) | {"nein"}
CONDITION_TRIGGERS = (
    "wenn", "falls", "sofern", "solange", "vorausgesetzt", "es sei denn", "unter der bedingung", "nur dann",
)  # fmt: skip
QUALIFIER_TRIGGERS = tuple(sorted(fidelity.QUALIFIERS)) + ("wobei", "allerdings", "jedoch", "abgesehen davon")
COMPARISON_TRIGGERS = (
    "im vergleich", "verglichen mit", "gegenüber", "im gegensatz zu", "statt", "anstatt", "mehr als",
    "weniger als", "doppelt so", "halb so", "als früher", "als vorher",
)  # fmt: skip
TEMPORAL_TRIGGERS = (
    "damals", "früher", "heute", "inzwischen", "mittlerweile", "seitdem", "seit", "vorher", "bisher",
    "anfangs", "zurzeit", "aktuell", "derzeit", "momentan", "letztes jahr", "letzten jahr", "dieses jahr",
    "im ersten quartal", "am anfang", "bis jetzt", "im moment",
)  # fmt: skip
UNCERTAINTY_TRIGGERS = (
    "wahrscheinlich", "vielleicht", "vermutlich", "eventuell", "möglicherweise", "ich glaube", "ich glaub", "ich denke",
    "ich schätze", "ungefähr", "etwa", "circa", "ca", "schätzungsweise", "angeblich", "anscheinend",
    "keine ahnung", "weiß nicht", "nicht sicher",
)  # fmt: skip
DEFINITION_TRIGGERS = (
    "das heißt", "heißt", "bedeutet", "meine ich", "gemeint", "verstehe ich", "versteht man", "nennt man",
    "nennen wir", "definiert", "im sinne von", "sprich",
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

# Stellen, vor denen eine Pause dramaturgisch ist (RK 7, Zeile „Pausen“).
CONTRAST_WORDS = tuple(fidelity.CONTRAST_STARTS) + ("sondern", "dennoch", "stattdessen")
# Rückmeldewörter des Gegenübers (``dach_nlp.BACKCHANNEL``) und Zögerlaute.
BACKCHANNEL_TOKENS = frozenset(dach_nlp.BACKCHANNEL) | frozenset(dach_nlp.HARD_FILLERS) | {"aha", "ah", "oh"}
RESTART_MAX_WORDS = 3
RESTART_BROKEN_SCAN = 5
# Funktionale Wiederholung („Nein, nein.“, „Ja, ja.“) ist kein abgebrochener Ansatz.
FUNCTIONAL_REPEAT = NEGATION_TRIGGERS | {"ja", "doch", "sehr", "ganz"}
# Einschränkungstypen, die ``reward_end`` nie kappt.
QUALIFYING_TYPES = frozenset({"negation", "condition", "qualifier", "uncertainty", "correction", "comparison_baseline"})
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


def _clause_end(words: Sequence[Mapping[str, Any]], b: int) -> int:
    """Letztes Wort des Satzes ab ``b``: Satzzeichen oder Sprecherwechsel, höchstens ``CLAUSE_MAX_WORDS``."""
    k = b
    limit = min(len(words) - 1, b + CLAUSE_MAX_WORDS)
    while k < limit and not _ends_sentence(_text(words[k])) and words[k + 1].get("speaker") == words[k].get("speaker"):
        k += 1
    return k


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


# -- Schutzbereiche --------------------------------------------------------------------------------


def protected_spans(words: Sequence[Mapping[str, Any]], policy: editorial.Policy | None = None) -> list[dict]:
    """Schutzbereiche je Typ aus ``PROTECTED_TYPES`` mit je einem Wort Rand.

    Rückgabe sortiert nach Wortbereich: ``{type, word_range: [a, b], trigger: [a, b], text}``. Bedingung,
    Vergleichsmaßstab, Definition, Sprecherzuordnung und Korrektur reichen bis zum Satzende (eine
    Bedingung ist mehr als ihr „wenn“), die übrigen Typen umfassen ihr Auslösewort. Einschränkungen
    kommen aus ``fidelity.QUALIFIERS`` plus „wobei“, „allerdings“, „jedoch“."""
    _policy_settings(policy)
    tokens = [_tok(w) for w in words]
    seen: set[tuple[str, int, int]] = set()
    out: list[dict] = []
    last = len(words) - 1
    for kind in PROTECTED_TYPES:
        for phrase in TRIGGERS[kind]:
            for ta, tb in _phrase_positions(tokens, phrase):
                end = _clause_end(words, tb) if kind in CLAUSE_TYPES else tb
                a, b = max(0, ta - MARGIN_WORDS), min(last, end + MARGIN_WORDS)
                if (kind, a, b) in seen:
                    continue
                seen.add((kind, a, b))
                out.append({
                    "type": kind, "word_range": [a, b], "trigger": [ta, tb],
                    "text": " ".join(_text(w) for w in words[ta : tb + 1]),
                })  # fmt: skip
    return sorted(out, key=lambda p: (p["word_range"][0], p["word_range"][1], PROTECTED_TYPES.index(p["type"])))


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


def _is_number(w: Mapping[str, Any]) -> bool:
    text = _text(w)
    if any(ch.isdigit() for ch in text):
        return True
    return fidelity.parse_number_word(_tok(w)) is not None


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
    * ``dramatic``: Pause vor einer Zahl, einer Negation oder einem Kontrastwort;
    * lange Stille ab ``trim.long_silence_s``: im laufenden Satz ``dramatic`` (Innehalten), sonst
      ``demonstration`` (mögliche Demonstration ohne Sprache);
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
    dramatic_before = set(cfg["dramatic_before"])
    reaction_after = set(cfg["reaction_after"])
    events = [e for e in (visual_events or []) if e.get("start") is not None and e.get("end") is not None]
    out: list[dict] = []
    for i in range(len(words) - 1):
        g = _gap(words, i)
        if g <= float(cfg["pause_target_s"]) + EPS:
            continue
        t0, t1 = float(words[i]["end"]), float(words[i + 1]["start"])
        cls, reason = _pause_class(words, i, g, t0, t1, ends, punch_inner, punch_after, events, heat_payload, cfg, dramatic_before, reaction_after)
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
    ends: set[int],
    punch_inner: dict[int, str],
    punch_after: dict[int, str],
    events: list[Mapping[str, Any]],
    heat_payload: Mapping[str, Any] | None,
    cfg: Mapping[str, Any],
    dramatic_before: set[str],
    reaction_after: set[str],
) -> tuple[str, str]:
    prev, nxt = words[i], words[i + 1]
    for e in events:
        overlap = min(t1, float(e["end"])) - max(t0, float(e["start"]))
        if overlap >= min(VISUAL_MIN_OVERLAP_S, 0.5 * g):
            return "demonstration", f"Bildereignis ohne Sprache ({e.get('type') or 'visual'})"
    if "punchline" in dramatic_before and i in punch_inner:
        return "dramatic", f"Pause vor der Pointe ({punch_inner[i]} danach)"
    if i in punch_after and ({"laughter", "reaction_word"} & reaction_after):
        return "reaction", f"Reaktion auf die Pointe ({punch_after[i]})"
    if "question" in reaction_after and _is_question(_text(prev)):
        return "reaction", "Pause nach einer Frage"
    if "reaction_word" in reaction_after and _is_reaction_word(words, i + 1, prev.get("speaker"), cfg):
        return "reaction", f"Pause vor dem Reaktionswort „{_text(nxt)}“"
    if "laughter" in reaction_after and _laughter_in(heat_payload, t0, t1):
        return "reaction", "Lachen in der Pause"
    tok = _tok(nxt)
    if "number" in dramatic_before and _is_number(nxt):
        return "dramatic", f"Pause vor der Zahl „{_text(nxt)}“"
    if "negation" in dramatic_before and tok in NEGATION_TRIGGERS:
        return "dramatic", f"Pause vor der Negation „{_text(nxt)}“"
    if "contrast" in dramatic_before and tok in CONTRAST_WORDS:
        return "dramatic", f"Pause vor dem Kontrastwort „{_text(nxt)}“"
    if g >= float(cfg["long_silence_s"]):
        if i not in ends and nxt.get("speaker") == prev.get("speaker"):
            return "dramatic", f"lange Stille im Satz ({g:.1f} s), Innehalten"
        return "demonstration", f"lange Stille ohne Sprache ({g:.1f} s), mögliche Demonstration"
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
    mitten im Beitrag eines anderen. Keiner, wenn der Beitrag davor eine Frage ist: dann ist das eine
    Antwort, auch wenn sie einsilbig ist („Ja.“ zwischen zwei Fragen)."""
    runs = _speaker_runs(words)
    out = []
    for k in range(1, len(runs) - 1):
        a, b = runs[k]
        prev_a, prev_b = runs[k - 1]
        nxt_a, _nxt_b = runs[k + 1]
        spk, other = words[a].get("speaker"), words[prev_b].get("speaker")
        if spk is None or other is None or words[nxt_a].get("speaker") != other:
            continue
        if b - a + 1 > compose.BACKCHANNEL_MAX_WORDS:
            continue
        if not all(_tok(words[i]) in BACKCHANNEL_TOKENS for i in range(a, b + 1)):
            continue
        if _is_question(_text(words[prev_b])):
            continue  # Antwort auf eine Frage
        out.append((a, b))
    return out


def _restarts(words: Sequence[Mapping[str, Any]], sentences: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Abgebrochener Ansatz mit Neustart am Satzanfang: dieselben ein bis drei Wörter noch einmal
    („Wir haben, äh, wir haben das …“) oder ein abgebrochenes Wort, nach dem der Satz neu beginnt
    („Wir hab- wir haben …“). Entfernt wird der erste Ansatz samt Zögerlauten dazwischen."""
    out = []
    toks = [_tok(w) for w in words]
    n = len(words)
    for i in sorted({a for a, _b in sentences}):
        found = None
        for k in range(RESTART_MAX_WORDS, 0, -1):
            first = list(range(i, i + k))
            if first[-1] >= n or any(not toks[j] or toks[j] in dach_nlp.HARD_FILLERS for j in first):
                continue
            if any(_ends_sentence(_text(words[j])) for j in first):
                continue
            if all(toks[j] in FUNCTIONAL_REPEAT for j in first):
                continue
            j = i + k
            while j < n and toks[j] in dach_nlp.HARD_FILLERS:
                j += 1
            second = list(range(j, j + k))
            if second[-1] >= n:
                continue
            if [toks[x] for x in first] == [toks[x] for x in second] and len({words[x].get("speaker") for x in first + second}) == 1:
                found = (i, j - 1)
                break
        if found is None:
            for j in range(i, min(n - 1, i + RESTART_BROKEN_SCAN)):
                t = _text(words[j]).rstrip(_CLOSERS)
                if t.endswith(("-", "…", "...")) and toks[j + 1] == toks[i] and words[j + 1].get("speaker") == words[i].get("speaker"):
                    found = (i, j)
                    break
        if found is not None:
            out.append(found)
    return out


def _edge_sentences(
    words: Sequence[Mapping[str, Any]], sentences: list[tuple[int, int]], cfg: Mapping[str, Any]
) -> list[tuple[int, int, str]]:
    """Begrüßung, Dank, Abschied und Organisatorisches als ganze Sätze am Anfang oder Ende; der letzte
    verbleibende Satz bleibt immer."""
    greeting = tuple(_norm(m) for m in cfg["edge_markers"])
    organisation = tuple(_norm(m) for m in cfg["organisation_markers"])

    def kind(a: int, b: int) -> str | None:
        text = f" {_norm(' '.join(_text(w) for w in words[a : b + 1]))} "
        if any(f" {m} " in text for m in organisation if m):
            return "organisational"
        if any(f" {m} " in text for m in greeting if m):
            return "greeting"
        return None

    out: list[tuple[int, int, str]] = []
    lo, hi = 0, len(sentences) - 1
    while lo < hi and (k := kind(*sentences[lo])) is not None:
        out.append((*sentences[lo], k))
        lo += 1
    while hi > lo and (k := kind(*sentences[hi])) is not None:
        out.append((*sentences[hi], k))
        hi -= 1
    return out


def removal_candidates(words: Sequence[Mapping[str, Any]], policy: editorial.Policy | None = None) -> list[dict]:
    """Was entfernt werden darf, je ``{word_range: [a, b], reason, text}``, sortiert.

    Gründe: ``hard_filler`` (äh, ähm; P3), ``backchannel`` (Einwurf des Gegenübers, nie eine Antwort
    auf eine Frage), ``restart`` (abgebrochener Ansatz mit Neustart am Satzanfang), ``greeting`` und
    ``organisational`` (nur am Anfang oder Ende, ``trim.removal.edge_markers`` und
    ``ausschluss.organisations_marker``). Ausgeschlossen sind Kandidaten mit einem Wort aus
    ``trim.removal.never_remove`` (Modalpartikeln), Kandidaten in einem Schutzbereich
    (``protected_spans``) und Kandidaten neben einer Stille ab ``trim.long_silence_s`` (das Zögern davor
    gehört zur Szene, etwa vor einer stillen Demonstration)."""
    pol, cfg = _policy_settings(policy)
    if not words:
        return []
    sentences = _sentence_ranges(words, pol)
    raw: list[tuple[int, int, str]] = []
    if cfg["fillers"] == "hard":
        raw += [(i, i, "hard_filler") for i, w in enumerate(words) if _tok(w) in dach_nlp.HARD_FILLERS]
    if cfg["backchannel"]:
        raw += [(a, b, "backchannel") for a, b in _backchannels(words)]
    if cfg["restarts"]:
        raw += [(a, b, "restart") for a, b in _restarts(words, sentences)]
    raw += _edge_sentences(words, sentences, cfg)

    protected = [tuple(p["word_range"]) for p in protected_spans(words, pol)]
    never = set(cfg["never_remove"])
    long_s = float(cfg["long_silence_s"])
    out, seen = [], set()
    for a, b, reason in sorted(raw):
        if (a, b, reason) in seen:
            continue
        seen.add((a, b, reason))
        if any(_tok(words[i]) in never for i in range(a, b + 1)):
            continue
        if any(_overlaps((a, b), p) for p in protected):
            continue
        if (a > 0 and _gap(words, a - 1) >= long_s) or (b + 1 < len(words) and _gap(words, b) >= long_s):
            continue
        out.append({"word_range": [a, b], "reason": reason, "text": " ".join(_text(w) for w in words[a : b + 1])})
    return out


# -- Ende nach dem Payoff --------------------------------------------------------------------------


def _sentence_text(s: Any) -> str:
    return str(s.get("text", "") if isinstance(s, Mapping) else getattr(s, "text", ""))


def _content_tokens(text: str) -> set[str]:
    return {t for t in _norm(text).split() if len(t) >= REPEAT_MIN_TOKEN_LEN}


def _is_qualifying(text: str, pol: editorial.Policy) -> bool:
    """Trägt der Satz eine Einschränkung, Bedingung, Negation, Unsicherheit oder Korrektur?"""
    low = _norm(text)
    markers = tuple(_norm(m) for m in pol.ausstieg.get("abschwaechung_marker") or ())
    if any(low == m or low.startswith(m + " ") for m in markers + tuple(fidelity.CONTRAST_STARTS) if m):
        return True
    pseudo = [{"text": t, "start": 0.0, "end": 0.0} for t in str(text).split()]
    return any(p["type"] in QUALIFYING_TYPES for p in protected_spans(pseudo, pol))


def _tail_reason(text: str, payoff_text: str, cfg: Mapping[str, Any]) -> str | None:
    low = f" {_norm(text)} "
    head = _norm(text)
    if any(head.startswith(_norm(m)) for m in cfg["weak_summary"]):
        return "weak_summary"
    if any(f" {_norm(m)}" in low for m in cfg["sales_call"]):  # Wortanfang: „abonnier“ trifft „abonniert“
        return "sales_call"
    if any(f" {_norm(m)} " in low for m in cfg["farewell"]):
        return "farewell"
    mine, payoff = _content_tokens(text), _content_tokens(payoff_text)
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
    """Neues letztes Satzindex und die gekappten Sätze ``{sentence, reason, text}``.

    Gekappt wird von hinten, solange jeder Satz nach dem Payoff Nachlauf ist: wiederholte Pointe
    (``repeated_payoff``), schwache Zusammenfassung (``weak_summary``), Verkaufsaufruf
    (``sales_call``) oder Verabschiedung (``farewell``). Ein Satz mit Einschränkung, Bedingung,
    Negation, Unsicherheit oder Korrektur wird nie gekappt und hält alles davor fest. Ohne Payoff
    (``None``) oder mit Payoff am Ende bleibt das Ende."""
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


def _pieces(
    ranges: list[tuple[int, int]], removed: set[int], split_after: set[int]
) -> list[tuple[int, int]]:
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


def _kept_ids(words: Sequence[Mapping[str, Any]], seg: compose.Segment, lo: int, hi: int) -> list[int]:
    return [i for i in range(lo, hi + 1) if seg.start <= (float(words[i]["start"]) + float(words[i]["end"])) / 2.0 <= seg.end]


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
    ``None`` heißt die ganze Spanne). Innerhalb davon werden lokale Schnitte gesetzt: Kandidaten aus
    ``removal_candidates`` (nicht neben einer Pause, die keine technische ist) und technische Pausen
    (``classify_pauses``) mit mindestens ``trim.min_trim_gain_s`` Gewinn, beide nie in einem
    Schutzbereich. Pausen werden auf ``trim.pause_target_s`` gekürzt, je zur Hälfte vor und nach der
    Naht. Ein lokaler Schnitt, der ein Segment unter ``trim.min_segment_s`` erzeugen würde, entfällt.

    Gezählt wird getrennt (``compose.splice_kinds``): ``semantic_splices`` (Verbindung nicht
    benachbarter Sätze, höchstens ``trim.max_semantic_splices``) und ``local_cuts``. ``density`` ist
    die gesprochene Zeit der Segmente (erstes bis letztes behaltenes Wort je Segment) durch die
    Gesamtdauer der Spanne; unter ``zusammenhang.mindest_dichte`` ist es eine Collage. Verstöße stehen
    in ``issues``, ``valid`` ist dann false; der Aufrufer fällt auf die ungekürzte Fassung zurück.

    ``removed_spans`` je Stelle: ``source_in``, ``source_out``, ``removal_reason``,
    ``protected_context_check`` (Master-Prompt Abschnitt 21) plus ``kind`` (``local``, ``semantic``,
    ``edge``), ``word_ids`` und ``text``."""
    pol, cfg = _policy_settings(policy)
    n = len(words)
    if not 0 <= first_word <= last_word < n:
        raise ValueError(f"Wortbereich {first_word} bis {last_word} liegt nicht in 0 bis {n - 1}")
    ranges = _keep_ranges(keep_decisions, first_word, last_word)
    span = list(words[first_word : last_word + 1])
    off = first_word

    def shift(r: Sequence[int]) -> tuple[int, int]:
        return int(r[0]) + off, int(r[1]) + off

    protected = [{**p, "word_range": list(shift(p["word_range"]))} for p in protected_spans(span, pol)]
    prot_ranges = [tuple(p["word_range"]) for p in protected]
    pauses = [{**p, "after_word": p["after_word"] + off} for p in classify_pauses(span, heat_payload, pol, visual_events)]
    pause_at = {p["after_word"]: p for p in pauses}
    range_of = {i: k for k, (a, b) in enumerate(ranges) for i in range(a, b + 1)}

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

    # Technische Pause: je die halbe Zielpause vor und nach der Naht behalten, nie null.
    for seg, nxt_seg in zip(comp.segments, comp.segments[1:]):
        between = [i for i in range(first_word, last_word + 1) if seg.end < (float(words[i]["start"]) + float(words[i]["end"])) / 2.0 < nxt_seg.start]
        ids_l = _kept_ids(words, seg, first_word, last_word)
        ids_r = _kept_ids(words, nxt_seg, first_word, last_word)
        if not between and ids_l and ids_r and ids_l[-1] in split_after and ids_r[0] == ids_l[-1] + 1:
            i = ids_l[-1]
            seg.end = max(seg.end, round(float(words[i]["end"]) + target / 2.0, 3))
            nxt_seg.start = min(nxt_seg.start, round(float(words[i + 1]["start"]) - target / 2.0, 3))

    kinds = compose.splice_kinds(comp, list(words))
    kept_ids = sorted({i for s in comp.segments for i in _kept_ids(words, s, first_word, last_word)})
    reason_of: dict[int, str] = {}
    for c in cuts:
        if c["active"] and c["kind"] == "words":
            for i in range(c["word_range"][0], c["word_range"][1] + 1):
                reason_of[i] = c["reason"]

    def removed_entry(t0: float, t1: float, ids: list[int], kind: str) -> dict:
        reasons = list(dict.fromkeys(r for i in ids for r in reason_of.get(i, "keep_decision").split(",")))
        if not ids:
            reasons = ["technical_pause"]
        t0, t1 = round(t0, 3), round(t1, 3)
        touched = sorted({
            p["type"] for p in protected
            if any(p["word_range"][0] <= i <= p["word_range"][1] for i in ids)
            or (ids == [] and float(words[p["word_range"][0]]["start"]) < t1 and t0 < float(words[p["word_range"][1]]["end"]))
        })  # fmt: skip
        return {
            "source_in": t0, "source_out": t1, "removal_reason": "+".join(reasons),
            "protected_context_check": {"passed": not touched, "touched_types": touched, "checked_spans": len(protected)},
            "kind": kind, "word_ids": ids, "text": " ".join(_text(words[i]) for i in ids),
        }  # fmt: skip

    removed_spans: list[dict] = []
    segs = comp.segments
    if kept_ids and kept_ids[0] > first_word:
        ids = list(range(first_word, kept_ids[0]))
        removed_spans.append(removed_entry(float(words[first_word]["start"]), segs[0].start, ids, "edge"))
    for (seg, nxt_seg), kind in zip(zip(segs, segs[1:]), kinds):
        ids = [i for i in range(first_word, last_word + 1) if i not in kept_ids and seg.end < (float(words[i]["start"]) + float(words[i]["end"])) / 2.0 < nxt_seg.start]
        if nxt_seg.start - seg.end > EPS:
            removed_spans.append(removed_entry(seg.end, nxt_seg.start, ids, kind))
    if kept_ids and kept_ids[-1] < last_word:
        ids = list(range(kept_ids[-1] + 1, last_word + 1))
        removed_spans.append(removed_entry(segs[-1].end, float(words[last_word]["end"]), ids, "edge"))

    total = float(words[last_word]["end"]) - float(words[first_word]["start"])
    spoken = 0.0
    for s in segs:
        ids = _kept_ids(words, s, first_word, last_word)
        if ids:
            spoken += float(words[ids[-1]]["end"]) - float(words[ids[0]]["start"])
    density = round(spoken / total, 3) if total > 0 else 1.0
    issues = comp.validate(list(words), max_splices=int(cfg["max_semantic_splices"]), debate_no_reorder=bool(cfg["debate_no_reorder"]))
    if density < float(cfg["min_density"]):
        issues.append(f"Dichte {density:.2f} unter zusammenhang.mindest_dichte {float(cfg['min_density']):.2f}: eher Collage als Passage")
    issues += [f"Schutzbereich berührt: {', '.join(r['protected_context_check']['touched_types'])}" for r in removed_spans if not r["protected_context_check"]["passed"]]
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
    "protected_spans",
    "removal_candidates",
    "reward_end",
]
