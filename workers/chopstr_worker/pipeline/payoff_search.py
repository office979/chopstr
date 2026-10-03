"""Deterministische Suche nach Momenten in beide Richtungen (AP5, Master-Prompt Abschnitt 7).

Payoff zuerst: ``find_payoffs`` findet Sätze, die etwas einlösen (Merksatz, Ergebnis mit Zahl, Folge,
Erklärung, Erkenntnis, Auflösung nach Frage, Pointe nach Setup, Lachen in der Heatmap).
``backtrack_opening`` geht vom Payoff rückwärts bis zum frühesten Satz, der als Einstieg taugt und den
nötigen Kontext mitbringt (Definitionen, Bedingungen, Sprecherzuordnung).

Einstieg zuerst: ``find_openings`` findet Sätze mit einem Hook-Typ aus Master-Prompt Abschnitt 9,
``forward_payoff`` prüft, ob das Material diesen Einstieg einlöst.

``reconcile`` gleicht beide Richtungen ab: Treffer aus beiden gelten als ``direction: both``, Einstiege
ohne Einlösung fallen mit ``promise_unfulfilled`` heraus, mehrere Vorschläge zu derselben Aussage
(gleicher ``payoff_sent``) werden als Dublette gemeldet und auf einen reduziert.
``alternative_openings`` liefert für einen Vorschlag bis zu drei verschiedene Originaleinstiege (AP6b).
``search_moments`` führt alles zusammen (Heuristik-Provider, später ``story_engine.run``).

Eingabe sind Sätze als ``segment.Sentence`` oder als Dict mit ``idx``, ``text``, ``speaker``, ``start``
und ``end`` (geschätzte Zeiten sind erlaubt). Alle Satzangaben in Ein- und Ausgabe sind Satznummern
(``idx``), keine Listenpositionen. Wortlisten und Längen kommen aus der Grundlage (``search``,
``einstieg``, ``ausstieg``, ``ausschluss``, ``moment_typen``, ``laenge``); ohne Abschnitt ``search``
(Fassung 1) scheitert die Suche laut.

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
from . import dach_nlp

PAYOFF_TYPES = ("rule", "result", "consequence", "explanation", "lesson", "resolution", "punchline", "laughter")
# Trägt ein Satz mehrere Arten, gilt die spezifischere als ``payoff_type``.
TYPE_PRIORITY = ("punchline", "resolution", "result", "rule", "lesson", "explanation", "consequence", "laughter")
DIRECTIONS = ("both", "payoff_only", "opening_only")
NARRATIVE_TYPES = ("insight", "problem_solution", "story", "demonstration", "debate", "comedy", "how_to")

# Welche Payoff-Arten einen Hook-Typ einlösen: Spalte „Erforderlicher Inhalt“ aus Master-Prompt Abschnitt 9.
HOOK_FULFILLED_BY: dict[str, tuple[str, ...]] = {
    "concrete_contradiction": ("explanation", "consequence", "result", "lesson", "resolution"),  # Auflösung
    "mistake_with_consequence": ("consequence", "result", "lesson", "explanation"),  # Mechanismus, Konsequenz
    "result_with_open_cause": ("explanation", "consequence", "lesson"),  # Erklärung
    "scene_with_stakes": ("result", "lesson", "punchline", "consequence", "resolution", "laughter"),  # Ausgang
    "decision_rule": ("explanation", "consequence", "result", "lesson"),  # Bedingung und Begründung
    "demonstration": ("result", "explanation"),  # sichtbarer Vergleich
    "self_correction": ("lesson", "explanation", "result"),  # tatsächlicher Lernprozess
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
    "explanation": "insight",
}

# -- Reine Textmerkmale (keine redaktionellen Schwellen) ---------------------------------------------
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
W_WORDS = frozenset(
    {"wer", "was", "wie", "wo", "warum", "wieso", "weshalb", "wann", "welche", "welcher", "welches", "welchen",
     "wem", "wen", "wozu", "woran", "wofür", "womit", "wodurch", "woher", "wohin"}
)  # fmt: skip
# Ankündigung eines vorgelesenen oder zitierten Textes: der Folgesatz gehört zu dieser Zuordnung.
QUOTE_ANNOUNCEMENT = re.compile(r"\b(?:les|lese|lesen)\b.*\bvor\b|\bvorlesen\b|\bzitier|:$")
# Erkenntnis-Marker, die auf ein früheres Ereignis zeigen und deshalb den Satz davor brauchen.
BACKWARD_LESSON_MARKERS = frozenset({"seitdem", "seither"})
_LEADING = "\"'„»«“”‘’([{"
_POLITE_VERB_FORMS = frozenset({"sind", "waren", "wären", "seid"})
_MIN_NOUN_LEN = 4
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
    pronouns: frozenset[str] = frozenset()
    qualification: tuple[str, ...] = ()
    merksatz: tuple[str, ...] = ()
    story: tuple[str, ...] = ()
    nouns: list[set[str]] = field(default_factory=list)
    definite: list[list[str]] = field(default_factory=list)

    def duration(self, a: int, b: int) -> float:
        return max(0.0, self.v[b].end - self.v[a].start)

    def organisational(self, i: int) -> bool:
        return self.policy.ist_organisatorisch(self.v[i].text)


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
        out.append(_S(idx=int(get("idx")), text=str(get("text") or ""), speaker=get("speaker"), start=float(start), end=float(end)))
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


def _first_marker(low: str, markers: Iterable[str]) -> str | None:
    return next((m for m in markers if _has(low, m)), None)


def _ctx(sents: Sequence[Any], policy: editorial.Policy) -> _Ctx:
    cfg = _settings(policy)
    v = _views(sents)
    ein = policy.einstieg
    pronouns = frozenset(str(x).lower() for x in (ein.get("pronomen") or ())) if ein.get("keine_pronomen_ohne_bezug") else frozenset()
    qualification = tuple(str(m).lower() for m in (policy.ausstieg.get("abschwaechung_marker") or ()))
    typen = {t.schluessel: t for t in policy.moment_typen}
    ctx = _Ctx(
        policy=policy,
        cfg=cfg,
        v=v,
        pos={s.idx: i for i, s in enumerate(v)},
        pronouns=pronouns,
        qualification=qualification,
        merksatz=typen["merksatz"].marker if "merksatz" in typen else (),
        story=(typen["ministory"].marker if "ministory" in typen else ()) + cfg["hook_type_markers"]["scene_with_stakes"],
    )
    for s in v:
        toks = _tokens(s.text)
        nouns, definite = set(), []
        for k, tok in enumerate(toks):
            core = _core(tok)
            if k == 0 or not _upper(tok) or core in pronouns or core in ("ich", "sie", "ihnen", "ihr") or len(core) < _MIN_NOUN_LEN:
                continue
            nouns.add(core)
            if _core(toks[k - 1]) in DEFINITE_ARTICLES:
                definite.append(core)
        ctx.nouns.append(nouns)
        ctx.definite.append(definite)
    return ctx


# -- Einstieg prüfen ------------------------------------------------------------------------------


def _address(toks: list[str], k: int) -> bool:
    """„Ihr …“ oder förmliches „Sie haben …“: Anrede, kein Pronomen ohne Bezug (wie story_engine)."""
    core = _core(toks[k])
    if core == "ihr":
        return True
    if core != "sie" or not toks[k].lstrip(_LEADING)[:1].isupper() or k + 1 >= len(toks):
        return False
    nxt = _core(toks[k + 1])
    return nxt.endswith("en") or nxt in _POLITE_VERB_FORMS


def _opening_defects(ctx: _Ctx, i: int) -> list[str]:
    toks = _tokens(ctx.v[i].text)
    k = 0
    while k < len(toks) and _core(toks[k]) in dach_nlp.HARD_FILLERS:
        k += 1
    if k >= len(toks):
        return ["leerer Satz"]
    toks = toks[k:]
    first, core = toks[0], _core(toks[0])
    out: list[str] = []
    if not _upper(first):
        out.append(f"Anfang mitten im Satz („{first}“)")
    if core in ctx.pronouns and not _address(toks, 0):
        out.append(f"Pronomen ohne Bezug am Anfang („{first}“)")
    else:
        seen_noun = False
        for k2, tok in enumerate(toks[1:], start=1):
            c = _core(tok)
            if c in ctx.pronouns and c != "ihr" and not _address(toks, k2):
                if not seen_noun:
                    out.append(f"Pronomen ohne Bezug im Einstiegssatz („{tok}“)")
                break
            if _upper(tok):
                seen_noun = True
    head = " ".join(_core(t) for t in toks[:4])
    nxt = toks[1] if len(toks) > 1 else ""
    if (
        core in dach_nlp.OPEN_LOOP_END
        or " ".join(_core(t) for t in toks[:2]) in dach_nlp.OPEN_LOOP_END
        or core in BACK_REFERENCE_STARTS
        or any(head == m or head.startswith(m + " ") for m in ctx.qualification)
        or (core in DEMONSTRATIVES and nxt and not _upper(nxt))
    ):
        out.append(f"Rückverweis am Anfang („{first}“)")
    elif any(p in ctx.v[i].low for p in REFERENCE_PHRASES):
        out.append("Rückverweis im Einstiegssatz")
    return out


def opening_defects(sents: Sequence[Any], sent_no: int, policy: editorial.Policy) -> list[str]:
    """Mängel, wenn ein Clip mit Satz ``sent_no`` beginnt; leer heißt: taugt als Einstieg.

    Geprüft werden Satzanfang (großgeschriebenes erstes Wort nach Füllwörtern aus
    ``dach_nlp.HARD_FILLERS``), Pronomen ohne Bezug (``einstieg.pronomen``, Anrede ausgenommen) und
    Rückverweis (Anschlusswort aus ``dach_nlp.OPEN_LOOP_END`` oder ``BACK_REFERENCE_STARTS``,
    Abschwächung aus ``ausstieg.abschwaechung_marker``, „Das ist …“, „wie gesagt“). Das ist die
    Standard-Prüfung von ``backtrack_opening``; ``story_engine`` kann ``start_defects`` übergeben."""
    ctx = _ctx(sents, policy)
    return _opening_defects(ctx, ctx.pos[sent_no])


def _default_gate(ctx: _Ctx) -> Callable[[int], bool]:
    return lambda sent_no: not _opening_defects(ctx, ctx.pos[sent_no])


def _other_speaker_question(ctx: _Ctx, a: int, p: int) -> bool:
    s = ctx.v[a]
    return s.text.rstrip().endswith("?") and s.speaker != ctx.v[p].speaker


def _context_needs(ctx: _Ctx, a: int, b: int) -> set[int]:
    """Positionen, die ein Abschnitt ``a`` bis ``b`` als Kontext braucht, ohne die Payoff-Art.

    Sprecherzuordnung: kündigt der Satz vor ``a`` einen vorgelesenen oder zitierten Text an, gehört er
    dazu. Definitionen: ein Nomen mit bestimmtem Artikel, das vor ``a`` eingeführt und im Abschnitt
    davor nicht wieder genannt wurde, braucht den Satz der letzten Nennung, solange er innerhalb von
    ``laenge.hart_max_s`` liegt."""
    needs: set[int] = set()
    if a > 0 and QUOTE_ANNOUNCEMENT.search(ctx.v[a - 1].low.rstrip()):
        needs.add(a - 1)
    for k in range(a, b + 1):
        for noun in ctx.definite[k]:
            if any(noun in ctx.nouns[m] for m in range(a, k)):
                continue
            j = next((m for m in range(a - 1, -1, -1) if noun in ctx.nouns[m]), None)
            if j is not None and ctx.duration(j, b) <= ctx.policy.hart_max_s:
                needs.add(j)
    return needs


# -- Payoff finden --------------------------------------------------------------------------------


def _laughter_after(heat: Mapping[str, Any] | None, s: _S) -> bool:
    """Lachen in der Heatmap (``heat["laughter"]`` je Bin) im Bin des Satzendes oder im nächsten."""
    if not heat or not heat.get("laughter"):
        return False
    bin_s = float(heat.get("bin_s") or 1.0) or 1.0
    values = heat["laughter"]
    b = int(s.end / bin_s)
    return any(float(x) > 0 for x in values[max(0, b) : b + 2])


def _payoff_at(ctx: _Ctx, i: int, heat: Mapping[str, Any] | None = None) -> dict | None:
    s = ctx.v[i]
    if not s.text.strip() or s.text.rstrip().endswith("?") or ctx.organisational(i):
        return None
    low = s.low
    markers = ctx.cfg["payoff_markers"]
    found: dict[str, tuple[int, str, tuple[int, ...]]] = {}  # Art: (Beleg-Position, Marker, Kontext)

    m = _first_marker(low, markers["rule"]) or next((x for x in ctx.merksatz if x in low), None)
    if m:
        found["rule"] = (i, m, ())
    zahl = next((t for t in ctx.policy.moment_typen if t.schluessel == "zahl"), None)
    if zahl is not None and zahl.trifft(low):
        found["result"] = (i, "zahl", ())
    prev = (i - 1,) if i > 0 and not ctx.organisational(i - 1) else ()
    for typ in ("consequence", "explanation", "lesson"):
        m = _first_marker(low, markers[typ])
        if m:
            needs = prev if typ != "lesson" or m in BACKWARD_LESSON_MARKERS else ()
            found[typ] = (i, m, needs)
    if i > 0:
        q = ctx.v[i - 1]
        if q.text.rstrip().endswith("?") and not ctx.organisational(i - 1) and any(_core(t) in W_WORDS for t in _tokens(q.text)):
            found["resolution"] = (i - 1, "frage", (i - 1,))
    for noun in ctx.definite[i]:
        if any(noun in ctx.nouns[m2] for m2 in range(max(0, i - 1), i)):
            continue
        j = next((m2 for m2 in range(i - 2, -1, -1) if noun in ctx.nouns[m2]), None)
        if j is None:
            continue
        if any(_has(ctx.v[j].low, x) for x in ctx.story):
            found["punchline"] = (j, noun, (j,))
            break
    if _laughter_after(heat, s):
        found["laughter"] = (i, "lachen", ())
    if not found:
        return None
    primary = next(t for t in TYPE_PRIORITY if t in found)
    evidence, marker, _needs = found[primary]
    needs = sorted({ctx.v[n].idx for _e, _m, ns in found.values() for n in ns})
    return {
        "payoff_sent": s.idx,
        "payoff_type": primary,
        "evidence_sent": ctx.v[evidence].idx,
        "marker": marker,
        "types": [t for t in TYPE_PRIORITY if t in found],
        "needs_sents": needs,
    }


def find_payoffs(sents: Sequence[Any], policy: editorial.Policy, heat: Mapping[str, Any] | None = None) -> list[dict]:
    """Sätze, die etwas einlösen, je mit ``payoff_type`` und Beleg-Satznummer ``evidence_sent``.

    Arten: ``rule`` (Merksatz, ``search.payoff_markers.rule`` und ``moment_typen.merksatz``),
    ``result`` (Ergebnis mit Zahl, ``moment_typen.zahl``), ``consequence`` („deshalb“), ``explanation``
    („das heißt“, „der Grund ist“), ``lesson`` („gelernt“, „seitdem“), ``resolution`` (Antwort auf eine
    W-Frage im Satz davor; Beleg ist die Frage), ``punchline`` (Pointe: ein Nomen mit bestimmtem
    Artikel greift ein Setup von mindestens zwei Sätzen davor auf, und das Setup eröffnet eine
    erzählte Szene, ``moment_typen.ministory`` oder ``hook_type_markers.scene_with_stakes``;
    Beleg ist das Setup), ``laughter`` (Lachen aus ``heat["laughter"]``, nur wenn die Heatmap es liefert).
    Fragen und organisatorische Sätze (``ausschluss.organisations_marker``) sind nie Payoff.
    ``needs_sents`` nennt die Sätze, ohne die der Payoff nicht verständlich ist."""
    ctx = _ctx(sents, policy)
    return [hit for i in range(len(ctx.v)) if (hit := _payoff_at(ctx, i, heat)) is not None]


# -- Payoff zuerst: rückwärts zum Einstieg ----------------------------------------------------------


def _backtrack(ctx: _Ctx, p: int, needs: set[int], gate: Callable[[int], bool]) -> dict | None:
    pol = ctx.policy
    best: tuple[int, set[int], float] | None = None
    for a in range(p, -1, -1):
        if a < p and (ctx.organisational(a) or (_other_speaker_question(ctx, a, p) and a not in needs)):
            break
        dur = ctx.duration(a, p)
        if dur > pol.hart_max_s:
            break
        req = needs | _context_needs(ctx, a, p)
        if any(r < a for r in req) or not gate(ctx.v[a].idx):
            continue
        best = (a, req, dur)
        if dur >= pol.hart_min_s:
            break
    if best is None:
        return None
    a, req, dur = best
    return {
        "opening_sent": ctx.v[a].idx,
        "payoff_sent": ctx.v[p].idx,
        "first_sent": ctx.v[a].idx,
        "last_sent": ctx.v[p].idx,
        "required_context_sents": sorted(ctx.v[r].idx for r in req if a <= r < p),
        "duration_s": round(dur, 2),
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

    ``gate_fn(satznummer) -> bool``; Standard ist ``opening_defects`` leer (kein Pronomen ohne Bezug,
    kein Rückverweis, Satzanfang). Kontext sind ``needs`` (Satznummern, Standard: die ``needs_sents``
    des Payoffs) und ``_context_needs`` (Sprecherzuordnung, Definitionen). Der Rückweg geht, bis der
    Abschnitt ``laenge.hart_min_s`` erreicht, und endet an ``laenge.hart_max_s``, an einem
    organisatorischen Satz und an der Frage eines anderen Sprechers, die nicht zum Kontext gehört.
    Wird ``hart_min_s`` nicht erreicht, gilt der früheste gültige Einstieg (``duration_s`` sagt es).
    Rückgabe ``{opening_sent, payoff_sent, first_sent, last_sent, required_context_sents, duration_s}``
    oder ``None``, wenn kein Einstieg mit vollständigem Kontext existiert."""
    ctx = _ctx(sents, policy)
    p = ctx.pos[payoff_idx]
    if needs is None:
        hit = _payoff_at(ctx, p)
        needs = hit["needs_sents"] if hit else ()
    need_pos = {ctx.pos[n] for n in needs if n in ctx.pos}
    return _backtrack(ctx, p, need_pos, gate_fn or _default_gate(ctx))


# -- Einstieg zuerst: vorwärts zum Payoff -----------------------------------------------------------


def _hook_at(ctx: _Ctx, i: int) -> tuple[str, str] | None:
    low = ctx.v[i].low
    for hook_type in editorial.SEARCH_HOOK_TYPES:
        m = _first_marker(low, ctx.cfg["hook_type_markers"][hook_type])
        if m:
            return hook_type, m
    return None


def find_openings(sents: Sequence[Any], policy: editorial.Policy) -> list[dict]:
    """Sätze mit einem Hook-Typ aus Master-Prompt Abschnitt 9 (``search.hook_type_markers``, origin H),
    die als Einstieg taugen (``opening_defects`` leer, nicht organisatorisch).

    Rückgabe je Treffer ``{opening_sent, hook_type, marker}``; ob eingelöst wird, sagt ``forward_payoff``."""
    ctx = _ctx(sents, policy)
    out = []
    for i, s in enumerate(ctx.v):
        if ctx.organisational(i):
            continue
        hit = _hook_at(ctx, i)
        if hit and not _opening_defects(ctx, i):
            out.append({"opening_sent": s.idx, "hook_type": hit[0], "marker": hit[1]})
    return out


def forward_payoff(
    sents: Sequence[Any],
    opening_idx: int,
    policy: editorial.Policy,
    hook_type: str | None = None,
    heat: Mapping[str, Any] | None = None,
) -> dict | None:
    """Löst das Material den Einstieg ``opening_idx`` ein? Erster Payoff nach dem Einstieg, dessen Art
    zum Hook-Typ passt (``HOOK_FULFILLED_BY``), bevorzugt der erste, mit dem der Abschnitt
    ``laenge.hart_min_s`` erreicht; Ende an ``laenge.hart_max_s`` und an einem organisatorischen Satz.

    Rückgabe ``{opening_sent, hook_type, payoff_sent, payoff_type, evidence_sent, first_sent, last_sent,
    required_context_sents, missing_context_sents, duration_s}`` oder ``None`` (Versprechen nicht
    eingelöst). ``missing_context_sents`` sind nötige Sätze vor dem Einstieg."""
    ctx = _ctx(sents, policy)
    a = ctx.pos[opening_idx]
    if hook_type is None:
        hit = _hook_at(ctx, a)
        hook_type = hit[0] if hit else None
    accepted = set(HOOK_FULFILLED_BY.get(hook_type or "", PAYOFF_TYPES))
    first_hit = None
    for b in range(a + 1, len(ctx.v)):
        if ctx.organisational(b):
            break
        dur = ctx.duration(a, b)
        if dur > policy.hart_max_s:
            break
        pay = _payoff_at(ctx, b, heat)
        matching = [t for t in (pay or {}).get("types", []) if t in accepted]
        if not matching:
            continue
        req = {ctx.pos[n] for n in pay["needs_sents"]} | _context_needs(ctx, a, b)
        cand = {
            "opening_sent": ctx.v[a].idx,
            "hook_type": hook_type,
            "payoff_sent": ctx.v[b].idx,
            "payoff_type": matching[0],
            "evidence_sent": pay["evidence_sent"],
            "first_sent": ctx.v[a].idx,
            "last_sent": ctx.v[b].idx,
            "required_context_sents": sorted(ctx.v[r].idx for r in req if a <= r < b),
            "missing_context_sents": sorted(ctx.v[r].idx for r in req if r < a),
            "duration_s": round(dur, 2),
        }
        if first_hit is None:
            first_hit = cand
        if dur >= policy.hart_min_s:
            return cand
    return first_hit


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


def reconcile(payoff_first: Sequence[Mapping[str, Any]], opening_first: Sequence[Mapping[str, Any]]) -> dict:
    """Beide Suchrichtungen abgleichen.

    ``payoff_first``: Einträge mit ``payoff_sent``, ``opening_sent``, ``first_sent``, ``last_sent``
    (aus ``backtrack_opening`` plus ``payoff_type``). ``opening_first``: Einträge aus ``find_openings``,
    ergänzt um das Ergebnis von ``forward_payoff`` (``payoff_sent`` ``None`` heißt nicht eingelöst).

    * Gleicher Payoff aus beiden Richtungen: ``direction: both``. Je passendem Einstieg entsteht eine
      Variante ab diesem Einstieg, wenn er seinen Kontext selbst mitbringt, sonst ab dem Einstieg der
      Payoff-Suche.
    * Payoff ohne passenden Einstieg: ``payoff_only``; Einstieg mit Einlösung, die die Payoff-Suche
      nicht hat: ``opening_only`` (fehlt Kontext vor dem Einstieg: verworfen, ``context_missing``).
    * Einstieg ohne Einlösung: verworfen, ``promise_unfulfilled``.
    * Mehrere Vorschläge zur selben Aussage (gleicher ``payoff_sent``) sind Dubletten: einer bleibt
      (``both`` vor ``payoff_only`` vor ``opening_only``, dann der Einstieg der Payoff-Suche, dann der
      kürzere), die anderen stehen in ``duplicates``.

    Rückgabe ``{proposals, rejected, duplicates}``, Vorschläge nach Satznummer sortiert."""
    rejected: list[dict] = []
    by_payoff = {int(p["payoff_sent"]): p for p in payoff_first}
    matched: dict[int, list[Mapping[str, Any]]] = {}
    variants: list[tuple[dict, bool]] = []  # (Vorschlag, Einstieg der Payoff-Suche)
    for o in opening_first:
        if o.get("payoff_sent") is None:
            rejected.append({"opening_sent": int(o["opening_sent"]), "hook_type": o.get("hook_type"), "reason": "promise_unfulfilled"})
        elif int(o["payoff_sent"]) in by_payoff:
            matched.setdefault(int(o["payoff_sent"]), []).append(o)
        elif o.get("missing_context_sents"):
            rejected.append({"opening_sent": int(o["opening_sent"]), "hook_type": o.get("hook_type"), "reason": "context_missing"})
        else:
            variants.append((_proposal(o, "opening_only", o.get("hook_type"), o.get("payoff_type")), False))
    for payoff, p in by_payoff.items():
        os_ = matched.get(payoff, [])
        inside = next((o for o in os_ if int(p["first_sent"]) <= int(o["opening_sent"]) <= payoff), None)
        hook = (inside or (os_[0] if os_ else {})).get("hook_type")
        variants.append((_proposal(p, "both" if os_ else "payoff_only", hook, p.get("payoff_type")), True))
        for o in os_:
            if o.get("missing_context_sents"):
                continue
            span = {**p, "first_sent": o["opening_sent"], "opening_sent": o["opening_sent"],
                    "duration_s": o.get("duration_s"), "required_context_sents": o.get("required_context_sents")}  # fmt: skip
            variants.append((_proposal(span, "both", o.get("hook_type"), p.get("payoff_type")), int(o["opening_sent"]) == int(p["opening_sent"])))

    groups: dict[int, list[tuple[dict, bool]]] = {}
    for prop, agrees in variants:
        group = groups.setdefault(prop["payoff_sent"], [])
        if all((x["first_sent"], x["last_sent"]) != (prop["first_sent"], prop["last_sent"]) for x, _a in group):
            group.append((prop, agrees))
    proposals, duplicates = [], []
    for payoff, group in groups.items():
        group.sort(key=lambda g: (DIRECTIONS.index(g[0]["direction"]), not g[1], g[0]["last_sent"] - g[0]["first_sent"], g[0]["first_sent"]))
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
    Satzfolge. Je Einstieg ``{opening_sent, hook_type, first_sent, last_sent, duration_s}``."""
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
    for _rank, j, hook in sorted(valid):
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


def search_moments(
    sents: Sequence[Any],
    policy: editorial.Policy,
    heat: Mapping[str, Any] | None = None,
    gate_fn: Callable[[int], bool] | None = None,
) -> dict:
    """Payoff zuerst und Einstieg zuerst (je nach ``search.payoff_first`` und ``search.opening_first``),
    abgeglichen über ``reconcile``. Vorschläge unter ``laenge.hart_min_s`` werden mit ``too_short``
    verworfen, Payoffs ohne gültigen Einstieg mit ``no_opening``.

    Rückgabe ``{proposals, rejected, duplicates, payoffs, openings}``. Schwaches Material (nur
    Organisatorisches, keine Behauptung mit Beleg) hat keinen Payoff und ergibt keinen Vorschlag."""
    ctx = _ctx(sents, policy)
    gate = gate_fn or _default_gate(ctx)
    cfg = ctx.cfg
    payoffs = [h for i in range(len(ctx.v)) if (h := _payoff_at(ctx, i, heat)) is not None] if cfg["payoff_first"] else []
    rejected: list[dict] = []
    payoff_first = []
    for hit in payoffs:
        p = ctx.pos[hit["payoff_sent"]]
        back = _backtrack(ctx, p, {ctx.pos[n] for n in hit["needs_sents"]}, gate)
        if back is None:
            rejected.append({"payoff_sent": hit["payoff_sent"], "payoff_type": hit["payoff_type"], "reason": "no_opening"})
            continue
        payoff_first.append({**back, "payoff_type": hit["payoff_type"], "evidence_sent": hit["evidence_sent"]})
    openings = find_openings(sents, policy) if cfg["opening_first"] else []
    opening_first = []
    for o in openings:
        fwd = forward_payoff(sents, o["opening_sent"], policy, o["hook_type"], heat)
        opening_first.append({**o, **(fwd or {"payoff_sent": None})})
    res = reconcile(payoff_first, opening_first)
    kept = []
    for prop in res["proposals"]:
        dur = ctx.duration(ctx.pos[prop["first_sent"]], ctx.pos[prop["last_sent"]])
        if dur < policy.hart_min_s:
            rejected.append({"first_sent": prop["first_sent"], "last_sent": prop["last_sent"], "payoff_sent": prop["payoff_sent"], "reason": "too_short", "duration_s": round(dur, 2)})
        else:
            kept.append(prop)
    return {
        "proposals": kept,
        "rejected": rejected + res["rejected"],
        "duplicates": res["duplicates"],
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
