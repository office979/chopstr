"""Kritiker (AP6b, nur Fassung 2): prüft einen ausgewählten Clip gezielt auf verlorenen Kontext.

Rollen nach Master-Prompt 22: Analyst ist ``episode_overview``, Editor ``propose_moments_v2`` und die
Einstiegswahl in ``story_engine.evaluate_span``, Evaluator die deterministischen Gates und Teilwerte. Der
Kritiker (``critique_clip_v1``) sucht nur: Stelle im Clip oder Kontext, die den Text-Hook oder die zentrale
Aussage widerlegt; unklares Pronomen; entfernte Bedingung oder Einschränkung; Übergang, der eine Beziehung
behauptet, die im Original nicht besteht; fremde Position als eigene.

Die Antwort des Modells wird deterministisch geprüft, bevor sie zählt: Art und Schwere aus der festen Liste,
das Zitat muss wörtlich im Clip oder im Kontext stehen (sonst ``ungrounded``), ein Befund zum Text-Hook ohne
Text-Hook wird verworfen (``no_hook``). Verwerfen darf nur ein bestätigter Befund der Schwere ``fidelity``
mit wörtlichem Beleg von einem Sprachmodell. Befunde der Heuristik (``heuristic: true``) sind unkalibriert
und werden nur berichtet. Ohne Text-Hook (``none_too_long`` und die anderen ``none_*``) prüft der Kritiker
keinen Hook und schlägt keinen vor; es bleibt beim Verhalten aus AP6a (kein Overlay)."""

from __future__ import annotations

import re
from typing import Any

from .. import editorial, prompts
from . import fidelity, story_graph
from .segment import Sentence, numbered

CRITIC_KINDS = (
    "hook_contradicted", "claim_contradicted", "unclear_pronoun", "removed_condition", "false_transition",
    "reported_position",
)  # fmt: skip
SEVERITIES = ("fidelity", "clarity", "minor")
# Kontext für den Kritiker: zwei Sätze davor (wie die Gates), danach das Folgefenster des Story-Graphs,
# höchstens sechs Sätze.
CONTEXT_BEFORE = 2
CONTEXT_AFTER_MAX = 6
CONTEXT_AFTER_S = story_graph.LOOKAHEAD_S
NO_HOOK = "-"

CRITIQUE_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(CRITIC_KINDS)},
                    "severity": {"type": "string", "enum": list(SEVERITIES)},
                    "evidence_quote": {"type": "string"},
                    "sentence_refs": {"type": "array", "items": {"type": "integer"}},
                    "explanation": {"type": "string"},
                },
                "required": ["kind", "severity", "evidence_quote", "sentence_refs", "explanation"],
            },
        },
        "confirmed": {"type": "boolean"},
        "heuristic": {"type": "boolean"},
    },
    "required": ["findings", "confirmed"],
}

_QUOTES = re.compile(r"[\"'„“”‚‘’«»]")
_EDGE = ".,;:!?…()[] "


def _norm(text: str) -> str:
    """Vergleichsform für den Wortlaut: Kleinschreibung, ohne Anführungszeichen, Satzzeichen am Rand jedes
    Wortes entfernt, Leerraum zusammengefasst. Die Wörter selbst und ihre Reihenfolge bleiben unverändert."""
    toks = (tok.strip(_EDGE) for tok in _QUOTES.sub("", str(text or "")).lower().split())
    return " ".join(tok for tok in toks if tok)


def _contains(text: str, quote: str) -> bool:
    """Steht ``quote`` als ganze Wortfolge in ``text`` (beide in Vergleichsform)? „sie“ trifft nicht „sieht“."""
    return bool(quote) and f" {quote} " in f" {text} "


def context_window(sents: list[Sentence], first: int, last: int) -> tuple[list[Sentence], list[Sentence]]:
    """Kontext davor (``CONTEXT_BEFORE`` Sätze) und danach (bis ``CONTEXT_AFTER_S`` Sekunden nach dem Ende,
    höchstens ``CONTEXT_AFTER_MAX`` Sätze)."""
    before = sents[max(0, first - CONTEXT_BEFORE) : first]
    end_t = sents[last].end
    after = [s for s in sents[last + 1 : last + 1 + CONTEXT_AFTER_MAX] if s.start - end_t <= CONTEXT_AFTER_S]
    return before, after


def text_hook(clip_text: str, words: list[dict]) -> tuple[str, str]:
    """Text-Hook, den der Kritiker prüft: der native Rückfall aus AP6a (``copy_engine.native_onscreen``) mit
    den unsicheren Zahlen der Wörter. Zurück (Text, Herkunft); leerer Text heißt kein Overlay."""
    from . import copy_engine

    return copy_engine.native_onscreen(clip_text, fidelity.uncertain_number_tokens(words))


def build_prompt(
    sents: list[Sentence], first: int, last: int, words: list[dict], policy: editorial.Policy | None = None
) -> tuple[str, prompts.Prompt, dict[str, Any]]:
    """Gerenderter Prompt ``critique_clip`` (gepinnt) und die Texte, gegen die Zitate geprüft werden."""
    p = prompts.load_pinned("critique_clip", policy)
    span = sents[first : last + 1]
    before, after = context_window(sents, first, last)
    a, b = span[0].word_range[0], span[-1].word_range[1]
    clip_text = " ".join(s.text for s in span)
    hook, hook_source = text_hook(clip_text, words[a : b + 1])
    user = p.render(
        opening=span[0].text,
        text_hook=hook or NO_HOOK,
        clip_text=numbered(span),
        context_before=numbered(before) if before else NO_HOOK,
        context_after=numbered(after) if after else NO_HOOK,
    )
    meta = {
        "texts": {
            "clip": _norm(clip_text),
            "context_before": _norm(" ".join(s.text for s in before)),
            "context_after": _norm(" ".join(s.text for s in after)),
        },
        "refs": {s.idx for s in (*before, *span, *after)},
        "hook": hook,
        "hook_source": hook_source,
    }
    return user, p, meta


def check_findings(raw: Any, meta: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    """Deterministische Prüfung der Befunde. Zurück (behaltene, verworfene mit ``drop_reason``)."""
    kept: list[dict] = []
    dropped: list[dict] = []
    if not isinstance(raw, list):
        return kept, [{"drop_reason": "invalid", "detail": "findings ist keine Liste"}]
    for item in raw:
        if not isinstance(item, dict):
            dropped.append({"drop_reason": "invalid", "detail": "Befund ist kein Objekt"})
            continue
        f = {
            "kind": item.get("kind"),
            "severity": item.get("severity"),
            "evidence_quote": str(item.get("evidence_quote") or ""),
            "sentence_refs": [r for r in (item.get("sentence_refs") or []) if isinstance(r, int) and not isinstance(r, bool)],
            "explanation": str(item.get("explanation") or ""),
        }
        if f["kind"] not in CRITIC_KINDS or f["severity"] not in SEVERITIES:
            dropped.append({**f, "drop_reason": "invalid"})
            continue
        if f["kind"] == "hook_contradicted" and not meta["hook"]:
            dropped.append({**f, "drop_reason": "no_hook"})
            continue
        quote = _norm(f["evidence_quote"])
        location = next((k for k, text in meta["texts"].items() if _contains(text, quote)), None)
        if location is None:
            dropped.append({**f, "drop_reason": "ungrounded"})
            continue
        f["sentence_refs"] = sorted({r for r in f["sentence_refs"] if r in meta["refs"]})
        f["location"] = location
        kept.append(f)
    return kept, dropped


def critique(
    candidate: Any,
    sents: list[Sentence],
    words: list[dict],
    llm: Any,
    policy: editorial.Policy | None = None,
) -> dict[str, Any]:
    """Kritiker für einen Kandidaten (``first_sent``, ``last_sent``). Ein Modellaufruf über ``llm.structured``;
    ``story_engine.LLMBudgetExceeded`` und ``SchemaError`` reicht er an den Aufrufer weiter.

    Rückgabe: ``findings`` (geprüft, mit ``location``), ``dropped`` (mit ``drop_reason``), ``confirmed``
    (wirksam: Modell bestätigt, mindestens ein belegter Befund der Schwere ``fidelity``, kein Heuristik-Befund),
    ``model_confirmed`` (Angabe des Modells), ``reject`` (der verwerfende Befund oder ``None``), ``heuristic``,
    ``hook_source`` und ``prompt_version``."""
    from .story_score import system_prompt

    first, last = int(candidate.first_sent), int(candidate.last_sent)
    user, p, meta = build_prompt(sents, first, last, words, policy)
    out = llm.structured(system_prompt(), user, CRITIQUE_SCHEMA, p.tool or "critique_clip", p.prompt_version, job_type="llm_critic")
    heuristic = bool(getattr(llm, "is_heuristic", False)) or out.get("heuristic") is True
    findings, dropped = check_findings(out.get("findings"), meta)
    model_confirmed = out.get("confirmed") is True
    fidelity_findings = [f for f in findings if f["severity"] == "fidelity"]
    confirmed = model_confirmed and bool(fidelity_findings) and not heuristic
    return {
        "findings": findings,
        "dropped": dropped,
        "confirmed": confirmed,
        "model_confirmed": model_confirmed,
        "reject": fidelity_findings[0] if confirmed else None,
        "heuristic": heuristic,
        "hook_source": meta["hook_source"],
        "prompt_version": p.prompt_version,
    }


__all__ = [
    "CONTEXT_AFTER_MAX",
    "CONTEXT_BEFORE",
    "CRITIC_KINDS",
    "CRITIQUE_SCHEMA",
    "SEVERITIES",
    "build_prompt",
    "check_findings",
    "context_window",
    "critique",
    "text_hook",
]
