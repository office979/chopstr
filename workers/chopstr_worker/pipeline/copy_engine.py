"""Copy-Engine (Phase 3): Hooks, On-Screen-Text und Post-Captions für einen Clip, passend zu ``hook_versions``.

Ablauf (Vertrag ``packages/schema/CLIPS.md``):
1. Prompt ``hooks_v1`` (Tool ``write_hooks``) liefert fünf Varianten ``{pattern, spoken, onscreen}``.
2. Jede Variante: ``copy_de.lint`` (Anrede, Land, Gender, gesperrte Phrasen), Wortlimits
   (gesprochen 12, im Bild 9) und ``fidelity.hook_claim_check`` gegen den Clip-Text.
3. ``post_caption_v1`` (Tool ``write_post_caption``) pro Plattform, wieder gelintet und claim-geprüft.
4. Optional LanguageTool über ``residency.guarded_client``: nur mit ``LANGUAGETOOL_URL``; Fehler dort sind
   nie fatal, sondern ein Hinweis in ``lint_notes``.
5. Auswahl: erste Variante ohne ``claim_issues``, sonst Variante 1 (mit Issues).

Reine Funktionen ohne DB; der Aufrufer schreibt die Zeile.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from .. import config, prompts, residency
from . import copy_de, fidelity

log = logging.getLogger("chopstr.copy")

PLATFORMS = ("tiktok", "reels", "shorts", "linkedin")
HOOK_PATTERNS = ("identity_call", "contrarian", "open_loop", "results_first", "mistake_warning")
SPOKEN_MAX_WORDS = 12
ONSCREEN_MAX_WORDS = 9
VARIANT_COUNT = 5
LT_LOCALES = {"DE": "de-DE", "AT": "de-AT", "CH": "de-CH"}
LT_TIMEOUT_S = 10.0
LT_MAX_NOTES_PER_TEXT = 5

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
        notes.append(f"Gesprochener Hook zu lang ({word_count(spoken)} Wörter, maximal {SPOKEN_MAX_WORDS})")
    if word_count(onscreen) > ONSCREEN_MAX_WORDS:
        notes.append(f"On-Screen-Hook zu lang ({word_count(onscreen)} Wörter, maximal {ONSCREEN_MAX_WORDS})")
    return notes


def _system_prompt() -> str:
    return prompts.load("system_editor").render()


def generate_variants(llm, clip_text: str, brand: copy_de.BrandProfile) -> tuple[list[HookVariant], str]:
    """``hooks_v1`` aufrufen, jede Variante linten, Limits und Claims prüfen. Gibt (Varianten, prompt_version)."""
    pr = prompts.load("hooks")
    user = pr.render(
        address=brand.address.upper(),
        country=brand.country,
        platform=brand.platform,
        protected_terms=brand.protected_terms,
        clip_text=clip_text,
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


def generate_post_caption(llm, clip_text: str, brand: copy_de.BrandProfile, platform: str, hook_onscreen: str) -> tuple[str, str, list[str], list[str], str]:
    """``post_caption_v1`` für eine Plattform: (text, cta, lint_notes, claim_issues, prompt_version)."""
    pr = prompts.load("post_caption")
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
    claims = [f"{platform}: {c}" for c in fidelity.hook_claim_check(text, clip_text)]
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
) -> CopyResult:
    """Komplette Copy für einen Clip: Varianten, Auswahl, Post-Captions je Plattform, Linter, optional LanguageTool."""
    s = s or config.settings()
    variants, hooks_version = generate_variants(llm, clip_text, brand)
    chosen = select_variant(variants)

    post_captions: dict[str, str] = {}
    ctas: dict[str, str] = {}
    lint_notes: list[str] = []
    claim_issues: list[str] = []
    caption_version = ""
    for platform in platforms:
        text, cta, notes, claims, caption_version = generate_post_caption(llm, clip_text, brand, platform, chosen.onscreen)
        post_captions[platform] = text
        ctas[platform] = cta
        lint_notes.extend(notes)
        claim_issues.extend(claims)

    lt_info: dict[str, Any] | None = None
    if (s.languagetool_url or "").strip():
        lt_notes = languagetool_check(chosen.spoken, brand.country, s, "hook")
        for platform, text in post_captions.items():
            lt_notes += languagetool_check(text, brand.country, s, platform)
        lint_notes.extend(lt_notes)
        lt_info = {"url": s.languagetool_url, "locale": LT_LOCALES.get(brand.country.upper(), "de-DE"), "notes": len(lt_notes)}

    cta = ctas.get(brand.platform) or next(iter(ctas.values()), "")
    return CopyResult(
        spoken_hook=chosen.spoken,
        onscreen_hook=chosen.onscreen,
        pattern=chosen.pattern,
        variants=[v.to_dict() for v in variants],
        post_captions=post_captions,
        cta=cta,
        lint_notes=[*chosen.lint_notes, *lint_notes],
        claim_issues=[*chosen.claim_issues, *claim_issues],
        model_id=llm.model(),
        prompt_version=hooks_version,
        post_caption_prompt_version=caption_version,
        languagetool=lt_info,
    )


__all__ = [
    "HOOKS_SCHEMA",
    "HOOK_PATTERNS",
    "LT_LOCALES",
    "ONSCREEN_MAX_WORDS",
    "PLATFORMS",
    "POST_CAPTION_SCHEMA",
    "SPOKEN_MAX_WORDS",
    "VARIANT_COUNT",
    "CopyResult",
    "HookVariant",
    "generate_post_caption",
    "generate_variants",
    "languagetool_check",
    "limit_notes",
    "select_variant",
    "word_count",
    "write_copy",
]
