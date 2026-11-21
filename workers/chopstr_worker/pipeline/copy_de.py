"""DACH-Copy-Layer (Phase 3): Hooks, On-Screen-Text, Post-Captions.

1) Markenprofil (Du/Sie, Land, Gendern-Modus, gesperrte Phrasen, Plattform)
2) Hook-Varianten per LLM über ``hooks_v1`` (``generate_hooks``)
3) Deterministischer Linter NACH der Generierung: KI-Floskeln, Gedankenstriche, Anrede-Konsistenz,
   ß/ss (CH), Komposita-Bindestriche, Gender-Modus
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .. import editorial, prompts
from . import fidelity

AI_FLOSKELN = [
    "essenziell", "nahtlos", "maßgeschneidert", "vielfältig", "ganzheitlich", "im digitalen zeitalter",
    "in der heutigen welt", "es ist wichtig zu beachten", "zusammenfassend lässt sich", "tauche ein",
    "revolutionär", "game changer", "gamechanger", "entfessle", "auf das nächste level", "spannend",
]  # fmt: skip
WORN_HOOKS = [
    "du glaubst nicht", "wenn ich das früher gewusst hätte", "niemand spricht darüber",
    "das hat mein leben verändert", "warte bis zum ende",
]  # fmt: skip
DU_FORMS = r"\b(du|dich|dir|dein|deine|deinen|deinem|deiner|euch|euer|eure)\b"
SIE_FORMS = r"\b(Sie|Ihnen|Ihr|Ihre|Ihren|Ihrem|Ihrer)\b"  # case-sensitiv: großes Sie
GENDER_CHARS = re.compile(r"(\w+)[*:_](innen|in)\b")
NOT_COMPOUND_HEADS = {
    "die", "der", "das", "den", "dem", "des", "ein", "eine", "einen", "einem", "einer", "ihr", "ihre",
    "ihren", "ihrem", "ihrer", "sie", "wir", "mein", "meine", "dein", "deine", "unser", "unsere", "euer",
    "diese", "dieser", "dieses", "jede", "jeder", "alle", "viele", "neue", "neuen", "gute", "beste", "mehr",
    "im", "am", "zum", "zur", "vom", "beim", "und", "oder", "aber", "als", "wie", "für", "mit", "ohne",
}  # fmt: skip
AD_LABELS = {"DE": "Anzeige", "AT": "Werbung", "CH": "Werbung"}

HOOK_SCHEMA = {
    "type": "object",
    "properties": {
        "hooks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "enum": ["identity_call", "contrarian", "open_loop", "results_first", "mistake_warning"]},
                    "spoken": {"type": "string"},
                    "onscreen": {"type": "string"},
                },
                "required": ["pattern", "spoken", "onscreen"],
            },
        }
    },
    "required": ["hooks"],
}


@dataclass
class BrandProfile:
    address: str = "du"  # "du" | "sie"
    country: str = "AT"  # "DE" | "AT" | "CH"
    gender_mode: str = "neutral"  # "neutral" | "paarform" | "doppelpunkt" | "stern" | "keine"
    banned_phrases: list[str] = field(default_factory=list)
    protected_terms: list[str] = field(default_factory=list)  # Austriazismen, die NIE ersetzt werden
    tone_adjectives: list[str] = field(default_factory=list)
    platform: str = "linkedin"  # "tiktok" | "reels" | "shorts" | "linkedin"
    # Trichterstufe für hooks_v3 (TOF Reichweite, MOF Vertrauen, BOF Entscheidung); ohne Angabe TOF
    funnel_stage: str = "TOF"


# Hinweise, die eine Hook-Variante in der Auswahl v2 disqualifizieren (copy_engine.select_variant_v2). Die
# übrigen sind korrigiert (Em-Dash, ß) oder nur Prüfhinweise (Durchkopplung, mögliche Sie-Form, Muster).
VIOLATION_PREFIXES = (
    "Floskel:", "Abgenutzter Hook:", "Hyperbel:", "Du-Form in Sie-Profil", "Genderzeichen",
    "Mehrere Gedankenstriche", "Zahl nicht im Clip:",
)  # fmt: skip

# -- SOP-Regeln für den Text-Hook (A2.2, nur mit editorial.Policy.hook_sop_v3) ---------------------
# Aus den Agentur-SOPs für Visual Hooks: kein Schlusspunkt, höchstens zwei kurze Zeilen, kein Rückbezug
# ohne Nomen, Zahlen nur mit Bezug und nur, wenn der Clip sie nennt, ein Gedanke, keine Striche und Emojis.
SOP_MAX_LINES = 2
SOP_MAX_LINE_CHARS = 32
SOP_DEMONSTRATIVES = frozenset({"das", "dies", "dieses", "darum", "deshalb", "deswegen", "daher", "genau"})
SOP_COPULAS = frozenset({"ist", "war", "sind", "waren", "wird", "bleibt"})
SOP_UNIT_WORDS = frozenset({
    "%", "€", "prozent", "euro", "eur", "chf", "franken", "dollar", "cent", "mio", "mio.", "millionen", "million",
    "milliarden", "tausend", "jahre", "jahren", "jahr", "monate", "monaten", "monat", "wochen", "woche", "tage",
    "tagen", "tag", "stunden", "stunde", "minuten", "minute", "sekunden", "uhr", "mal", "fach", "kilo", "kg",
    "km", "meter", "stück", "leute", "menschen", "kunden",
})  # fmt: skip
# Emojis und Bildzeichen (grobe Blöcke, genügt für Hooks): Symbole, Piktogramme, Dingbats, Variationswähler
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]")
# Strich mit Leerzeichen davor und danach; zwischen Ziffern ist es ein Bereich („5 - 10 Euro“) und bleibt
SPACED_DASH_RE = re.compile(r"(?<!\d)\s+[–-]\s+|\s+[–-]\s+(?!\d)")
# Gedanken- oder Halbgeviertstrich ohne Leerzeichen zwischen Buchstaben („Fehler—und Lehre“); ein Bindestrich
# ohne Leerzeichen ist ein Kompositum und bleibt, zwischen Ziffern ist es ein Bereich
UNSPACED_DASH_RE = re.compile(r"(?<=[^\W\d_])[—–](?=[^\W\d_])")
# Vor „und“ und „oder“ wird aus dem Strich ein Leerzeichen, kein Komma („Der Fehler und was wir lernten“).
# Vor „aber“ und „sondern“ bleibt es beim Komma, das verlangt die Regel für entgegenstellende Konjunktionen.
DASH_BEFORE_CONJ_RE = re.compile(r"(?:\s+[—–-]\s+|\s*[—–]\s*)(?=(?:und|oder)\b)", re.IGNORECASE)
# Rückbezüge aus mehreren Wörtern ohne Kopula („Genau das“, „Das hier“, „So ist es“)
SOP_BACKREF_PHRASES = (
    ("genau", "das"), ("genau", "so"), ("genau", "deshalb"), ("genau", "darum"), ("das", "hier"), ("so", "ist", "es"),
    ("das", "ist", "es"), ("und", "genau", "das"),
)  # fmt: skip
# Zahlenbereich: „5 - 10 Euro“, „5–10 Euro“, „5 bis 10 Euro“ ist eine Einheit, der Bezug steht nach der zweiten Zahl
RANGE_JOINERS = frozenset({"-", "–", "—", "bis"})


def _wrap(text: str, width: int) -> list[str]:
    """Gieriger Zeilenumbruch an Leerzeichen, wie ein Overlay ohne festen Umbruch ihn setzt."""
    lines: list[str] = []
    for part in text.split("\n"):
        line = ""
        for word in part.split():
            cand = f"{line} {word}".strip()
            if line and len(cand) > width:
                lines.append(line)
                line = word
            else:
                line = cand
        lines.append(line)
    return lines


def lint_sop(text: str, clip_text: str | None = None) -> tuple[str, list[str]]:
    """SOP-Regeln für den Text-Hook. Korrigiert Schlusspunkt, Striche und Emojis; der Rest sind Hinweise,
    nur eine Zahl, die der Clip nicht nennt, ist ein Verstoß (``Zahl nicht im Clip:``). ``clip_text`` fehlt:
    die Zahlenprüfung gegen den Clip entfällt."""
    notes: list[str] = []
    out = text.strip()

    if EMOJI_RE.search(out):
        out = " ".join(EMOJI_RE.sub("", out).split())
        notes.append("Emoji entfernt")
    dashed = SPACED_DASH_RE.search(out) or UNSPACED_DASH_RE.search(out)
    if dashed:
        # Bereiche zwischen Ziffern bleiben (beide Muster lassen sie aus), vor „und“ oder „aber“ nur ein Leerzeichen
        out = DASH_BEFORE_CONJ_RE.sub(lambda m: " " if not re.search(r"\d\s*$", out[: m.start()]) else m.group(0), out)
        out = UNSPACED_DASH_RE.sub(", ", out)
        out = SPACED_DASH_RE.sub(", ", out)
        out = re.sub(r" {2,}", " ", out)
        notes.append("Gedankenstrich ersetzt")
    if out.endswith(".") and not out.endswith("..."):
        out = out[:-1].rstrip()
        notes.append("Schlusspunkt entfernt")

    explicit = out.split("\n")
    long_lines = [ln for ln in explicit if len(ln.strip()) > SOP_MAX_LINE_CHARS] if len(explicit) > 1 else []
    if len(explicit) > SOP_MAX_LINES:
        notes.append(f"Mehr als {SOP_MAX_LINES} Zeilen")
    elif long_lines:
        notes.append(f"Zeile über {SOP_MAX_LINE_CHARS} Zeichen: '{long_lines[0].strip()}'")
    elif len(_wrap(out, SOP_MAX_LINE_CHARS)) > SOP_MAX_LINES:
        notes.append(f"Passt nicht in {SOP_MAX_LINES} Zeilen zu {SOP_MAX_LINE_CHARS} Zeichen")

    words = re.findall(r"[\wÄÖÜäöüß%€.]+", out)
    low = [w.lower().strip(".") for w in words]
    starts_backref = any(tuple(low[: len(ph)]) == ph for ph in SOP_BACKREF_PHRASES)
    if low and (
        (len(low) == 1 and low[0] in SOP_DEMONSTRATIVES)
        or (low[0] in SOP_DEMONSTRATIVES and len(low) <= 4 and len(low) > 1 and low[1] in SOP_COPULAS)
        or (starts_backref and len(low) <= 4)
    ):
        notes.append(f"Rückbezug ohne Nomen: '{out}' versteht man ohne Clip nicht")

    for mention in fidelity.number_mentions(out):
        if mention.unit is not None:
            continue
        at = out.find(mention.raw)
        rest = out[at + len(mention.raw) :] if at >= 0 else ""
        after = rest.split()[:2]
        # Erste Zahl eines Bereichs: der Bezug gehört zur zweiten Zahl, die wird für sich geprüft
        if re.match(r"\s*(?:[-–—]|bis\b)\s*\d", rest):
            continue
        has_ref = any(w[:1].isupper() or w.lower().strip(".,!?") in SOP_UNIT_WORDS or w[:1] in "%€" for w in after)
        if not has_ref:
            notes.append(f"Zahl ohne Bezug: '{mention.raw}'")
    if clip_text is not None:
        clip_values = {m.value for m in fidelity.number_mentions(clip_text)}
        for mention in fidelity.number_mentions(out):
            if mention.value not in clip_values:
                notes.append(f"Zahl nicht im Clip: '{mention.raw}'")

    if len(re.findall(r"\bund\b", out, flags=re.IGNORECASE)) > 1 and "," in out:
        notes.append("Mehr als ein Gedanke? Mehrere 'und' und Kommas")

    return out, notes


def lint_violations(notes: list[str]) -> list[str]:
    """Die Hinweise aus ``lint``, die ein Verstoß sind und keine bloße Prüfbitte."""
    return [n for n in notes if n.startswith(VIOLATION_PREFIXES)]


def prompt_clip_text(clip_text: str, prompt_version: int) -> str:
    """Clip-Text für den Hook-Prompt. Ab ``hooks_v2`` steht er zwischen ``<clip>``-Begrenzern; spitze
    Klammern im Transkript werden maskiert, damit kein Text den Begrenzer schließen kann."""
    if prompt_version < 2:
        return clip_text
    return clip_text.replace("<", "‹").replace(">", "›")


def lint(
    text: str,
    p: BrandProfile,
    hyperbole: tuple[str, ...] | list[str] | None = None,
    word_bounds: bool | None = None,
    onscreen: bool = False,
    clip_text: str | None = None,
    sop_v3: bool | None = None,
) -> tuple[str, list[str]]:
    """Gibt (korrigierter_text, hinweise) zurück. Korrigiert nur Eindeutiges, der Rest sind Hinweise.

    ``hyperbole``: leere Intensivierungen; ohne Angabe ``hook.hyperbole`` der aktiven Grundlage (Fassung 1
    hat keine, dort bleibt der Linter wie bisher). ``word_bounds``: Floskeln, abgenutzte Hooks und
    Hyperbeln nur an Wortgrenzen („spannend“ trifft nicht „Hochspannend“); ohne Angabe an, wenn die aktive
    Grundlage ``hook.native_spoken`` hat (Fassung 2), in Fassung 1 Teilstring wie bisher.

    ``onscreen``: der Text ist ein Text-Hook. Dann gelten zusätzlich die SOP-Regeln (``lint_sop``, mit
    ``clip_text`` für die Zahlenprüfung), sofern ``sop_v3`` an ist; ohne Angabe ``Policy.hook_sop_v3``."""
    notes, out = [], text
    if onscreen:
        if sop_v3 is None:
            sop_v3 = editorial.load().hook_sop_v3
        if sop_v3:
            out, notes = lint_sop(out, clip_text)
    policy = editorial.load() if hyperbole is None or word_bounds is None else None
    if hyperbole is None:
        hyperbole = policy.hyperbole if policy else ()
    if word_bounds is None:
        word_bounds = bool(policy and policy.hook_native_spoken)

    def found(phrase: str, low_text: str) -> bool:
        return bool(fidelity.phrase_hits([phrase], low_text)) if word_bounds else phrase in low_text

    if "—" in out:
        out = out.replace(" — ", ", ").replace("—", ", ")
        notes.append("Em-Dash ersetzt (im Deutschen unüblich)")
    if out.count("–") > 1:
        notes.append("Mehrere Gedankenstriche: wirkt KI-generiert")

    low = out.lower()
    for f in AI_FLOSKELN + [b.lower() for b in p.banned_phrases]:
        if f and found(f, low):
            notes.append(f"Floskel: '{f}'")
    for h in WORN_HOOKS:
        if found(h, low):
            notes.append(f"Abgenutzter Hook: '{h}'")
    for h in hyperbole:
        h = str(h).lower()
        if h and found(h, low) and h not in WORN_HOOKS:
            notes.append(f"Hyperbel: '{h}' ersetzt keine Substanz")
    if re.search(r"\bnicht\b[^.]{0,40}, sondern\b", low):
        notes.append("Muster 'nicht A, sondern B': sparsam einsetzen")

    has_du = re.search(DU_FORMS, out, flags=re.IGNORECASE) is not None
    has_sie = re.search(SIE_FORMS, out) is not None
    if p.address == "sie" and has_du:
        notes.append("Du-Form in Sie-Profil")
    if p.address == "du" and has_sie and not out.startswith(("Sie ", "Ihr ")):
        notes.append("Mögliche Sie-Form in Du-Profil prüfen")

    if p.country == "CH" and "ß" in out:
        out = out.replace("ß", "ss")
        notes.append("ß zu ss (CH)")

    if p.gender_mode in ("neutral", "paarform", "keine") and GENDER_CHARS.search(out):
        notes.append("Genderzeichen im Wortinneren passen nicht zum Profil")
    if p.gender_mode == "doppelpunkt":
        out = re.sub(r"(\w+)\*(innen|in)\b", r"\1:\2", out)
    if p.gender_mode == "stern":
        out = re.sub(r"(\w+):(innen|in)\b", r"\1*\2", out)

    for m in re.finditer(r"\b([A-Z]{2,}|[A-Z][a-z]+) ([A-ZÄÖÜ][a-zäöüß]{3,})\b", out):
        if m.group(1).lower() in NOT_COMPOUND_HEADS:
            continue
        notes.append(f"Durchkopplung prüfen: '{m.group(0)}' zu '{m.group(1)}-{m.group(2)}'?")

    return out, notes


def build_hook_prompt(clip_text: str, p: BrandProfile) -> tuple[str, prompts.Prompt]:
    pr = prompts.load_pinned("hooks")
    return (
        pr.render(
            address=p.address.upper(),
            country=p.country,
            platform=p.platform,
            protected_terms=p.protected_terms,
            clip_text=prompt_clip_text(clip_text, pr.version),
        ),
        pr,
    )


def generate_hooks(llm, clip_text: str, p: BrandProfile) -> list[dict]:
    """5 Hook-Varianten; jede wird gelintet und mit Claim-Check versehen."""
    from .fidelity import hook_claim_check
    from .story_score import system_prompt

    user, pr = build_hook_prompt(clip_text, p)
    out = llm.structured(system_prompt(), user, HOOK_SCHEMA, pr.tool or "write_hooks", pr.prompt_version, job_type="llm_copy")
    hooks = []
    for h in out.get("hooks", []):
        spoken, notes_s = lint(h.get("spoken", ""), p)
        onscreen, notes_o = lint(h.get("onscreen", ""), p)
        hooks.append(
            {
                "pattern": h.get("pattern"),
                "spoken": spoken,
                "onscreen": onscreen,
                "lint_notes": notes_s + notes_o,
                "claim_issues": hook_claim_check(spoken, clip_text) + hook_claim_check(onscreen, clip_text),
                "prompt_version": pr.prompt_version,
            }
        )
    return hooks


def ad_disclosure(p: BrandProfile, is_paid_partnership: bool, brand_mentioned: bool) -> str | None:
    """Werbekennzeichnung am ANFANG von Caption/Overlay. Keine Rechtsberatung, sondern Default-Logik."""
    if is_paid_partnership or brand_mentioned:
        return AD_LABELS.get(p.country, "Werbung")
    return None


__all__ = [
    "AD_LABELS", "AI_FLOSKELN", "HOOK_SCHEMA", "VIOLATION_PREFIXES", "WORN_HOOKS", "BrandProfile", "ad_disclosure",
    "build_hook_prompt", "generate_hooks", "lint", "lint_sop", "lint_violations", "prompt_clip_text",
]  # fmt: skip
