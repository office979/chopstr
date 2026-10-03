"""Harness für den redaktionellen Testsatz editorial_v1.

Die Fixtures unter ``cases/`` beschreiben, was ein Clip aus dem jeweiligen Material einhalten muss.
Ein Teil davon lässt sich gegen den heutigen Code prüfen (``tests/test_editorial_v1.py``). Der Rest
braucht Schnittstellen, die es noch nicht gibt: das ``ClipCandidate``-Schema aus Abschnitt 21 des
Master-Prompts mit ``segments[]``, ``removed_spans[]``, ``boundary_confidence``,
``assessment_uncertainties`` und einer Entscheidung mit Grund. Für diese späteren Arbeitspakete
stehen hier die Prüfungen bereit. Jede Funktion wirft ``AssertionError`` mit einer deutschen
Begründung, wenn der Clip den Fall verletzt, und gibt sonst ``None`` zurück.

Begriffe:

* Wortindex: Position in ``case["words"]``. Alle Bereiche sind inklusiv, ``[a, b]``.
* Out-Point ``i``: der Clip (oder ein Segment) endet mit Wort ``i`` als letztem behaltenem Wort.
* In-Point ``i``: der Clip (oder ein Segment) beginnt mit Wort ``i`` als erstem behaltenem Wort.
* Segment: Eintrag aus ``ClipCandidate.segments`` in Abspielreihenfolge. Behaltene Wörter kommen aus
  ``word_ids``, sonst aus ``source_in`` und ``source_out`` (Wortmitte innerhalb der Grenzen).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

VERSION = "editorial_v1"
CASES_DIR = Path(__file__).resolve().parent / "cases"

REQUIRED_CASE_IDS = (
    "negation_sentence_end",
    "conditional_recommendation",
    "later_self_correction",
    "reported_position",
    "unresolved_pronoun",
    "misrecognized_number_or_name",
    "silent_demonstration",
    "emotional_pause",
    "punchline_setup",
    "speaker_turn_attribution",
    "weak_material",
    "near_duplicate_candidates",
    "imprecise_timestamps",
    "instruction_in_transcript",
)

REQUIRED_EXPECTED_KEYS = (
    "must_include_word_ranges",
    "forbidden_out_points",
    "forbidden_in_points",
    "expect_reject",
    "protected_spans",
    "pronouns_to_resolve",
    "instruction_must_be_ignored",
    "boundary_confidence",
    "near_duplicate_candidates",
)

# Die sechs Grundtypen aus dem Auftrag plus ``visual_demonstration`` für stilles Zeigen
# (Master-Prompt Abschnitt 18). Eine stille Demonstration ist keine dramaturgische Pause.
WORD_SPAN_TYPES = ("negation", "condition", "correction", "attribution", "definition")
TIME_SPAN_TYPES = ("pause_dramatic", "visual_demonstration")
PROTECTED_SPAN_TYPES = WORD_SPAN_TYPES + TIME_SPAN_TYPES

# ClipCandidate nach Master-Prompt Abschnitt 21. Die Felder müssen vorhanden sein, ``None`` ist als
# Wert erlaubt („fehlende Datenbasis als null“).
CANDIDATE_FIELDS = (
    "candidate_id", "source_asset_id", "source_version", "objective", "audience_context",
    "audience_context_provenance", "central_idea", "viewer_promise", "payoff_description",
    "narrative_type", "opening_source_span", "required_context_spans", "payoff_source_span",
    "segments", "removed_spans", "meaning_dependencies", "unresolved_questions",
    "quality_gate_results", "editorial_subscores", "assessment_uncertainties", "decision",
    "decision_reason", "alternatives_considered", "model_version", "prompt_version", "policy_version",
)  # fmt: skip
SEGMENT_FIELDS = (
    "segment_id", "source_in", "source_out", "output_in", "output_out", "speaker_id", "word_ids",
    "verbatim_text", "editorial_role", "boundary_confidence",
)  # fmt: skip
REMOVED_SPAN_FIELDS = ("source_in", "source_out", "removal_reason", "protected_context_check")

REJECT_DECISIONS = frozenset({"reject", "rejected", "discard", "discarded"})
ACCEPT_DECISIONS = frozenset({"accept", "accepted", "keep", "kept", "cut"})

# Unsichere Schnittkanten: welche Angaben gelten als ehrlich niedrig?
LOW_CONFIDENCE_LABELS = frozenset({"low", "unknown"})
LOW_CONFIDENCE_MAX = 0.5

TIME_EPS_S = 0.01
SENTENCE_FINAL = (".", "!", "?")


# -- Laden und Schema ----------------------------------------------------------------------------


def load_cases(version: str = VERSION) -> list[dict]:
    """Alle Fälle einer Version, sortiert nach ``id``."""
    if version != VERSION:
        raise ValueError(f"Dieser Harness kennt nur {VERSION}, nicht {version}")
    cases = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(CASES_DIR.glob("*.json"))]
    return sorted(cases, key=lambda c: c["id"])


def load_case(case_id: str) -> dict:
    path = CASES_DIR / f"{case_id}.json"
    if not path.is_file():
        raise KeyError(f"Fall {case_id} existiert in {VERSION} nicht")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_case(case: Mapping[str, Any]) -> list[str]:
    """Strukturprüfung eines Falls. Leere Liste heißt gültig."""
    problems: list[str] = []
    for key in ("id", "version", "title", "description", "words", "expected"):
        if key not in case:
            problems.append(f"Feld {key} fehlt")
    if problems:
        return problems
    if case["version"] != VERSION:
        problems.append(f"version ist {case['version']}, erwartet {VERSION}")
    words = case["words"]
    n = len(words)
    if not 40 <= n <= 180:
        problems.append(f"{n} Wörter, erlaubt sind 40 bis 180")
    prev_start = -1.0
    for i, w in enumerate(words):
        for key in ("text", "start", "end", "speaker"):
            if key not in w:
                problems.append(f"Wort {i}: Feld {key} fehlt")
        if not str(w.get("text", "")).strip():
            problems.append(f"Wort {i}: leerer Text")
        start, end = float(w.get("start", 0.0)), float(w.get("end", 0.0))
        if end < start:
            problems.append(f"Wort {i}: Ende vor Anfang")
        if start < prev_start:
            problems.append(f"Wort {i}: Anfang liegt vor dem Anfang des vorigen Wortes")
        prev_start = start
        conf = w.get("asr_confidence")
        if conf is not None and not 0.0 <= float(conf) <= 1.0:
            problems.append(f"Wort {i}: asr_confidence außerhalb von 0 bis 1")

    exp = case["expected"]
    for key in REQUIRED_EXPECTED_KEYS:
        if key not in exp:
            problems.append(f"expected.{key} fehlt")

    def idx_ok(i: Any, where: str) -> None:
        if not isinstance(i, int) or not 0 <= i < n:
            problems.append(f"{where}: Wortindex {i!r} außerhalb von 0 bis {n - 1}")

    def range_ok(r: Any, where: str) -> None:
        if not (isinstance(r, list) and len(r) == 2):
            problems.append(f"{where}: Bereich {r!r} ist kein Paar")
            return
        idx_ok(r[0], where)
        idx_ok(r[1], where)
        if isinstance(r[0], int) and isinstance(r[1], int) and r[0] > r[1]:
            problems.append(f"{where}: Bereich {r!r} ist umgekehrt")

    for r in exp.get("must_include_word_ranges", []):
        range_ok(r, "must_include_word_ranges")
    for key in ("forbidden_out_points", "forbidden_in_points", "sentence_end_after", "no_sentence_end_after"):
        for i in exp.get(key, []) or []:
            idx_ok(i, key)
    rej = exp.get("expect_reject")
    if (
        not isinstance(rej, Mapping)
        or not isinstance(rej.get("value"), bool)
        or not str(rej.get("reason", "")).strip()
    ):
        problems.append("expect_reject braucht value (bool) und einen Grund")
    for p in exp.get("protected_spans", []):
        if p.get("type") not in PROTECTED_SPAN_TYPES:
            problems.append(f"protected_spans: unbekannter Typ {p.get('type')!r}")
        range_ok(p.get("word_range"), f"protected_spans[{p.get('type')}]")
        if p.get("type") in TIME_SPAN_TYPES and not p.get("time_range"):
            problems.append(f"protected_spans[{p.get('type')}]: time_range fehlt")
    for p in exp.get("pronouns_to_resolve", []):
        idx_ok(p.get("word"), "pronouns_to_resolve")
        range_ok(p.get("antecedent_word_range"), "pronouns_to_resolve")
    instr = exp.get("instruction_must_be_ignored")
    if instr is not None:
        range_ok(instr.get("word_range"), "instruction_must_be_ignored")
        if not instr.get("compliance_markers"):
            problems.append("instruction_must_be_ignored: compliance_markers fehlen")
    bc = exp.get("boundary_confidence")
    if bc is not None:
        range_ok(bc.get("word_range"), "boundary_confidence")
        if bc.get("expected") not in LOW_CONFIDENCE_LABELS:
            problems.append("boundary_confidence.expected muss low oder unknown sein")
    nd = exp.get("near_duplicate_candidates")
    if nd is not None:
        spans = nd.get("spans", [])
        if len(spans) != 2:
            problems.append("near_duplicate_candidates braucht genau zwei Spannen")
        for s in spans:
            range_ok(s.get("word_range"), "near_duplicate_candidates")
        if nd.get("max_survivors") != 1:
            problems.append("near_duplicate_candidates.max_survivors muss 1 sein")
    return problems


# -- Hilfen ----------------------------------------------------------------------------------------


def segment_from_word_range(case: Mapping[str, Any], first: int, last: int, **extra: Any) -> dict:
    """Ein Segment im Format aus Abschnitt 21 für die Wörter ``first`` bis ``last``.

    Für Tests und spätere Adapter. Felder, die der Harness nicht kennt, bleiben ``None``."""
    words = case["words"]
    seg = {
        "segment_id": extra.pop("segment_id", f"seg_{first}_{last}"),
        "source_in": float(words[first]["start"]),
        "source_out": float(words[last]["end"]),
        "output_in": None,
        "output_out": None,
        "speaker_id": words[first].get("speaker"),
        "word_ids": list(range(first, last + 1)),
        "verbatim_text": " ".join(str(w["text"]) for w in words[first : last + 1]),
        "editorial_role": "body",
        "boundary_confidence": None,
    }
    seg.update(extra)
    return seg


def segment_word_ids(case: Mapping[str, Any], segment: Mapping[str, Any]) -> list[int]:
    """Behaltene Wortindizes eines Segments, aufsteigend."""
    if segment.get("word_ids") is not None:
        return sorted(int(i) for i in segment["word_ids"])
    a, b = float(segment["source_in"]), float(segment["source_out"])
    out = []
    for i, w in enumerate(case["words"]):
        mid = (float(w["start"]) + float(w["end"])) / 2.0
        if a - TIME_EPS_S <= mid <= b + TIME_EPS_S:
            out.append(i)
    return out


def _playback_order(case: Mapping[str, Any], segments: Sequence[Mapping[str, Any]]) -> list[int]:
    seq: list[int] = []
    for seg in segments:
        seq.extend(segment_word_ids(case, seg))
    return seq


def _kept(case: Mapping[str, Any], segments: Sequence[Mapping[str, Any]]) -> set[int]:
    return set(_playback_order(case, segments))


def _text(case: Mapping[str, Any], a: int, b: int) -> str:
    return " ".join(str(w["text"]) for w in case["words"][a : b + 1])


def _time_range(case: Mapping[str, Any], span: Mapping[str, Any]) -> tuple[float, float]:
    if span.get("time_range"):
        t0, t1 = span["time_range"]
        return float(t0), float(t1)
    a, b = span["word_range"]
    return float(case["words"][a]["start"]), float(case["words"][b]["end"])


def _overlap_s(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _share_of_shorter(a: tuple[int, int], b: tuple[int, int]) -> float:
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]) + 1)
    shorter = min(a[1] - a[0] + 1, b[1] - b[0] + 1)
    return inter / shorter if shorter > 0 else 0.0


# -- Prüfungen gegen einen Schnittplan -------------------------------------------------------------


def assert_clip_respects_case(case: Mapping[str, Any], segments: Sequence[Mapping[str, Any]]) -> None:
    """Prüft einen Schnittplan (``ClipCandidate.segments`` in Abspielreihenfolge) gegen den Fall.

    Geprüft werden: Pflichtbereiche vollständig enthalten, kein Segment beginnt auf einem verbotenen
    In-Point oder endet auf einem verbotenen Out-Point, Schutzbereiche nicht teilweise geschnitten,
    Pronomen nur mit Bezug, Pausen und stilles Zeigen nicht herausgeschnitten, keine falsche
    Frage-Antwort-Zuordnung, Pointe samt Setup enthalten."""
    cid = case["id"]
    exp = case["expected"]
    assert segments, f"{cid}: Schnittplan ohne Segmente"
    for seg in segments:
        assert float(seg["source_out"]) >= float(seg["source_in"]), (
            f"{cid}: Segment {seg.get('segment_id')} endet vor seinem Anfang"
        )
    kept = _kept(case, segments)
    assert kept, f"{cid}: Schnittplan enthält kein Wort"

    for a, b in exp.get("must_include_word_ranges", []):
        missing = [i for i in range(a, b + 1) if i not in kept]
        assert not missing, f"{cid}: Pflichtbereich „{_text(case, a, b)}“ fehlt teilweise (Wörter {missing})"

    forbidden_in = set(exp.get("forbidden_in_points", []))
    forbidden_out = set(exp.get("forbidden_out_points", []))
    for seg in segments:
        ids = segment_word_ids(case, seg)
        if not ids:
            continue
        first, last = ids[0], ids[-1]
        assert first not in forbidden_in, (
            f"{cid}: Segment beginnt auf verbotenem In-Point „{case['words'][first]['text']}“ (Wort {first})"
        )
        assert last not in forbidden_out, (
            f"{cid}: Segment endet auf verbotenem Out-Point „{case['words'][last]['text']}“ (Wort {last})"
        )

    for span in exp.get("protected_spans", []):
        a, b = span["word_range"]
        if span["type"] in WORD_SPAN_TYPES:
            inside = [i for i in range(a, b + 1) if i in kept]
            if inside:
                missing = [i for i in range(a, b + 1) if i not in kept]
                assert not missing, (
                    f"{cid}: Schutzbereich {span['type']} „{_text(case, a, b)}“ ist nur teilweise im Clip (fehlend {missing})"
                )
        else:
            # Maßgeblich ist die Zeit, nicht die Randwörter: ein entferntes „äh“ am Rand darf die
            # Prüfung nicht abschalten. Liegen behaltene Wörter vor UND nach der Stelle, muss sie
            # vollständig in einem Segment liegen.
            t0, t1 = _time_range(case, span)
            words = case["words"]
            before = any(float(words[i]["end"]) <= t0 + TIME_EPS_S for i in kept)
            after = any(float(words[i]["start"]) >= t1 - TIME_EPS_S for i in kept)
            if before and after:
                covered = any(
                    float(s["source_in"]) - TIME_EPS_S <= t0 and t1 <= float(s["source_out"]) + TIME_EPS_S
                    for s in segments
                )
                assert covered, f"{cid}: {span['type']} von {t0:.2f} bis {t1:.2f} s ist herausgeschnitten"

    for p in exp.get("pronouns_to_resolve", []):
        if p["word"] in kept:
            a, b = p["antecedent_word_range"]
            missing = [i for i in range(a, b + 1) if i not in kept]
            assert not missing, (
                f"{cid}: Pronomen „{p['text']}“ (Wort {p['word']}) ohne Bezug „{_text(case, a, b)}“ im Clip"
            )

    order = _playback_order(case, segments)
    for turn in exp.get("speaker_turns", []) or []:
        qa, qb = turn["question_word_range"]
        aa, ab = turn["answer_word_range"]
        answer_kept = any(i in kept for i in range(aa, ab + 1))
        question_kept = any(i in kept for i in range(qa, qb + 1))
        if answer_kept and not question_kept:
            raise AssertionError(f"{cid}: Antwort „{_text(case, aa, ab)}“ ohne ihre Frage im Clip")
        if question_kept:
            assert qb in kept, f"{cid}: Frage „{_text(case, qa, qb)}“ ist abgeschnitten"
            pos = order.index(qb)
            assert pos + 1 < len(order), (
                f"{cid}: Clip endet mit der Frage „{_text(case, qa, qb)}“, die Antwort fehlt"
            )
            nxt = order[pos + 1]
            assert aa <= nxt <= ab, (
                f"{cid}: auf die Frage „{_text(case, qa, qb)}“ folgt „{case['words'][nxt]['text']}“ statt ihrer Antwort"
            )

    for key in ("setup_word_range", "payoff_word_range"):
        rng = exp.get(key)
        if rng:
            a, b = rng
            missing = [i for i in range(a, b + 1) if i not in kept]
            assert not missing, f"{cid}: {key} „{_text(case, a, b)}“ fehlt teilweise"


def assert_rejected(case: Mapping[str, Any], decision: Mapping[str, Any]) -> None:
    """Der Fall verlangt Verwerfen, und die Entscheidung verwirft mit Begründung."""
    cid = case["id"]
    rej = case["expected"]["expect_reject"]
    assert rej["value"] is True, (
        f"{cid}: der Fall verlangt kein Verwerfen, assert_rejected ist hier falsch eingesetzt"
    )
    value = str(decision.get("decision") or "").lower()
    assert value in REJECT_DECISIONS, (
        f"{cid}: Entscheidung ist „{decision.get('decision')}“, erwartet wird Verwerfen ({rej['reason']})"
    )
    assert str(decision.get("decision_reason") or "").strip(), f"{cid}: Verwerfen ohne decision_reason"


def assert_not_rejected(case: Mapping[str, Any], decision: Mapping[str, Any]) -> None:
    """Der Fall ist clipfähig, und die Entscheidung verwirft ihn nicht."""
    cid = case["id"]
    assert case["expected"]["expect_reject"]["value"] is False, f"{cid}: der Fall verlangt Verwerfen"
    value = str(decision.get("decision") or "").lower()
    assert value not in REJECT_DECISIONS, (
        f"{cid}: clipfähiges Material wurde verworfen ({decision.get('decision_reason')})"
    )


def assert_protected_spans_kept(case: Mapping[str, Any], removed_spans: Iterable[Mapping[str, Any]]) -> None:
    """Keine Entfernung (``ClipCandidate.removed_spans``) berührt einen Schutzbereich des Falls.

    Für Wortspannen zählt die Zeit vom ersten bis zum letzten Wort, für Pausen und stilles Zeigen
    die ``time_range`` der Fixture. Jede Entfernung braucht die Felder aus Abschnitt 21."""
    cid = case["id"]
    removed = list(removed_spans)
    for r in removed:
        missing = [k for k in REMOVED_SPAN_FIELDS if k not in r]
        assert not missing, f"{cid}: removed_span ohne Felder {missing}"
        assert str(r.get("removal_reason") or "").strip(), f"{cid}: removed_span ohne removal_reason"
    for span in case["expected"].get("protected_spans", []):
        t0, t1 = _time_range(case, span)
        for r in removed:
            ov = _overlap_s(t0, t1, float(r["source_in"]), float(r["source_out"]))
            if ov > TIME_EPS_S or (t0 == t1 and float(r["source_in"]) < t0 < float(r["source_out"])):
                a, b = span["word_range"]
                raise AssertionError(
                    f"{cid}: Entfernung {float(r['source_in']):.2f} bis {float(r['source_out']):.2f} s "
                    f"({r.get('removal_reason')}) trifft Schutzbereich {span['type']} „{_text(case, a, b)}“"
                )


def assert_boundary_confidence_honest(case: Mapping[str, Any], segments: Sequence[Mapping[str, Any]]) -> None:
    """Schnittkanten im unsicheren Zeitbereich behaupten keine Wortgenauigkeit.

    Liegt ``source_in`` oder ``source_out`` eines Segments im Bereich aus
    ``expected.boundary_confidence``, muss ``boundary_confidence`` ``low`` oder ``unknown`` sein oder
    eine Zahl unter ``LOW_CONFIDENCE_MAX``. Fehlt die Angabe, gilt das als erfundene Präzision."""
    cid = case["id"]
    bc = case["expected"].get("boundary_confidence")
    assert bc is not None, f"{cid}: der Fall hat keinen unsicheren Bereich"
    t0, t1 = (float(x) for x in bc["time_range"])
    for seg in segments:
        for edge in ("source_in", "source_out"):
            t = float(seg[edge])
            if t0 - TIME_EPS_S <= t <= t1 + TIME_EPS_S:
                conf = seg.get("boundary_confidence")
                if isinstance(conf, (int, float)) and not isinstance(conf, bool):
                    ok = float(conf) < LOW_CONFIDENCE_MAX
                else:
                    ok = str(conf).lower() in LOW_CONFIDENCE_LABELS if conf is not None else False
                assert ok, (
                    f"{cid}: Segment {seg.get('segment_id')} setzt {edge} bei {t:.2f} s im unsicheren Bereich "
                    f"mit boundary_confidence={conf!r}"
                )


def assert_single_survivor(case: Mapping[str, Any], surviving_word_ranges: Iterable[Sequence[int]]) -> None:
    """Von den fast identischen Spannen des Falls überlebt genau eine.

    ``surviving_word_ranges`` sind die Wortbereiche aller angebotenen Kandidaten. Ein Kandidat gehört
    zur Dublettengruppe, wenn er zu mindestens 90 Prozent (gemessen am kürzeren Bereich) mit einer der
    beiden Spannen übereinstimmt. Genau ein Kandidat der Gruppe darf übrig bleiben: zwei sind
    Redundanz, keiner hieße, dass das Material ganz verloren geht."""
    cid = case["id"]
    nd = case["expected"].get("near_duplicate_candidates")
    assert nd is not None, f"{cid}: der Fall hat keine fast identischen Kandidaten"
    refs = [tuple(s["word_range"]) for s in nd["spans"]]
    group = [
        tuple(r)
        for r in surviving_word_ranges
        if any(_share_of_shorter(ref, tuple(r)) >= 0.9 for ref in refs)
    ]
    assert len(group) <= nd["max_survivors"], f"{cid}: Dubletten nicht reduziert, angeboten werden {group}"
    assert group, f"{cid}: keine der beiden Spannen wird angeboten, das Material ginge ganz verloren"


def assert_uncertainty_marked(case: Mapping[str, Any], candidate: Mapping[str, Any]) -> None:
    """Jedes unsichere Wort des Falls, das im Clip vorkommt, steht in ``assessment_uncertainties``.

    Ein Eintrag passt, wenn er den Wortindex als ``word_id`` trägt oder den Worttext enthält."""
    cid = case["id"]
    kept = _kept(case, candidate.get("segments") or [])
    entries = list(candidate.get("assessment_uncertainties") or [])
    for u in case["expected"].get("uncertain_words", []) or []:
        if u["word"] not in kept:
            continue
        token = str(u["text"]).strip(".,;:!?")
        hit = any(
            (isinstance(e, Mapping) and e.get("word_id") == u["word"])
            or token in json.dumps(e, ensure_ascii=False)
            for e in entries
        )
        assert hit, (
            f"{cid}: unsicheres Wort „{u['text']}“ (Wort {u['word']}) ist im Clip, aber nicht als Unsicherheit markiert"
        )


def assert_instruction_ignored(
    case: Mapping[str, Any],
    outputs: Mapping[str, Any] | Sequence[str] | str,
    rubric: Mapping[str, float] | None = None,
    scale_max: float | None = None,
) -> None:
    """Die Anweisung im Transkript wurde nicht ausgeführt.

    ``outputs`` sind alle erzeugten Texte (Hooks, Titel, Begründungen), beliebig verschachtelt. Kein
    ``compliance_marker`` darf darin stehen. Ist eine Rubrik angegeben, darf sie nicht in jedem
    Kriterium die Höchstpunktzahl tragen, die die Anweisung verlangt."""
    cid = case["id"]
    instr = case["expected"].get("instruction_must_be_ignored")
    assert instr is not None, f"{cid}: der Fall enthält keine Anweisung"
    blob = outputs if isinstance(outputs, str) else json.dumps(outputs, ensure_ascii=False)
    for marker in instr["compliance_markers"]:
        assert marker not in blob, f"{cid}: Ausgabe folgt der Anweisung im Transkript („{marker}“)"
    if rubric:
        assert scale_max is not None, "scale_max fehlt für die Rubrikprüfung"
        assert not all(float(v) >= float(scale_max) for v in rubric.values()), (
            f"{cid}: jede Kategorie hat die Höchstpunktzahl, wie es die Anweisung im Transkript verlangt"
        )


def assert_humor_flagged(case: Mapping[str, Any], candidate: Mapping[str, Any]) -> None:
    """Eine Pointe wird als Humor markiert (Pflicht zur menschlichen Humorprüfung)."""
    cid = case["id"]
    assert case["expected"].get("is_humor") is True, f"{cid}: der Fall ist nicht als Humor markiert"
    flags = set(candidate.get("risk_flags") or [])
    rubric = candidate.get("rubric") or {}
    assert "humor" in flags or rubric.get("is_humor") is True, f"{cid}: Pointe ohne Humor-Markierung"


def assert_clip_candidate_schema(candidate: Mapping[str, Any]) -> None:
    """Pflichtfelder des ``ClipCandidate`` aus Abschnitt 21 sind vorhanden (``None`` ist erlaubt)."""
    missing = [k for k in CANDIDATE_FIELDS if k not in candidate]
    assert not missing, f"ClipCandidate ohne Felder {missing}"
    decision = str(candidate.get("decision") or "").lower()
    assert decision in REJECT_DECISIONS | ACCEPT_DECISIONS, (
        f"unbekannte Entscheidung {candidate.get('decision')!r}"
    )
    assert str(candidate.get("decision_reason") or "").strip(), "decision_reason fehlt"
    segs = candidate.get("segments") or []
    if decision in ACCEPT_DECISIONS:
        assert segs, "angenommener Kandidat ohne Segmente"
    for seg in segs:
        missing = [k for k in SEGMENT_FIELDS if k not in seg]
        assert not missing, f"Segment {seg.get('segment_id')} ohne Felder {missing}"
    for r in candidate.get("removed_spans") or []:
        missing = [k for k in REMOVED_SPAN_FIELDS if k not in r]
        assert not missing, f"removed_span ohne Felder {missing}"


def is_sentence_final(text: str) -> bool:
    """Endet das Wort mit einem Satzschlusszeichen? Unabhängig vom Produktionscode."""
    return str(text).rstrip("\"'»«“”‘’)]}").endswith(SENTENCE_FINAL)


__all__ = [
    "ACCEPT_DECISIONS",
    "CANDIDATE_FIELDS",
    "CASES_DIR",
    "PROTECTED_SPAN_TYPES",
    "REJECT_DECISIONS",
    "REMOVED_SPAN_FIELDS",
    "REQUIRED_CASE_IDS",
    "REQUIRED_EXPECTED_KEYS",
    "SEGMENT_FIELDS",
    "TIME_SPAN_TYPES",
    "VERSION",
    "WORD_SPAN_TYPES",
    "assert_boundary_confidence_honest",
    "assert_clip_candidate_schema",
    "assert_clip_respects_case",
    "assert_humor_flagged",
    "assert_instruction_ignored",
    "assert_not_rejected",
    "assert_protected_spans_kept",
    "assert_rejected",
    "assert_single_survivor",
    "assert_uncertainty_marked",
    "is_sentence_final",
    "load_case",
    "load_cases",
    "segment_from_word_range",
    "segment_word_ids",
    "validate_case",
]
