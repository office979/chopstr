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


# -- Gegenleser mit Modell (Lane P3, ``counter_reader_v1``) ----------------------------------------------------
# Sieht nur Clip und Text-Hook und liefert je Dimension same oder differs mit Zitaten. Die Zitate werden
# deterministisch geprüft wie beim Kritiker (``_contains``). Verwerfen nur bei bestätigtem Befund hoher Schwere des
# ersten Modells, nie aus der Heuristik (P42). Ein zweites Modell (``LLM_PROVIDER_SECOND``) wird nur gemessen:
# ``additional_findings`` (nur vom zweiten) und ``rejected_by_second_only``; es verwirft nicht.
COUNTER_SEVERITIES = ("high", "low")
COUNTER_VERDICTS = ("same", "differs")
COUNTER_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "dimension": {"type": "string", "enum": list(fidelity.COUNTER_DIMENSIONS)},
                    "verdict": {"type": "string", "enum": list(COUNTER_VERDICTS)},
                    "clip_quote": {"type": "string"},
                    "hook_quote": {"type": "string"},
                    "severity": {"type": "string", "enum": list(COUNTER_SEVERITIES)},
                    "explanation": {"type": "string"},
                },
                "required": ["dimension", "verdict"],
            },
        },
        "confirmed": {"type": "boolean"},
    },
    "required": ["findings", "confirmed"],
}


def check_counter_findings(raw: Any, clip_text: str, hook: str) -> tuple[list[dict], list[dict]]:
    """Deterministische Prüfung der Gegenleser-Antwort: Dimension und Urteil aus der festen Liste, bei
    ``differs`` beide Zitate wörtlich (``clip_quote`` im Clip, ``hook_quote`` im Hook), sonst ``ungrounded``.
    Zurück (behaltene ``differs``-Befunde, verworfene mit ``drop_reason``); ``same`` wird nicht gespeichert."""
    kept: list[dict] = []
    dropped: list[dict] = []
    if not isinstance(raw, list):
        return kept, [{"drop_reason": "invalid", "detail": "findings ist keine Liste"}]
    clip_n, hook_n = _norm(clip_text), _norm(hook)
    for item in raw:
        if not isinstance(item, dict):
            dropped.append({"drop_reason": "invalid", "detail": "Befund ist kein Objekt"})
            continue
        f = {
            "dimension": item.get("dimension"),
            "verdict": item.get("verdict"),
            "clip_quote": str(item.get("clip_quote") or ""),
            "hook_quote": str(item.get("hook_quote") or ""),
            "severity": item.get("severity") if item.get("severity") in COUNTER_SEVERITIES else "low",
            "explanation": str(item.get("explanation") or ""),
        }
        if f["dimension"] not in fidelity.COUNTER_DIMENSIONS or f["verdict"] not in COUNTER_VERDICTS:
            dropped.append({**f, "drop_reason": "invalid"})
            continue
        if f["verdict"] == "same":
            continue
        if not (_contains(clip_n, _norm(f["clip_quote"])) and _contains(hook_n, _norm(f["hook_quote"]))):
            dropped.append({**f, "drop_reason": "ungrounded"})
            continue
        kept.append(f)
    return kept, dropped


def _budget_allows(llm: Any) -> bool:
    used, limit = getattr(llm, "used", None), getattr(llm, "limit", None)
    if not isinstance(used, int) or not isinstance(limit, int) or getattr(llm, "enforce", False) is not True:
        return True
    return used < limit


def _count_call(llm: Any) -> None:
    if isinstance(getattr(llm, "used", None), int) and isinstance(getattr(llm, "limit", None), int):
        llm.used += 1


def _ask_counter_reader(model: Any, user: str, p: prompts.Prompt, clip_text: str, hook: str) -> dict[str, Any]:
    from .story_score import system_prompt

    out = model.structured(system_prompt(), user, COUNTER_SCHEMA, p.tool or "counter_reader", p.prompt_version, job_type="llm_critic")
    findings, dropped = check_counter_findings(out.get("findings"), clip_text, hook)
    high = [f for f in findings if f["severity"] == "high"]
    return {
        "status": "checked",
        "provider": str(getattr(model, "provider", "") or ""),
        "findings": findings,
        "dropped": dropped,
        "model_confirmed": out.get("confirmed") is True,
        "confirmed": out.get("confirmed") is True and bool(high),
        "reject": high[0] if out.get("confirmed") is True and high else None,
    }


def counter_read_model(clip_text: str, hook: str, llm: Any, policy: editorial.Policy | None = None, second: Any = None) -> dict[str, Any]:
    """Gegenleser mit Modell für einen Clip. Ohne Text-Hook kein Aufruf (``no_hook``), mit dem Heuristik-Provider
    kein Aufruf (``heuristic``: die Heuristik ist kein Modell). ``second`` ist das zweite Modell aus
    ``providers_llm.second_llm`` oder ``None``; ein Heuristik-Provider als zweites wird nie gerufen und als
    ``not_a_second_model`` markiert. Modellbudget: das erste Modell zählt über ``llm`` (``BudgetLLM``), das
    zweite wird im selben Budget mitgezählt. Rückgabe: ``model``, ``second``, ``additional_findings``,
    ``rejected_by_second_only``, ``confirmed`` und ``reject`` (der verwerfende Befund des ersten Modells)."""
    from ..providers_llm import HEURISTIC_PROVIDER, SchemaError
    from .story_engine import LLMBudgetExceeded

    result: dict[str, Any] = {"model": None, "second": None, "additional_findings": [], "rejected_by_second_only": False, "confirmed": False, "reject": None}
    if not hook:
        result["model"] = {"status": "no_hook"}
        return result
    if bool(getattr(llm, "is_heuristic", False)):
        result["model"] = {"status": "heuristic", "detail": "Heuristik-Provider: kein Modell, Gegenleser nur regelbasiert"}
        return result
    p = prompts.load_pinned("counter_reader", policy)
    user = p.render(clip_text=clip_text, text_hook=hook)
    try:
        first = _ask_counter_reader(llm, user, p, clip_text, hook)
    except LLMBudgetExceeded:
        first = {"status": "llm_budget"}
    except SchemaError as exc:
        first = {"status": "invalid_answer", "detail": str(exc)[:300]}
    first["prompt_version"] = p.prompt_version
    result["model"] = {k: v for k, v in first.items() if k != "reject"}
    result["confirmed"] = bool(first.get("confirmed"))
    result["reject"] = first.get("reject")
    if second is None:
        return result
    if getattr(second, "provider", None) == HEURISTIC_PROVIDER or bool(getattr(second, "is_heuristic", False)):
        result["second"] = {"status": "not_a_second_model", "provider": HEURISTIC_PROVIDER, "heuristic": True}
        return result
    if not _budget_allows(llm):
        result["second"] = {"status": "llm_budget", "provider": str(getattr(second, "provider", ""))}
        return result
    _count_call(llm)
    try:
        other = _ask_counter_reader(second, user, p, clip_text, hook)
    except SchemaError as exc:
        other = {"status": "invalid_answer", "detail": str(exc)[:300], "provider": str(getattr(second, "provider", ""))}
    other["prompt_version"] = p.prompt_version
    result["second"] = {k: v for k, v in other.items() if k != "reject"}
    if other.get("status") == "checked":
        seen = {f["dimension"] for f in (first.get("findings") or [])}
        result["additional_findings"] = [f for f in other["findings"] if f["dimension"] not in seen]
        result["rejected_by_second_only"] = bool(other.get("confirmed")) and not result["confirmed"]
    return result


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
    reject = fidelity_findings[0] if confirmed else None
    cr_cfg = fidelity.counter_reader_settings(policy)
    if cr_cfg is not None and cr_cfg["model"]:
        # Lane P3: Gegenleser mit Modell im selben Schritt, Ergebnis additiv in rubric.counter_reader; die
        # regelbasierten Befunde ergänzt clip_candidate.from_report. Verwerfen nur bestätigt und hoch (P42).
        from ..providers_llm import second_llm

        clip_text = " ".join(s.text for s in sents[first : last + 1])
        cr = counter_read_model(clip_text, meta["hook"], llm, policy, second_llm(llm))
        rubric = getattr(candidate, "rubric", None)
        if isinstance(rubric, dict):
            rubric["counter_reader"] = {**(rubric.get("counter_reader") or {}), **{k: v for k, v in cr.items() if k != "reject"}}
        if reject is None and cr["reject"] is not None and not heuristic:
            f = cr["reject"]
            reject = {
                "kind": f"counter_reader_{f['dimension']}", "severity": "fidelity", "evidence_quote": f["clip_quote"],
                "sentence_refs": [], "explanation": f["explanation"] or f"Hook weicht in {f['dimension']} vom Clip ab", "location": "clip",
            }  # fmt: skip
    return {
        "findings": findings,
        "dropped": dropped,
        "confirmed": confirmed,
        "model_confirmed": model_confirmed,
        "reject": reject,
        "heuristic": heuristic,
        "hook_source": meta["hook_source"],
        "prompt_version": p.prompt_version,
    }


__all__ = [
    "COUNTER_SCHEMA",
    "CONTEXT_AFTER_MAX",
    "CONTEXT_BEFORE",
    "CRITIC_KINDS",
    "CRITIQUE_SCHEMA",
    "SEVERITIES",
    "build_prompt",
    "check_counter_findings",
    "check_findings",
    "context_window",
    "counter_read_model",
    "critique",
    "text_hook",
]
