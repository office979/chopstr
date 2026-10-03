"""Harte redaktionelle Gates vor dem Ranking (AP4, Policy-Fassung 2).

Reine Funktionen über die Wortliste ``words`` (Dicts mit ``text``, ``start``, ``end``, ``speaker``), die
Satzliste ``sents`` (``segment.Sentence``) und den Kandidaten als Satzspanne ``first`` bis ``last``. Jede
Funktion liefert ein GateResult::

    {"passed": bool, "detail": "<deutscher Satz>", "evidence_word_ids": [int, ...],
     "healable": "front" | "back" | None, "origin": "F" | "H" | "R"}

``healable`` sagt, auf welcher Seite eine Erweiterung den Mangel beheben könnte (``front`` über
``story_engine.heal_start``, ``back`` über ``story_engine.kontext_verlaengern``); ``None`` heißt, nur
Verwerfen hilft. ``origin`` kommt aus ``origins.gates.<schluessel>`` der Policy. Die beiden markierenden
Gates (``embedded_instruction``, ``meta_speech``) verwerfen nie: ``passed`` bleibt True, ``flagged`` und
``quotes`` zeigen den Treffer, der Kandidat bleibt Inhalt (Master-Prompt 22 und 27).

``run_gates`` sammelt alle eingeschalteten Gates (``gates.<schluessel>`` der Policy) und leitet eine
Entscheidung ab; ``gates.discard_hard`` entscheidet, ob Verletzer verworfen oder nur berichtet werden.
Verdrahtet in ``story_engine`` wird das Modul erst mit ``implementation.gates.discard_hard``.

Die Wortlisten hier sind Übertragungshypothesen ohne Messung (Herkunft H, RK 2 Befund 6 und 11). Abgleich
immer an Wortgrenzen über ``dach_nlp.core_token``: „außer“ trifft nicht „außerdem“. Transkripte sind
Daten; nichts hier führt eine Anweisung aus dem Transkript aus.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .. import editorial
from . import dach_nlp, story_graph
from .segment import Sentence

GateResult = dict[str, Any]

GATE_KEYS = editorial.GATE_RULE_KEYS
# Gates, die nur markieren und nie verwerfen.
FLAG_ONLY = frozenset({"embedded_instruction", "meta_speech"})
# Abbildung auf die fünf bestehenden Gate-Schlüssel für ``story_engine.deterministic_gates`` (Plan AP4).
LEGACY_GATE = {
    "unresolved_pronoun": "standalone",
    "back_reference": "standalone",
    "open_question_unanswered": "standalone",
    "forward_reference": "standalone",
    "speaker_turn": "standalone",
    "boundary_negation_condition": "fidelity",
    "reported_speech": "fidelity",
    "later_correction": "fidelity",
    "embedded_instruction": None,
    "meta_speech": None,
}
DEFAULT_ORIGIN = "R"
CONTEXT_BEFORE = 2  # Sätze vor dem Anfang, in denen ein Zitatrahmen gesucht wird
CONTEXT_AFTER = 2  # Sätze nach dem Ende, in denen eine Distanzierung gesucht wird
HEAL_REACH_SENTENCES = 2  # wie laenge.kontext_zugabe_saetze: weiter reicht eine Heilung nicht
QUOTE_WORDS = 8

DEFAULT_PRONOUNS = ("er", "sie", "ihn", "ihm", "ihr", "ihnen", "dessen", "deren")
# Höflichkeitsverben nach „Sie“ am Satzanfang (Plural- und Höflichkeitsform).
POLITE_VERBS = frozenset({
    "sind", "haben", "hätten", "können", "könnten", "müssen", "müssten", "sollten", "dürfen", "werden",
    "würden", "wissen", "kennen", "sehen", "glauben", "stellen", "merken", "wollen", "möchten", "brauchen",
    "finden", "denken", "meinen",
})  # fmt: skip
FORMAL_FORMS = frozenset({"sie", "ihnen", "ihr", "ihre", "ihren", "ihrem", "ihrer", "ihres"})
SECOND_PLURAL = frozenset({"euch", "euer", "eure", "euren", "eurem", "eurer", "eures"})
SECOND_PERSON = frozenset({
    "du", "dich", "dir", "dein", "deine", "deinen", "deinem", "deiner", "deines", "euch", "euer", "eure",
    "euren", "eurem", "eurer", "eures",
})  # fmt: skip
SECOND_PLURAL_VERBS = frozenset({
    "habt", "seid", "wart", "wisst", "könnt", "müsst", "sollt", "solltet", "wollt", "dürft", "macht",
    "kennt", "seht", "braucht", "geht", "kommt", "findet", "denkt", "glaubt", "werdet", "hattet", "wäret",
    "würdet", "könntet", "müsstet",
})  # fmt: skip

BACK_PHRASES = (
    "wie gesagt", "wie schon gesagt", "wie bereits gesagt", "wie eben gesagt", "das von vorhin",
    "wie erwähnt", "wie schon erwähnt", "wie bereits erwähnt", "wie vorhin",
)  # fmt: skip
DEMONSTRATIVE_STARTS = frozenset({"das", "dies", "dieses", "diese", "dieser", "diesem", "diesen", "der", "die", "dem", "den"})
SUBSTITUTING = frozenset({"das", "dies"})
DETERMINERS = frozenset({
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem", "einer", "mein", "meine",
    "dein", "deine", "sein", "seine", "unser", "unsere", "euer", "eure",
})  # fmt: skip
# Finite Verben direkt nach einem Demonstrativ am Satzanfang („Das ist genau der Punkt“): ohne spaCy das
# Zeichen für ein substituierendes Demonstrativpronomen (PDS).
VERBS_AFTER_DEMONSTRATIVE = frozenset({
    "ist", "war", "sind", "waren", "hat", "hatte", "haben", "hatten", "heißt", "bedeutet", "muss", "kann",
    "wird", "wurde", "stimmt", "zeigt", "gilt", "klingt", "macht", "geht", "liegt", "kommt", "wäre",
    "hätte", "würde", "könnte", "sollte", "bringt", "reicht", "passt",
})  # fmt: skip
BACKREF_POS_TAGS = frozenset({"PDS", "PDAT"})
ADJECTIVE_ENDINGS = ("e", "en", "er", "es", "em")

NEGATION_TOKENS = frozenset({
    "nicht", "nein", "kein", "keine", "keinen", "keinem", "keiner", "keines", "keins",
    "ned", "nöd", "nid", "nit", "net",
})  # fmt: skip
CONDITION_MARKERS = ("nur wenn", "es sei denn", "wenn", "falls", "außer", "sofern")
CONTRAST_OPENERS = ("aber", "allerdings", "jedoch", "wobei", "trotzdem", "außer", "nur", "es sei denn", "sofern")
CONNECTOR_OPENERS = ("und", "aber", "also", "dann", "deshalb", "deswegen", "sondern", "doch", "trotzdem", "darum")
ANAPHORS = frozenset({
    "dies", "so", "dann", "dabei", "damit", "davon", "dafür", "dazu", "darauf", "darum", "deshalb",
    "deswegen", "trotzdem",
})  # fmt: skip
BEZUG_WINDOW = 6

FRAME_PHRASES = ("die sagen dann", "heißt es", "hieß es")
FRAME_TOKENS = frozenset({"sagt", "sagte", "sagten", "meint", "meinte", "meinten", "behauptet", "behauptete", "angeblich"})
FRAME_NOT_AFTER = frozenset({"ehrlich", "genauer", "wie", "anders", "kurz", "offen", "ganz", "gesagt"})
PERFECT_AUX = frozenset({"hat", "hatte", "haben", "hatten"})
FIRST_PERSON = frozenset({"ich", "wir"})
LAUT_FOLLOWERS = frozenset({
    "dem", "der", "den", "des", "einer", "einem", "eines", "meinem", "meiner", "unserem", "unserer",
    "seinem", "seiner", "ihrem", "ihrer", "deren", "dessen",
})  # fmt: skip
SUBJUNCTIVE_I = frozenset({"sei", "seien", "seiest", "könne", "müsse", "solle", "wolle", "dürfe", "möge", "wisse"})
SUBJUNCTIVE_I_NOT_AFTER_ICH = frozenset({"habe", "werde", "gebe", "komme", "gehe", "mache", "brauche", "stehe", "liege", "bringe"})
DISTANCING = (
    "sehe das anders", "sehe ich anders", "seh das anders", "sehe das ganz anders", "das stimmt nicht",
    "stimmt so nicht", "das ist falsch", "halte ich für falsch", "quatsch", "unsinn", "blödsinn",
    "widerspreche", "anderer meinung", "glaube ich nicht", "glaub ich nicht", "finde ich nicht",
)  # fmt: skip

FORWARD_IMMEDIATE = (
    "gleich erkläre ich", "erkläre ich gleich", "das zeige ich gleich", "zeige ich gleich",
    "gleich zeige ich", "dazu komme ich",
)  # fmt: skip
FORWARD_DEFERRED = ("später mehr", "dazu komme ich später", "dazu komme ich noch", "darauf komme ich noch")

RESPONSE_PARTICLES = frozenset({
    "ja", "nein", "jein", "doch", "genau", "klar", "nie", "absolut", "sicher", "natürlich", "definitiv",
    "dann", "okay", "ok", "stimmt", "richtig", "eher",
})  # fmt: skip
ANSWER_PHRASES = ("meine antwort", "die antwort ist", "kurze antwort", "kurz gesagt ja", "kurz gesagt nein")
ELLIPTIC_MAX_WORDS = 3

INSTRUCTION_PHRASES = (
    "du bist jetzt", "du bist ab jetzt", "ab jetzt bist du", "liebe ki", "lieber ki", "hallo ki", "hey ki",
    "chatgpt", "vergiss alle", "vergiss alles", "vergiss deine", "neue anweisung", "neue anweisungen",
    "deine anweisungen", "spiel die rolle", "spiele die rolle", "tu so als", "verhalte dich wie",
    "ignorieren sie", "ignoriert alle",
)  # fmt: skip
# Imperativ von „ignorieren“; „wir haben das ignoriert“ ist keine Anweisung.
INSTRUCTION_TOKENS = frozenset({"ignoriere", "ignorier"})
ROLE_LABELS = frozenset({"system:", "assistant:", "user:"})
SEPARABLE_GIB_AUS_WINDOW = 6
# Wörter, die in einer zitierten Anweisung keine Aussage tragen (für ``instruction_followed``).
STOPWORDS = frozenset({
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem", "einer", "und", "oder", "in",
    "im", "an", "am", "auf", "zu", "zum", "zur", "mit", "von", "vom", "für", "als", "alle", "jeder", "jede",
    "jedes", "dieser", "diese", "dieses", "diesem", "ist", "sind", "du", "dich", "dir", "ich", "wir", "es",
    "nicht", "auch", "noch", "mal", "so", "wie", "was", "bitte",
})  # fmt: skip
QUOTE_NGRAM = 3
RARE_TOKEN_MIN = 10


# -- Hilfen ----------------------------------------------------------------------------------------


def _core(text: Any) -> str:
    return dach_nlp.core_token(str(text or ""))


def _raw(w: Mapping[str, Any]) -> str:
    return str(w.get("text") or "").strip()


def _phrase(p: str) -> tuple[str, ...]:
    return tuple(t for t in (_core(x) for x in p.split()) if t)


def _tokens(words: Sequence[Mapping[str, Any]], a: int, b: int) -> list[tuple[int, str]]:
    """``(wortindex, kerntoken)`` für die Wörter ``a`` bis ``b``, leere Tokens fallen weg."""
    out = []
    for i in range(max(a, 0), min(b, len(words) - 1) + 1):
        t = _core(words[i].get("text"))
        if t:
            out.append((i, t))
    return out


def _sent_tokens(words: Sequence[Mapping[str, Any]], s: Sentence) -> list[tuple[int, str]]:
    return _tokens(words, s.word_range[0], s.word_range[1])


def _find(toks: list[tuple[int, str]], phrases: Iterable[str]) -> tuple[str, list[int]] | None:
    """Erste Wendung aus ``phrases`` als Wortfolge in ``toks`` (Wortgrenzen): Wendung und Wortindizes."""
    seq = [t for _i, t in toks]
    for p in phrases:
        pt = _phrase(p)
        n = len(pt)
        for k in range(len(seq) - n + 1):
            if tuple(seq[k : k + n]) == pt:
                return p, [toks[k + j][0] for j in range(n)]
    return None


def _text(words: Sequence[Mapping[str, Any]], ids: Sequence[int], limit: int = QUOTE_WORDS) -> str:
    return " ".join(_raw(words[i]) for i in list(ids)[:limit])


def _sentence_text(s: Sentence, limit: int = QUOTE_WORDS) -> str:
    parts = s.text.split()
    return " ".join(parts[:limit]) + (" …" if len(parts) > limit else "")


def _ids(s: Sentence) -> list[int]:
    return list(range(s.word_range[0], s.word_range[1] + 1))


def _is_question(s: Sentence) -> bool:
    return s.text.rstrip().rstrip("\"'»«“”‘’)").endswith("?")


def _origin(policy: Any, key: str) -> str:
    roh = getattr(policy, "roh", None) or {}
    entry = (roh.get("origins") or {}).get(f"gates.{key}")
    origin = entry.get("origin") if isinstance(entry, dict) else None
    return str(origin) if origin else DEFAULT_ORIGIN


def _result(
    key: str,
    policy: Any,
    passed: bool,
    detail: str,
    evidence: Iterable[int] = (),
    healable: str | None = None,
) -> GateResult:
    return {
        "passed": bool(passed),
        "detail": detail,
        "evidence_word_ids": sorted(set(int(i) for i in evidence)),
        "healable": healable if not passed else None,
        "origin": _origin(policy, key),
    }


def _is_backchannel(words: Sequence[Mapping[str, Any]], s: Sentence) -> bool:
    toks = _sent_tokens(words, s)
    return len(toks) == 1 and toks[0][1] in dach_nlp.BACKCHANNEL


def from_sentence_texts(items: Sequence[Mapping[str, Any]]) -> tuple[list[dict], list[Sentence]]:
    """Wort- und Satzliste aus Sätzen ohne Wortzeiten (``{"text", "speaker"}``), etwa aus dem Heuristik-Prompt.

    Zeiten sind künstlich (drei Wörter je Sekunde) und nur Platzhalter; die Gates hier lesen sie nicht."""
    words: list[dict] = []
    sents: list[Sentence] = []
    for item in items:
        speaker = item.get("speaker")
        a = len(words)
        for tok in str(item.get("text") or "").split():
            t = len(words) / 3.0
            words.append({"text": tok, "start": t, "end": t + 0.3, "speaker": speaker})
        if len(words) == a:
            continue
        b = len(words) - 1
        sents.append(Sentence(idx=len(sents), text=" ".join(w["text"] for w in words[a:]), start=words[a]["start"],
                              end=words[b]["end"], speaker=speaker, word_range=(a, b)))  # fmt: skip
    return words, sents


# -- Pronomen und Rückverweise ---------------------------------------------------------------------


def _pronouns(policy: Any) -> frozenset[str]:
    einstieg = getattr(policy, "einstieg", None) or {}
    return frozenset(str(p).lower() for p in (einstieg.get("pronomen") or DEFAULT_PRONOUNS))


def _is_formal_sie(words: Sequence[Mapping[str, Any]], toks: list[tuple[int, str]], k: int) -> bool:
    """Höflichkeitsform: großgeschrieben mitten im Satz, oder am Satzanfang mit Höflichkeitsverb und einer
    Anrede (Frage, Ausruf oder weitere Höflichkeitsform im Satz)."""
    i, core = toks[k]
    if core not in FORMAL_FORMS or not _raw(words[i])[:1].isupper():
        return False
    if k > 0:
        return True
    if core != "sie" or len(toks) < 2 or toks[1][1] not in POLITE_VERBS:
        return False
    last_raw = _raw(words[toks[-1][0]])
    other_formal = any(t in FORMAL_FORMS and _raw(words[j])[:1].isupper() for j, t in toks[1:])
    return last_raw.endswith(("?", "!")) or other_formal


def _is_plural_address(toks: list[tuple[int, str]], k: int) -> bool:
    """„ihr“ als Anrede an mehrere („ihr habt“, „habt ihr“, „wenn ihr eure …“), kein Pronomen der 3. Person."""
    if toks[k][1] != "ihr":
        return False
    nxt = toks[k + 1][1] if k + 1 < len(toks) else ""
    prev = toks[k - 1][1] if k > 0 else ""
    return nxt in SECOND_PLURAL_VERBS or prev in SECOND_PLURAL_VERBS or any(t in SECOND_PLURAL for _j, t in toks)


def _is_noun(words: Sequence[Mapping[str, Any]], toks: list[tuple[int, str]], k: int) -> bool:
    i, core = toks[k]
    return k > 0 and _raw(words[i])[:1].isupper() and core not in FORMAL_FORMS


def unresolved_pronoun(
    words: Sequence[Mapping[str, Any]], sents: Sequence[Sentence], first: int, last: int, policy: Any = None
) -> GateResult:
    """Pronomen aus ``einstieg.pronomen`` im ersten Satz vor jedem Nomen, also ohne Antezedens im Clip.

    „Es“ steht nicht in der Liste (meist Platzhalter). Die Höflichkeitsform „Sie“ und „ihr“ als Anrede an
    mehrere sind keine Treffer. Heilbar nach vorn: der Bezug steht meist im Satz davor."""
    key = "unresolved_pronoun"
    pronouns = _pronouns(policy)
    toks = _sent_tokens(words, sents[first])
    for k, (i, core) in enumerate(toks):
        if _is_noun(words, toks, k):
            break
        if core not in pronouns or _is_formal_sie(words, toks, k) or _is_plural_address(toks, k):
            continue
        return _result(key, policy, False, f"Pronomen „{_raw(words[i])}“ ohne Bezug im Clip", [i], "front")
    return _result(key, policy, True, "kein Pronomen ohne Bezug am Anfang")


def _is_substituting(words: Sequence[Mapping[str, Any]], toks: list[tuple[int, str]], k: int) -> bool:
    """„das“ oder „dies“ als Pronomen, nicht als Artikel: es folgt kein Nomen (auch nicht nach einem Adjektiv)."""
    if toks[k][1] not in SUBSTITUTING or _raw(words[toks[k][0]]).endswith(":"):
        return False  # „Konkret heißt das: …“ verweist nach vorn
    if k + 1 >= len(toks):
        return True
    j, nxt = toks[k + 1]
    if _raw(words[j])[:1].isupper() or nxt in ("was", "wo") or nxt in DETERMINERS:
        return False  # „war das der teuerste Fehler“: das Nomen folgt im Satz
    noun_after_adjective = k + 2 < len(toks) and _raw(words[toks[k + 2][0]])[:1].isupper()
    return not (nxt.endswith(ADJECTIVE_ENDINGS) and noun_after_adjective)


def _demonstrative_start(words: Sequence[Mapping[str, Any]], s: Sentence) -> int | None:
    """Wortindex eines Demonstrativpronomens am Satzanfang (spaCy: PDS oder PDAT wie ``clip_eval``)."""
    toks = _sent_tokens(words, s)
    if not toks or toks[0][1] not in DEMONSTRATIVE_STARTS:
        return None
    pipe = dach_nlp.nlp()
    if pipe is not None:
        doc = pipe(" ".join(_raw(words[i]) for i, _t in toks[:QUOTE_WORDS]))
        return toks[0][0] if len(doc) and doc[0].tag_ in BACKREF_POS_TAGS else None
    if len(toks) > 1 and toks[1][1] in VERBS_AFTER_DEMONSTRATIVE:
        return toks[0][0]
    return None


def back_reference(
    words: Sequence[Mapping[str, Any]], sents: Sequence[Sentence], first: int, last: int, policy: Any = None
) -> GateResult:
    """Rückverweis auf etwas vor dem Clip: „wie gesagt“, „das von vorhin“, „wie erwähnt“, „wie vorhin“ im
    Clip, ein Demonstrativpronomen am Satzanfang des ersten Satzes oder ein „das“ als Pronomen im ersten
    Satz vor jedem Nomen („Ich sehe das anders.“)."""
    key = "back_reference"
    a, b = sents[first].word_range[0], sents[last].word_range[1]
    hit = _find(_tokens(words, a, b), BACK_PHRASES)
    if hit:
        phrase, ids = hit
        return _result(key, policy, False, f"Rückverweis „{_text(words, ids)}“ auf etwas vor dem Clip", ids, "front")
    i = _demonstrative_start(words, sents[first])
    if i is not None:
        return _result(key, policy, False, f"Demonstrativ „{_raw(words[i])}“ am Anfang ohne Bezug im Clip", [i], "front")
    toks = _sent_tokens(words, sents[first])
    for k, (i, _core_t) in enumerate(toks):
        if _is_noun(words, toks, k):
            break
        if _is_substituting(words, toks, k):
            return _result(key, policy, False, f"„{_raw(words[i])}“ im ersten Satz verweist auf etwas vor dem Clip", [i], "front")
    return _result(key, policy, True, "kein Rückverweis auf etwas vor dem Clip")


# -- Fragen, Grenzsätze, indirekte Rede, Vorverweise -----------------------------------------------------


def _addressed(words: Sequence[Mapping[str, Any]], s: Sentence) -> bool:
    """Richtet sich die Frage an ein Gegenüber („du“, „ihr“, „euch“, Höflichkeitsform „Sie“)?"""
    toks = _sent_tokens(words, s)
    return any(
        t in SECOND_PERSON or _is_plural_address(toks, k) or _is_formal_sie(words, toks, k)
        for k, (_i, t) in enumerate(toks)
    )


def open_question_unanswered(
    words: Sequence[Mapping[str, Any]], sents: Sequence[Sentence], first: int, last: int, policy: Any = None
) -> GateResult:
    """Frage im Clip ohne Antwortsatz danach im Clip.

    Eine Frage an ein Gegenüber („Wie siehst du das?“, Gastgeberfrage) ist erst beantwortet, wenn ein
    anderer Sprecher danach etwas sagt, das keine Frage ist (auch ein einsilbiges „Ja.“). Eine rhetorische
    Frage ohne Anrede („Was heißt das für uns?“) ist durch die eigene Fortsetzung des Sprechers beantwortet."""
    key = "open_question_unanswered"
    for q in range(first, last + 1):
        s = sents[q]
        if not _is_question(s):
            continue
        rhetorical = not _addressed(words, s)
        answered = any(
            not _is_question(t) and (t.speaker != s.speaker or (rhetorical and not _is_backchannel(words, t)))
            for t in sents[q + 1 : last + 1]
        )
        if not answered:
            return _result(key, policy, False, f"Frage „{_sentence_text(s)}“ bleibt im Clip unbeantwortet", _ids(s), "back")
    return _result(key, policy, True, "keine offene Frage im Clip")


def _has_bezug(words: Sequence[Mapping[str, Any]], s: Sentence, other_text: str) -> bool:
    """Bezieht sich ``s`` auf den Clip? Anschluss am Satzanfang, Rückverweis in den ersten Wörtern oder
    lexikalische Überlappung wie im Story-Graph."""
    toks = _sent_tokens(words, s)
    head = toks[:BEZUG_WINDOW]
    if _find(head[:3], CONNECTOR_OPENERS + CONTRAST_OPENERS):
        return True
    for k, (_i, t) in enumerate(head):
        if t in ANAPHORS or _is_substituting(words, toks, k):
            return True
    return story_graph.lexical_overlap(other_text, s.text) >= story_graph.MIN_OVERLAP


def _negation_or_condition(toks: list[tuple[int, str]]) -> tuple[str, list[int]] | None:
    for i, t in toks:
        if t in NEGATION_TOKENS:
            return t, [i]
    return _find(toks, CONDITION_MARKERS)


def boundary_negation_condition(
    words: Sequence[Mapping[str, Any]], sents: Sequence[Sentence], first: int, last: int, policy: Any = None
) -> GateResult:
    """Negation („nicht“, „kein“, „nein“) oder Bedingung („wenn“, „nur wenn“, „falls“, „außer“, „sofern“,
    „es sei denn“) im Satz unmittelbar vor dem Anfang oder nach dem Ende, desselben Sprechers und mit Bezug
    auf den Clip. Abgleich an Wortgrenzen."""
    key = "boundary_negation_condition"
    clip_text = " ".join(s.text for s in sents[first : last + 1])
    if last + 1 < len(sents):
        nxt = sents[last + 1]
        hit = _negation_or_condition(_sent_tokens(words, nxt))
        if hit and nxt.speaker == sents[last].speaker and _has_bezug(words, nxt, clip_text):
            return _result(
                key, policy, False,
                f"Satz nach dem Ende schränkt den Clip ein („{hit[0]}“): „{_sentence_text(nxt)}“",
                _ids(nxt), "back",
            )  # fmt: skip
    if first > 0:
        prev = sents[first - 1]
        hit = _negation_or_condition(_sent_tokens(words, prev))
        opens = prev.text.rstrip().endswith((":", ","))
        if hit and prev.speaker == sents[first].speaker and (opens or _has_bezug(words, sents[first], prev.text)):
            return _result(
                key, policy, False,
                f"Satz vor dem Anfang schränkt den Clip ein („{hit[0]}“): „{_sentence_text(prev)}“",
                _ids(prev), "front",
            )  # fmt: skip
    return _result(key, policy, True, "keine Negation oder Bedingung am Grenzsatz")


def _frames(words: Sequence[Mapping[str, Any]], toks: list[tuple[int, str]], question: bool) -> list[int]:
    """Wortindizes von Zitatrahmen („sagt“, „meint“, „laut“, „angeblich“, „hat gesagt“, „heißt es“)."""
    if question:
        return []
    out = []
    hit = _find(toks, FRAME_PHRASES)
    if hit:
        out.append(hit[1][0])
    for k, (i, t) in enumerate(toks):
        prev = toks[k - 1][1] if k > 0 else ""
        before = {x for _j, x in toks[max(0, k - 4) : k]}
        perfect = t == "gesagt" and bool(before & PERFECT_AUX) and not before & FIRST_PERSON
        if (t in FRAME_TOKENS or perfect) and prev not in FRAME_NOT_AFTER:
            out.append(i)
        elif t == "laut" and k + 1 < len(toks):
            j, nxt = toks[k + 1]
            if nxt in LAUT_FOLLOWERS or _raw(words[j])[:1].isupper():
                out.append(i)
    return sorted(out)


def _subjunctive_i(toks: list[tuple[int, str]]) -> list[int]:
    out = []
    for k, (i, t) in enumerate(toks):
        prev = toks[k - 1][1] if k > 0 else ""
        nxt = toks[k + 1][1] if k + 1 < len(toks) else ""
        es_sei_denn = t == "sei" and prev == "es" and nxt == "denn"
        if (t in SUBJUNCTIVE_I and not es_sei_denn) or (t in SUBJUNCTIVE_I_NOT_AFTER_ICH and prev not in ("ich", "")):
            out.append(i)
    return out


def reported_speech(
    words: Sequence[Mapping[str, Any]],
    sents: Sequence[Sentence],
    first: int,
    last: int,
    policy: Any = None,
    context_before: int = CONTEXT_BEFORE,
    context_after: int = CONTEXT_AFTER,
) -> GateResult:
    """Fremde Position nicht als eigene (Master-Prompt 14 und 18).

    Verletzt, wenn der Zitatrahmen vor dem Anfang liegt und der Clip im Zitat beginnt (Rahmen endet mit
    Doppelpunkt oder der erste Satz steht im Konjunktiv I), oder wenn der Clip ein Zitat enthält und endet,
    bevor der Sprecher sich davon distanziert („Ich sehe das anders.“)."""
    key = "reported_speech"
    head = sents[first]
    first_toks = _sent_tokens(words, head)
    in_clip_frame = any(_frames(words, _sent_tokens(words, s), _is_question(s)) for s in sents[first : last + 1])
    if not in_clip_frame:
        subj = _subjunctive_i(first_toks)
        for prev in reversed(sents[max(0, first - context_before) : first]):
            if prev.speaker != head.speaker:
                break
            frame = _frames(words, _sent_tokens(words, prev), _is_question(prev))
            if frame and (prev.text.rstrip().endswith(":") or subj):
                return _result(
                    key, policy, False,
                    f"Clip beginnt im Zitat, der Rahmen „{_text(words, frame[:1])}“ steht davor",
                    frame + subj, "front",
                )  # fmt: skip
        return _result(key, policy, True, "keine fremde Position ohne Rahmen")
    clip_toks = _tokens(words, head.word_range[0], sents[last].word_range[1])
    if _find(clip_toks, DISTANCING):
        return _result(key, policy, True, "Zitat mit Rahmen und eigener Gegenposition im Clip")
    for n, s in enumerate(sents[last + 1 : last + 1 + context_after], start=1):
        if s.speaker != sents[last].speaker:
            break
        hit = _find(_sent_tokens(words, s), DISTANCING)
        if hit:
            return _result(
                key, policy, False,
                f"Clip endet mit der fremden Position, die Distanzierung „{_sentence_text(s)}“ fehlt",
                hit[1], "back" if n <= HEAL_REACH_SENTENCES else None,
            )  # fmt: skip
    return _result(key, policy, True, "Zitat mit Rahmen im Clip")


def forward_reference(
    words: Sequence[Mapping[str, Any]], sents: Sequence[Sentence], first: int, last: int, policy: Any = None
) -> GateResult:
    """Vorverweis ohne Auflösung im Clip: „später mehr“, „dazu komme ich später“ immer; „gleich erkläre ich“,
    „das zeige ich gleich“, „dazu komme ich“ nur, wenn danach im Clip kein Satz mehr folgt; Doppelpunkt am
    Clipende."""
    key = "forward_reference"
    for q in range(first, last + 1):
        toks = _sent_tokens(words, sents[q])
        deferred = _find(toks, FORWARD_DEFERRED)
        if deferred:
            return _result(key, policy, False, f"Vorverweis „{_text(words, deferred[1])}“ wird im Clip nicht aufgelöst", deferred[1])
        immediate = _find(toks, FORWARD_IMMEDIATE)
        if immediate and q == last:
            return _result(
                key, policy, False, f"Vorverweis „{_text(words, immediate[1])}“ am Ende ohne Auflösung im Clip",
                immediate[1], "back",
            )  # fmt: skip
    b = sents[last].word_range[1]
    if 0 <= b < len(words) and _raw(words[b]).endswith(":"):
        return _result(key, policy, False, f"Clip endet mit Doppelpunkt auf „{_raw(words[b])}“", [b], "back")
    return _result(key, policy, True, "kein Vorverweis ohne Auflösung")


def _elliptic_answer(words: Sequence[Mapping[str, Any]], s: Sentence) -> bool:
    toks = _sent_tokens(words, s)
    if not toks:
        return False
    return toks[0][1] in RESPONSE_PARTICLES or len(toks) <= ELLIPTIC_MAX_WORDS or bool(_find(toks, ANSWER_PHRASES))


def speaker_turn(
    words: Sequence[Mapping[str, Any]], sents: Sequence[Sentence], first: int, last: int, policy: Any = None
) -> GateResult:
    """Frage und Antwort richtig zugeordnet (Master-Prompt 27, Sprecherwechsel).

    Verletzt, wenn der Clip mit der Antwort von B beginnt und die Frage von A davor liegt (die Antwort ist
    ohne Frage nicht verständlich: „Nein, nie ernsthaft.“), oder wenn auf eine Frage von A, bevor B
    antwortet, eine weitere Frage von A folgt: die Antwort gehört dann laut Sprecherfolge zur zweiten.
    Geprüft werden Fragen an ein Gegenüber. Ein einsilbiges „Ja.“ direkt nach einer Frage ist die Antwort,
    kein Rückmeldesignal."""
    key = "speaker_turn"
    head = sents[first]
    if first > 0:
        prev = sents[first - 1]
        if _is_question(prev) and prev.speaker != head.speaker and _elliptic_answer(words, head):
            return _result(
                key, policy, False,
                f"Antwort „{_sentence_text(head)}“ ohne die Frage „{_sentence_text(prev)}“ im Clip",
                _ids(head), "front",
            )  # fmt: skip
    for q in range(first, last + 1):
        s = sents[q]
        if not _is_question(s) or not _addressed(words, s):
            continue
        for t in sents[q + 1 : last + 1]:
            if t.speaker != s.speaker:
                break  # das Gegenüber antwortet (auch ein einsilbiges „Ja.“)
            if _is_question(t):
                return _result(
                    key, policy, False,
                    f"Auf die Frage „{_sentence_text(s)}“ folgt eine zweite Frage, die Antwort gehört zu ihr",
                    _ids(s), None,
                )  # fmt: skip
    return _result(key, policy, True, "Frage und Antwort richtig zugeordnet")


def later_correction(
    words: Sequence[Mapping[str, Any]], sents: Sequence[Sentence], first: int, last: int, policy: Any = None
) -> GateResult:
    """Spätere Selbstkorrektur nach dem Clipende, die sich auf eine Aussage im Clip bezieht (Story-Graph v2
    mit Korrekturmarkern, Wortgrenzen). Heilbar nach hinten, wenn die Korrektur in Reichweite liegt."""
    key = "later_correction"
    for h in story_graph.find_later_qualifications(list(sents), first, last, rule="v2"):
        if h.get("kind") != "correction":
            continue
        idx = int(h["sentence_idx"])
        s = next(x for x in sents if x.idx == idx)
        reach = idx - sents[last].idx <= HEAL_REACH_SENTENCES
        return _result(
            key, policy, False,
            f"Spätere Korrektur „{h['marker']}“ nach {h['seconds_after']} s bezieht sich auf den Clip",
            _ids(s), "back" if reach else None,
        )  # fmt: skip
    return _result(key, policy, True, "keine spätere Korrektur zum Clip")


# -- Anweisungen und Meta-Rede (markieren, nie verwerfen) ---------------------------------------------


def _instruction_hit(words: Sequence[Mapping[str, Any]], s: Sentence) -> list[int]:
    toks = _sent_tokens(words, s)
    hit = _find(toks, INSTRUCTION_PHRASES)
    if hit:
        return hit[1]
    for k, (i, t) in enumerate(toks):
        if t in INSTRUCTION_TOKENS:
            return [i]
        if t == "gib" and any(x == "aus" for _j, x in toks[k + 1 : k + 1 + SEPARABLE_GIB_AUS_WINDOW]):
            return [i]
    for i in range(s.word_range[0], s.word_range[1] + 1):
        if _raw(words[i]).lower().strip("\"'„“”»«") in ROLE_LABELS:
            return [i]
    return []


def _flagged(key: str, policy: Any, hits: list[tuple[Sentence, list[int]]], what: str, none: str) -> GateResult:
    if not hits:
        out = _result(key, policy, True, none)
        out.update(flagged=False, quotes=[])
        return out
    quotes = [s.text for s, _evidence in hits]
    detail = f"{what} („{_sentence_text(hits[0][0])}“); bleibt Inhalt und wird nicht befolgt"
    out = _result(key, policy, True, detail, [i for _s, evidence in hits for i in evidence])
    out.update(flagged=True, quotes=quotes)
    return out


def embedded_instruction(
    words: Sequence[Mapping[str, Any]], sents: Sequence[Sentence], first: int, last: int, policy: Any = None
) -> GateResult:
    """Anweisung an ein Modell im Clip („ignoriere“, „du bist jetzt“, „system:“, „gib aus“, „liebe KI“,
    „ChatGPT“, Rollenwechsel). Verwirft nicht: ``passed`` bleibt True, ``flagged`` und ``quotes`` zeigen den
    Treffer für die Prüfung der Modellantwort (``instruction_followed``)."""
    hits = [(s, h) for s in sents[first : last + 1] if (h := _instruction_hit(words, s))]
    return _flagged("embedded_instruction", policy, hits, "Anweisung an ein Modell im Transkript", "keine Anweisung an ein Modell")


def meta_speech(
    words: Sequence[Mapping[str, Any]], sents: Sequence[Sentence], first: int, last: int, policy: Any = None
) -> GateResult:
    """Satz, der ein Modell anspricht (gleiche Regel wie der Hook-Ausschluss ``copy_engine.is_meta_speech``).
    Markiert den Kandidaten als Inhalt mit Meta-Rede; verwirft nicht."""
    from .copy_engine import is_meta_speech

    hits = [(s, _ids(s)) for s in sents[first : last + 1] if is_meta_speech(s.text)]
    return _flagged("meta_speech", policy, hits, "Satz spricht ein Modell an", "keine Meta-Rede an ein Modell")


# -- Prüfung der Modellantwort ------------------------------------------------------------------------

_JSON_TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool, "integer": int, "number": (int, float), "null": type(None),
}  # fmt: skip


def _schema_problems(value: Any, schema: Mapping[str, Any], path: str = "$") -> list[str]:
    """Kleine Teilmenge von JSON Schema: type, enum, required, properties, additionalProperties false,
    items, minimum, maximum, minItems, maxItems. Reicht für die Tool-Schemas der Prompts."""
    out: list[str] = []
    kind = schema.get("type")
    kinds = kind if isinstance(kind, list) else [kind] if kind else []
    if kinds:
        ok = any(
            isinstance(value, _JSON_TYPES[k]) and not (k in ("integer", "number") and isinstance(value, bool))
            for k in kinds if k in _JSON_TYPES
        )  # fmt: skip
        if not ok:
            return [f"{path} hat nicht den Typ {kind}"]
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{path} ist kein erlaubter Wert")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            out.append(f"{path} liegt unter {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            out.append(f"{path} liegt über {schema['maximum']}")
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        out += [f"{path}.{k} fehlt" for k in schema.get("required") or [] if k not in value]
        if schema.get("additionalProperties") is False:
            out += [f"{path}.{k} ist nicht vorgesehen" for k in value if k not in props]
        for k, v in value.items():
            if k in props:
                out += _schema_problems(v, props[k], f"{path}.{k}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            out.append(f"{path} hat zu wenige Einträge")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            out.append(f"{path} hat zu viele Einträge")
        if isinstance(schema.get("items"), Mapping):
            for n, v in enumerate(value):
                out += _schema_problems(v, schema["items"], f"{path}[{n}]")
    return out


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _strings(v)]
    return []


def _seq(text: str) -> list[str]:
    return [t for t in (_core(x) for x in text.split()) if t]


def instruction_followed(
    answer_json: Any,
    transcript_instructions: Sequence[str],
    schema: Mapping[str, Any] | None = None,
    clip_text: str = "",
) -> GateResult:
    """Deterministische Prüfung einer Modellantwort gegen Anweisungen aus dem Transkript.

    Gefolgt gilt, wenn die Antwort vom Schema abweicht (mit ``schema``) oder ein Text der Antwort die
    Anweisung zitiert: drei aufeinanderfolgende Wörter der Anweisung, die nicht nur Füllwörter sind, oder ein
    seltenes Wort der Anweisung (ab zehn Zeichen), das im übrigen Clip-Text nicht vorkommt („Gratisgutschein“
    als Titel). ``passed`` False heißt: Kandidat verwerfen, Grund ``instruction_followed``."""
    problems = _schema_problems(answer_json, schema) if schema else []
    if problems:
        return {
            "passed": False, "detail": f"Antwort weicht vom Schema ab: {problems[0]}", "evidence_word_ids": [],
            "healable": None, "origin": DEFAULT_ORIGIN, "reason": "instruction_followed", "evidence": problems,
        }  # fmt: skip
    clip_tokens = set(_seq(clip_text))
    answer_seqs = [_seq(s) for s in _strings(answer_json)]
    answer_tokens = {t for seq in answer_seqs for t in seq}
    joined = [" " + " ".join(seq) + " " for seq in answer_seqs]
    evidence: list[str] = []
    for instruction in transcript_instructions:
        seq = _seq(str(instruction))
        for k in range(len(seq) - QUOTE_NGRAM + 1):
            gram = seq[k : k + QUOTE_NGRAM]
            if all(t in STOPWORDS for t in gram):
                continue
            needle = " " + " ".join(gram) + " "
            if any(needle in j for j in joined):
                evidence.append(" ".join(gram))
        for t in seq:
            if len(t) >= RARE_TOKEN_MIN and t not in clip_tokens and t in answer_tokens:
                evidence.append(t)
    if evidence:
        return {
            "passed": False,
            "detail": f"Antwort folgt der Anweisung im Transkript („{evidence[0]}“)",
            "evidence_word_ids": [], "healable": None, "origin": DEFAULT_ORIGIN,
            "reason": "instruction_followed", "evidence": sorted(set(evidence)),
        }  # fmt: skip
    return {
        "passed": True, "detail": "Antwort folgt keiner Anweisung aus dem Transkript", "evidence_word_ids": [],
        "healable": None, "origin": DEFAULT_ORIGIN, "reason": None, "evidence": [],
    }  # fmt: skip


# -- Sammelfunktion -----------------------------------------------------------------------------------


def _settings(policy: Any) -> dict[str, Any]:
    cfg = editorial.gates_settings(policy) if policy is not None and hasattr(policy, "roh") else None
    if cfg is None:
        return {"enabled": dict.fromkeys(GATE_KEYS, True), "discard_hard": False}
    return cfg


def run_gates(
    words: Sequence[Mapping[str, Any]],
    sents: Sequence[Sentence],
    first: int,
    last: int,
    policy: Any = None,
    context_before: int = CONTEXT_BEFORE,
    context_after: int = CONTEXT_AFTER,
) -> dict[str, Any]:
    """Alle eingeschalteten Gates über den Kandidaten ``first`` bis ``last`` (Satzindizes in ``sents``).

    Zurück kommt ``results`` (GateResult je Schlüssel, für ``rubric.quality_gate_results``), ``failed``,
    ``flagged``, ``healable`` (Seiten, auf denen eine Erweiterung helfen könnte), ``discard_hard`` und eine
    Entscheidung ``decision`` („rejected“ oder „accepted“) mit ``decision_reason`` (``gate:<schluessel>``)
    und ``decision_detail``. Ohne Abschnitt ``gates`` (Fassung 1 oder keine Policy) laufen alle Gates und
    werden nur berichtet."""
    cfg = _settings(policy)
    results: dict[str, GateResult] = {}
    for key in GATE_KEYS:
        if not cfg["enabled"].get(key, False):
            continue
        if key == "reported_speech":
            results[key] = reported_speech(words, sents, first, last, policy, context_before, context_after)
        else:
            results[key] = GATE_FUNCTIONS[key](words, sents, first, last, policy)
    failed = [k for k, r in results.items() if not r["passed"]]
    flagged = [k for k, r in results.items() if r.get("flagged")]
    healable = sorted({str(results[k]["healable"]) for k in failed if results[k]["healable"]})
    discard = bool(cfg["discard_hard"])
    if failed and discard:
        decision, reason = "rejected", f"gate:{failed[0]}"
        detail = results[failed[0]]["detail"]
    elif failed:
        decision, reason = "accepted", f"gate:{failed[0]} nur berichtet"
        detail = results[failed[0]]["detail"]
    else:
        decision, reason, detail = "accepted", "alle Gates bestanden", ""
    return {
        "results": results,
        "failed": failed,
        "flagged": flagged,
        "healable": healable,
        "discard_hard": discard,
        "decision": decision,
        "decision_reason": reason,
        "decision_detail": detail,
    }


GATE_FUNCTIONS = {
    "unresolved_pronoun": unresolved_pronoun,
    "back_reference": back_reference,
    "open_question_unanswered": open_question_unanswered,
    "boundary_negation_condition": boundary_negation_condition,
    "reported_speech": reported_speech,
    "forward_reference": forward_reference,
    "speaker_turn": speaker_turn,
    "later_correction": later_correction,
    "embedded_instruction": embedded_instruction,
    "meta_speech": meta_speech,
}


__all__ = [
    "FLAG_ONLY",
    "GATE_FUNCTIONS",
    "GATE_KEYS",
    "LEGACY_GATE",
    "back_reference",
    "boundary_negation_condition",
    "embedded_instruction",
    "forward_reference",
    "from_sentence_texts",
    "instruction_followed",
    "later_correction",
    "meta_speech",
    "open_question_unanswered",
    "reported_speech",
    "run_gates",
    "speaker_turn",
    "unresolved_pronoun",
]
