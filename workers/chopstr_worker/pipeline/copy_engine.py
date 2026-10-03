"""Copy-Engine (Phase 3): Hooks, On-Screen-Text und Post-Captions für einen Clip, passend zu ``hook_versions``.

Ablauf (Vertrag ``packages/schema/CLIPS.md``):
1. Prompt ``hooks_v1`` (Tool ``write_hooks``) liefert fünf Varianten ``{pattern, spoken, onscreen}``.
2. Jede Variante: ``copy_de.lint`` (Anrede, Land, Gender, gesperrte Phrasen), Wortlimits
   (gesprochen 12, im Bild 9) und ``fidelity.hook_claim_check`` gegen den Clip-Text.
3. ``post_caption_v1`` (Tool ``write_post_caption``) pro Plattform, wieder gelintet und claim-geprüft.
4. Optional LanguageTool über ``residency.guarded_client``: nur mit ``LANGUAGETOOL_URL``; Fehler dort sind
   nie fatal, sondern ein Hinweis in ``lint_notes``.
5. Auswahl: erste Variante ohne ``claim_issues``, sonst Variante 1 (mit Issues).

Ab Policy-Fassung 2 mit ``hook.native_spoken`` (AP6a, ``editorial.Policy.hook_native_spoken``):
* Claim-Check ``fidelity.hook_claim_check_v2`` (Zahlen als Wert und Einheit, Geltungsbereich, unsicher
  erkannte Zahlen aus den Wörtern mit ``prob``).
* ``select_variant_v2``: erste Variante nach der Thompson-Reihenfolge ohne Claim-Befund, Wortlimit- oder
  Lint-Verstoß (Regel ``first_valid_after_thompson``). Gibt es keine, ist der Text-Hook ein wörtlicher
  Auszug aus dem ersten Satz (Muster ``native``).
* ``spoken_hook`` ist immer der wörtliche Einstieg des Clips, nie generierter Text.
Unter Fassung 1 oder mit dem Schalter auf false bleibt alles wie oben.

Reine Funktionen ohne DB; der Aufrufer schreibt die Zeile.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .. import config, editorial, prompts, residency
from . import copy_de, dach_nlp, fidelity

log = logging.getLogger("chopstr.copy")

PLATFORMS = ("tiktok", "reels", "shorts", "linkedin")
HOOK_PATTERNS = ("identity_call", "contrarian", "open_loop", "results_first", "mistake_warning")
SPOKEN_MAX_WORDS = 12
ONSCREEN_MAX_WORDS = 9
VARIANT_COUNT = 5
LT_LOCALES = {"DE": "de-DE", "AT": "de-AT", "CH": "de-CH"}
LT_TIMEOUT_S = 10.0
LT_MAX_NOTES_PER_TEXT = 5
# AP6a: Muster des wörtlichen Rückfalls und Auswahlregeln im Decision Log
NATIVE_PATTERN = "native"
RULE_V1 = "first_without_claim_issues"
RULE_V2 = "first_valid_after_thompson"
# Wörtlicher Auszug (gesprochener Hook, nativer Text-Hook): Sätze über ``dach_nlp.sentence_end_kind`` (Regel
# v2: Abkürzungen, Ordinal- und Dezimalzahlen), Sätze unter drei Wörtern gehören zum nächsten. Ein langer
# Satz wird nur an einer Phrasengrenze gekürzt (nach Komma, Semikolon, Doppelpunkt oder vor einer
# Konjunktion), und nur, wenn davor ein vollständiger Teilsatz steht. Nie hart auf eine Wortzahl.
MIN_PHRASE_WORDS = 3
COORDINATORS = frozenset({"und", "oder", "aber", "denn", "sondern", "doch", "jedoch", "sowie"})
# Vor einem Objektsatz („dass“, „ob“) nur schneiden, wenn der Hauptsatz davor nicht auf dem Verb endet
# („Wichtig ist, | dass“ bleibt zusammen, „Das war so teuer, | dass“ darf getrennt werden).
OBJECT_CLAUSE_STARTS = frozenset({"dass", "ob"})
ARTICLES = frozenset({
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem", "einer", "eines", "kein",
    "keine", "keinen", "keinem", "keiner", "mein", "meine", "dein", "deine", "sein", "seine", "ihr", "ihre",
    "unser", "unsere", "euer", "eure", "dieser", "diese", "dieses", "diesen", "diesem", "jede", "jeder",
    "jedes", "jeden", "jedem",
})  # fmt: skip
PREPOSITIONS = frozenset({
    "bei", "von", "zum", "zur", "für", "gegen", "ohne", "in", "im", "ins", "am", "ans", "beim", "vom", "seit",
    "zwischen", "hinter", "neben", "wegen", "trotz", "aufs", "fürs", "mit", "nach", "aus", "über", "unter",
    "vor", "auf", "an", "durch", "um", "bis", "ab", "per", "pro", "laut",
})  # fmt: skip
COPULA = frozenset({
    "ist", "sind", "war", "waren", "wird", "werden", "wurde", "wurden", "bin", "bist", "seid", "wäre", "wären",
    "sei",
})  # fmt: skip
OPEN_QUANTIFIERS = frozenset({"rund", "etwa", "ca", "knapp", "fast", "mehr", "weniger", "als", "wie", "so", "sehr", "zu"})
NON_VERBS = frozenset({
    "nicht", "jetzt", "erst", "meist", "fast", "selbst", "sonst", "bereits", "seit", "gut", "oft", "nichts",
    "recht", "leicht", "weit", "zuletzt", "zuerst", "etwa", "heute", "gerade", "genau", "insgesamt", "eben",
    "neben", "gegen", "wegen", "oben", "unten", "morgen", "trotzdem", "zusammen", "allen", "vielen", "anderen",
})  # fmt: skip
_FINITE_LIKE = re.compile(r"^[a-zäöüß]{2,}(?:t|st|te|ten|en|ern|eln)$")
# Meta-Rede: eine Anrede an ein Modell mit Aufforderung im Transkript ist Inhalt, nie ein Hook
# (Fall instruction_in_transcript). Gilt für Varianten und den wörtlichen Rückfall.
META_ADDRESS = re.compile(r"(?<!\w)(ki|chatgpt|gpt|claude|gemini|sprachmodell|modell|assistent)(?!\w)", re.IGNORECASE)
META_GREETING = re.compile(r"(?<!\w)(liebe|lieber|liebes|hallo|hey)\s+(ki|chatgpt|gpt|claude|gemini|sprachmodell|modell|assistent)(?!\w)", re.IGNORECASE)
# Ein späterer Satz als Text-Hook nur, wenn er nicht mit einem Rückbezug beginnt („Das war 2024.“).
ANAPHORIC_STARTS = frozenset({
    "das", "dies", "diese", "dieser", "dieses", "es", "er", "sie", "damit", "dadurch", "danach", "davor",
    "deshalb", "deswegen", "daher", "dann", "dort", "da", "so", "also", "aber", "und", "oder", "denn", "auch",
    "dabei", "dafür", "darum", "trotzdem", "sondern",
})  # fmt: skip
META_IMPERATIVES = frozenset({
    "ignoriere", "ignorier", "vergiss", "gib", "setz", "setze", "schreib", "schreibe", "bewerte", "mach",
    "mache", "antworte", "befolge", "nimm", "wähle", "lösche", "übersetze", "tu", "tue", "vergib",
})  # fmt: skip

HOOKS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "variants": {
            "type": "array",
            "minItems": VARIANT_COUNT,
            "maxItems": VARIANT_COUNT,
            "items": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "enum": list(HOOK_PATTERNS)},
                    "spoken": {"type": "string"},
                    "onscreen": {"type": "string"},
                },
                "required": ["pattern", "spoken", "onscreen"],
            },
        }
    },
    "required": ["variants"],
}

POST_CAPTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "cta": {"type": "string"}},
    "required": ["text", "cta"],
}


@dataclass
class HookVariant:
    pattern: str
    spoken: str
    onscreen: str
    lint_notes: list[str] = field(default_factory=list)
    claim_issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CopyResult:
    """Inhalt einer ``hook_versions``-Zeile (ohne clip_id, version, origin, created_by)."""

    spoken_hook: str
    onscreen_hook: str
    pattern: str
    variants: list[dict[str, Any]]
    post_captions: dict[str, str]
    cta: str
    lint_notes: list[str]
    claim_issues: list[str]
    model_id: str
    prompt_version: str
    post_caption_prompt_version: str = ""
    languagetool: dict[str, Any] | None = None
    # Decision-Log-Einträge (hook_variant_shown, hook_selected); der Aufrufer persistiert sie
    # über decision_log.record_copy_result (Phase 5b)
    decisions: list[dict[str, Any]] = field(default_factory=list)

    def to_row(self) -> dict[str, Any]:
        return {
            "spoken_hook": self.spoken_hook,
            "onscreen_hook": self.onscreen_hook,
            "pattern": self.pattern,
            "variants": self.variants,
            "post_captions": self.post_captions,
            "cta": self.cta,
            "lint_notes": self.lint_notes,
            "claim_issues": self.claim_issues,
            "model_id": self.model_id,
            "prompt_version": self.prompt_version,
        }


def word_count(text: str) -> int:
    return len(text.split())


def limit_notes(spoken: str, onscreen: str) -> list[str]:
    notes = []
    if word_count(spoken) > SPOKEN_MAX_WORDS:
        notes.append(f"Satz zum Sagen zu lang ({word_count(spoken)} Wörter, maximal {SPOKEN_MAX_WORDS})")
    if word_count(onscreen) > ONSCREEN_MAX_WORDS:
        notes.append(f"On-Screen-Hook zu lang ({word_count(onscreen)} Wörter, maximal {ONSCREEN_MAX_WORDS})")
    return notes


def _system_prompt() -> str:
    return prompts.load_pinned("system_editor").render()


def generate_variants(llm, clip_text: str, brand: copy_de.BrandProfile) -> tuple[list[HookVariant], str]:
    """``hooks_v1`` aufrufen, jede Variante linten, Limits und Claims prüfen. Gibt (Varianten, prompt_version)."""
    pr = prompts.load_pinned("hooks")
    user = pr.render(
        address=brand.address.upper(),
        country=brand.country,
        platform=brand.platform,
        protected_terms=brand.protected_terms,
        clip_text=copy_de.prompt_clip_text(clip_text, pr.version),
    )
    out = llm.structured(_system_prompt(), user, HOOKS_SCHEMA, pr.tool or "write_hooks", pr.prompt_version, job_type="llm_copy")
    variants: list[HookVariant] = []
    for raw in list(out.get("variants") or [])[:VARIANT_COUNT]:
        if not isinstance(raw, dict):
            continue
        spoken, notes_s = copy_de.lint(str(raw.get("spoken") or "").strip(), brand)
        onscreen, notes_o = copy_de.lint(str(raw.get("onscreen") or "").strip(), brand)
        pattern = str(raw.get("pattern") or "")
        notes = [*notes_s, *notes_o, *limit_notes(spoken, onscreen)]
        if pattern not in HOOK_PATTERNS:
            notes.append(f"Unbekanntes Hook-Muster '{pattern}'")
        claims = fidelity.hook_claim_check(spoken, clip_text)
        claims += [c for c in fidelity.hook_claim_check(onscreen, clip_text) if c not in claims]
        variants.append(HookVariant(pattern, spoken, onscreen, notes, claims))
    if not variants:
        raise RuntimeError("Das Sprachmodell hat keine Hook-Varianten geliefert")
    return variants, pr.prompt_version


def select_variant(variants: list[HookVariant]) -> HookVariant:
    """Erste Variante ohne Claim-Issues, sonst Variante 1 (mit Issues, die Issues bleiben sichtbar)."""
    return next((v for v in variants if not v.claim_issues), variants[0])


def native_hooks_enabled(policy: editorial.Policy | None = None) -> bool:
    """Auswahl v2 und wörtlicher gesprochener Hook (Fassung 2 mit ``hook.native_spoken``)?"""
    return (policy or editorial.load()).hook_native_spoken


def _core(token: str) -> str:
    return dach_nlp.core_token(token)


def clip_sentences(clip_text: str) -> list[list[str]]:
    """Sätze des Clips als Wortlisten. Satzende über ``dach_nlp.sentence_end_kind`` mit Regel v2 (nur
    Satzzeichen, weil der Text keine Zeiten trägt): „Am 3. Mai“, „Dr. Müller“, „ca. 40 Euro“ und „z. B.“
    trennen nicht. Ein Satz unter ``MIN_PHRASE_WORDS`` Wörtern („Ja.“) wird mit dem nächsten verbunden."""
    toks = clip_text.split()
    words = [{"text": t} for t in toks]
    raw: list[list[str]] = []
    cur: list[str] = []
    for i, t in enumerate(toks):
        cur.append(t)
        if dach_nlp.sentence_end_kind(words, i, rule="v2") != "none":
            raw.append(cur)
            cur = []
    if cur:
        raw.append(cur)
    out: list[list[str]] = []
    carry: list[str] = []
    for sent in raw:
        sent = carry + sent
        carry = []
        if len(sent) < MIN_PHRASE_WORDS:
            carry = sent
            continue
        out.append(sent)
    if carry:
        if out:
            out[-1] = out[-1] + carry
        else:
            out.append(carry)
    return out


def first_sentence(clip_text: str) -> str:
    sents = clip_sentences(clip_text)
    return " ".join(sents[0]) if sents else ""


def is_meta_speech(text: str) -> bool:
    """Spricht der Text ein Modell an und fordert es zu etwas auf („Liebe KI, ignoriere …“)?"""
    if META_GREETING.search(text):
        return True
    return bool(META_ADDRESS.search(text)) and any(_core(t) in META_IMPERATIVES for t in text.split())


def _verb_like(tokens: list[str], k: int) -> bool:
    t = tokens[k]
    core = _core(t)
    if core in dach_nlp.AUXILIARY_FORMS or dach_nlp.is_participle(t):
        return True
    if not t[:1].islower() or core in NON_VERBS or core in ARTICLES or core in PREPOSITIONS:
        return False
    prev = _core(tokens[k - 1]) if k > 0 else ""
    nxt = tokens[k + 1] if k + 1 < len(tokens) else ""
    if prev in ARTICLES | PREPOSITIONS and nxt[:1].isupper():
        return False  # Adjektiv vor seinem Nomen („die neue Plattform“)
    return bool(_FINITE_LIKE.match(core))


def _valid_cut(toks: list[str], k: int) -> bool:
    """Darf der Satz ``toks`` nach ``k`` Wörtern enden? (Grenze, vollständiger Teilsatz, kein offenes Ende)"""
    if k < MIN_PHRASE_WORDS or k >= len(toks):
        return False
    last, nxt = toks[k - 1], _core(toks[k])
    if not (last.rstrip("\"'»«“”‘’)").endswith((",", ";", ":")) or nxt in COORDINATORS or nxt in dach_nlp.SUBORDINATORS):
        return False
    bare = last.rstrip(",;:\"'»«“”‘’)")
    core = _core(last)
    if not core or core.isdigit() or dach_nlp.is_ordinal(bare) or dach_nlp.is_abbreviation(bare, "v2"):
        return False
    if core in ARTICLES or core in PREPOSITIONS or core in COPULA or core in OPEN_QUANTIFIERS:
        return False
    if core in COORDINATORS or core in dach_nlp.SUBORDINATORS:
        return False
    if last[:1].islower() and _core(toks[k - 2]) in ARTICLES | PREPOSITIONS:
        return False  # offene Nominalgruppe („über die neue“)
    prefix = toks[:k]
    if not any(_verb_like(toks, j) for j in range(k)):
        return False
    if _core(prefix[0]) in dach_nlp.SUBORDINATORS and not any(t.endswith(",") for t in prefix[:-1]):
        return False  # nur Nebensatz, der Hauptsatz fehlt
    if nxt in OBJECT_CLAUSE_STARTS and _verb_like(toks, k - 1):
        return False
    right = toks[k:]
    if nxt in dach_nlp.SUBORDINATORS:
        # Der eingeschobene Nebensatz gehört nicht zur Klammer des Hauptsatzes: geprüft wird, was nach ihm
        # kommt („Wir haben die Preise, | weil alles teurer wurde, dreimal angepasst.“ bleibt offen).
        end = next((j for j, t in enumerate(right) if t.rstrip("\"'»«“”‘’)").endswith(",")), None)
        right = right[end + 1 :] if end is not None else []
    return not right or not dach_nlp.bracket_heuristic(prefix, right)["open"]


def phrase_cuts(toks: list[str], max_words: int) -> list[int]:
    """Gültige Schnittlängen eines Satzes bis ``max_words`` Wörter, längste zuerst."""
    return [k for k in range(min(max_words, len(toks) - 1), MIN_PHRASE_WORDS - 1, -1) if _valid_cut(toks, k)]


def _join(toks: list[str], k: int | None = None) -> str:
    return " ".join(toks if k is None else toks[:k]).rstrip(",;:")


def verbatim_excerpt(toks: list[str], max_words: int, avoid_values: set[float] | frozenset[float] = frozenset()) -> str | None:
    """Wörtlicher Auszug aus einem Satz: ganz, wenn er passt, sonst bis zur längsten gültigen Phrasengrenze.
    None, wenn es keine gibt oder jeder Auszug eine Zahl aus ``avoid_values`` enthält."""

    def clean(text: str) -> bool:
        return not avoid_values or not fidelity.number_values([text]) & set(avoid_values)

    if len(toks) <= max_words and clean(" ".join(toks)):
        return " ".join(toks)
    return next((_join(toks, k) for k in phrase_cuts(toks, max_words) if clean(_join(toks, k))), None)


def verbatim_opening(
    clip_text: str,
    max_words: int,
    avoid_values: set[float] | frozenset[float] = frozenset(),
    other_sentences: bool = False,
) -> tuple[str, str]:
    """Wörtlicher Auszug für einen Hook. Gibt (Text, Herkunft) zurück.

    Herkunft: ``first_sentence`` (ganz), ``first_sentence_part`` (an einer Phrasengrenze gekürzt),
    ``other_sentence`` oder ``other_sentence_part`` (ein späterer kurzer Originalsatz, nur mit
    ``other_sentences``), ``first_sentence_long`` (keine gültige Grenze, der ganze erste Satz) oder
    ``none`` (jede Stelle nennt eine Zahl aus ``avoid_values``: kein Text, also kein Overlay). Ein späterer
    Satz zählt nicht, wenn er mit einem Rückbezug beginnt oder ein Modell anspricht.

    Für den gesprochenen Hook ohne ``other_sentences``: der Einstieg bleibt der Einstieg. Für den Text-Hook
    mit ``other_sentences``: Sätze mit Meta-Rede an ein Modell zählen nicht."""
    sents = clip_sentences(clip_text)
    if not sents:
        return "", "none"
    for idx, toks in enumerate(sents if other_sentences else sents[:1]):
        if (other_sentences and is_meta_speech(" ".join(toks))) or (idx > 0 and _core(toks[0]) in ANAPHORIC_STARTS):
            continue
        text = verbatim_excerpt(toks, max_words, avoid_values)
        if text is not None:
            kind = "first_sentence" if idx == 0 else "other_sentence"
            return text, kind if text == " ".join(toks) else f"{kind}_part"
    first = " ".join(sents[0])
    if avoid_values and fidelity.number_values([first]) & set(avoid_values):
        return ("", "none") if other_sentences else (first, "first_sentence_long")
    if other_sentences and is_meta_speech(first):
        return "", "none"
    return first, "first_sentence_long"


OPENING_NOTES = {
    "first_sentence_part": "wörtlicher Teil des ersten Satzes, an einer Phrasengrenze gekürzt",
    "other_sentence": "wörtlich ein späterer kurzer Satz des Clips",
    "other_sentence_part": "wörtlicher Teil eines späteren Satzes, an einer Phrasengrenze gekürzt",
    "first_sentence_long": "erster Satz ungekürzt, keine gültige Phrasengrenze innerhalb der Wortgrenze",
    "none": "kein Text: jede Originalstelle nennt eine unsicher erkannte Zahl",
}


def variant_disqualifiers(v: HookVariant) -> list[str]:
    """Gründe, aus denen ``select_variant_v2`` eine Variante verwirft. Bewertet wird nur der Text-Hook
    (``onscreen``): der gesprochene Hook wird unter Fassung 2 durch den wörtlichen Einstieg ersetzt, seine
    Befunde stehen als Hinweis in ``lint_notes`` (keine Doppelzählung)."""
    reasons = [f"Claim: {c}" for c in v.claim_issues]
    reasons += limit_notes("", v.onscreen)
    reasons += [n for n in copy_de.lint_violations(v.lint_notes) if n not in reasons]
    if is_meta_speech(v.onscreen):
        reasons.append("Meta-Rede an ein Modell im Hook")
    if not v.onscreen.strip():
        reasons.append("Leerer Text-Hook")
    if v.pattern not in HOOK_PATTERNS:
        reasons.append(f"Unbekanntes Hook-Muster '{v.pattern}'")
    return reasons


def select_variant_v2(variants: list[HookVariant]) -> HookVariant | None:
    """Erste gültige Variante in der gegebenen Reihenfolge (nach ``order_variants``), sonst None.

    Anders als ``select_variant`` gewinnt keine Variante mit Befund: lieber der wörtliche Rückfall als ein
    Hook, der mehr behauptet als der Clip."""
    return next((v for v in variants if not variant_disqualifiers(v)), None)


def native_variant(clip_text: str, brand: copy_de.BrandProfile, uncertain: list[str] | tuple[str, ...] = ()) -> HookVariant:
    """Rückfall ohne gültige Variante: Text-Hook als wörtlicher Auszug (Muster ``native``), bevorzugt aus dem
    ersten Satz, sonst aus einem späteren kurzen Satz; nie mit einer unsicher erkannten Zahl."""
    avoid = fidelity.number_values(uncertain)
    spoken, _ = verbatim_opening(clip_text, SPOKEN_MAX_WORDS)
    raw, kind = verbatim_opening(clip_text, ONSCREEN_MAX_WORDS, avoid, other_sentences=True)
    onscreen, notes = copy_de.lint(raw, brand)
    if kind != "first_sentence":
        notes.append(f"On-Screen-Hook: {OPENING_NOTES[kind]}")
    claims = fidelity.hook_claim_check_v2(onscreen, clip_text, uncertain) if onscreen else []
    return HookVariant(NATIVE_PATTERN, spoken, onscreen, notes, claims)


def order_variants(variants: list[HookVariant], pattern_order: list[str] | None) -> list[HookVariant]:
    """Varianten nach einer Muster-Reihenfolge (z. B. ``learning.thompson_order``) sortieren; unbekannte
    Muster bleiben hinten in Originalreihenfolge. Ohne Reihenfolge unverändert."""
    if not pattern_order:
        return list(variants)
    rank = {p: i for i, p in enumerate(pattern_order)}
    return sorted(variants, key=lambda v: (rank.get(v.pattern, len(rank)), variants.index(v)))


def _variant_summary(v: HookVariant) -> dict[str, Any]:
    return {
        "pattern": v.pattern, "spoken": v.spoken, "onscreen": v.onscreen,
        "claim_issues": len(v.claim_issues), "lint_notes": len(v.lint_notes),
    }  # fmt: skip


def copy_decisions(
    variants: list[HookVariant],
    chosen: HookVariant,
    platform: str,
    explored: bool,
    rule: str = RULE_V1,
    extra: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """``hook_variant_shown`` (Reihenfolge der fünf Muster) und ``hook_selected`` (Wahl plus vier Alternativen).

    Unter Fassung 2 ``rule`` gleich ``RULE_V2``; ``extra`` ergänzt die Merkmale von ``hook_selected`` (Gründe
    der Disqualifikation, Herkunft des gesprochenen Hooks). Ein nativer Rückfall steht nicht in ``variants``,
    dann ist ``chosen_index`` None und alle fünf sind Alternativen."""
    patterns = [v.pattern for v in variants]
    shown = {
        "decision_type": "hook_variant_shown",
        "features": {"platform": platform, "patterns": patterns, "n": len(variants), "order_from_learning": explored},
        "alternatives": [],
        "chosen": {},
        "actor_type": "ai",
    }
    selected = {
        "decision_type": "hook_selected",
        "features": {
            "platform": platform,
            "patterns": patterns,
            "rule": rule,
            "chosen_index": next((i for i, v in enumerate(variants) if v is chosen), None),
            "claim_issues": len(chosen.claim_issues),
            **(extra or {}),
        },
        "alternatives": [_variant_summary(v) for v in variants if v is not chosen],
        "chosen": _variant_summary(chosen),
        "actor_type": "ai",
    }
    return [shown, selected]


def generate_post_caption(
    llm,
    clip_text: str,
    brand: copy_de.BrandProfile,
    platform: str,
    hook_onscreen: str,
    uncertain: list[str] | tuple[str, ...] | None = None,
) -> tuple[str, str, list[str], list[str], str]:
    """``post_caption_v1`` für eine Plattform: (text, cta, lint_notes, claim_issues, prompt_version).

    ``uncertain`` (unter Fassung 2, auch leer): Prüfung mit ``hook_claim_check_v2`` und den unsicher
    erkannten Zahlen; ohne Angabe ``hook_claim_check`` wie in Fassung 1."""
    pr = prompts.load_pinned("post_caption")
    user = pr.render(
        address=brand.address.upper(),
        country=brand.country,
        platform=platform,
        tone_adjectives=brand.tone_adjectives,
        banned_phrases=brand.banned_phrases,
        clip_text=clip_text,
        hook_onscreen=hook_onscreen,
    )
    out = llm.structured(
        _system_prompt(), user, POST_CAPTION_SCHEMA, pr.tool or "write_post_caption", pr.prompt_version, job_type="llm_copy"
    )
    text, notes_t = copy_de.lint(str(out.get("text") or "").strip(), brand)
    cta, notes_c = copy_de.lint(str(out.get("cta") or "").strip(), brand)
    notes = [f"{platform}: {n}" for n in [*notes_t, *notes_c]]
    if uncertain is None:
        claims = [f"{platform}: {c}" for c in fidelity.hook_claim_check(text, clip_text)]
    else:
        claims = [f"{platform}: {c}" for c in fidelity.hook_claim_check_v2(text, clip_text, uncertain)]
    if hook_onscreen and hook_onscreen.strip() and hook_onscreen.strip().lower() in text.lower():
        notes.append(f"{platform}: Post wiederholt den On-Screen-Hook wörtlich")
    return text, cta, notes, claims, pr.prompt_version


def languagetool_check(text: str, country: str, s: config.Settings | None = None, label: str = "") -> list[str]:
    """Grammatikprüfung über LanguageTool, nur mit ``LANGUAGETOOL_URL``. Jeder Fehler wird zum Hinweis, nie zur Ausnahme.

    Der Aufruf läuft über ``residency.guarded_client``; ein nicht erlaubter Host bricht vor dem Netz ab."""
    s = s or config.settings()
    base = (s.languagetool_url or "").strip()
    if not base or not text.strip():
        return []
    url = base.rstrip("/")
    if not url.endswith("/check"):
        url += "/check"
    locale = LT_LOCALES.get((country or "").upper(), "de-DE")
    prefix = f"LanguageTool ({label}): " if label else "LanguageTool: "
    try:
        with residency.guarded_client(s, timeout=LT_TIMEOUT_S) as client:
            r = client.post(url, data={"text": text, "language": locale})
            r.raise_for_status()
            data = r.json()
    except residency.ResidencyError as exc:
        return [f"{prefix}nicht erlaubt ({exc})"]
    except Exception as exc:  # Netz, Timeout, JSON: nie fatal
        return [f"{prefix}nicht erreichbar ({exc.__class__.__name__})"]
    notes = []
    for m in (data.get("matches") or [])[:LT_MAX_NOTES_PER_TEXT]:
        rule = (m.get("rule") or {}).get("id", "")
        msg = str(m.get("message") or "").strip()
        ctx = (m.get("context") or {})
        snippet = ""
        try:
            off, ln = int(ctx.get("offset", 0)), int(ctx.get("length", 0))
            snippet = str(ctx.get("text", ""))[off : off + ln]
        except (TypeError, ValueError):
            pass
        notes.append(f"{prefix}{msg}" + (f" bei '{snippet}'" if snippet else "") + (f" [{rule}]" if rule else ""))
    return notes


def write_copy(
    llm,
    clip_text: str,
    brand: copy_de.BrandProfile,
    platforms: tuple[str, ...] | list[str] = PLATFORMS,
    s: config.Settings | None = None,
    pattern_order: list[str] | None = None,
    words: list[dict] | None = None,
) -> CopyResult:
    """Komplette Copy für einen Clip: Varianten, Auswahl, Post-Captions je Plattform, Linter, optional LanguageTool.

    ``pattern_order`` (aus ``learning.thompson_order``) sortiert die Varianten vor der Auswahl; die
    Entscheidungen landen in ``CopyResult.decisions`` für das Decision Log. ``words`` sind die Wörter des
    Clips mit ``prob``; unter Fassung 2 dürfen unsicher erkannte Zahlen nicht in den Hook."""
    s = s or config.settings()
    variants, hooks_version = generate_variants(llm, clip_text, brand)
    variants = order_variants(variants, pattern_order)
    native = native_hooks_enabled()
    uncertain: list[str] | None = None
    if native:
        uncertain = fidelity.uncertain_number_tokens(words or [])
        chosen, spoken_hook, extra_notes, extra_claims, extra = _select_v2(variants, clip_text, brand, uncertain)
        rule = RULE_V2
    else:
        chosen = select_variant(variants)
        spoken_hook, extra_notes, extra_claims, rule, extra = chosen.spoken, [], [], RULE_V1, None

    post_captions: dict[str, str] = {}
    ctas: dict[str, str] = {}
    lint_notes: list[str] = []
    claim_issues: list[str] = []
    caption_version = ""
    for platform in platforms:
        text, cta, notes, claims, caption_version = generate_post_caption(
            llm, clip_text, brand, platform, chosen.onscreen, uncertain
        )
        post_captions[platform] = text
        ctas[platform] = cta
        lint_notes.extend(notes)
        claim_issues.extend(claims)

    lt_info: dict[str, Any] | None = None
    if (s.languagetool_url or "").strip():
        lt_notes = languagetool_check(spoken_hook, brand.country, s, "hook")
        for platform, text in post_captions.items():
            lt_notes += languagetool_check(text, brand.country, s, platform)
        lint_notes.extend(lt_notes)
        lt_info = {"url": s.languagetool_url, "locale": LT_LOCALES.get(brand.country.upper(), "de-DE"), "notes": len(lt_notes)}

    cta = ctas.get(brand.platform) or next(iter(ctas.values()), "")
    return CopyResult(
        spoken_hook=spoken_hook,
        onscreen_hook=chosen.onscreen,
        pattern=chosen.pattern,
        variants=[v.to_dict() for v in variants],
        post_captions=post_captions,
        cta=cta,
        lint_notes=[*chosen.lint_notes, *extra_notes, *lint_notes],
        claim_issues=[*chosen.claim_issues, *extra_claims, *claim_issues],
        model_id=llm.model(),
        prompt_version=hooks_version,
        post_caption_prompt_version=caption_version,
        languagetool=lt_info,
        decisions=copy_decisions(variants, chosen, brand.platform, bool(pattern_order), rule, extra),
    )


def _select_v2(
    variants: list[HookVariant], clip_text: str, brand: copy_de.BrandProfile, uncertain: list[str]
) -> tuple[HookVariant, str, list[str], list[str], dict[str, Any]]:
    """Auswahl unter Fassung 2: Claim-Check v2 und Lint je Text-Hook, erste gültige oder nativer Rückfall,
    gesprochener Hook wörtlich. Gibt (Wahl, spoken_hook, Zusatzhinweise, Zusatzbefunde, Merkmale)."""
    for v in variants:
        _, notes_o = copy_de.lint(v.onscreen, brand)
        _, notes_s = copy_de.lint(v.spoken, brand)
        spoken_claims = fidelity.hook_claim_check_v2(v.spoken, clip_text, uncertain)
        v.claim_issues = fidelity.hook_claim_check_v2(v.onscreen, clip_text, uncertain)
        v.lint_notes = [
            *notes_o,
            *limit_notes("", v.onscreen),
            *(f"Gesprochen (Hinweis): {n}" for n in [*notes_s, *limit_notes(v.spoken, ""), *spoken_claims]),
        ]
        if v.pattern not in HOOK_PATTERNS:
            v.lint_notes.append(f"Unbekanntes Hook-Muster '{v.pattern}'")
    disqualified = {f"{i}:{v.pattern}": variant_disqualifiers(v) for i, v in enumerate(variants)}
    chosen = select_variant_v2(variants)
    fallback = chosen is None
    if chosen is None:
        chosen = native_variant(clip_text, brand, uncertain)
    spoken, kind = verbatim_opening(clip_text, SPOKEN_MAX_WORDS)
    notes = [f"Gesprochener Hook: {OPENING_NOTES[kind]}"] if kind != "first_sentence" else []
    claims = [f"Gesprochener Hook: {c}" for c in fidelity.hook_claim_check_v2(spoken, clip_text, uncertain)]
    extra = {
        "native_fallback": fallback,
        "spoken_source": kind,
        "uncertain_numbers": len(uncertain),
        "disqualified": {k: len(r) for k, r in disqualified.items() if r},
    }
    return chosen, spoken, notes, claims, extra


__all__ = [
    "HOOKS_SCHEMA",
    "HOOK_PATTERNS",
    "LT_LOCALES",
    "NATIVE_PATTERN",
    "ONSCREEN_MAX_WORDS",
    "PLATFORMS",
    "POST_CAPTION_SCHEMA",
    "RULE_V1",
    "RULE_V2",
    "SPOKEN_MAX_WORDS",
    "VARIANT_COUNT",
    "CopyResult",
    "HookVariant",
    "clip_sentences",
    "copy_decisions",
    "first_sentence",
    "generate_post_caption",
    "generate_variants",
    "languagetool_check",
    "limit_notes",
    "is_meta_speech",
    "native_hooks_enabled",
    "native_variant",
    "order_variants",
    "phrase_cuts",
    "select_variant",
    "select_variant_v2",
    "variant_disqualifiers",
    "verbatim_excerpt",
    "verbatim_opening",
    "word_count",
    "write_copy",
]
