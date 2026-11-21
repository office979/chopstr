"""Mehrstufige Engine (T2): billig breit suchen, teuer nur für die Besten, danach die bestehenden Prüfungen.

  Stufe A (lokal, 0 €):   Signale der Heatmap plus Ereignisse des Szenen-Scans (``mm_scan``) ergeben Seeds.
  Stufe B (Vorfilter):     ``prefilter_v1`` (Modellstufe ``prefilter``, Standard Haiku) markiert je Transkriptblock
                           Kandidaten als Satzspannen mit Typ, kurzem Grund und Score. Richtlinie als
                           Cache-Block, Ereignisse als Pseudo-Sätze ohne Nummer.
  Stufe C (Editor):        ``editor_v1`` (Modellstufe ``editor``, Standard Sonnet) nur für die Top-K: exakte Grenzen
                           als Wortnummern, Hook (erste 1 bis 3 s), deutsche Copy (Titel, On-Screen-Text, Post-Text je
                           Plattform), Bewertung mit Belegen. Der Block ist Cache-Präfix, mehrere Kandidaten desselben
                           Blocks lesen ihn aus dem Cache.
  Danach:                  ``story_engine.evaluate_span`` mit den bestehenden Heilungen und Gates (die Bewertung des
                           Editors ersetzt den Aufruf von ``score_clip`` für genau diese Spanne, jede weitere
                           Modellfrage geht an die Stufe ``judge``), Auswahl mit Reserve, Kritiker (``roles.critic``)
                           und ClipCandidates wie im bisherigen Pfad. Der Claim-Check läuft danach unverändert in
                           ``analyze.auto_accept_blockers`` und im Copy-Schritt.

Volumen nach Länge: ``candidates_per_source_hour`` mal Quellstunden (zwischen ``min_candidates`` und
``max_candidates``), Short-Form-Mindestlänge ``min_len_s``. Alles aus ``implementation.engine`` der Policy v2.

Schalter: ``CHOPSTR_ENGINE=tiered`` (Prozess) oder ``implementation.engine.tiered`` (Policy); ``CHOPSTR_ENGINE=classic``
erzwingt den alten Pfad, der unverändert als Rückfall bleibt.

Budget: mit ``ledger`` (``costlog.RunLedger``) prüft jede Stufe vor dem Aufruf. Ist das Budget erreicht, fällt die
Stufe weg (Vorfilter: restliche Blöcke; Editor: der Kandidat geht mit den Grenzen des Vorfilters weiter) und
``report.search["tiered"]["skipped"]`` nennt es.

Pseudo-Sätze sind nie Schnittkante: Spannen zeigen immer auf echte Sätze bzw. Wortnummern, eine Wortnummer außerhalb
des Kandidaten wird verworfen, und jede Copy läuft durch ``mm_scan.strip_pseudo``.
"""

from __future__ import annotations

import logging
import math
import os
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .. import editorial, prompts
from ..costlog import BudgetExceeded
from ..providers_llm import SchemaError
from ..residency import ResidencyError
from . import mm_scan, payoff_search, signals, story_engine, story_score
from .segment import Sentence, chapterize, numbered, sentences_from_annotated, sentences_from_words

log = logging.getLogger("chopstr.tiered")

ENGINE_VERSION = "tiered_engine_v1"
ENGINE_ENV = "CHOPSTR_ENGINE"
SWITCH = "engine"
DEFAULTS: dict[str, Any] = {
    "tiered": False,
    "candidates_per_source_hour": 12.0,
    "min_candidates": 3,
    "max_candidates": 40,
    "editor_oversample": 1.5,
    "prefilter_block_s": 480.0,
    "prefilter_overlap_s": 30.0,
    "min_len_s": 8.0,
    "max_len_s": 75.0,
    "editor_context_sents": 4,
}
PREFILTER_TYPES = ("hot_take", "story", "punchline", "reaction", "conflict", "insight", "number", "emotional", "other")
PLATFORMS = ("tiktok", "reels", "shorts")
PREFILTER_MAX_PER_BLOCK = 8
SCORE_TOOL = "score_clip"

PREFILTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "first_sent": {"type": "integer"},
                    "last_sent": {"type": "integer"},
                    "type": {"type": "string", "enum": list(PREFILTER_TYPES)},
                    "why": {"type": "string"},
                    "score": {"type": "number", "minimum": 0, "maximum": 10},
                },
                "required": ["first_sent", "last_sent", "type", "score"],
            },
        }
    },
    "required": ["candidates"],
}
_SCORE = {"type": "integer", "minimum": 0, "maximum": 10}
EDITOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "keep": {"type": "boolean"},
        "start_word": {"type": "integer"},
        "end_word": {"type": "integer"},
        "hook": {
            "type": "object",
            "properties": {"start_word": {"type": "integer"}, "end_word": {"type": "integer"}, "text": {"type": "string"}},
            "required": ["start_word", "end_word", "text"],
        },
        "title": {"type": "string"},
        "onscreen_text": {"type": "string"},
        "post_text": {"type": "object", "properties": {p: {"type": "string"} for p in PLATFORMS}, "required": list(PLATFORMS)},
        "scores": {
            "type": "object",
            "properties": {k: _SCORE for k in story_engine.SCORE_KEYS},
            "required": list(story_engine.SCORE_KEYS),
        },
        "evidence": {"type": "object", "properties": {k: {"type": "string"} for k in story_engine.SCORE_KEYS}},
        "needs_earlier_context": {"type": "boolean"},
        "ends_before_answer": {"type": "boolean"},
        "unresolved_references": {"type": "array", "items": {"type": "string"}},
        "is_humor": {"type": "boolean"},
        "sensitive_topic": {"type": "boolean"},
        "why": {"type": "string"},
    },
    "required": ["keep", "start_word", "end_word", "hook", "title", "post_text", "scores"],
}


# -- Einstellungen ------------------------------------------------------------------------------------------
def engine_settings(policy: editorial.Policy | None) -> dict[str, Any]:
    """``implementation.engine`` der Policy über ``DEFAULTS``; Fassung 1 kennt den Abschnitt nicht (Standards)."""
    cfg = dict(DEFAULTS)
    raw = (policy.roh.get("implementation") or {}).get(SWITCH) if policy is not None and policy.version >= 2 else None
    if isinstance(raw, dict):
        cfg.update({k: raw[k] for k in DEFAULTS if k in raw})
    cfg["tiered"] = cfg["tiered"] is True
    for k in ("min_candidates", "max_candidates", "editor_context_sents"):
        cfg[k] = int(cfg[k])
    for k in ("candidates_per_source_hour", "editor_oversample", "prefilter_block_s", "prefilter_overlap_s", "min_len_s", "max_len_s"):
        cfg[k] = float(cfg[k])
    if not 0 < cfg["min_len_s"] < cfg["max_len_s"]:
        raise editorial.PolicyError("implementation.engine: 0 < min_len_s < max_len_s")
    if cfg["min_candidates"] < 1 or cfg["max_candidates"] < cfg["min_candidates"]:
        raise editorial.PolicyError("implementation.engine: 1 <= min_candidates <= max_candidates")
    return cfg


def engine_mode(policy: editorial.Policy | None = None) -> str:
    """``tiered`` oder ``classic``: ENV ``CHOPSTR_ENGINE`` vor dem Policy-Schalter."""
    env = os.environ.get(ENGINE_ENV, "").strip().lower()
    if env in ("tiered", "classic"):
        return env
    if env:
        raise ValueError(f"{ENGINE_ENV}={env!r} unbekannt, erlaubt: tiered, classic")
    return "tiered" if engine_settings(policy)["tiered"] else "classic"


def output_count(duration_s: float, cfg: Mapping[str, Any]) -> int:
    """Ausgabemenge nach Länge: Kandidaten je Quellstunde mal Stunden, begrenzt auf ``min``/``max``."""
    n = math.ceil(float(cfg["candidates_per_source_hour"]) * max(0.0, float(duration_s)) / 3600.0)
    return int(min(int(cfg["max_candidates"]), max(int(cfg["min_candidates"]), n)))


def prompt_versions(policy: editorial.Policy | None = None) -> list[str]:
    pol = _prompt_policy(policy)
    return [prompts.load_pinned(n, pol).prompt_version for n in ("prefilter", "editor", "mm_scan")]


def _prompt_policy(policy: editorial.Policy | None) -> editorial.Policy:
    """Die Prompts der Engine sind ab Fassung 2 gepinnt; unter Fassung 1 gelten die Pins der Fassung 2."""
    pol = policy or editorial.load()
    return pol if "prefilter" in pol.prompt_pins else editorial.load(2)


# -- Texte für die Prompts ------------------------------------------------------------------------------------
def _clock(t: float) -> str:
    return mm_scan._clock(t)


def block_text(block: Sequence[Sentence], events: Sequence[Mapping[str, Any]], min_intensity: float) -> str:
    """Block mit nummerierten Sätzen und Pseudo-Sätzen, zwischen ``<block>``-Begrenzern (Daten, Cache-Präfix)."""
    body = mm_scan.interleave(block, events, lambda s: numbered([s]), min_intensity)
    return f"<block>\n{body.replace('</block>', '[/block]')}\n</block>"


def candidate_words_text(
    words: Sequence[Mapping[str, Any]], sents: Sequence[Sentence], first: int, last: int, events: Sequence[Mapping[str, Any]],
    min_intensity: float,
) -> str:
    """Kandidat mit Umgebung: je Satz ``[S<idx>] (Sprecher) <wortnr>:<wort> ...``; Ereignisse ohne Wortnummer."""

    def line(s: Sentence) -> str:
        a, b = s.word_range
        toks = " ".join(f"{i}:{str(words[i].get('text', ''))}" for i in range(a, b + 1))
        return f"[S{s.idx}] ({s.speaker or '?'}) {toks}"

    body = mm_scan.interleave(list(sents[first : last + 1]), events, line, min_intensity)
    return f"<kandidat>\n{body.replace('</kandidat>', '[/kandidat]')}\n</kandidat>"


# -- Stufe B: Vorfilter ---------------------------------------------------------------------------------------
def _valid_spans(raw: Any, block: Sequence[Sentence], sents: Sequence[Sentence], cfg: Mapping[str, Any]) -> list[dict]:
    """Vorschläge des Vorfilters, nur gültige Satznummern im Block, plausible Länge (der Editor kürzt noch)."""
    lo, hi = block[0].idx, block[-1].idx
    out = []
    for c in (raw or {}).get("candidates") or []:
        try:
            f, t = int(c["first_sent"]), int(c["last_sent"])
            score = float(c.get("score", 0))
        except (KeyError, TypeError, ValueError):
            continue
        if not (lo <= f <= t <= hi):
            continue
        dur = sents[t].end - sents[f].start
        if dur < float(cfg["min_len_s"]) * 0.5 or dur > float(cfg["max_len_s"]) * 1.6:
            continue
        kind = str(c.get("type") or "other")
        out.append({
            "first_sent": f, "last_sent": t, "type": kind if kind in PREFILTER_TYPES else "other",
            "why": mm_scan.strip_pseudo(str(c.get("why") or ""))[:160], "score": max(0.0, min(10.0, score)), "source": "prefilter",
        })  # fmt: skip
    return out[:PREFILTER_MAX_PER_BLOCK]


def _local_prefilter(
    block: Sequence[Sentence], sents: Sequence[Sentence], words: Sequence[Mapping[str, Any]], heat: Mapping[str, Any] | None,
    pol: editorial.Policy | None, cfg: Mapping[str, Any],
) -> list[dict]:
    """Ohne Sprachmodell (Heuristik-Provider): deterministische Payoff-Suche, sonst Fenster um die Seeds."""
    out: list[dict] = []
    if pol is not None and pol.version >= 2:
        try:
            found = payoff_search.search_moments(list(block), pol, heat, words=list(words))
            for p in found.get("proposals") or []:
                out.append({"first_sent": int(p["first_sent"]), "last_sent": int(p["last_sent"]), "type": "other",
                            "why": "Payoff-Suche ohne Modell", "score": 5.0, "source": "local_search"})  # fmt: skip
        except (editorial.PolicyError, KeyError, TypeError, ValueError):
            out = []
    if out:
        return out[:PREFILTER_MAX_PER_BLOCK]
    target = (float(cfg["min_len_s"]) + float(cfg["max_len_s"])) / 2.0
    for seed in story_engine.seeds_from_heat(dict(heat or {})):
        s0 = next((s for s in block if s.start <= seed <= s.end + 1.0), None)
        if s0 is None:
            continue
        last = s0.idx
        while last + 1 <= block[-1].idx and sents[last].end - s0.start < target:
            last += 1
        out.append({"first_sent": s0.idx, "last_sent": last, "type": "other", "why": "Seed ohne Modell", "score": 4.0, "source": "local_seed"})
    return out[:PREFILTER_MAX_PER_BLOCK]


def _rank_prefilter(cands: list[dict], sents: Sequence[Sentence], seeds: Sequence[float], events: Sequence[Mapping[str, Any]]) -> list[dict]:
    """Rangfolge vor dem Editor: Score, +1 mit Seed in der Spanne, +1 mit starkem Ereignis bis 3 s nach dem Ende;
    überlappende Spannen (ab 60 % am kürzeren) nur einmal."""
    for c in cands:
        a, b = sents[c["first_sent"]].start, sents[c["last_sent"]].end
        bonus = (1.0 if any(a <= s <= b for s in seeds) else 0.0) + (
            1.0 if any(a <= float(e["t_start"]) <= b + 3.0 and float(e["intensity"]) >= 0.6 and e["type"] != "speaker_change" for e in events) else 0.0
        )
        c["rank_score"] = round(float(c["score"]) + bonus, 3)
    kept: list[dict] = []
    for c in sorted(cands, key=lambda x: (-x["rank_score"], x["first_sent"])):
        a, b = sents[c["first_sent"]].start, sents[c["last_sent"]].end
        if any(story_engine.gemeinsamer_anteil(a, b, sents[k["first_sent"]].start, sents[k["last_sent"]].end) >= 0.6 for k in kept):
            continue
        kept.append(c)
    return kept


# -- Stufe C: Editor ----------------------------------------------------------------------------------------
def _sentence_of_word(sents: Sequence[Sentence], w: int) -> int | None:
    for s in sents:
        if s.word_range[0] <= w <= s.word_range[1]:
            return s.idx
    return None


def _obj(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


def _score(v: Any) -> int:
    """Wert 0 bis 10; Unlesbares (z. B. „8/10“ aus der CLI ohne Schema-Zwang) zählt 0."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0
    return int(max(0, min(10, round(f)))) if math.isfinite(f) else 0


def apply_editor(out: Mapping[str, Any], sents: Sequence[Sentence], win_first: int, win_last: int) -> dict | None:
    """Antwort des Editors prüfen und in einen Vorschlag für ``evaluate_span`` übersetzen; ``None`` heißt verwerfen.

    Wortnummern müssen im Kandidatenfenster liegen (echte Wörter, nie Pseudo-Sätze). Die Spanne wird auf
    Satzgrenzen gelegt, weil die Gates an Satzgrenzen prüfen; ein Schnitt mitten im Satz steht in
    ``cut_inside_sentence``."""
    if not isinstance(out, Mapping) or not out.get("keep", True):
        return None
    lo, hi = sents[win_first].word_range[0], sents[win_last].word_range[1]
    try:
        sw, ew = int(out["start_word"]), int(out["end_word"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (lo <= sw <= ew <= hi):
        return None
    first, last = _sentence_of_word(sents, sw), _sentence_of_word(sents, ew)
    if first is None or last is None:
        return None
    inside = []
    if sw != sents[first].word_range[0]:
        inside.append("start")
    if ew != sents[last].word_range[1]:
        inside.append("end")
    hook = _obj(out.get("hook"))
    try:
        hs, he = int(hook.get("start_word", sw)), int(hook.get("end_word", sw))
    except (TypeError, ValueError):
        hs, he = sw, sw
    if not (sw <= hs <= he <= ew):
        hs, he = sents[first].word_range[0], sents[first].word_range[1]
    post = {p: mm_scan.strip_pseudo(str(_obj(out.get("post_text")).get(p) or "")) for p in PLATFORMS}
    return {
        "first_sent": first, "last_sent": last, "start_word": sw, "end_word": ew, "cut_inside_sentence": inside,
        "hook": {"start_word": hs, "end_word": he, "text": mm_scan.strip_pseudo(str(hook.get("text") or ""))},
        "title": mm_scan.strip_pseudo(str(out.get("title") or "")),
        "onscreen_text": mm_scan.strip_pseudo(str(out.get("onscreen_text") or "")),
        "post_text": post,
        "scores": {k: _score(_obj(out.get("scores")).get(k)) for k in story_engine.SCORE_KEYS},
        "evidence": {k: mm_scan.strip_pseudo(str(_obj(out.get("evidence")).get(k) or "")) for k in story_engine.SCORE_KEYS},
        "flags": {
            "needs_earlier_context": bool(out.get("needs_earlier_context")), "ends_before_answer": bool(out.get("ends_before_answer")),
            "unresolved_references": [str(x) for x in (out.get("unresolved_references") or [])][:10],
            "is_humor": bool(out.get("is_humor")), "sensitive_topic": bool(out.get("sensitive_topic")),
        },
        "why": mm_scan.strip_pseudo(str(out.get("why") or ""))[:240],
    }  # fmt: skip


def _local_editor(c: Mapping[str, Any], sents: Sequence[Sentence]) -> dict:
    """Ohne Editor (Heuristik oder Budget): Grenzen des Vorfilters, Hook = erster Satz, Titel aus dem Anfang."""
    s0 = sents[c["first_sent"]]
    words = s0.text.split()
    title = mm_scan.strip_pseudo(" ".join(words[:8]))
    return {
        "first_sent": int(c["first_sent"]), "last_sent": int(c["last_sent"]),
        "start_word": s0.word_range[0], "end_word": sents[c["last_sent"]].word_range[1], "cut_inside_sentence": [],
        "hook": {"start_word": s0.word_range[0], "end_word": s0.word_range[1], "text": title},
        "title": title, "onscreen_text": "", "post_text": {p: mm_scan.strip_pseudo(s0.text) for p in PLATFORMS},
        "scores": None, "evidence": {}, "flags": {}, "why": str(c.get("why") or ""), "local": True,
    }  # fmt: skip


class EditorScoreLLM:
    """Gibt ``evaluate_span`` die Bewertung des Editors als Antwort auf ``score_clip`` für genau seine Spanne.

    Jede andere Frage (Neubewertung nach einer Heilung, Bestätigung einer späteren Relativierung, Kritiker) geht an
    ``judge``; ist das Budget erreicht, meldet er ``LLMBudgetExceeded``, das ``evaluate_span`` schon behandelt."""

    def __init__(self, judge: Any, ledger: Any = None):
        self._judge, self._ledger = judge, ledger
        self.precomputed: dict[tuple[int, int], dict] = {}

    def __getattr__(self, name: str) -> Any:
        return getattr(self._judge, name)

    @property
    def is_heuristic(self) -> bool:
        return bool(getattr(self._judge, "is_heuristic", False))

    def structured(self, system: str, user: str, schema: dict, tool_name: str, prompt_version: str, **kw: Any) -> dict:
        if tool_name == SCORE_TOOL:
            idx = [int(x) for x in re.findall(r"^\[(\d+)\]", user, re.MULTILINE)]
            if idx and (min(idx), max(idx)) in self.precomputed:
                return dict(self.precomputed[(min(idx), max(idx))])
        if self._ledger is not None:
            try:
                self._ledger.check(kw.get("stage") or kw.get("job_type") or "judge")
            except BudgetExceeded as exc:
                raise story_engine.LLMBudgetExceeded(str(exc)) from exc
        return self._judge.structured(system, user, schema, tool_name, prompt_version, **kw)


def score_response(ed: Mapping[str, Any]) -> dict:
    """Bewertung des Editors im Format von ``score_clip`` (die alten fünf, 0 bis 10; ``_harmonise`` rechnet um)."""
    flags = dict(ed.get("flags") or {})
    out: dict[str, Any] = {
        "needs_earlier_context": bool(flags.get("needs_earlier_context")),
        "ends_before_answer": bool(flags.get("ends_before_answer")),
        "unresolved_references": list(flags.get("unresolved_references") or []),
        "is_humor": bool(flags.get("is_humor")),
        "sensitive_topic": bool(flags.get("sensitive_topic")),
        "suggested_title_card": str(ed.get("title") or ""),
        "why": str(ed.get("why") or ""),
    }
    for k in story_engine.SCORE_KEYS:
        out[k] = int((ed.get("scores") or {}).get(k, 0))
        out[f"{k}_evidence"] = str((ed.get("evidence") or {}).get(k) or "")
    return out


# -- Lauf -----------------------------------------------------------------------------------------------------
def _tier(llm: Any, tier: str) -> Any:
    fn = getattr(llm, "with_tier", None)
    return fn(tier) if callable(fn) else llm


def run(
    words: list[dict],
    brief: dict[str, Any] | None,
    brand: dict[str, Any] | None,
    heat_payload: dict[str, Any] | None,
    llm: Any,
    weights: dict[str, float] | None = None,
    on_progress: Callable[[int, int, int], None] | None = None,
    silence: Any = None,
    events: Sequence[Mapping[str, Any]] | None = None,
    ledger: Any = None,
    policy: editorial.Policy | None = None,
    duration_s: float | None = None,
) -> story_engine.DetectReport:
    """Mehrstufiger Lauf; liefert einen ``DetectReport`` im selben Vertrag wie ``story_engine.run``."""
    brief = dict(brief or {})
    brand = dict(brand or {})
    pol = policy or story_engine._active_policy()
    cfg = engine_settings(pol)
    mm_cfg = mm_scan.settings_from_policy(pol)
    min_int = float(mm_cfg["min_intensity"])
    weights = dict(weights) if weights else story_engine.resolve_weights(brand.get("learned_weights"))
    heuristic = bool(getattr(llm, "is_heuristic", False))
    if story_engine._sentence_rule(pol) == "v1":
        sents = sentences_from_words(words, silence=silence)
    else:
        args = story_engine._cut_args(words, pol)
        sents = sentences_from_annotated(words) or sentences_from_words(
            words, rule=args["rule"], max_s=args["max_s"], max_words=args["max_words"], silence=silence
        )
    heat = dict(heat_payload or {})
    heat_cfg = signals.text_heat_settings(pol)
    if heat_cfg is not None:
        heat = signals.payload_with_text_v2(heat, words, heat_cfg)
    evs = list(events if events is not None else heat.get("events") or [])
    if evs and "event_values" not in heat:
        heat = mm_scan.apply_to_heat(heat, evs, min_int)
    seeds = story_engine.seeds_from_heat(heat)
    dur = float(duration_s or (sents[-1].end if sents else 0.0))
    n_out = output_count(dur, cfg)
    n_editor = max(n_out, math.ceil(n_out * float(cfg["editor_oversample"])))
    ppol = _prompt_policy(pol)
    pre_llm, ed_llm, judge_llm = _tier(llm, "prefilter"), _tier(llm, "editor"), _tier(llm, "judge")
    report = story_engine.DetectReport(
        prompt_versions=prompt_versions(pol), model_id=getattr(ed_llm, "model", lambda: "")(), provider=getattr(llm, "provider", ""),
        weights=weights, engine=ENGINE_VERSION,
    )  # fmt: skip
    report.nlp_status = story_engine.nlp_status_for(pol)
    info: dict[str, Any] = {
        "version": ENGINE_VERSION, "output_count": n_out, "editor_k": n_editor, "duration_s": round(dur, 2),
        "min_len_s": cfg["min_len_s"], "max_len_s": cfg["max_len_s"], "events": len(evs), "seeds": len(seeds),
        "blocks": 0, "prefilter": {"calls": 0, "candidates": 0, "local": heuristic}, "editor": {"calls": 0, "local": 0, "rejected": 0},
        "skipped": [], "models": {
            "prefilter": getattr(pre_llm, "model", lambda: "")(), "editor": getattr(ed_llm, "model", lambda: "")(),
            "judge": getattr(judge_llm, "model", lambda: "")(),
        },
    }  # fmt: skip
    report.search["tiered"] = info
    if not sents:
        return report

    # Stufe B: Vorfilter je Block
    blocks = chapterize(sents, float(cfg["prefilter_block_s"]), float(cfg["prefilter_overlap_s"]))
    report.chapters = info["blocks"] = len(blocks)
    report.chapters_with_seeds = sum(1 for b in blocks if any(b[0].start <= s <= b[-1].end for s in seeds))
    system = story_score.system_prompt()
    policy_text = pol.als_prompt_text() if pol is not None else None
    pf = prompts.load_pinned("prefilter", ppol)
    max_per_block = max(3, min(PREFILTER_MAX_PER_BLOCK, math.ceil(n_editor * 2 / max(1, len(blocks)))))
    found: list[dict] = []
    block_of: dict[tuple[int, int], int] = {}
    budget_stop = False
    for n, block in enumerate(blocks):
        got: list[dict] = []
        if heuristic or budget_stop:
            got = _local_prefilter(block, sents, words, heat, pol, cfg)
        else:
            try:
                if ledger is not None:
                    ledger.check("prefilter")
                user = pf.render(
                    audience=brief.get("audience"), wanted=brief.get("wanted"), exclude=brief.get("exclude"),
                    platforms="TikTok, Reels, Shorts", min_len_s=int(cfg["min_len_s"]), max_len_s=int(cfg["max_len_s"]),
                    max_candidates=max_per_block, block_start=_clock(block[0].start), block_end=_clock(block[-1].end),
                )  # fmt: skip
                raw = pre_llm.structured(
                    system, user, PREFILTER_SCHEMA, pf.tool or "prefilter_moments", pf.prompt_version, job_type="llm_propose",
                    policy_block=policy_text, cache_prefix=block_text(block, evs, min_int), stage="prefilter",
                )  # fmt: skip
                info["prefilter"]["calls"] += 1
                got = _valid_spans(raw, block, sents, cfg)
            except BudgetExceeded as exc:
                budget_stop = True
                info["skipped"].append({"stage": "prefilter", "from_block": n, "reason": "budget_exhausted", "detail": exc.detail})
                got = _local_prefilter(block, sents, words, heat, pol, cfg)
            except ResidencyError:
                raise
            except (SchemaError, RuntimeError, ValueError, TypeError, KeyError) as exc:
                # Kaputte Antwort oder Fehler des Anbieters: dieser Block läuft lokal, der Lauf geht weiter
                info["prefilter"].setdefault("errors", []).append({"block": n, "error": exc.__class__.__name__, "detail": str(exc)[:160]})
                got = _local_prefilter(block, sents, words, heat, pol, cfg)
        for c in got:
            block_of.setdefault((c["first_sent"], c["last_sent"]), n)
        found.extend(got)
        if on_progress:
            on_progress(n + 1, len(blocks) + 1, len(found))
    report.proposals = info["prefilter"]["candidates"] = len(found)
    ranked = _rank_prefilter(found, sents, seeds, evs)
    top, rest = ranked[:n_editor], ranked[n_editor:]
    for c in rest:
        report.discarded.append({"reason": "prefilter_rank", "stage": "prefilter", "first_sent": c["first_sent"], "last_sent": c["last_sent"],
                                 "rank_score": c["rank_score"]})  # fmt: skip

    # Stufe C: Editor nur für die Top-K, gruppiert nach Block (gemeinsamer Cache-Präfix)
    ed_prompt = prompts.load_pinned("editor", ppol)
    adapter = EditorScoreLLM(judge_llm, ledger)
    ctx_n = int(cfg["editor_context_sents"])
    raw_cands: list[story_engine.CandidateResult] = []
    gate_rejected: list[story_engine.CandidateResult] = []
    seen: set[tuple[int, int]] = set()
    editor_stop = heuristic
    top.sort(key=lambda c: (block_of.get((c["first_sent"], c["last_sent"]), 0), c["first_sent"]))
    with story_engine.tiered_limits(cfg["min_len_s"], cfg["max_len_s"], n_out):
        for c in top:
            bno = block_of.get((c["first_sent"], c["last_sent"]), 0)
            win_first, win_last = max(0, c["first_sent"] - ctx_n), min(len(sents) - 1, c["last_sent"] + ctx_n)
            ed: dict | None = None
            if not editor_stop:
                try:
                    if ledger is not None:
                        ledger.check("editor")
                    user = ed_prompt.render(
                        audience=brief.get("audience"), platforms="TikTok, Reels, Shorts", address=brand.get("address") or "du",
                        country=brand.get("country") or "AT", min_len_s=int(cfg["min_len_s"]), max_len_s=int(cfg["max_len_s"]),
                        prefilter_note=f"Satz {c['first_sent']} bis {c['last_sent']}, Typ {c['type']}: {c.get('why') or '-'}",
                        candidate_words=candidate_words_text(words, sents, win_first, win_last, evs, min_int),
                    )  # fmt: skip
                    out = ed_llm.structured(
                        system, user, EDITOR_SCHEMA, ed_prompt.tool or "edit_clip", ed_prompt.prompt_version, job_type="llm_copy",
                        policy_block=policy_text, cache_prefix=block_text(blocks[bno], evs, min_int), stage="editor",
                    )  # fmt: skip
                    info["editor"]["calls"] += 1
                    ed = apply_editor(out, sents, win_first, win_last)
                    if ed is None:
                        info["editor"]["rejected"] += 1
                        report.discarded.append({"reason": "editor_rejected", "stage": "editor", "first_sent": c["first_sent"], "last_sent": c["last_sent"]})
                        continue
                except BudgetExceeded as exc:
                    editor_stop = True
                    info["skipped"].append({"stage": "editor", "reason": "budget_exhausted", "detail": exc.detail})
                except ResidencyError:
                    raise
                except (SchemaError, RuntimeError, ValueError, TypeError, KeyError) as exc:
                    info["editor"].setdefault("errors", []).append({"first_sent": c["first_sent"], "error": exc.__class__.__name__, "detail": str(exc)[:160]})
            if ed is None:
                ed = _local_editor(c, sents)
                info["editor"]["local"] += 1
            if ed.get("scores") is not None:
                adapter.precomputed[(ed["first_sent"], ed["last_sent"])] = score_response(ed)
            proposal = {
                "first_sent": ed["first_sent"], "last_sent": ed["last_sent"], "structure": "hook_build_payoff",
                "why": ed.get("why") or c.get("why") or "", "prompt_version": ed_prompt.prompt_version,
            }  # fmt: skip
            try:
                res = story_engine.evaluate_span(words, sents, proposal, brief, adapter, weights, heat)
            except story_engine.LLMBudgetExceeded:
                report.discarded.append({"reason": "llm_budget", "stage": "gates", "first_sent": ed["first_sent"], "last_sent": ed["last_sent"]})
                continue
            if isinstance(res, dict):
                report.discarded.append({**res, "stage": "gates"})
                continue
            key = (res.first_sent, res.last_sent)
            if key in seen:
                report.discarded.append({"reason": "same_result", "stage": "gates", "first_sent": key[0], "last_sent": key[1]})
                continue
            seen.add(key)
            res.rubric["tiered"] = {
                "prefilter": {k: c.get(k) for k in ("first_sent", "last_sent", "type", "why", "score", "rank_score", "source")},
                "editor": {k: ed.get(k) for k in ("start_word", "end_word", "cut_inside_sentence", "hook", "title", "onscreen_text",
                                                  "post_text", "scores", "local")},
                "events": [e for e in evs if sents[res.first_sent].start <= float(e["t_start"]) <= sents[res.last_sent].end + 3.0][:20],
            }  # fmt: skip
            decision = res.rubric.get("quality_gate_decision") or {}
            if story_engine.gates_wired(pol) is not None and decision.get("decision") == "rejected":
                report.discarded.append({"reason": str(decision.get("reason")), "stage": "gates", "first_sent": res.first_sent,
                                         "last_sent": res.last_sent, "detail": str(decision.get("detail") or "")})  # fmt: skip
                gate_rejected.append(res)
                continue
            raw_cands.append(res)
        critic_on = pol is not None and editorial.critic_enabled(pol)
        report.candidates, dropped, reserve = story_engine.select_with_reserve(
            raw_cands, n_out, pol=pol, heuristic=heuristic, reserve_size=story_engine.RESERVE_SIZE if critic_on else 0
        )
    report.verworfen = [c for c in raw_cands if all(c is not k for k in report.candidates)] + gate_rejected
    report.discarded.extend(dropped)
    if story_engine.gates_wired(pol) is not None:
        report.gate_rejections = story_engine.gate_rejection_rates([*raw_cands, *gate_rejected])
    if critic_on:
        try:
            story_engine.apply_critic(report, words, sents, adapter, pol, n_out, evaluated=len(raw_cands) + len(gate_rejected), reserve=reserve)
        except story_engine.LLMBudgetExceeded:
            info["skipped"].append({"stage": "critic", "reason": "budget_exhausted"})
    if ledger is not None:
        info["skipped"].extend(x for x in ledger.skipped if x not in info["skipped"])
    if pol is not None and pol.version >= 2:
        story_engine.attach_clip_candidates(report, words, sents, pol, brief)
    if on_progress:
        on_progress(len(blocks) + 1, len(blocks) + 1, len(report.candidates))
    return report


__all__ = [
    "DEFAULTS",
    "EDITOR_SCHEMA",
    "ENGINE_ENV",
    "ENGINE_VERSION",
    "PREFILTER_SCHEMA",
    "EditorScoreLLM",
    "apply_editor",
    "block_text",
    "candidate_words_text",
    "engine_mode",
    "engine_settings",
    "output_count",
    "prompt_versions",
    "run",
    "score_response",
]
