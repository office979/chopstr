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
from . import copy_de, dach_nlp, fidelity, story_graph
from .segment import Sentence

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
# Wörtlicher Auszug (gesprochener Hook, nativer Text-Hook). Sätze über ``dach_nlp.sentence_end_kind`` (Regel
# v2: Abkürzungen, Ordinal- und Dezimalzahlen); ein Satz mit weniger als drei Inhaltswörtern gehört zum
# nächsten (Füll- und Rückmeldewörter zählen nicht). Standard unter Fassung 2 (``hook.allow_partial_opening``
# false): der Text-Hook ist immer ein ganzer Originalsatz oder es gibt keinen. Teilsatz-Auszüge nur als
# Opt-in; Fehlerrichtung ist immer ganzer Satz oder kein Overlay, nie ein Bruchstück.
MIN_PHRASE_WORDS = 3
NATIVE_SENTENCE_WINDOW = 4  # Text-Hook nur aus den ersten vier Sätzen des Clips
FILLER_WORDS = frozenset(dach_nlp.HARD_FILLERS | dach_nlp.BACKCHANNEL | {"also", "naja", "na", "tja", "gut", "so"})
COORDINATORS = frozenset({"und", "oder", "denn", "sowie"})
# Nie davor schneiden: Kontrast, Bedingung und Einschränkung gehören zur Aussage („… jedem Kunden, | aber
# nicht …“, „Wir haben die Preise erhöht, | ohne vorher …“, „Das lohnt sich, | wenn …“).
CONTRAST_NO_CUT = frozenset({
    *fidelity.CONTRAST_STARTS, "sondern", "doch", "jedoch", "ohne", "statt", "anstatt", "wenn", "falls",
    "sofern", "solange", "soweit",
})  # fmt: skip
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
    "vor", "auf", "an", "durch", "um", "bis", "ab", "per", "pro", "laut", "statt", "anstatt",
})  # fmt: skip
COPULA = frozenset({
    "ist", "sind", "war", "waren", "wird", "werden", "wurde", "wurden", "bin", "bist", "seid", "wäre", "wären",
    "sei",
})  # fmt: skip
OPEN_QUANTIFIERS = frozenset({"rund", "etwa", "ca", "knapp", "fast", "mehr", "weniger", "als", "wie", "so", "sehr", "zu"})
W_WORDS = frozenset({
    "wer", "wen", "wem", "wessen", "was", "wie", "wo", "wann", "warum", "weshalb", "wieso", "weswegen", "woher",
    "wohin", "womit", "wofür", "worüber", "woran", "worauf", "wovon", "wozu", "welche", "welcher", "welches",
    "welchen", "welchem",
})  # fmt: skip
CORRELATES = frozenset({
    "darum", "daran", "davon", "dafür", "dazu", "darauf", "darüber", "dabei", "dadurch", "daraus", "darin",
    "damit", "dahin", "davor", "danach", "dagegen", "darunter",
})  # fmt: skip
GRADE_PARTICLES = frozenset({"nur", "auch", "noch", "sogar", "schon", "erst", "bereits", "selbst", "gerade", "eben", "bloß"})
RELATIVE_PRONOUNS = frozenset({
    "der", "die", "das", "dem", "den", "deren", "dessen", "denen", "welche", "welcher", "welches", "welchen",
    "welchem", "wo",
})  # fmt: skip
INFINITIVE_INTROS = frozenset({"um", "ohne", "statt", "anstatt"})
# Nach Verben des Sagens, Zeigens und Meinens folgt der Inhalt erst: nicht davor schneiden.
SAYING_VERBS = frozenset({
    "sage", "sagst", "sagt", "sagen", "sagte", "sagten", "gesagt", "meine", "meinst", "meint", "meinen",
    "meinte", "meinten", "gemeint", "glaube", "glaubst", "glaubt", "glauben", "glaubte", "geglaubt", "denke",
    "denkst", "denkt", "denken", "dachte", "dachten", "gedacht", "zeige", "zeigst", "zeigt", "zeigen", "zeigte",
    "gezeigt", "finde", "findest", "findet", "finden", "fand", "weiß", "weißt", "wissen", "wisst", "wusste",
    "wussten", "gewusst", "erkläre", "erklärt", "erklären", "erklärte", "behaupte", "behauptet", "behaupten",
    "hoffe", "hofft", "hoffen", "erzähle", "erzählt", "erzählen", "erzählte", "frage", "fragt", "fragen",
    "fragte", "gefragt", "sehe", "siehst", "sieht", "sehen", "sah", "gesehen", "merke", "merkt", "gemerkt",
    "heißt", "bedeutet",
})  # fmt: skip
NON_VERBS = frozenset({
    "nicht", "jetzt", "erst", "meist", "fast", "selbst", "sonst", "bereits", "seit", "gut", "oft", "nichts",
    "recht", "leicht", "weit", "zuletzt", "zuerst", "etwa", "heute", "gerade", "genau", "insgesamt", "eben",
    "neben", "gegen", "wegen", "oben", "unten", "morgen", "trotzdem", "zusammen", "allen", "vielen", "anderen",
    "alle", "gerne", "gern", "ohne", "eine", "keine", "seite", "ganze", "ganzen", "eigene", "eigenen", "beste",
    "besten", "letzte", "letzten", "erste", "ersten", "nächste", "nächsten", "halbe", "halben", "ende", "einfach",
})  # fmt: skip
_FINITE_LIKE = re.compile(r"^[a-zäöüß]{2,}(?:t|st|te|ten|en|ern|eln)$")
# Erste Person auf -e („ich rufe“) nur direkt nach dem Pronomen, sonst ist -e meist ein Adjektiv („gute“).
_FIRST_PERSON_E = re.compile(r"^[a-zäöüß]{2,}e$")
PRONOUNS_BEFORE_VERB = frozenset({"ich", "er", "sie", "es", "man", "wir", "ihr"})
_ZU_INFINITIVE = re.compile(r"^[a-zäöüß]+zu[a-zäöüß]+(?:en|ern|eln)$")
_PUNCT_END = (",", ".", "!", "?", ";", ":")
# Meta-Rede: eine echte Anrede an ein Modell (Vokativ am Satz- oder Teilsatzanfang mit Komma, Doppelpunkt
# oder Ausrufezeichen, oder Gruß davor), eine Rollenmarke „System:“ oder ein Imperativ mit Steuerbegriff
# („Ignoriere alle Anweisungen“). „Nimm KI ernst“ und „Wähle das richtige Modell“ sind keine Meta-Rede.
_MODEL_TERMS = r"(?:ki|chatgpt|gpt|claude|gemini|sprachmodell|modell|assistent|bot)"
META_VOCATIVE = re.compile(rf"(?:^|[.!?;:,]\s*)(?:(?:liebe|lieber|liebes|hallo|hey|hi)\s+)?{_MODEL_TERMS}\s*[,:!]", re.IGNORECASE)
META_GREETING = re.compile(rf"(?<!\w)(?:liebe|lieber|liebes|hallo|hey|hi)\s+{_MODEL_TERMS}(?!\w)", re.IGNORECASE)
META_ROLE = re.compile(r"(?:^|[.!?]\s*)(?:system|assistant|user)\s*:", re.IGNORECASE)
META_CONTROL_STEMS = ("anweisung", "regel", "prompt", "punktzahl", "bestnote", "bewertung", "systemprompt")
META_IMPERATIVES = frozenset({
    "ignoriere", "ignorier", "vergiss", "gib", "setz", "setze", "schreib", "schreibe", "bewerte", "mach",
    "mache", "antworte", "befolge", "nimm", "wähle", "lösche", "übersetze", "tu", "tue", "vergib", "missachte",
})  # fmt: skip
# Ein späterer Satz als Text-Hook nur, wenn er nicht mit einem Rückbezug beginnt („Das war 2024.“).
ANAPHORIC_STARTS = frozenset({
    "das", "dies", "diese", "dieser", "dieses", "es", "er", "sie", "damit", "dadurch", "danach", "davor",
    "deshalb", "deswegen", "daher", "dann", "dort", "da", "so", "also", "aber", "und", "oder", "denn", "auch",
    "dabei", "dafür", "darum", "trotzdem", "sondern", "ihm", "ihn", "ihr", "ihnen",
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


def allow_partial_opening(policy: editorial.Policy | None = None) -> bool:
    """Teilsatz-Auszüge als Hook erlaubt (``hook.allow_partial_opening``)? Standard false: ganzer Satz."""
    return (policy or editorial.load()).allow_partial_opening


def _core(token: str) -> str:
    return dach_nlp.core_token(token)


def _content_words(toks: list[str]) -> int:
    return sum(1 for t in toks if _core(t) and _core(t) not in FILLER_WORDS)


def clip_sentences(clip_text: str) -> list[list[str]]:
    """Sätze des Clips als Wortlisten. Satzende über ``dach_nlp.sentence_end_kind`` mit Regel v2 (nur
    Satzzeichen, weil der Text keine Zeiten trägt): „Am 3. Mai“, „Dr. Müller“, „ca. 40 Euro“ und „z. B.“
    trennen nicht. Ein Satz mit weniger als ``MIN_PHRASE_WORDS`` Inhaltswörtern („Ja.“, „Ähm. Okay.“) wird
    mit dem nächsten verbunden."""
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
        if _content_words(sent) < MIN_PHRASE_WORDS:
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
    """Spricht der Text ein Modell an oder steuert es („Liebe KI, …“, „System: …“, „Ignoriere alle
    Anweisungen …“)? Ein Modellbegriff allein („Nimm KI ernst“) ist keine Meta-Rede."""
    if META_ROLE.search(text) or META_GREETING.search(text) or META_VOCATIVE.search(text.strip()):
        return True
    cores = [_core(t) for t in text.split()]
    return any(c in META_IMPERATIVES for c in cores) and any(c.startswith(META_CONTROL_STEMS) for c in cores)


def _finite(toks: list[str], j: int) -> bool:
    """Grobe Erkennung eines finiten Verbs (kein Partizip, kein Adjektiv vor seinem Nomen)."""
    t = toks[j]
    core = _core(t)
    if core in dach_nlp.AUXILIARY_FORMS:
        return True
    if not t[:1].islower() or dach_nlp.is_participle(t) or len(core) < 3:
        return False
    if core in NON_VERBS or core in ARTICLES or core in PREPOSITIONS or core in W_WORDS or core in CORRELATES:
        return False
    if core in COORDINATORS or core in dach_nlp.SUBORDINATORS or core in GRADE_PARTICLES:
        return False
    prev = _core(toks[j - 1]) if j > 0 else ""
    nxt = toks[j + 1] if j + 1 < len(toks) else ""
    if prev in ARTICLES | PREPOSITIONS and nxt[:1].isupper():
        return False  # Adjektiv vor seinem Nomen („die neue Plattform“)
    if prev == "zu" or _ZU_INFINITIVE.match(core):
        return False  # Infinitiv mit zu („zu schalten“, „auszugleichen“)
    if _FIRST_PERSON_E.match(core) and prev in PRONOUNS_BEFORE_VERB:
        return True
    return bool(_FINITE_LIKE.match(core))


def _segment(toks: list[str], start: int) -> list[str]:
    """Wörter ab ``start`` bis einschließlich des nächsten Kommas (oder Satzende)."""
    out = []
    for t in toks[start:]:
        out.append(t)
        if t.rstrip("\"'»«“”‘’)").endswith((",", ";", ":")):
            break
    return out


def _has_finite(toks: list[str], start: int, end: int) -> bool:
    return any(_finite(toks, j) for j in range(start, end))


def _cut_problem(toks: list[str], k: int) -> str | None:
    """Warum der Satz ``toks`` nach ``k`` Wörtern nicht enden darf, oder None, wenn der Auszug geschlossen ist."""
    if k < MIN_PHRASE_WORDS or k >= len(toks):
        return "zu kurz oder ganzer Satz"
    last, nxt = toks[k - 1], _core(toks[k])
    comma = last.rstrip("\"'»«“”‘’)").endswith((",", ";", ":"))
    if nxt in CONTRAST_NO_CUT:
        return "vor Kontrast oder Einschränkung"
    clause_starts = dach_nlp.SUBORDINATORS + tuple(INFINITIVE_INTROS)
    if not (comma or nxt in COORDINATORS or nxt in clause_starts):
        return "keine Phrasengrenze"
    bare = last.rstrip(",;:\"'»«“”‘’)")
    core = _core(last)
    if not core or any(ch.isdigit() for ch in core) or dach_nlp.is_ordinal(bare) or dach_nlp.is_abbreviation(bare, "v2"):
        return "endet auf Zahl oder Abkürzung"
    closed_word_sets = (
        ARTICLES, PREPOSITIONS, COPULA, OPEN_QUANTIFIERS, COORDINATORS, dach_nlp.SUBORDINATORS, W_WORDS,
        CORRELATES, GRADE_PARTICLES, CONTRAST_NO_CUT,
    )  # fmt: skip
    if any(core in words for words in closed_word_sets):
        return "endet auf Funktionswort"
    if last[:1].islower() and _core(toks[k - 2]) in ARTICLES | PREPOSITIONS:
        return "offene Nominalgruppe"
    prefix, rest = toks[:k], toks[k:]
    cores = [_core(t) for t in prefix]
    first_seg = _segment(toks, 0)
    if len(first_seg) > k:
        first_seg = prefix
    if cores[0] in dach_nlp.SUBORDINATORS or cores[0] in INFINITIVE_INTROS:
        later = len(first_seg)
        if later >= k or not _has_finite(toks, later, k):
            return "nur Nebensatz"
    elif not _has_finite(toks, 0, len(first_seg)):
        return "erstes Segment ohne finites Verb"
    starts = [j for j in range(1, k) if prefix[j - 1].rstrip("\"'»«“”‘’)").endswith((",", ";", ":"))]
    for n, j in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else k
        if not _has_finite(toks, j, end):
            return "Teilsatz ohne finites Verb (Aufzählung, Apposition)"
    for j in range(1, k):
        if prefix[j - 1].rstrip("\"'»«“”‘’)").endswith(","):
            c = cores[j]
            c2 = cores[j + 1] if j + 1 < k else ""
            if c in RELATIVE_PRONOUNS or c in W_WORDS or (c in PREPOSITIONS and c2 in RELATIVE_PRONOUNS):
                return "Relativsatz oder w-Satz offen"
    for j in range(k - 1):
        if prefix[j].rstrip("\"'»«“”‘’)").endswith(",") and (cores[j] in COPULA or _finite(toks, j)):
            return "Parenthese nach finitem Verb"
    if any(c in SAYING_VERBS for c in cores):
        return "Verb des Sagens, Zeigens oder Meinens"
    for j, c in enumerate(cores):
        if c in INFINITIVE_INTROS and not any(
            cc == "zu" or re.fullmatch(r"[a-zäöüß]+zu[a-zäöüß]+en", cc) for cc in cores[j + 1 :]
        ):
            return "um, ohne oder statt ohne zu plus Infinitiv"
    for t in rest:
        if t[:1].islower() and _core(t) in dach_nlp.VERB_PARTICLES and t.rstrip("\"'»«“”‘’)").endswith(_PUNCT_END):
            return "Verbpartikel steht im Rest des Satzes"
    if nxt in OBJECT_CLAUSE_STARTS and (_finite(toks, k - 1) or dach_nlp.is_participle(last)):
        return "Objektsatz nach dem Verb"
    if nxt in COORDINATORS:
        seg = _segment(toks, k + 1)
        if not _has_finite(toks, k + 1, k + 1 + len(seg)):
            return "Aufzählung, kein neuer Teilsatz"
    elif comma and nxt not in clause_starts:
        seg = _segment(toks, k)
        if not _has_finite(toks, k, k + len(seg)):
            return "Aufzählung oder Apposition"
    right = rest
    if nxt in clause_starts:
        # Der eingeschobene Nebensatz gehört nicht zur Klammer des Hauptsatzes: geprüft wird, was nach ihm
        # kommt („Wir haben die Preise, | weil alles teurer wurde, dreimal angepasst.“ bleibt offen).
        end = next((j for j, t in enumerate(right) if t.rstrip("\"'»«“”‘’)").endswith(",")), None)
        right = right[end + 1 :] if end is not None else []
    if right and dach_nlp.bracket_heuristic(prefix, right)["open"]:
        return "Verbklammer offen"
    return None


def phrase_cuts(toks: list[str], max_words: int) -> list[int]:
    """Gültige Schnittlängen eines Satzes bis ``max_words`` Wörter, längste zuerst."""
    return [k for k in range(min(max_words, len(toks) - 1), MIN_PHRASE_WORDS - 1, -1) if _cut_problem(toks, k) is None]


def _join(toks: list[str], k: int | None = None) -> str:
    return " ".join(toks if k is None else toks[:k]).rstrip(",;:")


def verbatim_excerpt(toks: list[str], max_words: int, accept=None) -> str | None:
    """Geschlossener Teilsatz-Auszug (Opt-in ``hook.allow_partial_opening``): der ganze Satz, wenn er passt,
    sonst bis zur längsten gültigen Phrasengrenze. ``accept`` prüft jeden Kandidaten zusätzlich (Claim-Check,
    unsichere Zahl, Meta-Rede). None, wenn es keinen gibt."""
    ok = accept or (lambda _text: True)
    if len(toks) <= max_words and ok(" ".join(toks)):
        return " ".join(toks)
    return next((_join(toks, k) for k in phrase_cuts(toks, max_words) if ok(_join(toks, k))), None)


def sentence_hook(toks: list[str], max_words: int, partial: bool, accept=None) -> str | None:
    """Hook aus einem Satz: der ganze Satz bis ``max_words`` Wörter; mit ``partial`` auch ein geschlossener
    Teilsatz-Auszug; sonst None."""
    ok = accept or (lambda _text: True)
    if len(toks) <= max_words:
        return " ".join(toks) if ok(" ".join(toks)) else None
    return verbatim_excerpt(toks, max_words, ok) if partial else None


def spoken_opening(clip_text: str, partial: bool = False) -> tuple[str, str]:
    """Gesprochener Hook: der wörtliche Einstieg des Clips. Gibt (Text, Herkunft) zurück: ``first_sentence``,
    ``first_sentence_part`` (nur mit ``partial`` und gültiger Grenze) oder ``first_sentence_long``."""
    sents = clip_sentences(clip_text)
    if not sents:
        return "", "none_too_long"
    first = " ".join(sents[0])
    if len(sents[0]) <= SPOKEN_MAX_WORDS:
        return first, "first_sentence"
    part = verbatim_excerpt(sents[0], SPOKEN_MAX_WORDS) if partial else None
    return (part, "first_sentence_part") if part else (first, "first_sentence_long")


# Eine Aussage, die der Clip (oder der Kontext danach) zurücknimmt oder relativiert, oder eine fremde Position,
# wird nie zum Text-Hook (Master-Prompt 8 und 13, Fälle later_self_correction und reported_position).
RETRACTION_WINDOW = 3  # so viele Folgesätze prüfen Korrektur- und Relativierungsmarker
RETRACTION_PHRASES = ("das heißt aber nicht", "das heißt nicht", "das bedeutet nicht", "das stimmt so nicht")
RETRACTION_STARTS = ("moment",)
REPORTED_FRAMES = (
    "viele sagen", "man sagt", "heißt es", "angeblich", "so nach dem motto", "hat immer gesagt", "hat gesagt",
    "sagte immer", "meinte immer", "behauptet", "behaupten", "laut",
)  # fmt: skip
HOOK_OVERLAP_RETRACTED = 0.6  # Anteil der Inhaltswörter eines Hooks, die in einer zurückgenommenen Aussage stehen


def _sentence_objects(texts: list[str]) -> list[Sentence]:
    # Ohne Zeiten: der Abstand zählt in Sätzen, eine Sekunde je Satz liegt sicher im Story-Graph-Fenster.
    return [Sentence(idx=i, text=t, start=float(i), end=float(i), speaker=None, word_range=(0, 0)) for i, t in enumerate(texts)]


def _is_reported(texts: list[str], i: int) -> bool:
    """Gibt der Satz eine fremde Position wieder (Zitatrahmen im Satz oder Doppelpunkt-Rahmen davor)?"""
    low = texts[i].lower()
    if fidelity.phrase_hits(REPORTED_FRAMES, low):
        return True
    toks = texts[i].split()
    if any(t.endswith(":") and _core(t) in SAYING_VERBS for t in toks):
        return True
    prev = texts[i - 1] if i > 0 else ""
    return prev.rstrip().endswith(":") and any(_core(t) in SAYING_VERBS for t in prev.split())


def _is_retracted(texts: list[str], sents: list[Sentence], i: int) -> bool:
    """Wird Satz ``i`` danach korrigiert oder relativiert? Story-Graph v2 (Korrektur- und Kontrastmarker mit
    Bezug), ein Folgesatz, der mit einem Kontrastwort beginnt, oder „Moment“, „Das heißt aber nicht“ und
    Korrekturmarker in den nächsten ``RETRACTION_WINDOW`` Sätzen mit Bezug auf den Satz. Ein Korrektursatz
    selbst zählt auch als ausgeschlossen."""
    if story_graph.find_later_qualifications(sents, i, i, rule="v2"):
        return True
    if i + 1 < len(texts) and fidelity.starts_with_contrast(texts[i + 1].lower(), "v2"):
        return True
    own = texts[i]
    if _core(own.split()[0] if own.split() else "") in RETRACTION_STARTS or story_graph.find_marker(
        own, story_graph.CORRECTION_MARKERS
    ):
        return True  # der Korrektursatz selbst („Moment, das muss ich korrigieren.“) ist kein Hook
    for j in range(i + 1, min(len(texts), i + 1 + RETRACTION_WINDOW)):
        later = texts[j]
        first = _core(later.split()[0]) if later.split() else ""
        marked = first in RETRACTION_STARTS or fidelity.phrase_hits(RETRACTION_PHRASES, later.lower())
        marked = marked or bool(story_graph.find_marker(later, story_graph.CORRECTION_MARKERS))
        if not marked:
            continue
        # Bezug wie im Story-Graph: der Markersatz und der Satz danach teilen Inhaltswörter mit dem Satz.
        target = f"{later} {texts[j + 1]}" if j + 1 < len(texts) else later
        if story_graph.lexical_overlap(own, target) >= story_graph.MIN_OVERLAP:
            return True
    return False


def retracted_statements(clip_text: str, context_after: str = "") -> dict[int, str]:
    """Sätze des Clips (Index in ``clip_sentences``), die nicht zum Hook taugen, mit Grund: ``retracted``
    (später korrigiert oder relativiert, auch durch ``context_after``) oder ``reported`` (fremde Position)."""
    clip = [" ".join(t) for t in clip_sentences(clip_text)]
    texts = clip + [" ".join(t) for t in clip_sentences(context_after)]
    sents = _sentence_objects(texts)
    out: dict[int, str] = {}
    for i in range(len(clip)):
        if _is_reported(texts, i):
            out[i] = "reported"
        elif _is_retracted(texts, sents, i):
            out[i] = "retracted"
    return out


def _content_tokens(text: str) -> set[str]:
    return {c for c in (_core(t) for t in text.split()) if len(c) >= 3 and c not in ARTICLES | PREPOSITIONS | COPULA}


def retraction_issue(hook: str, clip_text: str, context_after: str = "") -> str | None:
    """Befund, wenn ein (generierter) Text-Hook im Wesentlichen eine zurückgenommene oder fremde Aussage des
    Clips wiedergibt, sonst None."""
    hook_tokens = _content_tokens(hook)
    if not hook_tokens:
        return None
    clip = clip_sentences(clip_text)
    for i, reason in retracted_statements(clip_text, context_after).items():
        sent = " ".join(clip[i])
        if len(hook_tokens & _content_tokens(sent)) / len(hook_tokens) >= HOOK_OVERLAP_RETRACTED:
            what = "eine später korrigierte oder relativierte Aussage" if reason == "retracted" else "eine fremde Position"
            return f"Text-Hook gibt {what} wieder ('{sent}')"
    return None


def native_onscreen(
    clip_text: str, uncertain: list[str] | tuple[str, ...] = (), partial: bool = False, context_after: str = ""
) -> tuple[str, str]:
    """Text-Hook des Rückfalls. Gibt (Text, Herkunft) zurück.

    Standard (``partial`` false): ein ganzer Originalsatz mit höchstens ``ONSCREEN_MAX_WORDS`` Wörtern, ohne
    unsichere Zahl, ohne Meta-Rede und ohne Claim-Befund; zuerst der erste Satz, sonst der nächste solche Satz
    ohne Rückbezug innerhalb der ersten vier Sätze. Herkunft ``first_sentence`` oder ``other_sentence``; mit
    ``partial`` auch ``*_part``. Sätze, die der Clip oder ``context_after`` später korrigiert oder relativiert,
    und Sätze mit fremder Position sind ausgeschlossen. Gibt es keinen, ist der Text leer (kein Overlay):
    ``none_meta`` (der erste Satz ist Meta-Rede), ``none_retracted`` (ein kurzer Satz im Fenster wurde wegen
    Korrektur oder fremder Position ausgeschlossen), ``none_uncertain`` (der erste Satz nennt eine unsicher erkannte Zahl)
    oder ``none_too_long``."""
    sents = clip_sentences(clip_text)
    excluded = retracted_statements(clip_text, context_after)

    def accept(text: str) -> bool:
        return not is_meta_speech(text) and not fidelity.hook_claim_check_v2(text, clip_text, uncertain)

    for idx, toks in enumerate(sents[:NATIVE_SENTENCE_WINDOW]):
        if (idx > 0 and _core(toks[0]) in ANAPHORIC_STARTS) or idx in excluded:
            continue
        text = sentence_hook(toks, ONSCREEN_MAX_WORDS, partial, accept)
        if text is not None:
            kind = "first_sentence" if idx == 0 else "other_sentence"
            return text, kind if text == " ".join(toks) else f"{kind}_part"
    first = " ".join(sents[0]) if sents else ""
    if first and is_meta_speech(first):
        return "", "none_meta"
    if any(i < NATIVE_SENTENCE_WINDOW and len(sents[i]) <= ONSCREEN_MAX_WORDS for i in excluded):
        return "", "none_retracted"  # ein kurzer Satz wäre wählbar gewesen, wird aber korrigiert oder ist fremd
    if first and fidelity.number_values([first]) & fidelity.number_values(uncertain):
        return "", "none_uncertain"
    return "", "none_too_long"


OPENING_NOTES = {
    "first_sentence_part": "wörtlicher Teil des ersten Satzes, an einer geschlossenen Phrasengrenze gekürzt",
    "other_sentence": "wörtlich ein späterer kurzer Satz des Clips",
    "other_sentence_part": "wörtlicher Teil eines späteren Satzes, an einer geschlossenen Phrasengrenze gekürzt",
    "first_sentence_long": "erster Satz ungekürzt, länger als die Wortgrenze",
    "none_too_long": "kein Text: kein ganzer kurzer Originalsatz ohne Befund in den ersten vier Sätzen",
    "none_meta": "kein Text: der Einstieg spricht ein Modell an",
    "none_uncertain": "kein Text: der Einstieg nennt eine unsicher erkannte Zahl, kein anderer kurzer Satz passt",
    "none_retracted": "kein Text: die kurzen Sätze werden später korrigiert oder geben eine fremde Position wieder",
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


def native_variant(
    clip_text: str,
    brand: copy_de.BrandProfile,
    uncertain: list[str] | tuple[str, ...] = (),
    partial: bool = False,
    context_after: str = "",
) -> tuple[HookVariant, str]:
    """Rückfall ohne gültige Variante (Muster ``native``): Text-Hook nach ``native_onscreen``, gesprochen der
    wörtliche Einstieg. Gibt (Variante, Herkunft des Text-Hooks); ein leerer Text-Hook heißt kein Overlay."""
    spoken, _ = spoken_opening(clip_text, partial)
    raw, kind = native_onscreen(clip_text, uncertain, partial, context_after)
    onscreen, notes = copy_de.lint(raw, brand) if raw else ("", [])
    if kind != "first_sentence":
        notes.append(f"On-Screen-Hook: {OPENING_NOTES[kind]}")
    claims = fidelity.hook_claim_check_v2(onscreen, clip_text, uncertain) if onscreen else []
    return HookVariant(NATIVE_PATTERN, spoken, onscreen, notes, claims), kind


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
    context_after: str = "",
) -> CopyResult:
    """Komplette Copy für einen Clip: Varianten, Auswahl, Post-Captions je Plattform, Linter, optional LanguageTool.

    ``pattern_order`` (aus ``learning.thompson_order``) sortiert die Varianten vor der Auswahl; die
    Entscheidungen landen in ``CopyResult.decisions`` für das Decision Log. ``words`` sind die Wörter des
    Clips mit ``prob``; unter Fassung 2 dürfen unsicher erkannte Zahlen nicht in den Hook. ``context_after``
    ist Transkripttext nach dem Clip: korrigiert er eine Aussage des Clips, wird sie nicht zum Hook."""
    s = s or config.settings()
    variants, hooks_version = generate_variants(llm, clip_text, brand)
    variants = order_variants(variants, pattern_order)
    native = native_hooks_enabled()
    uncertain: list[str] | None = None
    if native:
        uncertain = fidelity.uncertain_number_tokens(words or [])
        chosen, spoken_hook, extra_notes, extra_claims, extra = _select_v2(
            variants, clip_text, brand, uncertain, context_after
        )
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
    variants: list[HookVariant],
    clip_text: str,
    brand: copy_de.BrandProfile,
    uncertain: list[str],
    context_after: str = "",
) -> tuple[HookVariant, str, list[str], list[str], dict[str, Any]]:
    """Auswahl unter Fassung 2 mit ``hook.native_spoken``.

    1. Je Variante zählt nur der Text-Hook: Claim-Check v2 (mit unsicheren Zahlen), Lint, Wortlimit und ob er
       eine später korrigierte Aussage oder eine fremde Position wiedergibt (``retraction_issue``).
       Befunde zum gesprochenen Text stehen als ``Gesprochen (Hinweis): …`` in ``lint_notes``.
    2. Gewählt wird die erste gültige Variante in der Thompson-Reihenfolge (``select_variant_v2``), sonst der
       wörtliche Rückfall ``native_variant`` (ganzer Originalsatz oder kein Overlay; Teilsätze nur mit
       ``hook.allow_partial_opening``).
    3. Der gesprochene Hook ist immer der wörtliche Einstieg (``spoken_opening``); Meta-Rede oder eine
       unsicher erkannte Zahl darin wird als Hinweis oder Befund gemeldet, nicht ersetzt.
    Gibt (Wahl, spoken_hook, Zusatzhinweise, Zusatzbefunde, Merkmale für das Decision Log)."""
    partial = allow_partial_opening()
    for v in variants:
        _, notes_o = copy_de.lint(v.onscreen, brand)
        _, notes_s = copy_de.lint(v.spoken, brand)
        spoken_claims = fidelity.hook_claim_check_v2(v.spoken, clip_text, uncertain)
        v.claim_issues = fidelity.hook_claim_check_v2(v.onscreen, clip_text, uncertain)
        retraction = retraction_issue(v.onscreen, clip_text, context_after)
        if retraction:
            v.claim_issues.append(retraction)
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
    onscreen_source = "variant"
    if chosen is None:
        chosen, onscreen_source = native_variant(clip_text, brand, uncertain, partial, context_after)
    spoken, kind = spoken_opening(clip_text, partial)
    notes = [f"Gesprochener Hook: {OPENING_NOTES[kind]}"] if kind != "first_sentence" else []
    if retracted_statements(clip_text, context_after).get(0):
        notes.append(
            "Gesprochener Hook: der Einstieg wird später korrigiert oder gibt eine fremde Position wieder, bitte prüfen"
        )
    if is_meta_speech(spoken):
        notes.append("Gesprochener Hook: der Einstieg enthält Meta-Rede an ein Modell, sie wird nicht befolgt, bitte prüfen")
    claims = []
    uncertain_values = fidelity.number_values(uncertain)
    for m in fidelity.number_mentions(spoken):
        if m.value in uncertain_values:
            claims.append(f"Gesprochener Hook: Zahl '{m.raw}' im Einstieg unsicher erkannt, am Audio prüfen")
    claims += [
        f"Gesprochener Hook: {c}"
        for c in fidelity.hook_claim_check_v2(spoken, clip_text, uncertain)
        if "unsicher erkannt" not in c
    ]
    extra = {
        "native_fallback": fallback,
        "onscreen_source": onscreen_source,
        "spoken_source": kind,
        "partial_opening": partial,
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
    "allow_partial_opening",
    "is_meta_speech",
    "native_onscreen",
    "retracted_statements",
    "retraction_issue",
    "native_hooks_enabled",
    "native_variant",
    "order_variants",
    "phrase_cuts",
    "select_variant",
    "select_variant_v2",
    "variant_disqualifiers",
    "sentence_hook",
    "spoken_opening",
    "verbatim_excerpt",
    "word_count",
    "write_copy",
]
