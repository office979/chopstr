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
Verworfen wird nur, wenn zusätzlich ``implementation.gates.discard_hard`` an ist; sonst ist die
Entscheidung ``reported`` (nur berichtet). Heilreichweiten kommen aus ``laenge`` der Policy
(``context_front_sentences`` und ``context_front_s`` vorn, ``kontext_zugabe_saetze`` und ``kontext_zugabe_s``
hinten).

Die Wortlisten hier sind Übertragungshypothesen ohne Messung (Herkunft H, ``origins.gates.<k>.wordlist``,
RK 2 Befund 6 und 11). Abgleich
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
# Heilreichweite ohne Policy (gleiche Startwerte wie laenge.context_front_* und laenge.kontext_zugabe_*).
DEFAULT_REACH = {"front": (2, 7.0), "back": (2, 7.0)}
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
# Nach „Sie“ + Modalverb am Satzanfang: typische Anrede („Sie müssen wissen“, „Sie müssen sich vorstellen“).
FORMAL_MODALS = frozenset({"müssen", "können", "sollten", "dürfen", "werden", "würden", "möchten", "wollen"})
FORMAL_CUES = frozenset({"wissen", "sich", "verstehen", "bedenken", "beachten", "mir", "uns", "ruhig", "gerne", "gern", "mal"})
# Satzanfänge, die kein Name sind (für „Name an Position 0 ist ein Nomen“).
NOT_A_NAME = frozenset({
    "gestern", "heute", "morgen", "damals", "dann", "jetzt", "danach", "später", "früher", "deshalb", "also",
    "trotzdem", "plötzlich", "leider", "zum", "am", "im", "ehrlich", "natürlich", "eigentlich", "irgendwann",
    "schließlich", "zuerst", "zunächst", "anfangs", "immer", "nie", "oft", "manchmal", "hier", "dort", "da",
    "so", "und", "aber", "oder", "doch", "ja", "nein", "wir", "ich", "du", "man", "es", "auch", "nur", "noch",
    "schon", "ganz", "wie", "was", "wer", "warum", "wo", "wann", "bei", "mit", "nach", "von", "vor", "in",
})  # fmt: skip
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
# Feste Wendungen am Satzanfang, die nach vorn weisen oder für sich stehen („Das heißt …“, „Das Problem ist
# …“): kein Rückverweis (Begrenzung nach dem Modulbericht AP4, 26 von 45 Demo-Fenstern; Herkunft H).
FIXED_OPENERS = (
    "das wichtigste ist", "das problem ist", "das ergebnis", "deshalb", "darum geht es",
)  # fmt: skip
# „Das heißt“ und „Das bedeutet“ verweisen immer zurück, auch vor einem Doppelpunkt.
BACKWARD_OPENERS = ("das heißt", "das bedeutet")
# Pronominaladverbien am Satzanfang mit finitem Verb verweisen zurück („Davon kann ich nur abraten.“).
DA_STARTS = frozenset({"davon", "darüber", "daran", "dagegen"})
# „Das war …“ ist nur dann kein Rückverweis, wenn der Satz selbst den Bezug nachliefert: Nebensatz oder
# Doppelpunkt nach dem Komma („Das war der Tag, an dem …“, „Das war, als wir …“).
DAS_WAR_ANCHORS = (
    "als", "dass", "wo", "wie", "weil", "bevor", "nachdem", "in dem", "an dem", "bei dem", "mit dem", "in der",
    "an der", "bei der", "mit der",
)  # fmt: skip
ADJECTIVE_ENDINGS = ("e", "en", "er", "es", "em")

NEGATION_TOKENS = frozenset({
    "nicht", "nein", "kein", "keine", "keinen", "keinem", "keiner", "keines", "keins", "nie", "nichts",
    "niemand", "kaum", "ned", "nöd", "nid", "nit", "net",
})  # fmt: skip
# Verstärkende Negation schränkt nichts ein („keinen einzigen Kunden gekostet“, „noch nicht verstanden“);
# „Nein, Quatsch.“ ist eine Selbstkorrektur, kein einschränkender Grenzsatz.
EMPHATIC_NEGATIONS = (
    "kein einziger", "keine einzige", "keinen einzigen", "keinem einzigen", "kein einziges", "noch nicht",
    "noch nie", "übertreibe nicht", "übertreib nicht", "nicht übertrieben",
    "nein quatsch", "nein falsch",  # Korrekturpartikel, die prüft later_correction
)  # fmt: skip
# Gegenwörter, mit denen eine Folgenegation eine verneinte Aussage doch einschränkt („Nie. Außer …“).
POLARITY_TURNS = ("aber", "doch", "schon", "sondern", "allerdings", "außer", "ausser")
# Bekräftigung einer verneinten Aussage besteht nur aus Negation und Verstärker („Nie.“, „Überhaupt nichts.“).
REINFORCERS = frozenset({"gar", "überhaupt", "absolut", "wirklich", "echt", "einfach", "null", "eben", "so"})
CONDITION_MARKERS = ("nur wenn", "es sei denn", "wenn", "wenns", "falls", "außer", "ausser", "sofern")
CONTRAST_OPENERS = (
    "aber", "allerdings", "jedoch", "wobei", "trotzdem", "außer", "ausser", "nur", "es sei denn", "sofern",
)  # fmt: skip
# Ein Clip, der mit einem Gegenwort beginnt, wendet sich von der Negation davor ab; sie schränkt ihn nicht ein.
TURN_AWAY = frozenset({"aber", "allerdings", "jedoch", "trotzdem", "doch"})
ELLIPTIC_FOLLOW_WORDS = 5  # kurzer Folgesatz ohne eigenes Thema bezieht sich auf den Clip
CONNECTOR_OPENERS = ("und", "aber", "also", "dann", "deshalb", "deswegen", "sondern", "doch", "trotzdem", "darum")
ANAPHORS = frozenset({
    "dies", "so", "dann", "dabei", "damit", "davon", "dafür", "dazu", "darauf", "darum", "deshalb",
    "deswegen", "trotzdem",
})  # fmt: skip
BEZUG_WINDOW = 6

FRAME_PHRASES = ("die sagen dann", "heißt es", "hieß es")
FRAME_TOKENS = frozenset({
    "sagt", "sagte", "sagten", "sagen", "meint", "meinte", "meinten", "behauptet", "behauptete", "behaupten",
    "angeblich", "erzählen", "erzählt", "erzählte", "erzählten", "schreiben", "schreibt", "schrieb",
    "predigen", "predigt", "predigte",
})  # fmt: skip
FRAME_NOT_AFTER = frozenset({"ehrlich", "genauer", "wie", "anders", "kurz", "offen", "ganz", "gesagt"})
PERFECT_AUX = frozenset({"hat", "hatte", "haben", "hatten"})
FIRST_PERSON = frozenset({"ich", "wir"})
FRAME_WINDOW = 3  # Wörter vor dem Rahmenverb, in denen „ich“, „wir“ oder „wie man“ gesucht wird
LAUT_FOLLOWERS = frozenset({
    "dem", "der", "den", "des", "einer", "einem", "eines", "meinem", "meiner", "unserem", "unserer",
    "seinem", "seiner", "ihrem", "ihrer", "deren", "dessen",
})  # fmt: skip
SUBJUNCTIVE_I = frozenset({"sei", "seien", "seiest", "könne", "müsse", "solle", "wolle", "dürfe", "möge", "wisse"})
SUBJUNCTIVE_I_NOT_AFTER_ICH = frozenset({"habe", "werde", "gebe", "komme", "gehe", "mache", "brauche", "stehe", "liege", "bringe"})
DISTANCING = ("quatsch", "unsinn", "blödsinn", "widerspreche", "anderer meinung", "falsch")
# Distanzierung über ein Wortfenster („sehe … anders“, „stimmt … nicht“).
DISTANCING_PAIRS = (
    ("sehe", "anders"), ("seh", "anders"), ("sieht", "anders"), ("stimmt", "nicht"), ("stimmt", "nöd"),
    ("glaube", "nicht"), ("glaub", "nicht"), ("finde", "nicht"),
)  # fmt: skip
DISTANCING_WINDOW = 4

FORWARD_IMMEDIATE = (
    "gleich erkläre ich", "erkläre ich gleich", "das zeige ich gleich", "zeige ich gleich",
    "gleich zeige ich", "dazu komme ich",
)  # fmt: skip
FORWARD_DEFERRED = ("später mehr dazu", "dazu komme ich später", "dazu komme ich noch", "darauf komme ich noch")
# „später mehr“ nur am Satzende („Später mehr.“), nicht in „später mehr verdienen“.
FORWARD_DEFERRED_AT_END = ("später mehr",)

RESPONSE_PARTICLES = frozenset({
    "ja", "nein", "jein", "doch", "genau", "klar", "nie", "absolut", "sicher", "natürlich", "definitiv",
    "dann", "okay", "ok", "stimmt", "richtig", "eher",
})  # fmt: skip
ANSWER_PHRASES = ("meine antwort", "die antwort ist", "kurze antwort", "kurz gesagt ja", "kurz gesagt nein")
ELLIPTIC_MAX_WORDS = 3
# Fortsetzung, die eine Frage erläutert statt sie zu beantworten („Ich frage, weil …“).
QUESTION_ELABORATION = ("ich frage", "ich frag", "frage ich", "meine frage", "ich will wissen", "mich interessiert")
HOST_FOLLOWUP_OPENERS = frozenset({"und", "aber"})
HOST_FOLLOWUP_MAX_WORDS = 5

INSTRUCTION_PHRASES = (
    "du bist jetzt", "du bist ab jetzt", "ab jetzt bist du", "liebe ki", "lieber ki", "hallo ki", "hey ki",
    "chatgpt", "vergiss alle", "vergiss alles", "vergiss deine", "neue anweisung", "neue anweisungen",
    "deine anweisungen", "spiel die rolle", "spiele die rolle", "tu so als", "verhalte dich wie",
    "ignorieren sie", "ignoriert alle",
)  # fmt: skip
# Imperativ von „ignorieren“; „wir haben das ignoriert“ ist keine Anweisung. Alle Hinweise zählen nur in
# einem Satz, der ein Modell anspricht oder steuert (``copy_engine.is_meta_speech``), oder direkt nach so
# einem Satz desselben Sprechers: „Ignorier die Kritiker“ ist Coaching, keine Anweisung.
INSTRUCTION_TOKENS = frozenset({"ignoriere", "ignorier", "ignoriert", "vergiss", "missachte", "befolge"})
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
# Forderung nach der Höchstwertung in der Anweisung; mit Schema-Maximum wird geprüft, ob alle Zahlen darauf stehen.
MAX_SCORE_DEMANDS = ("volle punktzahl", "höchste punktzahl", "höchstpunktzahl", "maximale punktzahl", "bestnote")


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


def _reach(policy: Any, side: str) -> tuple[int, float]:
    """Heilreichweite (Sätze, Sekunden) aus ``laenge`` der Policy: vorn ``context_front_*``, hinten
    ``kontext_zugabe_*``; ohne Policy die Startwerte aus ``DEFAULT_REACH``."""
    laenge = ((getattr(policy, "roh", None) or {}).get("laenge")) or {}
    keys = ("context_front_sentences", "context_front_s") if side == "front" else ("kontext_zugabe_saetze", "kontext_zugabe_s")
    n, sec = DEFAULT_REACH[side]
    try:
        return int(laenge.get(keys[0], n)), float(laenge.get(keys[1], sec))
    except (TypeError, ValueError):
        return n, sec


def _back_heal(sents: Sequence[Sentence], last: int, target: int, policy: Any) -> str | None:
    """``back``, wenn der Clip bis Satz ``target`` wachsen darf (Sätze und Sekunden der Policy), sonst None."""
    n, sec = _reach(policy, "back")
    if target <= last:
        return "back"
    ok = target - last <= n and sents[target].end - sents[last].end <= sec + 1e-9
    return "back" if ok else None


# -- Pronomen und Rückverweise ---------------------------------------------------------------------


def _pronouns(policy: Any) -> frozenset[str]:
    einstieg = getattr(policy, "einstieg", None) or {}
    return frozenset(str(p).lower() for p in (einstieg.get("pronomen") or DEFAULT_PRONOUNS))


def _upper(words: Sequence[Mapping[str, Any]], i: int) -> bool:
    return _raw(words[i])[:1].isupper()


def _is_formal_sie(words: Sequence[Mapping[str, Any]], toks: list[tuple[int, str]], k: int) -> bool:
    """Höflichkeitsform: großgeschrieben mitten im Satz; am Satzanfang „Sie“ mit Höflichkeitsverb und Anrede
    (Frage, Ausruf, weitere Höflichkeitsform, „Sie müssen wissen“, „Sie müssen sich vorstellen“) oder „Ihr“ vor
    einem Nomen („Ihr Unternehmen braucht …“)."""
    i, core = toks[k]
    if core not in FORMAL_FORMS or not _upper(words, i):
        return False
    if k > 0:
        return True
    nxt = toks[1][1] if len(toks) > 1 else ""
    if core != "sie":
        return core != "ihr" or (len(toks) > 1 and _upper(words, toks[1][0]))
    if nxt not in POLITE_VERBS:
        return False
    if nxt in FORMAL_MODALS and len(toks) > 2 and toks[2][1] in FORMAL_CUES:
        return True
    last_raw = _raw(words[toks[-1][0]])
    other_formal = any(t in FORMAL_FORMS and _upper(words, j) for j, t in toks[1:])
    return last_raw.endswith(("?", "!")) or other_formal


def _is_plural_address(toks: list[tuple[int, str]], k: int) -> bool:
    """„ihr“ als Anrede an mehrere („ihr habt“, „habt ihr“, „wenn ihr eure …“), kein Pronomen der 3. Person."""
    if toks[k][1] != "ihr":
        return False
    nxt = toks[k + 1][1] if k + 1 < len(toks) else ""
    prev = toks[k - 1][1] if k > 0 else ""
    return nxt in SECOND_PLURAL_VERBS or prev in SECOND_PLURAL_VERBS or any(t in SECOND_PLURAL for _j, t in toks)


def _is_name_start(words: Sequence[Mapping[str, Any]], toks: list[tuple[int, str]]) -> bool:
    """Name oder Nomen an Position 0 („Thomas hat …“, „Frau Brenner …“): großgeschrieben, kein Funktionswort,
    gefolgt von einem finiten Verb oder einem weiteren großgeschriebenen Wort."""
    if len(toks) < 2:
        return False
    core = toks[0][1]
    if core in NOT_A_NAME or core in DEMONSTRATIVE_STARTS or core in FORMAL_FORMS or core in DEFAULT_PRONOUNS:
        return False
    nxt = toks[1][1]
    return nxt in dach_nlp.AUXILIARY_FORMS or nxt in VERBS_AFTER_DEMONSTRATIVE or _upper(words, toks[1][0])


def _is_noun(words: Sequence[Mapping[str, Any]], toks: list[tuple[int, str]], k: int) -> bool:
    i, core = toks[k]
    if k == 0:
        return _is_name_start(words, toks)
    return _upper(words, i) and core not in FORMAL_FORMS


def unresolved_pronoun(
    words: Sequence[Mapping[str, Any]], sents: Sequence[Sentence], first: int, last: int, policy: Any = None
) -> GateResult:
    """Pronomen aus ``einstieg.pronomen`` im ersten Satz vor jedem Nomen, also ohne Antezedens im Clip.

    „Es“ steht nicht in der Liste (meist Platzhalter). Die Höflichkeitsform („Sie müssen wissen“, „Ihr
    Unternehmen“) und „ihr“ als Anrede an mehrere sind keine Treffer; ein Name am Satzanfang ist Bezug.
    Heilbar nach vorn: der Bezug steht meist im Satz davor."""
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
    if _upper(words, j) or nxt in ("was", "wo") or nxt in DETERMINERS:
        return False  # „war das der teuerste Fehler“: das Nomen folgt im Satz
    noun_after_adjective = k + 2 < len(toks) and _upper(words, toks[k + 2][0])
    return not (nxt.endswith(ADJECTIVE_ENDINGS) and noun_after_adjective)


def _colon_after(words: Sequence[Mapping[str, Any]], toks: list[tuple[int, str]], k: int) -> bool:
    """Steht nach Position ``k`` im Satz ein Doppelpunkt? Dann weist das Demonstrativ nach vorn (Katapher)."""
    return any(_raw(words[i]).endswith(":") for i, _t in toks[k:])


def _demonstrative_start(words: Sequence[Mapping[str, Any]], toks: list[tuple[int, str]]) -> int | None:
    """Wortindex eines Demonstrativpronomens am (Teil-)Satzanfang (spaCy: PDS oder PDAT wie ``clip_eval``),
    eines Pronominaladverbs mit finitem Verb („Davon kann …“) oder von „Das heißt“, „Das bedeutet“."""
    if not toks:
        return None
    if _find(toks[:2], BACKWARD_OPENERS):
        return toks[0][0]
    if toks[0][1] in DA_STARTS and len(toks) > 1 and toks[1][1] in VERBS_AFTER_DEMONSTRATIVE:
        return toks[0][0]
    if toks[0][1] not in DEMONSTRATIVE_STARTS or _colon_after(words, toks, 1) or _fixed_opener(toks):
        return None
    pipe = dach_nlp.nlp()
    if pipe is not None:
        doc = pipe(" ".join(_raw(words[i]) for i, _t in toks[:QUOTE_WORDS]))
        return toks[0][0] if len(doc) and doc[0].tag_ in BACKREF_POS_TAGS else None
    if len(toks) > 1 and toks[1][1] in VERBS_AFTER_DEMONSTRATIVE:
        return toks[0][0]
    return None


def _fixed_opener(toks: list[tuple[int, str]]) -> int:
    """Anzahl Tokens einer festen Wendung am Satzanfang (``FIXED_OPENERS``, „Das war …“ mit Bezug im Satz), sonst 0."""
    seq = [t for _i, t in toks]
    for p in FIXED_OPENERS:
        pt = _phrase(p)
        if tuple(seq[: len(pt)]) == pt:
            return len(pt)
    if tuple(seq[:2]) == ("das", "war") and _find(toks[2:], DAS_WAR_ANCHORS):
        return 2
    return 0


def _clause_before(words: Sequence[Mapping[str, Any]], toks: list[tuple[int, str]], k: int) -> bool:
    """Ein Partizip vor „das“ im Satz liefert den Bezug („Ich habe gekündigt, und das war …“); „ehrlich gesagt“
    und ähnliche Wendungen zählen nicht."""
    for n, (i, _t) in enumerate(toks[:k]):
        prev = toks[n - 1][1] if n > 0 else ""
        if dach_nlp.is_participle(_raw(words[i])) and prev not in FRAME_NOT_AFTER:
            return True
    return False


def _subclause_starts(words: Sequence[Mapping[str, Any]], toks: list[tuple[int, str]]) -> list[int]:
    """Satzanfang und jedes großgeschriebene Wort nach einem Doppelpunkt („Ganz ehrlich: Das hat …“)."""
    return [0] + [k + 1 for k in range(len(toks) - 1) if _raw(words[toks[k][0]]).endswith(":") and _upper(words, toks[k + 1][0])]


def back_reference(
    words: Sequence[Mapping[str, Any]], sents: Sequence[Sentence], first: int, last: int, policy: Any = None
) -> GateResult:
    """Rückverweis auf etwas vor dem Clip, nur im ersten Satz: „wie gesagt“, „das von vorhin“, „wie erwähnt“,
    „wie vorhin“, ein Demonstrativ am Satzanfang oder nach einem Doppelpunkt („Ganz ehrlich: Das hat …“),
    „Das heißt“, „Davon kann ich nur abraten“, oder ein „das“ als Pronomen vor jedem Nomen („Ich sehe das
    anders.“). Kein Treffer: Doppelpunkt nach dem Demonstrativ (Katapher, „Das ist so: …“), Partizip vor
    „das“ („Ich habe gekündigt, und das war …“), feste Wendungen (``FIXED_OPENERS``), „…das?“ als Frage, auf
    die derselbe Sprecher selbst weiterredet („Kennt ihr das? Man arbeitet …“). Heilbar nach vorn."""
    key = "back_reference"
    head = sents[first]
    toks = _sent_tokens(words, head)
    hit = _find(toks, BACK_PHRASES)
    if hit:
        return _result(key, policy, False, f"Rückverweis „{_text(words, hit[1])}“ auf etwas vor dem Clip", hit[1], "front")
    for k0 in _subclause_starts(words, toks):
        i = _demonstrative_start(words, toks[k0:])
        if i is not None:
            return _result(key, policy, False, f"Demonstrativ „{_raw(words[i])}“ am Anfang ohne Bezug im Clip", [i], "front")
    skip = _fixed_opener(toks)
    nxt = sents[first + 1] if first + 1 < len(sents) else None
    own_followup = _is_question(head) and nxt is not None and nxt.speaker == head.speaker and not _is_question(nxt)
    for k, (i, _core_t) in enumerate(toks):
        if k < skip:
            continue
        if _is_noun(words, toks, k):
            break
        if not _is_substituting(words, toks, k) or _colon_after(words, toks, k) or _clause_before(words, toks, k):
            continue
        if own_followup and k == len(toks) - 1:
            continue  # „Kennt ihr das?“: das Folgende erklärt, worauf „das“ zeigt
        return _result(key, policy, False, f"„{_raw(words[i])}“ im ersten Satz verweist auf etwas vor dem Clip", [i], "front")
    return _result(key, policy, True, "kein Rückverweis auf etwas vor dem Clip")


# -- Fragen, Grenzsätze, indirekte Rede, Vorverweise -----------------------------------------------------


def _addressed(words: Sequence[Mapping[str, Any]], s: Sentence) -> bool:
    """Enthält die Frage eine Anrede („du“, „ihr“, „euch“, Höflichkeitsform „Sie“)? Nur Zusatzsignal."""
    toks = _sent_tokens(words, s)
    return any(
        t in SECOND_PERSON or _is_plural_address(toks, k) or _is_formal_sie(words, toks, k)
        for k, (_i, t) in enumerate(toks)
    )


def _host_followup(words: Sequence[Mapping[str, Any]], s: Sentence) -> bool:
    """Elliptische Nachfrage ohne Verb („Und der größte Fehler?“): typisch für die Frage an das Gegenüber."""
    toks = _sent_tokens(words, s)
    if not toks or toks[0][1] not in HOST_FOLLOWUP_OPENERS or len(toks) > HOST_FOLLOWUP_MAX_WORDS:
        return False
    return not any(t in dach_nlp.AUXILIARY_FORMS or (not _upper(words, i) and t.endswith(("t", "st", "en", "te")) and k > 0)
                   for k, (i, t) in enumerate(toks))  # fmt: skip


def _to_counterpart(words: Sequence[Mapping[str, Any]], sents: Sequence[Sentence], q: int) -> bool:
    """Richtet sich die Frage an das Gegenüber? Entscheidend ist die Sprecherfolge: redet als Nächstes ein
    anderer, ja; redet derselbe Sprecher weiter, ist sie rhetorisch, außer er erläutert nur seine Frage
    („Ich frage, weil …“) oder es ist eine elliptische Nachfrage („Und der größte Fehler?“). Ohne Folgesatz
    entscheidet die Anrede."""
    s = sents[q]
    if _host_followup(words, s):
        return True
    nxt = sents[q + 1] if q + 1 < len(sents) else None
    if nxt is None:
        return _addressed(words, s)
    if nxt.speaker != s.speaker:
        return True
    return bool(_find(_sent_tokens(words, nxt), QUESTION_ELABORATION))


def open_question_unanswered(
    words: Sequence[Mapping[str, Any]], sents: Sequence[Sentence], first: int, last: int, policy: Any = None
) -> GateResult:
    """Frage im Clip ohne Antwortsatz danach im Clip.

    Eine Frage an das Gegenüber (laut Sprecherfolge, siehe ``_to_counterpart``) ist erst beantwortet, wenn ein
    anderer Sprecher danach im Clip etwas sagt, das keine Frage ist (auch ein einsilbiges „Ja.“). Eine
    rhetorische Frage („Weißt du, was das größte Problem ist?“ und der Sprecher redet weiter) ist durch die
    eigene Fortsetzung beantwortet, wenn die im Clip liegt. Heilbar nach hinten, wenn die Antwort in Reichweite
    liegt."""
    key = "open_question_unanswered"
    for q in range(first, last + 1):
        s = sents[q]
        if not _is_question(s):
            continue
        counterpart = _to_counterpart(words, sents, q)
        later = sents[q + 1 : last + 1]
        if counterpart:
            answered = any(not _is_question(t) and t.speaker != s.speaker for t in later)
        else:
            answered = any(not _is_question(t) and not _is_backchannel(words, t) for t in later)
        if not answered:
            target = next(
                (t.idx for t in sents[last + 1 :] if not _is_question(t) and (not counterpart or t.speaker != s.speaker)),
                None,
            )
            heal = _back_heal(sents, last, target, policy) if target is not None else None
            return _result(key, policy, False, f"Frage „{_sentence_text(s)}“ bleibt im Clip unbeantwortet", _ids(s), heal)
    return _result(key, policy, True, "keine offene Frage im Clip")


def _elliptic_follow(words: Sequence[Mapping[str, Any]], s: Sentence) -> bool:
    """Kurzer Folgesatz (bis fünf Wörter) oder ohne finites Verb: er bezieht sich auf den Satz davor."""
    toks = _sent_tokens(words, s)
    if len(toks) <= ELLIPTIC_FOLLOW_WORDS:
        return True
    return not any(t in dach_nlp.AUXILIARY_FORMS or (not _upper(words, i) and t.endswith(("t", "st", "en"))) for i, t in toks)


def _has_bezug(words: Sequence[Mapping[str, Any]], s: Sentence, other_text: str) -> bool:
    """Bezieht sich ``s`` auf den Clip? Kurzer elliptischer Satz, Anschluss am Satzanfang, Rückverweis in den
    ersten Wörtern oder lexikalische Überlappung wie im Story-Graph."""
    toks = _sent_tokens(words, s)
    if _elliptic_follow(words, s):
        return True
    head = toks[:BEZUG_WINDOW]
    if _find(head[:3], CONNECTOR_OPENERS + CONTRAST_OPENERS):
        return True
    for k, (_i, t) in enumerate(head):
        if t in ANAPHORS or _is_substituting(words, toks, k):
            return True
    return story_graph.lexical_overlap(other_text, s.text) >= story_graph.MIN_OVERLAP


def _negation_or_condition(words: Sequence[Mapping[str, Any]], toks: list[tuple[int, str]]) -> tuple[str, list[int]] | None:
    """Erste einschränkende Negation oder Bedingung. Verstärkende Negation („keinen einzigen“, „noch nicht“)
    zählt nicht; „Na,“ am Anfang eines kurzen Satzes ist österreichisch „nein“."""
    emphatic: set[int] = set()
    seq = [t for _i, t in toks]
    for p in EMPHATIC_NEGATIONS:
        pt = _phrase(p)
        for k in range(len(seq) - len(pt) + 1):
            if tuple(seq[k : k + len(pt)]) == pt:
                emphatic.update(toks[k + j][0] for j in range(len(pt)))
    for i, t in toks:
        if t in NEGATION_TOKENS and i not in emphatic:
            return t, [i]
    if toks and toks[0][1] == "na" and _raw(words[toks[0][0]]).endswith(",") and len(toks) <= ELLIPTIC_FOLLOW_WORDS:
        return "na", [toks[0][0]]
    return _find(toks, CONDITION_MARKERS)


def _restricts(words: Sequence[Mapping[str, Any]], clip_last: Sentence, nxt: Sentence) -> tuple[str, list[int]] | None:
    """Schränkt ``nxt`` den Satz davor ein? Eine Negation, die eine verneinte Aussage nur bekräftigt
    („Bringt gar nichts. Nie.“, nur Negation und Verstärker), schränkt nicht ein."""
    toks = _sent_tokens(words, nxt)
    hit = _negation_or_condition(words, toks)
    if hit is None or hit[0] not in NEGATION_TOKENS:
        return hit
    clip_negated = _negation_or_condition(words, _sent_tokens(words, clip_last))
    only_reinforcing = all(t in NEGATION_TOKENS or t in REINFORCERS for _i, t in toks)
    if clip_negated and clip_negated[0] in NEGATION_TOKENS and only_reinforcing:
        return None
    return hit


def boundary_negation_condition(
    words: Sequence[Mapping[str, Any]], sents: Sequence[Sentence], first: int, last: int, policy: Any = None
) -> GateResult:
    """Negation („nicht“, „kein“, „nein“, „nie“, „nichts“, „niemand“, „kaum“) oder Bedingung („wenn“, „nur
    wenn“, „wenn's“, „falls“, „außer“, „ausser“, „sofern“, „es sei denn“) im Satz unmittelbar vor dem Anfang
    oder nach dem Ende, desselben Sprechers und mit Bezug auf den Clip. Abgleich an Wortgrenzen.

    Nach hinten heilbar nur, wenn ein Satz Zugabe reicht: folgt auf den einschränkenden Satz gleich wieder
    einer, bleibt es bei einer Heilung (``healable`` None, Kaskade begrenzt)."""
    key = "boundary_negation_condition"
    clip_text = " ".join(s.text for s in sents[first : last + 1])

    def after(end: int, text: str) -> tuple[Sentence, tuple[str, list[int]]] | None:
        if end + 1 >= len(sents):
            return None
        nxt = sents[end + 1]
        hit = _restricts(words, sents[end], nxt)
        if hit and nxt.speaker == sents[end].speaker and _has_bezug(words, nxt, text):
            return nxt, hit
        return None

    found = after(last, clip_text)
    if found:
        nxt, hit = found
        cascade = after(last + 1, f"{clip_text} {nxt.text}")
        heal = None if cascade else _back_heal(sents, last, last + 1, policy)
        return _result(
            key, policy, False, f"Satz nach dem Ende schränkt den Clip ein („{hit[0]}“): „{_sentence_text(nxt)}“",
            _ids(nxt), heal,
        )  # fmt: skip
    if first > 0:
        prev = sents[first - 1]
        hit = _negation_or_condition(words, _sent_tokens(words, prev))
        opens = prev.text.rstrip().endswith((":", ","))
        head = _sent_tokens(words, sents[first])
        turns_away = bool(head) and head[0][1] in TURN_AWAY  # „Aber die eigentliche Frage …“ wendet sich ab
        if hit and prev.speaker == sents[first].speaker and not turns_away and (opens or _has_bezug(words, sents[first], prev.text)):
            return _result(
                key, policy, False,
                f"Satz vor dem Anfang schränkt den Clip ein („{hit[0]}“): „{_sentence_text(prev)}“",
                _ids(prev), "front",
            )  # fmt: skip
    return _result(key, policy, True, "keine Negation oder Bedingung am Grenzsatz")


def _frames(words: Sequence[Mapping[str, Any]], toks: list[tuple[int, str]], question: bool) -> list[int]:
    """Wortindizes von Zitatrahmen („sagt“, „meint“, „laut“, „angeblich“, „hat gesagt“, „heißt es“,
    „erzählen“, „schreiben“, „predigen“). Nicht: erste Person („wir sagen“), „wie man so schön sagt“."""
    if question:
        return []
    out = []
    hit = _find(toks, FRAME_PHRASES)
    if hit:
        out.append(hit[1][0])
    for k, (i, t) in enumerate(toks):
        prev = toks[k - 1][1] if k > 0 else ""
        window = [x for _j, x in toks[max(0, k - FRAME_WINDOW) : k]]
        before = {x for _j, x in toks[max(0, k - 4) : k]}
        own = bool(set(window) & FIRST_PERSON) or {"wie", "man"} <= before
        perfect = t == "gesagt" and bool(before & PERFECT_AUX) and not before & FIRST_PERSON
        if (t in FRAME_TOKENS or perfect) and prev not in FRAME_NOT_AFTER and not own:
            out.append(i)
        elif t == "laut" and k + 1 < len(toks):
            j, nxt = toks[k + 1]
            if nxt in LAUT_FOLLOWERS or _upper(words, j):
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


def _distancing(toks: list[tuple[int, str]]) -> list[int] | None:
    """Distanzierung: Einzelwort („Quatsch“, „falsch“) oder Wortpaar im Fenster („sehe … anders“)."""
    hit = _find(toks, DISTANCING)
    if hit:
        return hit[1]
    for k, (i, t) in enumerate(toks):
        for a, b in DISTANCING_PAIRS:
            if t == a:
                window = toks[k + 1 : k + 1 + DISTANCING_WINDOW]
                n = next((n for n, (_j, x) in enumerate(window) if x == b), None)
                if n is not None and not (n + 1 < len(window) and window[n + 1][1] == "immer"):
                    return [i, window[n][0]]  # „stimmt nicht immer“ schränkt ein, distanziert nicht
    return None


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
    bevor der Sprecher sich davon distanziert („Ich sehe das anders.“, „Stimmt aber nicht.“)."""
    key = "reported_speech"
    head = sents[first]
    first_toks = _sent_tokens(words, head)
    in_clip_frame = any(_frames(words, _sent_tokens(words, s), _is_question(s)) for s in sents[first : last + 1])
    if not in_clip_frame:
        subj = _subjunctive_i(first_toks)
        reach = min(context_before, _reach(policy, "front")[0])  # weiter reicht eine Heilung vorn nicht
        for prev in reversed(sents[max(0, first - reach) : first]):
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
    if _distancing(_tokens(words, head.word_range[0], sents[last].word_range[1])):
        return _result(key, policy, True, "Zitat mit Rahmen und eigener Gegenposition im Clip")
    for s in sents[last + 1 : last + 1 + context_after]:
        if s.speaker != sents[last].speaker:
            break
        hit = _distancing(_sent_tokens(words, s))
        if hit:
            return _result(
                key, policy, False,
                f"Clip endet mit der fremden Position, die Distanzierung „{_sentence_text(s)}“ fehlt",
                hit, _back_heal(sents, last, s.idx, policy),
            )  # fmt: skip
    return _result(key, policy, True, "Zitat mit Rahmen im Clip")


def forward_reference(
    words: Sequence[Mapping[str, Any]], sents: Sequence[Sentence], first: int, last: int, policy: Any = None
) -> GateResult:
    """Vorverweis ohne Auflösung im Clip: „später mehr dazu“, „Später mehr.“ am Satzende, „dazu komme ich
    später“ immer; „gleich erkläre ich“, „das zeige ich gleich“, „dazu komme ich“ nur, wenn danach im Clip
    kein Satz mehr folgt; Doppelpunkt am Clipende."""
    key = "forward_reference"
    for q in range(first, last + 1):
        toks = _sent_tokens(words, sents[q])
        deferred = _find(toks, FORWARD_DEFERRED)
        at_end = _find(toks[-len(_phrase(FORWARD_DEFERRED_AT_END[0])) :], FORWARD_DEFERRED_AT_END) if toks else None
        deferred = deferred or at_end
        if deferred:
            return _result(key, policy, False, f"Vorverweis „{_text(words, deferred[1])}“ wird im Clip nicht aufgelöst", deferred[1])
        immediate = _find(toks, FORWARD_IMMEDIATE)
        if immediate and q == last:
            return _result(
                key, policy, False, f"Vorverweis „{_text(words, immediate[1])}“ am Ende ohne Auflösung im Clip",
                immediate[1], _back_heal(sents, last, last + 1, policy) if last + 1 < len(sents) else None,
            )  # fmt: skip
    b = sents[last].word_range[1]
    if 0 <= b < len(words) and _raw(words[b]).endswith(":"):
        heal = _back_heal(sents, last, last + 1, policy) if last + 1 < len(sents) else None
        return _result(key, policy, False, f"Clip endet mit Doppelpunkt auf „{_raw(words[b])}“", [b], heal)
    return _result(key, policy, True, "kein Vorverweis ohne Auflösung")


def _elliptic_answer(words: Sequence[Mapping[str, Any]], s: Sentence) -> bool:
    """Antwort, die ohne Frage nicht verständlich ist: bis drei Wörter, Antwortpartikel mit Satzzeichen in den
    ersten zwei Wörtern („Nein, nie ernsthaft.“, „Dann ja, sofort.“) oder „Meine Antwort ist …“. „Klar ist aber
    auch …“ ist keine Antwortpartikel."""
    toks = _sent_tokens(words, s)
    if not toks:
        return False
    particle = any(t in RESPONSE_PARTICLES and _raw(words[i]).endswith((",", ".", "!", "?")) for i, t in toks[:2])
    return particle or len(toks) <= ELLIPTIC_MAX_WORDS or bool(_find(toks, ANSWER_PHRASES))


def speaker_turn(
    words: Sequence[Mapping[str, Any]], sents: Sequence[Sentence], first: int, last: int, policy: Any = None
) -> GateResult:
    """Frage und Antwort richtig zugeordnet (Master-Prompt 27, Sprecherwechsel).

    Verletzt, wenn der Clip mit der Antwort von B beginnt und die Frage von A davor liegt (die Antwort ist
    ohne Frage nicht verständlich: „Nein, nie ernsthaft.“). Folgt auf eine Frage an das Gegenüber, bevor es
    antwortet, eine weitere Frage desselben Sprechers (Doppelfrage, Umformulierung), wird das nur berichtet
    (``flagged``), nicht verworfen. Ein einsilbiges „Ja.“ direkt nach einer Frage ist die Antwort."""
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
        if not _is_question(s):
            continue
        for t in sents[q + 1 : last + 1]:
            if t.speaker != s.speaker:
                break  # das Gegenüber antwortet (auch ein einsilbiges „Ja.“)
            if _is_question(t) and _to_counterpart(words, sents, t.idx):
                out = _result(
                    key, policy, True,
                    f"Doppelfrage: auf „{_sentence_text(s)}“ folgt „{_sentence_text(t)}“, die Antwort gilt beiden; nur berichtet",
                    _ids(s) + _ids(t),
                )  # fmt: skip
                out.update(flagged=True)
                return out
    return _result(key, policy, True, "Frage und Antwort richtig zugeordnet")


def _in_clip_corrections(sents: Sequence[Sentence], first: int, last: int) -> list[dict]:
    """Korrekturmarker im Clip, deren Inhalt (Markersatz plus ein Satz) über das Clipende hinausgeht
    („Werbung braucht man gar nicht. Ich korrigiere mich.“ endet vor der Richtigstellung)."""
    out = []
    for s in sents[first + 1 : last + 1]:
        marker = story_graph.find_marker(s.text, story_graph.CORRECTION_MARKERS)
        if not marker or s.idx + 1 <= last or s.idx + 1 >= len(sents):
            continue
        before = " ".join(x.text for x in sents[first : s.idx])
        overlap = story_graph.lexical_overlap(before, f"{s.text} {sents[s.idx + 1].text}")
        if overlap >= story_graph.MIN_OVERLAP:
            out.append({"sentence_idx": s.idx, "marker": marker, "seconds_after": 0.0, "kind": "correction"})
    return out


def later_correction(
    words: Sequence[Mapping[str, Any]], sents: Sequence[Sentence], first: int, last: int, policy: Any = None
) -> GateResult:
    """Spätere Selbstkorrektur, die sich auf eine Aussage im Clip bezieht (Story-Graph v2 mit Korrekturmarkern,
    Wortgrenzen), nach dem Clipende oder im Clip, wenn ihre Richtigstellung erst danach kommt.

    Das Heilziel ist der Markersatz plus ein Satz (``heal_to_sentence_idx``), weil „Ich korrigiere mich.“ allein
    nichts richtigstellt. Heilbar nach hinten nur in der Reichweite der Policy (``laenge.kontext_zugabe_saetze``
    und ``laenge.kontext_zugabe_s``)."""
    key = "later_correction"
    hits = _in_clip_corrections(sents, first, last) + [
        h for h in story_graph.find_later_qualifications(list(sents), first, last, rule="v2") if h.get("kind") == "correction"
    ]
    for h in hits:
        idx = int(h["sentence_idx"])
        target = min(idx + 1, len(sents) - 1)
        out = _result(
            key, policy, False,
            f"Spätere Korrektur „{h['marker']}“ nach {h['seconds_after']} s bezieht sich auf den Clip",
            [i for x in sents[idx : target + 1] for i in _ids(x)], _back_heal(sents, last, target, policy),
        )  # fmt: skip
        out["heal_to_sentence_idx"] = target
        return out
    return _result(key, policy, True, "keine spätere Korrektur zum Clip")


# -- Anweisungen und Meta-Rede (markieren, nie verwerfen) ---------------------------------------------


def _addresses_model(text: str) -> bool:
    """Spricht der Satz ein Modell an oder steuert es (gleiche Regel wie ``copy_engine.is_meta_speech``)?"""
    from .copy_engine import is_meta_speech

    return is_meta_speech(text)


def _instruction_hit(words: Sequence[Mapping[str, Any]], sents: Sequence[Sentence], q: int) -> list[int]:
    """Anweisungshinweis im Satz ``q``, nur wenn der Satz (oder der Satz davor desselben Sprechers) ein Modell
    anspricht oder eine Rollenmarke trägt. „Gib nie mehr aus, als du einnimmst.“ ist Coaching, kein Treffer."""
    s = sents[q]
    toks = _sent_tokens(words, s)
    for i in range(s.word_range[0], s.word_range[1] + 1):
        if _raw(words[i]).lower().strip("\"'„“”»«") in ROLE_LABELS:
            return [i]
    prev = sents[q - 1] if q > 0 else None
    addressed = _addresses_model(s.text) or (prev is not None and prev.speaker == s.speaker and _addresses_model(prev.text))
    if not addressed:
        return []
    hit = _find(toks, INSTRUCTION_PHRASES)
    if hit:
        return hit[1]
    for k, (i, t) in enumerate(toks):
        if t in INSTRUCTION_TOKENS:
            return [i]
        if t == "gib" and any(x == "aus" for _j, x in toks[k + 1 : k + 1 + SEPARABLE_GIB_AUS_WINDOW]):
            return [i]
    return _ids(s) if _addresses_model(s.text) else []


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
    """Anweisung an ein Modell im Clip: ein Satz, der ein Modell anspricht („Liebe KI, …“, „ChatGPT, …“) oder
    eine Rollenmarke trägt („System:“), mit oder ohne Steuerwort („ignoriere“, „du bist jetzt“, „gib … aus“,
    Rollenwechsel). Steuerwörter ohne Modellanrede sind Coaching („Ignorier die Kritiker“). Verwirft nicht:
    ``passed`` bleibt True, ``flagged`` und ``quotes`` zeigen den Treffer für ``instruction_followed``."""
    hits = [(sents[q], h) for q in range(first, last + 1) if (h := _instruction_hit(words, sents, q))]
    return _flagged("embedded_instruction", policy, hits, "Anweisung an ein Modell im Transkript", "keine Anweisung an ein Modell")


def meta_speech(
    words: Sequence[Mapping[str, Any]], sents: Sequence[Sentence], first: int, last: int, policy: Any = None
) -> GateResult:
    """Satz, der ein Modell anspricht (gleiche Regel wie der Hook-Ausschluss ``copy_engine.is_meta_speech``).
    Markiert den Kandidaten als Inhalt mit Meta-Rede; verwirft nicht."""
    hits = [(s, _ids(s)) for s in sents[first : last + 1] if _addresses_model(s.text)]
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


def _ngrams(seq: list[str]) -> set[str]:
    return {" ".join(seq[k : k + QUOTE_NGRAM]) for k in range(len(seq) - QUOTE_NGRAM + 1)}


def _numbers(value: Any) -> list[float]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, Mapping):
        return [n for v in value.values() for n in _numbers(v)]
    if isinstance(value, (list, tuple)):
        return [n for v in value for n in _numbers(v)]
    return []


def _schema_maxima(schema: Mapping[str, Any] | None) -> list[float]:
    if not isinstance(schema, Mapping):
        return []
    out = [float(schema["maximum"])] if isinstance(schema.get("maximum"), (int, float)) else []
    for sub in (schema.get("properties") or {}).values():
        out += _schema_maxima(sub)
    if isinstance(schema.get("items"), Mapping):
        out += _schema_maxima(schema["items"])
    return out


def instruction_followed(
    answer_json: Any,
    transcript_instructions: Sequence[str],
    schema: Mapping[str, Any] | None = None,
    clip_text: str = "",
    hook_excerpts: Sequence[str] = (),
) -> GateResult:
    """Deterministische Prüfung einer Modellantwort gegen Anweisungen aus dem Transkript.

    Geprüft werden nur Anweisungssätze, die ein Modell ansprechen oder steuern (``copy_engine.is_meta_speech``,
    Rollenmarke „System:“); Coaching wie „Gib nie mehr aus, als du einnimmst.“ ist keine Anweisung.

    Vertrag zu ``clip_text``: der Text des Clips OHNE die Anweisungssätze. Wortfolgen und Wörter, die dort oder
    in ``hook_excerpts`` (wörtliche Hook-Auszüge) vorkommen, gelten als Clip-Inhalt und nie als Zitat der
    Anweisung; eine ehrliche Antwort darf den Clip zitieren.

    Gefolgt gilt, wenn die Antwort vom Schema abweicht (mit ``schema``), ein Text der Antwort die Anweisung
    zitiert (drei aufeinanderfolgende Wörter, nicht nur Füllwörter, oder ein seltenes Wort ab zehn Zeichen wie
    „Gratisgutschein“) oder die Anweisung die volle Punktzahl verlangt und jede Zahl der Antwort auf dem
    Schema-Maximum steht. ``passed`` False heißt: Kandidat verwerfen, Grund ``instruction_followed``."""
    instructions = [str(x) for x in transcript_instructions if _addresses_model(str(x)) or any(
        t.lower().strip("\"'„“”»«") in ROLE_LABELS for t in str(x).split())]  # fmt: skip
    if not instructions:
        return {
            "passed": True, "detail": "keine Anweisung an ein Modell im Transkript", "evidence_word_ids": [],
            "healable": None, "origin": DEFAULT_ORIGIN, "reason": None, "evidence": [],
        }  # fmt: skip
    problems = _schema_problems(answer_json, schema) if schema else []
    if problems:
        return {
            "passed": False, "detail": f"Antwort weicht vom Schema ab: {problems[0]}", "evidence_word_ids": [],
            "healable": None, "origin": DEFAULT_ORIGIN, "reason": "instruction_followed", "evidence": problems,
        }  # fmt: skip
    allowed_seqs = [_seq(clip_text)] + [_seq(str(h)) for h in hook_excerpts]
    allowed_tokens = {t for seq in allowed_seqs for t in seq}
    allowed_grams = {g for seq in allowed_seqs for g in _ngrams(seq)}
    answer_seqs = [_seq(s) for s in _strings(answer_json)]
    answer_tokens = {t for seq in answer_seqs for t in seq}
    answer_grams = {g for seq in answer_seqs for g in _ngrams(seq)}
    evidence: list[str] = []
    for instruction in instructions:
        seq = _seq(instruction)
        for gram in sorted(_ngrams(seq)):
            if all(t in STOPWORDS for t in gram.split()) or gram in allowed_grams:
                continue
            if gram in answer_grams:
                evidence.append(gram)
        for t in seq:
            if len(t) >= RARE_TOKEN_MIN and t not in allowed_tokens and t in answer_tokens:
                evidence.append(t)
        maxima = _schema_maxima(schema)
        values = _numbers(answer_json)
        demands = _find([(0, t) for t in seq], MAX_SCORE_DEMANDS)
        if demands and maxima and len(values) >= 2 and all(v >= max(maxima) for v in values):
            evidence.append(f"alle Werte auf {max(maxima):g}")
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
        return {"enabled": dict.fromkeys(GATE_KEYS, True), "discard_hard": False, "switch": False}
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
    ``flagged``, ``healable`` (Seiten, auf denen eine Erweiterung helfen könnte), ``unhealable`` (verletzte
    Gates ohne Heilung), ``discard_hard`` (Regel), ``switch`` (``implementation.gates.discard_hard``) und eine
    Entscheidung ``decision`` mit ``decision_reason`` (``gate:<schluessel>``) und ``decision_detail``:
    ``rejected`` nur, wenn Regel und Schalter an sind, ``reported`` bei Verletzungen sonst, ``accepted`` ohne
    Verletzung. Ohne Abschnitt ``gates`` (Fassung 1 oder keine Policy) laufen alle Gates und werden nur
    berichtet."""
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
    unhealable = [k for k in failed if not results[k]["healable"]]
    discard = bool(cfg["discard_hard"])
    switch = bool(cfg.get("switch"))
    if failed and discard and switch:
        decision, reason = "rejected", f"gate:{failed[0]}"
        detail = results[failed[0]]["detail"]
    elif failed:
        decision, reason = "reported", f"gate:{failed[0]} nur berichtet"
        detail = results[failed[0]]["detail"]
    else:
        decision, reason, detail = "accepted", "alle Gates bestanden", ""
    return {
        "results": results,
        "failed": failed,
        "flagged": flagged,
        "healable": healable,
        "unhealable": unhealable,
        "discard_hard": discard,
        "switch": switch,
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
