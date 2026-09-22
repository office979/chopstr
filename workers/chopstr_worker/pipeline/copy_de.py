"""DACH-Copy-Layer (Phase 3): Hooks, On-Screen-Text, Post-Captions.

1) Markenprofil (Du/Sie, Land, Gendern-Modus, gesperrte Phrasen, Plattform)
2) Hook-Varianten per LLM über ``hooks_v1`` (``generate_hooks``)
3) Deterministischer Linter NACH der Generierung: KI-Floskeln, Gedankenstriche, Anrede-Konsistenz,
   ß/ss (CH), Komposita-Bindestriche, Gender-Modus
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .. import prompts

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


def lint(text: str, p: BrandProfile) -> tuple[str, list[str]]:
    """Gibt (korrigierter_text, hinweise) zurück. Korrigiert nur Eindeutiges, der Rest sind Hinweise."""
    notes, out = [], text

    if "—" in out:
        out = out.replace(" — ", ", ").replace("—", ", ")
        notes.append("Em-Dash ersetzt (im Deutschen unüblich)")
    if out.count("–") > 1:
        notes.append("Mehrere Gedankenstriche: wirkt KI-generiert")

    low = out.lower()
    for f in AI_FLOSKELN + [b.lower() for b in p.banned_phrases]:
        if f and f in low:
            notes.append(f"Floskel: '{f}'")
    for h in WORN_HOOKS:
        if h in low:
            notes.append(f"Abgenutzter Hook: '{h}'")
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
    pr = prompts.load("hooks")
    return (
        pr.render(
            address=p.address.upper(),
            country=p.country,
            platform=p.platform,
            protected_terms=p.protected_terms,
            clip_text=clip_text,
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


__all__ = ["AD_LABELS", "AI_FLOSKELN", "HOOK_SCHEMA", "WORN_HOOKS", "BrandProfile", "ad_disclosure", "build_hook_prompt", "generate_hooks", "lint"]
