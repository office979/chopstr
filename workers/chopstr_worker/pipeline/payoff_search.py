"""Deterministische Suche nach Momenten in beide Richtungen (AP5, Master-Prompt Abschnitt 7).

Payoff zuerst: ``find_payoffs`` findet Sätze, die etwas einlösen (Merksatz, Ergebnis mit Zahl, Folge,
Erklärung, Erkenntnis, emotionale Auflösung, Auflösung nach Frage, Pointe nach Setup, Lachen in der
Heatmap). ``backtrack_opening`` geht vom Payoff rückwärts zum frühesten Satz, der als Einstieg taugt und
den nötigen Kontext mitbringt (Definitionen, Bedingungen, Bezug von Pronomen, Sprecherzuordnung); Ziel ist
``laenge.gut_von_s``, ``laenge.hart_min_s`` ist nur der Boden.

Einstieg zuerst: ``find_openings`` findet Sätze mit einem Hook-Typ aus Master-Prompt Abschnitt 9,
``forward_payoff`` prüft, ob das Material diesen Einstieg einlöst.

Ein Clip endet nicht zwingend auf dem Payoff: ``search_moments`` verlängert danach bis ``laenge.gut_von_s``
(höchstens ``laenge.ziel_s``), solange derselbe Sprecher weiterführt; eine Einschränkung direkt danach
gehört samt dem Satz, der sie auflöst, in den Clip (Master-Prompt 6, „nie vor einem aber enden“), eine
Verabschiedung, ein Themenwechsel, ein Sponsor-Read oder ein anderer Sprecher beenden die Verlängerung.

``reconcile`` gleicht beide Richtungen ab: Treffer aus beiden gelten als ``direction: both``, Einstiege
ohne Einlösung fallen mit ``promise_unfulfilled`` heraus, Vorschläge unter ``min_s`` mit ``too_short``
(vor der Dublettenauflösung), mehrere Vorschläge zu derselben Aussage (gleicher ``payoff_sent``) werden als
Dublette gemeldet. ``search_moments`` meldet zusätzlich gleiche Spannen, gleiche Einstiege mit
überlappender Spanne und fast gleichen Payoff-Text als Dubletten. ``alternative_openings`` liefert für
einen Vorschlag bis zu drei verschiedene Originaleinstiege (AP6b).

Eingabe sind Sätze als ``segment.Sentence`` oder als Dict mit ``idx``, ``text``, ``speaker``, ``start``
und ``end`` (geschätzte Zeiten sind erlaubt). Alle Satzangaben in Ein- und Ausgabe sind Satznummern
(``idx``), keine Listenpositionen. Wortlisten und Längen kommen aus der Grundlage (``search``,
``einstieg``, ``ausstieg``, ``ausschluss``, ``moment_typen``, ``laenge``); ohne Abschnitt ``search``
(Fassung 1) scheitert die Suche laut. Ob ``story_engine.run`` die Suche nutzt, entscheidet der Schalter
``implementation.search.payoff_first`` (``editorial.search_settings(...)["wired"]``), nicht dieses Modul.

Ein Satz, der ein Modell anspricht oder eine Anweisung enthält (``editorial_gates.embedded_instruction``,
``editorial_gates.meta_speech``), oder ein vorgelesener oder zitierter Satz (Ankündigung im Satz davor) ist
nie Payoff und nie Einstieg; er bleibt Inhalt. Nicht angekündigt beendet er wie ein Sponsor-Read den
Rückweg.

GRENZEN: reine Textmerkmale. Ob eine Aussage trägt, ob sie ironisch gemeint ist, was im Bild passiert
und wie etwas klingt (außer Lachen aus der Heatmap), misst dieses Modul nicht. Es findet Kandidaten für
die Bewertung, es bewertet nicht. Alles ist deterministisch: gleiche Eingabe, gleiche Ausgabe.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .. import editorial
from . import dach_nlp, editorial_gates

PAYOFF_TYPES = (
    "rule", "result", "consequence", "explanation", "lesson", "emotional", "resolution", "punchline", "laughter",
)  # fmt: skip
# Trägt ein Satz mehrere Arten, gilt die spezifischere als ``payoff_type``.
TYPE_PRIORITY = (
    "punchline", "resolution", "result", "rule", "lesson", "emotional", "explanation", "consequence", "laughter",
)  # fmt: skip
DIRECTIONS = ("both", "payoff_only", "opening_only")
NARRATIVE_TYPES = ("insight", "problem_solution", "story", "demonstration", "debate", "comedy", "how_to")
# Marker, die nur am Satz- oder Teilsatzanfang zählen; lesson und emotional zählen überall.
CLAUSE_START_TYPES = frozenset({"rule", "consequence", "explanation"})

# Welche Payoff-Arten einen Hook-Typ einlösen: Spalte „Erforderlicher Inhalt“ aus Master-Prompt Abschnitt 9.
HOOK_FULFILLED_BY: dict[str, tuple[str, ...]] = {
    "concrete_contradiction": ("explanation", "consequence", "result", "lesson", "resolution"),  # Auflösung
    "mistake_with_consequence": ("consequence", "result", "lesson", "explanation", "emotional"),  # Konsequenz
    "result_with_open_cause": ("explanation", "consequence", "lesson"),  # Erklärung
    "scene_with_stakes": ("result", "lesson", "punchline", "consequence", "resolution", "laughter", "emotional"),
    "decision_rule": ("explanation", "consequence", "result", "lesson"),  # Bedingung und Begründung
    "demonstration": ("result", "explanation"),  # sichtbarer Vergleich
    "self_correction": ("lesson", "explanation", "result", "emotional"),  # tatsächlicher Lernprozess
    "recognizable_problem": ("explanation", "rule", "resolution", "consequence", "lesson"),  # Erklärung, Handlung
    "perspective_shift": ("explanation", "consequence", "rule"),  # Abgrenzung und Begründung
    "punchline": ("punchline", "laughter"),  # Setup und vollständiger komischer Moment
}

# Clip-Funktion nach Master-Prompt Abschnitt 11, abgeleitet aus Hook-Typ und Payoff-Art.
_NARRATIVE_BY_HOOK = {
    "scene_with_stakes": "story",
    "mistake_with_consequence": "story",
    "demonstration": "demonstration",
    "recognizable_problem": "problem_solution",
    "punchline": "comedy",
}
_NARRATIVE_BY_PAYOFF = {
    "punchline": "comedy",
    "laughter": "comedy",
    "resolution": "debate",
    "rule": "how_to",
    "consequence": "problem_solution",
    "result": "insight",
    "lesson": "insight",
    "emotional": "story",
    "explanation": "insight",
}

# -- Reine Textmerkmale (Sprache, keine redaktionellen Schwellen) --------------------------------------
# Satzanfänge, die auf etwas davor zeigen, zusätzlich zu ``dach_nlp.OPEN_LOOP_END`` („aber“, „und“, …).
BACK_REFERENCE_STARTS = frozenset(
    {"außerdem", "dazu", "darum", "danach", "davor", "dabei", "damit", "dadurch", "stattdessen", "seitdem",
     "seither", "trotzdem", "ebenso", "genauso"}
)  # fmt: skip
REFERENCE_PHRASES = (
    "wie gesagt", "wie vorhin", "wie erwähnt", "das von vorhin", "diese grafik", "dieses bild",
    "wie ihr seht", "wie sie sehen", "die folie",
)  # fmt: skip
# „Das ist …“, „Das war …“: Demonstrativ mit kleingeschriebenem Folgewort verweist zurück.
DEMONSTRATIVES = frozenset({"das", "dies", "dieses", "diese"})
DEFINITE_ARTICLES = frozenset({"der", "die", "das", "den", "dem", "des", "im", "am", "zum", "zur", "beim", "vom"})
# Begleiter, nach denen ein Marker noch als Teilsatzanfang gilt („Die Faustregel …“, „Mein Rat ist …“).
LEADING_DETERMINERS = frozenset({"der", "die", "das", "ein", "eine", "mein", "meine", "unser", "unsere", "dein", "deine"})
CLAUSE_CONJUNCTIONS = frozenset({"und", "aber", "sondern", "oder", "denn"})
W_WORDS = frozenset(
    {"wer", "was", "wie", "wo", "warum", "wieso", "weshalb", "wann", "welche", "welcher", "welches", "welchen",
     "wem", "wen", "wozu", "woran", "wofür", "womit", "wodurch", "woher", "wohin"}
)  # fmt: skip
NUMBER_WORDS = frozenset(
    {"zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun", "zehn", "elf", "zwölf", "zwanzig",
     "dreißig", "vierzig", "fünfzig", "sechzig", "siebzig", "achtzig", "neunzig", "hundert", "tausend",
     "million", "millionen", "hälfte", "drittel", "viertel", "doppelt", "verdoppelt", "halbiert", "dritte",
     "vierte", "fünfte", "zehnte"}
)  # fmt: skip
# Ein Zahlwort ist nur mit einem Ergebnisverb ein Ergebnis („von zwölf auf vier reduziert“), nicht als
# Mengenangabe in einer Erzählung („mit drei Leuten“).
RESULT_VERBS = frozenset(
    {"gespart", "gesteigert", "reduziert", "gesenkt", "erhöht", "verdoppelt", "halbiert", "gestiegen",
     "gesunken", "gewachsen", "verloren", "gewonnen", "verdient", "eingespart", "zurückgegangen", "angestiegen"}
)  # fmt: skip
ENUMERATION_STARTS = frozenset({"erstens", "zweitens", "drittens", "viertens", "fünftens", "letztens"})
# Floskelfragen: ihre Antwort ist keine Auflösung.
SMALL_TALK_QUESTIONS = (
    "wie geht's", "wie gehts", "wie geht es", "alles gut", "alles klar", "was gibt's neues", "wie war dein wochenende",
    "wie war euer wochenende", "hörst du mich", "hören sie mich",
)  # fmt: skip
# Moderation statt Aussage („Darum geht es heute.“): kein Payoff.
TOPIC_ANNOUNCEMENTS = ("darum geht es", "darum geht's", "darum soll es gehen", "dazu kommen wir", "dazu komme ich")
# Antwort auf eine Entscheidungsfrage eines anderen Sprechers: Antwortpartikel unter den ersten Wörtern
# oder eine Antwortformel am Anfang. Ohne die Frage ist sie nicht verständlich.
ANSWER_PARTICLES = frozenset({"ja", "nein", "jein", "nie", "niemals"})
ANSWER_PHRASES = ("meine antwort ist", "die antwort ist", "kurze antwort", "ehrlich gesagt nein", "ehrlich gesagt ja")
ANSWER_HEAD = 3
# Begründung oder Bedingung, die eine Ja-Nein-Antwort zur Auflösung macht.
JUSTIFICATION = ("weil", "nur wenn", "wenn", "sofern", "falls", "außer", "es sei denn", "solange", "aber nur")
CONDITION_WORDS = frozenset({"wenn", "falls", "sofern"})
# Zitierte Rede ist nie eine Auflösung (fremde Position, Master-Prompt 27).
REPORTED_FRAMES = frozenset({"gesagt", "sagt", "sagte", "sagten", "meint", "meinte", "gemeint", "behauptet", "behauptete"})
# Zusätzliches Signal einer Pointe neben dem wieder aufgenommenen Setup.
PUNCHLINE_CONTRAST = frozenset({"aber", "doch", "ausgerechnet", "stattdessen", "statt"})
NARRATOR_CLOSERS = ("das war", "das ist", "so war das", "und das war")
# Ankündigung eines vorgelesenen oder zitierten Textes: der Folgesatz gehört zu dieser Zuordnung.
QUOTE_ANNOUNCEMENT = re.compile(r"\b(?:les|lese|lesen)\b.*\bvor\b|\bvorlesen\b|\bzitier|:$")
# Erkenntnis-Marker, die auf ein früheres Ereignis zeigen und deshalb den Satz davor brauchen.
BACKWARD_LESSON_MARKERS = frozenset({"seitdem", "seither"})
_LEADING = "\"'„»«“”‘’([{"
_NOT_NOUNS = frozenset({"ich"}) | editorial_gates.FORMAL_FORMS
_MIN_NOUN_LEN = 4
_MIN_CLAIM_TOKENS = 4
_SAME_TEXT_JACCARD = 0.8


@dataclass(frozen=True)
class _S:
    idx: int
    text: str
    speaker: str | None
    start: float
    end: float

    @property
    def low(self) -> str:
        return self.text.lower()


@dataclass
class _Ctx:
    policy: editorial.Policy
    cfg: dict[str, Any]
    v: list[_S]
    pos: dict[int, int] = field(default_factory=dict)
    toks: list[list[str]] = field(default_factory=list)
    cores: list[list[str]] = field(default_factory=list)
    qualification: tuple[str, ...] = ()
    merksatz: tuple[str, ...] = ()
    story: tuple[str, ...] = ()
    nouns: list[set[str]] = field(default_factory=list)
    has_noun: list[bool] = field(default_factory=list)
    definite: list[list[str]] = field(default_factory=list)
    pronoun_open: list[bool] = field(default_factory=list)
    addressed: list[bool] = field(default_factory=list)
    quoted: list[bool] = field(default_factory=list)
    stop: list[bool] = field(default_factory=list)
    no_host_question: bool = True
    front_s: float | None = None

    def duration(self, a: int, b: int) -> float:
        return max(0.0, self.v[b].end - self.v[a].start)

    def question(self, i: int) -> bool:
        return self.v[i].text.rstrip().endswith("?")


def _settings(policy: editorial.Policy) -> dict[str, Any]:
    cfg = editorial.search_settings(policy)
    if cfg is None:
        raise editorial.PolicyError(
            f"payoff_search braucht den Abschnitt search der Grundlage (ab Fassung 2), "
            f"{editorial.policy_version(policy.version)} hat ihn nicht."
        )
    return cfg


def _views(sents: Sequence[Any]) -> list[_S]:
    out = []
    for s in sents:
        get = s.get if isinstance(s, Mapping) else (lambda k, _s=s: getattr(_s, k, None))
        start, end = get("start"), get("end")
        if start is None or end is None:
            raise ValueError(f"Satz {get('idx')} ohne start und end; payoff_search braucht Zeiten (geschätzt ist erlaubt).")
        text = str(get("text") or "")
        out.append(_S(idx=int(get("idx")), text=text, speaker=get("speaker"), start=float(start), end=float(end)))
    return out


def _core(token: str) -> str:
    return dach_nlp.core_token(token)


def _tokens(text: str) -> list[str]:
    return [t for t in text.split() if _core(t)]


def _upper(token: str) -> bool:
    t = token.lstrip(_LEADING)
    return bool(t[:1]) and (t[:1].isupper() or t[:1].isdigit())


def _has(low: str, marker: str) -> bool:
    """Marker als ganze Wörter im kleingeschriebenen Text."""
    return re.search(rf"(?<!\w){re.escape(marker)}(?!\w)", low) is not None


def _any(low: str, markers: Iterable[str]) -> bool:
    return any(_has(low, m) for m in markers)


def _ctx(sents: Sequence[Any], policy: editorial.Policy) -> _Ctx:
    cfg = _settings(policy)
    v = _views(sents)
    typen = {t.schluessel: t for t in policy.moment_typen}
    laenge = policy.roh.get("laenge") or {}
    ctx = _Ctx(
        policy=policy,
        cfg=cfg,
        v=v,
        pos={s.idx: i for i, s in enumerate(v)},
        qualification=tuple(str(m).lower() for m in (policy.ausstieg.get("abschwaechung_marker") or ())),
        merksatz=typen["merksatz"].marker if "merksatz" in typen else (),
        story=(typen["ministory"].marker if "ministory" in typen else ()) + cfg["hook_type_markers"]["scene_with_stakes"],
        no_host_question=bool(policy.einstieg.get("keine_gastgeberfrage")),
        front_s=float(laenge["context_front_s"]) if laenge.get("context_front_s") is not None else None,
    )
    # Wort- und Satzliste für die Gates aus editorial_gates (Pronomen, Anweisung, Meta-Rede).
    gw, gs = editorial_gates.from_sentence_texts([{"text": s.text.strip() or "-", "speaker": s.speaker} for s in v])
    stops = [m for markers in cfg["stop_markers"].values() for m in markers]
    for k, s in enumerate(v):
        toks = _tokens(s.text)
        cores = [_core(t) for t in toks]
        ctx.toks.append(toks)
        ctx.cores.append(cores)
        nouns, definite = set(), []
        for j, tok in enumerate(toks):
            if j == 0 or not _upper(tok) or cores[j] in _NOT_NOUNS or cores[j].isdigit():
                continue
            if len(cores[j]) >= _MIN_NOUN_LEN:
                nouns.add(cores[j])
                if _core(toks[j - 1]) in DEFINITE_ARTICLES:
                    definite.append(cores[j])
        ctx.nouns.append(nouns)
        ctx.has_noun.append(any(j > 0 and _upper(t) and c not in _NOT_NOUNS for j, (t, c) in enumerate(zip(toks, cores))))
        ctx.definite.append(definite)
        ctx.pronoun_open.append(not editorial_gates.unresolved_pronoun(gw, gs, k, k, policy)["passed"])
        ctx.addressed.append(
            bool(editorial_gates.embedded_instruction(gw, gs, k, k, policy)["flagged"])
            or bool(editorial_gates.meta_speech(gw, gs, k, k, policy)["flagged"])
        )
        ctx.quoted.append(k > 0 and bool(QUOTE_ANNOUNCEMENT.search(v[k - 1].low.rstrip())))
        ctx.stop.append(
            policy.ist_organisatorisch(s.text) or _any(s.low, stops) or (ctx.addressed[k] and not ctx.quoted[k])
        )
    return ctx


# -- Einstieg prüfen ------------------------------------------------------------------------------


def _head(ctx: _Ctx, i: int) -> list[str]:
    toks = ctx.toks[i]
    k = 0
    while k < len(toks) and _core(toks[k]) in dach_nlp.HARD_FILLERS:
        k += 1
    return toks[k:]


def _starts_with_qualification(ctx: _Ctx, i: int) -> bool:
    head = " ".join(_core(t) for t in _head(ctx, i)[:4])
    return any(head == m or head.startswith(m + " ") for m in ctx.qualification)


def _opening_defects(ctx: _Ctx, i: int) -> list[str]:
    toks = _head(ctx, i)
    if not toks:
        return ["leerer Satz"]
    first, core = toks[0], _core(toks[0])
    out: list[str] = []
    if not _upper(first):
        out.append(f"Anfang mitten im Satz („{first}“)")
    if ctx.pronoun_open[i]:
        out.append("Pronomen ohne Bezug im Einstiegssatz")
    nxt = toks[1] if len(toks) > 1 else ""
    if (
        core in dach_nlp.OPEN_LOOP_END
        or " ".join(_core(t) for t in toks[:2]) in dach_nlp.OPEN_LOOP_END
        or core in BACK_REFERENCE_STARTS
        or _starts_with_qualification(ctx, i)
        or (core in DEMONSTRATIVES and nxt and not _upper(nxt))
    ):
        out.append(f"Rückverweis am Anfang („{first}“)")
    elif any(p in ctx.v[i].low for p in REFERENCE_PHRASES):
        out.append("Rückverweis im Einstiegssatz")
    if ctx.quoted[i]:
        out.append("vorgelesener oder zitierter Satz, Zuordnung steht davor")
    if ctx.addressed[i]:
        out.append("Satz spricht ein Modell an oder enthält eine Anweisung, bleibt Inhalt")
    if ctx.stop[i] and not ctx.addressed[i]:
        out.append("Organisatorisches, Sponsor, Verabschiedung oder Themenwechsel")
    return out


def opening_defects(sents: Sequence[Any], sent_no: int, policy: editorial.Policy) -> list[str]:
    """Mängel, wenn ein Clip mit Satz ``sent_no`` beginnt; leer heißt: taugt als Einstieg.

    Geprüft werden Satzanfang (großgeschriebenes erstes Wort nach Füllwörtern), Pronomen ohne Bezug
    (``editorial_gates.unresolved_pronoun``: Höflichkeitsform „Sie“ und „Ihnen“ mitten im Satz und
    Inversion wie „Wissen Sie“ sind Anrede), Rückverweis (Anschlusswort aus ``dach_nlp.OPEN_LOOP_END`` oder
    ``BACK_REFERENCE_STARTS``, Abschwächung aus ``ausstieg.abschwaechung_marker``, „Das ist …“, „wie
    gesagt“), vorgelesener oder zitierter Satz, an ein Modell gerichteter Satz und Stoppsatz
    (Organisatorisches, ``search.stop_markers``). Das ist die Standard-Prüfung von ``backtrack_opening``;
    ``story_engine`` kann ``start_defects`` übergeben."""
    ctx = _ctx(sents, policy)
    return _opening_defects(ctx, ctx.pos[sent_no])


def _default_gate(ctx: _Ctx) -> Callable[[int], bool]:
    return lambda sent_no: not _opening_defects(ctx, ctx.pos[sent_no])


def _other_speaker_question(ctx: _Ctx, a: int, p: int) -> bool:
    return ctx.question(a) and ctx.v[a].speaker != ctx.v[p].speaker


def _small_talk(ctx: _Ctx, i: int) -> bool:
    return any(q in ctx.v[i].low for q in SMALL_TALK_QUESTIONS)


def _answers_question(ctx: _Ctx, i: int) -> bool:
    """Ist Satz ``i`` die Ja-Nein-Antwort auf die Frage eines anderen Sprechers direkt davor?"""
    if i <= 0:
        return False
    q, s = ctx.v[i - 1], ctx.v[i]
    if not ctx.question(i - 1) or q.speaker == s.speaker or ctx.stop[i - 1] or _small_talk(ctx, i - 1):
        return False
    head = [_core(t) for t in _head(ctx, i)]
    joined = " ".join(head)
    return bool(set(head[:ANSWER_HEAD]) & ANSWER_PARTICLES) or any(joined == p or joined.startswith(p + " ") for p in ANSWER_PHRASES)


def _resolution(ctx: _Ctx, i: int) -> int | None:
    """Position der Frage, die Satz ``i`` auflöst, oder ``None``.

    W-Frage im Satz davor (nicht organisatorisch, keine Floskel), Antwort mit Inhalt und ohne zitierte Rede;
    oder Ja-Nein-Frage eines anderen Sprechers mit Antwortpartikel und Begründung oder Bedingung (in der
    Antwort „weil“, „nur wenn“, oder die Frage nennt die Bedingung)."""
    if i <= 0 or not ctx.question(i - 1) or ctx.stop[i - 1] or ctx.quoted[i - 1] or _small_talk(ctx, i - 1):
        return None
    if set(ctx.cores[i]) & REPORTED_FRAMES:
        return None
    if set(ctx.cores[i - 1]) & W_WORDS:
        return i - 1 if len(ctx.toks[i]) >= _MIN_CLAIM_TOKENS and _substance(ctx, i, 0) else None
    if _answers_question(ctx, i) and (_any(ctx.v[i].low, JUSTIFICATION) or set(ctx.cores[i - 1]) & CONDITION_WORDS):
        return i - 1
    return None


def _qa_unit(ctx: _Ctx, a: int, end: int) -> bool:
    """Darf die Frage ``a`` eines anderen Sprechers den Clip eröffnen? Nur kurz (``laenge.context_front_s``)
    und wenn der Satz danach sie beantwortet: Frage plus Antwort als Einheit."""
    if a + 1 > end or ctx.front_s is None or ctx.duration(a, a) > ctx.front_s:
        return False
    return _resolution(ctx, a + 1) is not None or _answers_question(ctx, a + 1)


def _short_answered(ctx: _Ctx, a: int, end: int) -> bool:
    """Kurze Frage (``laenge.context_front_s``), auf die direkt die Antwort eines anderen Sprechers folgt."""
    if a + 1 > end or ctx.front_s is None or ctx.duration(a, a) > ctx.front_s:
        return False
    return ctx.v[a + 1].speaker != ctx.v[a].speaker and not ctx.question(a + 1)


def _context_needs(ctx: _Ctx, a: int, b: int) -> set[int]:
    """Positionen, die ein Abschnitt ``a`` bis ``b`` als Kontext braucht, ohne die Payoff-Art.

    Sprecherzuordnung: kündigt der Satz vor ``a`` einen vorgelesenen oder zitierten Text an, gehört er
    dazu; beginnt der Abschnitt mit der Ja-Nein-Antwort auf die Frage eines anderen Sprechers, gehört die
    Frage dazu. Pronomen: ein Pronomen ohne vorausgehendes Nomen im Clip braucht den letzten Satz davor mit
    einem Nomen oder Namen. Definitionen: ein Nomen mit bestimmtem Artikel, das der Clip nicht selbst
    einführt, braucht den Satz der letzten Nennung davor. Alles nur innerhalb von ``laenge.hart_max_s``."""
    needs: set[int] = set()
    reach = ctx.policy.hart_max_s
    if a > 0 and ctx.quoted[a]:
        needs.add(a - 1)
    if _answers_question(ctx, a):
        needs.add(a - 1)
    for k in range(a, b + 1):
        if ctx.pronoun_open[k] and not any(ctx.has_noun[m] for m in range(a, k)):
            j = next((m for m in range(a - 1, -1, -1) if ctx.has_noun[m]), None)
            if j is not None and ctx.duration(j, b) <= reach:
                needs.add(j)
        for noun in ctx.definite[k]:
            if any(noun in ctx.nouns[m] for m in range(a, k)):
                continue
            j = next((m for m in range(a - 1, -1, -1) if noun in ctx.nouns[m]), None)
            if j is not None and ctx.duration(j, b) <= reach:
                needs.add(j)
    return needs


# -- Payoff finden --------------------------------------------------------------------------------


def _laughter_after(heat: Mapping[str, Any] | None, s: _S) -> bool:
    """Lachen in der Heatmap (``heat["laughter"]`` je Bin) im Bin des Satzendes oder im nächsten."""
    if not heat or not heat.get("laughter"):
        return False
    bin_s = float(heat.get("bin_s") or 1.0) or 1.0
    b = int(s.end / bin_s)
    return any(float(x) > 0 for x in heat["laughter"][max(0, b) : b + 2])


def _number_token(tok: str, core: str) -> bool:
    return any(ch.isdigit() for ch in tok) or core in NUMBER_WORDS


def _substance(ctx: _Ctx, i: int, after: int) -> bool:
    """Folgt ab Token ``after`` ein Nomen oder eine Zahl?"""
    toks, cores = ctx.toks[i], ctx.cores[i]
    return any(
        _number_token(toks[j], cores[j]) or (j > 0 and _upper(toks[j]) and cores[j] not in _NOT_NOUNS)
        for j in range(after, len(toks))
    )


def _clause_start(ctx: _Ctx, i: int, j: int) -> bool:
    """Steht Token ``j`` am Satz- oder Teilsatzanfang (auch nach Füllwort, Begleiter oder Konjunktion)?"""
    toks, cores = ctx.toks[i], ctx.cores[i]
    k = j
    if k > 0 and cores[k - 1] in LEADING_DETERMINERS:
        k -= 1
    if k > 0 and cores[k - 1] in CLAUSE_CONJUNCTIONS:
        k -= 1
    while k > 0 and cores[k - 1] in dach_nlp.HARD_FILLERS:
        k -= 1
    return k == 0 or toks[k - 1].rstrip(_LEADING[::-1] + "\"'»«“”‘’)]}").endswith((",", ";", ":", ".", "!", "?"))


def _marker_hit(ctx: _Ctx, i: int, markers: Iterable[str], clause_start: bool) -> tuple[str, int] | None:
    """Erster Marker als Wortfolge in Satz ``i`` mit Nomen oder Zahl danach: ``(marker, ende)``."""
    cores = ctx.cores[i]
    for m in markers:
        words = [_core(w) for w in m.split()]
        for j in range(len(cores) - len(words) + 1):
            if cores[j : j + len(words)] != words:
                continue
            if clause_start and not _clause_start(ctx, i, j):
                continue
            return m, j + len(words)
    return None


def _excluded_payoff(ctx: _Ctx, i: int) -> bool:
    s = ctx.v[i]
    if not ctx.toks[i] or ctx.question(i) or ctx.stop[i] or ctx.quoted[i] or ctx.addressed[i]:
        return True
    if _any(s.low, ctx.cfg["hedge_markers"]) or any(p in s.low for p in TOPIC_ANNOUNCEMENTS):
        return True
    return bool(ctx.cores[i]) and ctx.cores[i][0] in ENUMERATION_STARTS


def _payoff_at(ctx: _Ctx, i: int, heat: Mapping[str, Any] | None = None) -> dict | None:
    if _excluded_payoff(ctx, i):
        return None
    s = ctx.v[i]
    low = s.low
    markers = ctx.cfg["payoff_markers"]
    found: dict[str, tuple[int, str, tuple[int, ...]]] = {}  # Art: (Beleg-Position, Marker, Kontext)
    prev = (i - 1,) if i > 0 and not ctx.stop[i - 1] else ()

    for typ in ("rule", "consequence", "explanation", "lesson", "emotional"):
        pool = tuple(markers[typ]) + (ctx.merksatz if typ == "rule" else ())
        hit = _marker_hit(ctx, i, pool, typ in CLAUSE_START_TYPES)
        if hit is None:
            continue
        marker, end = hit
        if typ == "emotional":
            if len(ctx.toks[i]) < _MIN_CLAIM_TOKENS:
                continue
        elif not _substance(ctx, i, end):
            continue
        if typ == "explanation" and end < len(ctx.cores[i]) and ctx.cores[i][end] in ("ich", "wir", "du", "man"):
            continue  # „Das heißt, ich muss morgen früher los.“
        needs = prev if typ in ("consequence", "explanation") or marker in BACKWARD_LESSON_MARKERS else ()
        found[typ] = (i, marker, needs)
    zahl = next((t for t in ctx.policy.moment_typen if t.schluessel == "zahl"), None)
    numbers = (zahl is not None and zahl.trifft(low)) or (
        any(c in NUMBER_WORDS for c in ctx.cores[i]) and bool(set(ctx.cores[i]) & RESULT_VERBS)
    )
    if numbers and ctx.has_noun[i]:
        found["result"] = (i, "zahl", ())
    q = _resolution(ctx, i)
    if q is not None:
        found["resolution"] = (q, "frage", (q,))
    for noun in ctx.definite[i]:
        if any(noun in ctx.nouns[m] for m in range(max(0, i - 1), i)):
            continue
        j = next((m for m in range(i - 2, -1, -1) if noun in ctx.nouns[m]), None)
        if j is None or not _any(ctx.v[j].low, ctx.story):
            continue
        closer = (
            i + 1 < len(ctx.v)
            and ctx.v[i + 1].speaker == s.speaker
            and any(ctx.v[i + 1].low.startswith(c + " ") for c in NARRATOR_CLOSERS)
        )
        if closer or set(ctx.cores[i]) & PUNCHLINE_CONTRAST or _laughter_after(heat, s):
            found["punchline"] = (j, noun, (j,))
            break
    if _laughter_after(heat, s):
        found["laughter"] = (i, "lachen", ())
    if not found:
        return None
    primary = next(t for t in TYPE_PRIORITY if t in found)
    evidence, marker, _needs = found[primary]
    return {
        "payoff_sent": s.idx,
        "payoff_type": primary,
        "evidence_sent": ctx.v[evidence].idx,
        "marker": marker,
        "types": [t for t in TYPE_PRIORITY if t in found],
        "needs_sents": sorted({ctx.v[n].idx for _e, _m, ns in found.values() for n in ns}),
    }


def find_payoffs(sents: Sequence[Any], policy: editorial.Policy, heat: Mapping[str, Any] | None = None) -> list[dict]:
    """Sätze, die etwas einlösen, je mit ``payoff_type`` und Beleg-Satznummer ``evidence_sent``.

    Arten: ``rule`` (Merksatz), ``consequence`` („deshalb“), ``explanation`` („das heißt“, „der Grund
    ist“), jeweils nur am Satz- oder Teilsatzanfang und mit Nomen oder Zahl danach; ``lesson``
    („gelernt“, „seitdem“, „rückblickend“) und ``emotional`` („heute weiß ich“) überall; ``result``
    (Zahl aus ``moment_typen.zahl`` oder Zahlwort mit Ergebnisverb, mit Nomen im Satz); ``resolution`` (Antwort auf eine
    W-Frage oder begründete Ja-Nein-Antwort auf die Frage eines anderen Sprechers; Beleg ist die Frage);
    ``punchline`` (Nomen mit bestimmtem Artikel greift ein Setup in einer erzählten Szene auf, plus Lachen,
    Kontrast oder Erzählende danach; Beleg ist das Setup); ``laughter`` (nur mit ``heat["laughter"]``).
    Nie Payoff: Fragen, Sätze mit Heckenwörtern (``search.hedge_markers``), Aufzählungsanfang, Moderation
    („Darum geht es heute“), Stoppsätze, vorgelesene oder an ein Modell gerichtete Sätze.
    ``needs_sents`` nennt die Sätze, ohne die der Payoff nicht verständlich ist."""
    ctx = _ctx(sents, policy)
    return [hit for i in range(len(ctx.v)) if (hit := _payoff_at(ctx, i, heat)) is not None]


# -- Payoff zuerst: rückwärts zum Einstieg ----------------------------------------------------------


def _walk_back(ctx: _Ctx, start: int, end: int, speaker_pos: int, needs: set[int], gate: Callable[[int], bool], target: float) -> int | None:
    """Frühester gültiger Einstieg ab ``start`` rückwärts, bis der Abschnitt bis ``end`` ``target`` erreicht.

    Ende an einem Stoppsatz und an ``laenge.hart_max_s``. Die Frage eines anderen Sprechers eröffnet den
    Clip nur als Einheit mit ihrer Antwort (``_qa_unit``); sonst wird sie bei
    ``einstieg.keine_gastgeberfrage`` übersprungen, der Rückweg bricht dort nicht ab. Bleibt der Abschnitt
    ohne sie unter ``laenge.hart_min_s``, darf eine kurze Frage eröffnen, deren Antwort direkt folgt."""
    best = None
    fallback = None
    for a in range(start, -1, -1):
        if a < start and ctx.stop[a]:
            break
        dur = ctx.duration(a, end)
        if dur > ctx.policy.hart_max_s:
            break
        req = needs | _context_needs(ctx, a, end)
        valid = not any(r < a for r in req) and gate(ctx.v[a].idx)
        if _other_speaker_question(ctx, a, speaker_pos) and ctx.no_host_question and not _qa_unit(ctx, a, end):
            if valid and fallback is None and _short_answered(ctx, a, end):
                fallback = a
            continue
        if not valid:
            continue
        best = a
        if dur >= target:
            break
    if fallback is not None and (best is None or (best > fallback and ctx.duration(best, end) < ctx.policy.hart_min_s)):
        return fallback
    return best


def _backchannel(ctx: _Ctx, i: int) -> bool:
    cores = ctx.cores[i]
    return 0 < len(cores) <= 2 and all(c in dach_nlp.BACKCHANNEL or c in dach_nlp.HARD_FILLERS for c in cores)


def _extend(ctx: _Ctx, a: int, b: int, p: int) -> int:
    """Ende nach dem Payoff ``p`` verlängern (siehe Moduldoku). Rückgabe das neue Ende."""
    pol = ctx.policy
    speaker = ctx.v[p].speaker
    b0 = b

    def blocked(n: int) -> bool:
        if n >= len(ctx.v) or ctx.stop[n] or ctx.addressed[n] or ctx.duration(a, n) > pol.hart_max_s:
            return True
        if _backchannel(ctx, n):
            return False
        return ctx.v[n].speaker != speaker or ctx.question(n)

    while True:
        n = b + 1
        if blocked(n):
            break
        if _backchannel(ctx, n):
            b = n
            continue
        if _starts_with_qualification(ctx, n):
            m = n + 1
            while m < len(ctx.v) and _backchannel(ctx, m) and not blocked(m):
                m += 1
            if blocked(m) or _starts_with_qualification(ctx, m):
                break
            b = m
            continue
        if dach_nlp.ends_with_open_loop(ctx.v[b].text) or ctx.v[b].text.rstrip().endswith((",", ":")):
            b = n
            continue
        if ctx.duration(a, b) >= pol.gut_von_s or ctx.duration(a, n) > pol.ziel_s:
            break
        b = n
    while b > b0 and (_backchannel(ctx, b) or _starts_with_qualification(ctx, b)):
        b -= 1
    return b


def _span(ctx: _Ctx, a: int, b: int, p: int, needs: set[int]) -> dict:
    req = needs | _context_needs(ctx, a, b)
    return {
        "opening_sent": ctx.v[a].idx,
        "payoff_sent": ctx.v[p].idx,
        "first_sent": ctx.v[a].idx,
        "last_sent": ctx.v[b].idx,
        "required_context_sents": sorted(ctx.v[r].idx for r in req if a <= r <= b and r != p),
        "duration_s": round(ctx.duration(a, b), 2),
    }


def backtrack_opening(
    sents: Sequence[Any],
    payoff_idx: int,
    policy: editorial.Policy,
    gate_fn: Callable[[int], bool] | None = None,
    needs: Iterable[int] | None = None,
) -> dict | None:
    """Vom Payoff ``payoff_idx`` rückwärts zum frühesten Satz, der ``gate_fn`` besteht und den nötigen
    Kontext einschließt.

    ``gate_fn(satznummer) -> bool``; Standard ist ``opening_defects`` leer. Kontext sind ``needs``
    (Satznummern, Standard: die ``needs_sents`` des Payoffs) und ``_context_needs`` (Sprecherzuordnung,
    Pronomen, Definitionen). Ziel ist ``laenge.gut_von_s``; ``laenge.hart_min_s`` ist nur der Boden, den
    ``search_moments`` prüft. Der Rückweg endet an ``laenge.hart_max_s`` und an einem Stoppsatz; die Frage
    eines anderen Sprechers eröffnet nur als kurze Einheit mit ihrer Antwort und wird sonst übersprungen.
    Rückgabe ``{opening_sent, payoff_sent, first_sent, last_sent, required_context_sents, duration_s}``
    mit ``last_sent`` gleich Payoff, oder ``None``, wenn kein Einstieg mit vollständigem Kontext existiert."""
    ctx = _ctx(sents, policy)
    p = ctx.pos[payoff_idx]
    if needs is None:
        hit = _payoff_at(ctx, p)
        needs = hit["needs_sents"] if hit else ()
    need_pos = {ctx.pos[n] for n in needs if n in ctx.pos}
    a = _walk_back(ctx, p, p, p, need_pos, gate_fn or _default_gate(ctx), policy.gut_von_s)
    return None if a is None else _span(ctx, a, p, p, need_pos)


# -- Einstieg zuerst: vorwärts zum Payoff -----------------------------------------------------------


def _hook_at(ctx: _Ctx, i: int) -> tuple[str, str] | None:
    """Hook-Typ allein aus dem Einstiegssatz ``i``."""
    for hook_type in editorial.SEARCH_HOOK_TYPES:
        hit = _marker_hit(ctx, i, ctx.cfg["hook_type_markers"][hook_type], clause_start=False)
        if hit:
            return hook_type, hit[0]
    return None


def find_openings(sents: Sequence[Any], policy: editorial.Policy) -> list[dict]:
    """Sätze mit einem Hook-Typ aus Master-Prompt Abschnitt 9 (``search.hook_type_markers``, origin H),
    die als Einstieg taugen (``opening_defects`` leer).

    Rückgabe je Treffer ``{opening_sent, hook_type, marker}``; ob eingelöst wird, sagt ``forward_payoff``."""
    ctx = _ctx(sents, policy)
    return _openings(ctx)


def _openings(ctx: _Ctx) -> list[dict]:
    out = []
    for i, s in enumerate(ctx.v):
        hit = _hook_at(ctx, i)
        if hit and not _opening_defects(ctx, i):
            out.append({"opening_sent": s.idx, "hook_type": hit[0], "marker": hit[1]})
    return out


def _forward(ctx: _Ctx, a: int, hook_type: str | None, heat: Mapping[str, Any] | None) -> dict | None:
    accepted = set(HOOK_FULFILLED_BY.get(hook_type or "", PAYOFF_TYPES))
    first_hit = None
    for b in range(a + 1, len(ctx.v)):
        if ctx.stop[b]:
            break
        dur = ctx.duration(a, b)
        if dur > ctx.policy.hart_max_s:
            break
        pay = _payoff_at(ctx, b, heat)
        matching = [t for t in (pay or {}).get("types", []) if t in accepted]
        if not matching:
            continue
        need_pos = {ctx.pos[n] for n in pay["needs_sents"]}
        req = need_pos | _context_needs(ctx, a, b)
        cand = {
            **_span(ctx, a, b, b, need_pos),
            "hook_type": hook_type,
            "payoff_type": matching[0],
            "evidence_sent": pay["evidence_sent"],
            "missing_context_sents": sorted(ctx.v[r].idx for r in req if r < a),
        }
        if first_hit is None:
            first_hit = cand
        if dur >= ctx.policy.hart_min_s:
            return cand
    return first_hit


def forward_payoff(
    sents: Sequence[Any],
    opening_idx: int,
    policy: editorial.Policy,
    hook_type: str | None = None,
    heat: Mapping[str, Any] | None = None,
) -> dict | None:
    """Löst das Material den Einstieg ``opening_idx`` ein? Erster Payoff nach dem Einstieg, dessen Art
    zum Hook-Typ passt (``HOOK_FULFILLED_BY``), bevorzugt der erste, mit dem der Abschnitt
    ``laenge.hart_min_s`` erreicht; Ende an ``laenge.hart_max_s`` und an einem Stoppsatz.

    Rückgabe ``{opening_sent, hook_type, payoff_sent, payoff_type, evidence_sent, first_sent, last_sent,
    required_context_sents, missing_context_sents, duration_s}`` (``last_sent`` gleich Payoff) oder
    ``None`` (Versprechen nicht eingelöst). ``missing_context_sents`` sind nötige Sätze vor dem Einstieg."""
    ctx = _ctx(sents, policy)
    a = ctx.pos[opening_idx]
    if hook_type is None:
        hit = _hook_at(ctx, a)
        hook_type = hit[0] if hit else None
    return _forward(ctx, a, hook_type, heat)


# -- Abgleich ------------------------------------------------------------------------------------


def narrative_type(payoff_type: str | None, hook_type: str | None) -> str:
    """Clip-Funktion (Master-Prompt Abschnitt 11) aus Payoff-Art und Hook-Typ."""
    if payoff_type in ("punchline", "laughter"):
        return "comedy"
    if hook_type in _NARRATIVE_BY_HOOK:
        return _NARRATIVE_BY_HOOK[hook_type]
    return _NARRATIVE_BY_PAYOFF.get(payoff_type or "", "insight")


def _proposal(span: Mapping[str, Any], direction: str, hook_type: str | None, payoff_type: str | None) -> dict:
    return {
        "first_sent": int(span["first_sent"]),
        "last_sent": int(span["last_sent"]),
        "opening_sent": int(span["opening_sent"]),
        "payoff_sent": int(span["payoff_sent"]),
        "required_context_sents": sorted(int(x) for x in span.get("required_context_sents") or ()),
        "direction": direction,
        "payoff_type": payoff_type,
        "hook_type": hook_type,
        "evidence_sent": span.get("evidence_sent"),
        "duration_s": span.get("duration_s"),
        "narrative_type": narrative_type(payoff_type, hook_type),
    }


def _rank(prop: Mapping[str, Any]) -> tuple:
    payoff_type = prop.get("payoff_type")
    type_rank = TYPE_PRIORITY.index(payoff_type) if payoff_type in TYPE_PRIORITY else len(TYPE_PRIORITY)
    return (DIRECTIONS.index(prop["direction"]), type_rank, prop["first_sent"] - prop["last_sent"], prop["first_sent"])


def reconcile(
    payoff_first: Sequence[Mapping[str, Any]],
    opening_first: Sequence[Mapping[str, Any]],
    min_s: float | None = None,
) -> dict:
    """Beide Suchrichtungen abgleichen.

    ``payoff_first``: Einträge mit ``payoff_sent``, ``opening_sent``, ``first_sent``, ``last_sent``,
    ``duration_s`` (aus ``backtrack_opening`` plus ``payoff_type``). ``opening_first``: Einträge aus
    ``find_openings``, ergänzt um das Ergebnis von ``forward_payoff`` (``payoff_sent`` ``None`` heißt nicht
    eingelöst).

    * Zuerst die Länge: mit ``min_s`` fällt jeder Eintrag darunter mit ``too_short`` heraus, bevor
      abgeglichen und dedupliziert wird (sonst könnte eine zu kurze Variante eine lange verdrängen).
    * Einstieg ohne Einlösung: ``promise_unfulfilled``.
    * Gleicher Payoff aus beiden Richtungen: ``direction: both``; je passendem Einstieg eine Variante ab
      diesem Einstieg, wenn er seinen Kontext selbst mitbringt. Den Hook-Typ erbt die Payoff-Spanne nur
      von einem Einstieg im selben Satz.
    * Payoff ohne passenden Einstieg: ``payoff_only``; Einlösung, die die Payoff-Suche nicht hat:
      ``opening_only`` (fehlt Kontext vor dem Einstieg: ``context_missing``).
    * Mehrere Vorschläge zum selben ``payoff_sent`` sind Dubletten: einer bleibt (``both`` vor
      ``payoff_only`` vor ``opening_only``, dann der Einstieg der Payoff-Suche, dann der längere), die
      anderen stehen in ``duplicates`` (``same_payoff``).

    Rückgabe ``{proposals, rejected, duplicates}``, Vorschläge nach Satznummer sortiert."""
    rejected: list[dict] = []

    def long_enough(e: Mapping[str, Any]) -> bool:
        if min_s is None or e.get("duration_s") is None or float(e["duration_s"]) >= min_s:
            return True
        rejected.append(
            {"first_sent": e["first_sent"], "last_sent": e["last_sent"], "payoff_sent": e["payoff_sent"],
             "reason": "too_short", "duration_s": e["duration_s"]}
        )  # fmt: skip
        return False

    by_payoff = {int(p["payoff_sent"]): p for p in payoff_first if long_enough(p)}
    matched: dict[int, list[Mapping[str, Any]]] = {}
    variants: list[tuple[dict, bool]] = []  # (Vorschlag, Einstieg der Payoff-Suche)
    for o in opening_first:
        if o.get("payoff_sent") is None:
            rejected.append({"opening_sent": int(o["opening_sent"]), "hook_type": o.get("hook_type"), "reason": "promise_unfulfilled"})
        elif not long_enough(o):
            continue
        elif int(o["payoff_sent"]) in by_payoff:
            matched.setdefault(int(o["payoff_sent"]), []).append(o)
        elif o.get("missing_context_sents"):
            rejected.append({"opening_sent": int(o["opening_sent"]), "hook_type": o.get("hook_type"), "reason": "context_missing"})
        else:
            variants.append((_proposal(o, "opening_only", o.get("hook_type"), o.get("payoff_type")), False))
    for payoff, p in by_payoff.items():
        os_ = matched.get(payoff, [])
        same = next((o for o in os_ if int(o["opening_sent"]) == int(p["opening_sent"])), None)
        variants.append((_proposal(p, "both" if os_ else "payoff_only", (same or {}).get("hook_type"), p.get("payoff_type")), True))
        for o in os_:
            if o.get("missing_context_sents") or o is same:
                continue
            variants.append((_proposal({**o, "payoff_type": p.get("payoff_type")}, "both", o.get("hook_type"), p.get("payoff_type")), False))

    groups: dict[int, list[tuple[dict, bool]]] = {}
    for prop, agrees in variants:
        group = groups.setdefault(prop["payoff_sent"], [])
        if all((x["first_sent"], x["last_sent"]) != (prop["first_sent"], prop["last_sent"]) for x, _a in group):
            group.append((prop, agrees))
    proposals, duplicates = [], []
    for payoff, group in groups.items():
        group.sort(key=lambda g: (DIRECTIONS.index(g[0]["direction"]), not g[1], g[0]["first_sent"] - g[0]["last_sent"], g[0]["first_sent"]))
        proposals.append(group[0][0])
        if len(group) > 1:
            duplicates.append(
                {
                    "payoff_sent": payoff,
                    "kept": [group[0][0]["first_sent"], group[0][0]["last_sent"]],
                    "dropped": [[g["first_sent"], g["last_sent"]] for g, _a in group[1:]],
                    "reason": "same_payoff",
                }
            )
    proposals.sort(key=lambda x: (x["first_sent"], x["last_sent"]))
    return {"proposals": proposals, "rejected": rejected, "duplicates": duplicates}


# -- Alternative Einstiege (AP6b) -----------------------------------------------------------------


def _same_text(a: str, b: str) -> bool:
    ta, tb = {_core(t) for t in a.split()} - {""}, {_core(t) for t in b.split()} - {""}
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= _SAME_TEXT_JACCARD


def alternative_openings(
    sents: Sequence[Any],
    first: int,
    payoff_idx: int,
    policy: editorial.Policy | None = None,
    gate_fn: Callable[[int], bool] | None = None,
    limit: int = 3,
) -> list[dict]:
    """Bis zu ``limit`` (drei) substanziell verschiedene Originaleinstiege für den Abschnitt ``first`` bis
    ``payoff_idx``: verschiedene Sätze zwischen ``first`` und dem Satz vor dem Payoff, die ``gate_fn``
    bestehen, ihren Kontext selbst mitbringen und im Wortlaut nicht fast gleich sind (Jaccard unter 0,8).
    ``first`` steht vorn, wenn er gültig ist, danach Sätze mit Hook-Typ, danach die übrigen in
    Satzfolge. Je Einstieg ``{opening_sent, hook_type, first_sent, last_sent, duration_s}``. Ohne
    ``policy`` gilt die aktive Fassung."""
    ctx = _ctx(sents, policy or editorial.load())
    gate = gate_fn or _default_gate(ctx)
    a, p = ctx.pos[first], ctx.pos[payoff_idx]
    hit = _payoff_at(ctx, p)
    needs = {ctx.pos[n] for n in (hit["needs_sents"] if hit else ()) if n in ctx.pos}
    valid = []
    for j in range(a, p):
        if any(r < j for r in needs | _context_needs(ctx, j, p)) or not gate(ctx.v[j].idx):
            continue
        hook = _hook_at(ctx, j)
        valid.append((0 if j == a else (1 if hook else 2), j, hook[0] if hook else None))
    out: list[dict] = []
    for _order, j, hook in sorted(valid):
        if any(_same_text(ctx.v[j].text, ctx.v[ctx.pos[o["opening_sent"]]].text) for o in out):
            continue
        out.append(
            {
                "opening_sent": ctx.v[j].idx,
                "hook_type": hook,
                "first_sent": ctx.v[j].idx,
                "last_sent": ctx.v[p].idx,
                "duration_s": round(ctx.duration(j, p), 2),
            }
        )
        if len(out) >= limit:
            break
    return out


# -- Beide Richtungen zusammen ----------------------------------------------------------------------


def _merge_duplicates(ctx: _Ctx, proposals: list[dict]) -> tuple[list[dict], list[dict]]:
    """Gleiche Spanne, gleicher Einstieg mit überlappender Spanne oder fast gleicher Payoff-Text: einer bleibt."""
    kept: list[dict] = []
    duplicates: list[dict] = []
    for prop in sorted(proposals, key=_rank):
        reason = None
        other = None
        for k in kept:
            if (k["first_sent"], k["last_sent"]) == (prop["first_sent"], prop["last_sent"]):
                reason, other = "same_span", k
            elif k["first_sent"] == prop["first_sent"] and not (k["last_sent"] < prop["first_sent"] or prop["last_sent"] < k["first_sent"]):
                reason, other = "same_opening", k
            elif _same_text(ctx.v[ctx.pos[k["payoff_sent"]]].text, ctx.v[ctx.pos[prop["payoff_sent"]]].text):
                reason, other = "same_statement", k
            if reason:
                break
        if reason is None:
            kept.append(prop)
            continue
        duplicates.append(
            {
                "payoff_sent": prop["payoff_sent"],
                "kept": [other["first_sent"], other["last_sent"]],
                "dropped": [[prop["first_sent"], prop["last_sent"]]],
                "reason": reason,
            }
        )
    kept.sort(key=lambda x: (x["first_sent"], x["last_sent"]))
    return kept, duplicates


def search_moments(
    sents: Sequence[Any],
    policy: editorial.Policy,
    heat: Mapping[str, Any] | None = None,
    gate_fn: Callable[[int], bool] | None = None,
) -> dict:
    """Payoff zuerst und Einstieg zuerst (je nach ``search.payoff_first`` und ``search.opening_first``),
    jede Spanne nach dem Payoff verlängert (siehe Moduldoku), dann über ``reconcile`` mit
    ``min_s = laenge.hart_min_s`` abgeglichen; danach werden gleiche Spannen, gleiche Einstiege und fast
    gleiche Aussagen zusammengeführt. Payoffs ohne gültigen Einstieg fallen mit ``no_opening`` heraus.

    Rückgabe ``{proposals, rejected, duplicates, payoffs, openings}``. Schwaches Material (nur
    Organisatorisches oder Füllgespräch, keine Behauptung mit Beleg) hat keinen Payoff und ergibt keinen
    Vorschlag."""
    ctx = _ctx(sents, policy)
    gate = gate_fn or _default_gate(ctx)
    cfg = ctx.cfg
    payoffs = [h for i in range(len(ctx.v)) if (h := _payoff_at(ctx, i, heat)) is not None] if cfg["payoff_first"] else []
    rejected: list[dict] = []
    payoff_first = []
    for hit in payoffs:
        p = ctx.pos[hit["payoff_sent"]]
        needs = {ctx.pos[n] for n in hit["needs_sents"]}
        a = _walk_back(ctx, p, p, p, needs, gate, policy.gut_von_s)
        if a is None:
            rejected.append({"payoff_sent": hit["payoff_sent"], "payoff_type": hit["payoff_type"], "reason": "no_opening"})
            continue
        b = _extend(ctx, a, p, p)
        payoff_first.append({**_span(ctx, a, b, p, needs), "payoff_type": hit["payoff_type"], "evidence_sent": hit["evidence_sent"]})
    openings = _openings(ctx) if cfg["opening_first"] else []
    opening_first = []
    for o in openings:
        a = ctx.pos[o["opening_sent"]]
        fwd = _forward(ctx, a, o["hook_type"], heat)
        if fwd is None:
            opening_first.append({**o, "payoff_sent": None})
            continue
        p = ctx.pos[fwd["payoff_sent"]]
        b = _extend(ctx, a, p, p)
        span = _span(ctx, a, b, p, {ctx.pos[n] for n in (_payoff_at(ctx, p, heat) or {}).get("needs_sents", [])})
        opening_first.append({**o, **fwd, **span})
    res = reconcile(payoff_first, opening_first, min_s=policy.hart_min_s)
    kept, merged = _merge_duplicates(ctx, res["proposals"])
    return {
        "proposals": kept,
        "rejected": rejected + res["rejected"],
        "duplicates": res["duplicates"] + merged,
        "payoffs": payoffs,
        "openings": openings,
    }


__all__ = [
    "BACK_REFERENCE_STARTS",
    "DIRECTIONS",
    "HOOK_FULFILLED_BY",
    "NARRATIVE_TYPES",
    "PAYOFF_TYPES",
    "TYPE_PRIORITY",
    "alternative_openings",
    "backtrack_opening",
    "find_openings",
    "find_payoffs",
    "forward_payoff",
    "narrative_type",
    "opening_defects",
    "reconcile",
    "search_moments",
]
