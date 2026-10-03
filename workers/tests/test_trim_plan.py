"""AP7: Remove- und Keep-Logik (``pipeline/trim_plan.py``) unter Policy v2, Abschnitt ``trim``.

Schutzbereiche werden nie entfernt, nur technische Pausen gekürzt und nie auf null, Modalpartikeln
bleiben, eine einsilbige Antwort zwischen zwei Fragen ist kein Einwurf, höchstens zwei semantische
Splices, das Ende nach dem Payoff wird gekappt, eine Einschränkung nie, und die Dichte aus
``zusammenhang.mindest_dichte`` gilt für die Komposition.
"""

from __future__ import annotations

import copy
import json

import pytest

from chopstr_worker import editorial
from chopstr_worker.pipeline import compose, dach_nlp, fidelity, trim_plan
from chopstr_worker.pipeline.segment import Sentence
from tests.editorial_v1 import harness

WORD_S = 0.3
GAP_S = 0.2


@pytest.fixture
def pol():
    return editorial.load(2)


def W(*items, gaps: dict[int, float] | None = None) -> list[dict]:
    """Wörter mit 0,3 s Dauer und 0,2 s Lücke (unter der Zielpause, also keine Pause im Sinne von AP7).

    ``items`` sind Texte oder ``(text, speaker)``; ``gaps`` setzt die Lücke nach Wort ``i``."""
    out, t = [], 0.0
    for i, it in enumerate(items):
        text, spk = (it, "A") if isinstance(it, str) else it
        out.append({"text": text, "start": round(t, 3), "end": round(t + WORD_S, 3), "speaker": spk})
        t += WORD_S + (gaps or {}).get(i, GAP_S)
    return out


def S(text: str) -> list[str]:
    return text.split()


def candidate_ranges(words, pol) -> list[tuple[list[int], str]]:
    return [(c["word_range"], c["reason"]) for c in trim_plan.removal_candidates(words, pol)]


def kept_ids(result) -> set[int]:
    return {i for a, b in result["kept_word_ranges"] for i in range(a, b + 1)}


def build(words, pol, keep=None, **kw):
    return trim_plan.build_composition(words, 0, len(words) - 1, keep, pol, **kw)


# -- Policy ----------------------------------------------------------------------------------------


def test_trim_needs_policy_v2(pol):
    assert editorial.trim_settings(editorial.load(1)) is None
    with pytest.raises(editorial.PolicyError, match="Fassung 2 mit Abschnitt trim"):
        trim_plan.protected_spans(W("nicht"), editorial.load(1))


def test_trim_is_off_until_the_blind_comparison(pol):
    cfg = editorial.trim_settings(pol)
    assert cfg["enabled"] is False
    assert pol.roh["trim"]["enabled"] is False
    assert pol.roh["implementation"]["trim"]["enabled"] is False
    assert "trim.enabled" not in editorial.V2_IMPLEMENTED_SWITCHES
    assert "trim" in editorial.V2_RULE_SECTIONS
    assert cfg["max_semantic_splices"] == 2 and cfg["debate_no_reorder"] is True
    assert cfg["pause_target_s"] == 0.25 and cfg["long_silence_s"] == 1.5
    assert cfg["min_density"] == pol.zusammenhang["mindest_dichte"]


def test_trim_enabled_needs_rule_and_switch(pol):
    raw = copy.deepcopy(pol.roh)
    raw["trim"]["enabled"] = True
    assert editorial.trim_settings(editorial.Policy(2, "t", raw))["enabled"] is False
    raw["implementation"]["trim"]["enabled"] = True
    assert editorial.trim_settings(editorial.Policy(2, "t", raw))["enabled"] is True


@pytest.mark.parametrize(
    ("path", "value", "match"),
    [
        (("trim", "max_semantic_splices"), 3, "E6 nicht lockern"),
        (("trim", "debate_no_reorder"), False, "Debatten nie umordnen"),
        (("trim", "pause_target_s"), 0, "nie auf null"),
        (("trim", "removal", "fillers"), "soft", "P3"),
    ],
)
def test_trim_settings_refuse_loosening_e6_or_p3(pol, path, value, match):
    raw = copy.deepcopy(pol.roh)
    node = raw
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    with pytest.raises(editorial.PolicyError, match=match):
        editorial.trim_settings(editorial.Policy(2, "t", raw))


def test_every_trim_rule_has_an_origin(pol):
    paths = [p for p in editorial.rule_paths(pol.roh) if p.startswith("trim.")]
    assert len(paths) == 22
    origins = pol.roh["origins"]
    for p in paths:
        assert origins[p]["origin"] in ("R", "H"), p
    for p in ("trim.max_semantic_splices", "trim.debate_no_reorder"):
        assert origins[p]["origin"] == "R" and "E6" in origins[p]["source"]
    for p in ("trim.pause_classes.dramatic_before", "trim.pause_classes.reaction_after"):
        assert origins[p]["origin"] == "R" and "RK 7" in origins[p]["source"]
    for p in ("trim.removal.fillers", "trim.removal.never_remove"):
        assert origins[p]["origin"] == "R" and "P3" in origins[p]["source"] and "RK 7" in origins[p]["source"]


# -- Schutzbereiche --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "kind", "trigger"),
    [
        ("Das hat bei uns nicht funktioniert.", "negation", "nicht"),
        ("Ja, aber nur, wenn ihr vorher dokumentiert.", "condition", "wenn"),
        ("Das gilt nur für kleine Betriebe.", "qualifier", "nur"),
        ("Im Vergleich zu früher ist das viel.", "comparison_baseline", "Im Vergleich"),
        ("Damals war das anders.", "temporal", "Damals"),
        ("Das waren wahrscheinlich 40 Kunden.", "uncertainty", "wahrscheinlich"),
        ("Churn heißt, dass Kunden abspringen.", "definition", "heißt,"),
        ("Mein Steuerberater sagt, das lohnt sich.", "attribution", "sagt,"),
        ("Drei Monate, beziehungsweise vier.", "correction", "beziehungsweise"),
    ],
)
def test_protected_span_types(pol, text, kind, trigger):
    spans = trim_plan.protected_spans(W(*S(text)), pol)
    hit = [p for p in spans if p["type"] == kind]
    assert hit and hit[0]["text"] == trigger


def test_protected_span_has_one_word_margin_and_conditions_reach_the_clause_end(pol):
    w = W(*S("Ja, aber nur, wenn ihr vorher dokumentiert. Danach geht es."))
    cond = next(p for p in trim_plan.protected_spans(w, pol) if p["type"] == "condition")
    assert cond["trigger"] == [3, 3]
    assert cond["word_range"] == [2, 7]  # Rand vorn, Satzende „dokumentiert.“ plus ein Wort Rand
    neg = next(p for p in trim_plan.protected_spans(W(*S("Das ist nicht gut.")), pol) if p["type"] == "negation")
    assert neg["word_range"] == [1, 3]


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Das hat bei uns äh nicht funktioniert und jetzt äh machen wir es anders.", "negation"),
        ("Ja, aber nur, wenn ihr äh vorher dokumentiert. Jetzt sind wir äh deutlich schneller.", "condition"),
        ("Das waren äh wahrscheinlich viele Kunden und jetzt äh machen wir es anders.", "uncertainty"),
    ],
)
def test_negation_condition_uncertainty_are_never_removed(pol, text, kind):
    w = W(*S(text))
    protected_aeh, free_aeh = [i for i, x in enumerate(w) if x["text"] == "äh"]
    spans = [p for p in trim_plan.protected_spans(w, pol) if p["type"] == kind]
    assert any(p["word_range"][0] <= protected_aeh <= p["word_range"][1] for p in spans)
    cands = [c["word_range"] for c in trim_plan.removal_candidates(w, pol)]
    assert [free_aeh, free_aeh] in cands and [protected_aeh, protected_aeh] not in cands
    r = build(w, pol)
    assert protected_aeh in kept_ids(r) and free_aeh not in kept_ids(r)
    for p in spans:
        assert all(i in kept_ids(r) for i in range(p["word_range"][0], p["word_range"][1] + 1))
    kept = [tuple(x) for x in r["kept_word_ranges"]]
    assert not [x for x in fidelity.check_cut(w, kept, policy=pol) if x["type"] == "protected_removed"]


# -- Pausenklassen ---------------------------------------------------------------------------------


def pause_after(words, i, pol, **kw) -> dict:
    return next(p for p in trim_plan.classify_pauses(words, kw.pop("heat", None), pol, **kw) if p["after_word"] == i)


def test_technical_pause_is_trimmed_to_the_target_never_to_zero(pol):
    w = W(*S("Wir haben das im Team lange besprochen und dann umgesetzt."), gaps={4: 1.0})
    assert pause_after(w, 4, pol)["class"] == "technical"
    r = build(w, pol)
    a, b = r["segments"]
    assert b["start"] - a["end"] > 0
    silence = (w[5]["start"] - b["start"]) + (a["end"] - w[4]["end"])
    assert silence == pytest.approx(0.25, abs=1e-3)
    assert r["local_cuts"] == 1 and r["semantic_splices"] == 0
    assert r["removed_spans"][0]["removal_reason"] == "technical_pause"
    assert r["removed_spans"][0]["source_out"] - r["removed_spans"][0]["source_in"] == pytest.approx(0.75, abs=1e-3)


@pytest.mark.parametrize(
    ("text", "cls", "reason"),
    [
        ("Am Ende hatten wir 40 Kunden mehr als vorher.", "dramatic", "Zahl"),
        ("Am Ende hatten wir nicht mehr Kunden als vorher.", "dramatic", "Negation"),
        ("Am Ende hatten wir aber mehr Kunden als vorher.", "dramatic", "Kontrastwort"),
    ],
)
def test_pause_before_number_negation_contrast_is_dramatic(pol, text, cls, reason):
    w = W(*S(text), gaps={3: 0.9})
    p = pause_after(w, 3, pol)
    assert p["class"] == cls and reason in p["reason"]
    assert build(w, pol)["removed_spans"] == []


def test_pause_after_question_is_reaction_and_orientation_at_sentence_boundaries(pol):
    w = W(*S("Was ist passiert? Wir haben verkauft. Erstens die Halle, dann das Lager."), gaps={2: 0.6, 5: 0.6})
    assert pause_after(w, 2, pol)["class"] == "reaction"
    assert pause_after(w, 5, pol)["class"] == "orientation"
    w = W(*S("Wir haben verkauft. Danach war Ruhe im Betrieb."), gaps={2: 1.1})
    assert pause_after(w, 2, pol)["class"] == "orientation"


def test_pause_before_the_punchline_stays(pol):
    setup = S("Unser Stand war direkt neben den Toiletten.")
    punch = S("Der einzige Besucher fragte nach dem Klo.")
    plain = W(*setup, *punch, gaps={6: 0.8})
    assert pause_after(plain, 6, pol)["class"] == "technical"  # ohne Reaktion keine Pointe
    assert build(plain, pol)["local_cuts"] == 1

    reacted = W(*setup, *punch, ("Haha.", "B"), gaps={6: 0.8, 13: 0.4})
    p = pause_after(reacted, 6, pol)
    assert p["class"] == "dramatic" and "Pointe" in p["reason"]
    assert pause_after(reacted, 13, pol)["class"] == "reaction"
    r = build(reacted, pol)
    assert r["local_cuts"] == 0 and r["removed_spans"] == []

    heat = {"bin_s": 1.0, "laughter_values": [0.0] * 8 + [1.0, 1.0]}
    laughed = W(*setup, *punch, gaps={6: 0.8})
    assert laughed[-1]["end"] < 8.0 + 1.5
    assert pause_after(laughed, 6, pol, heat=heat)["class"] == "dramatic"
    assert build(laughed, pol, heat_payload=heat)["removed_spans"] == []


def test_long_silence_stays_and_is_marked_as_demonstration(pol):
    w = W(*S("Ich zeige es Ihnen am Werkstück. So hält das ohne Leim."), gaps={5: 3.0})
    p = pause_after(w, 5, pol)
    assert p["class"] == "demonstration" and "Demonstration" in p["reason"]
    r = build(w, pol)
    assert r["removed_spans"] == [] and len(r["segments"]) == 1
    assert next(x for x in r["pauses"] if x["after_word"] == 5)["action"] == "kept"


def test_silent_demonstration_fixture_with_and_without_visual_events(pol):
    c = harness.load_case("silent_demonstration")
    w = copy.deepcopy(c["words"])
    aeh = c["expected"]["protected_spans"][0]["word_range"][0]
    assert pause_after(w, aeh, pol, visual_events=c["visual_events"])["class"] == "demonstration"
    assert pause_after(w, aeh, pol)["class"] in ("dramatic", "demonstration")  # nie technical
    assert [aeh, aeh] not in [c_["word_range"] for c_ in trim_plan.removal_candidates(w, pol)]
    assert dach_nlp.classify_fillers(copy.deepcopy(w))[aeh]["filler"] == "hard"  # v1 hätte es entfernt
    r = build(w, pol, visual_events=c["visual_events"])
    t0, t1 = c["expected"]["protected_spans"][0]["time_range"]
    assert any(s["start"] <= t0 and t1 <= s["end"] for s in r["segments"])


# -- Entfernungskandidaten -------------------------------------------------------------------------


def test_one_word_answer_between_two_questions_stays(pol):
    w = W(("Machst", "H"), ("du", "H"), ("das", "H"), ("wieder?", "H"), ("Klar.", "G"), ("Und", "H"), ("warum?", "H"))
    assert candidate_ranges(w, pol) == []
    assert dach_nlp.classify_fillers(copy.deepcopy(w))[4]["filler"] == "backchannel"  # v1 hielt es für einen Einwurf
    monolog = W(("Wir", "G"), ("haben", "G"), ("das,", "G"), ("Klar.", "H"), ("ganz", "G"), ("anders", "G"), ("gemacht.", "G"))
    assert candidate_ranges(monolog, pol) == [([3, 3], "backchannel")]


def test_speaker_turn_fixture_keeps_the_answer_and_removes_the_backchannel(pol):
    c = harness.load_case("speaker_turn_attribution")
    w = c["words"]
    cands = trim_plan.removal_candidates(w, pol)
    assert [x["word_range"] for x in cands] == [[i, i] for i in c["expected"]["backchannel_words"]]
    a, b = c["expected"]["speaker_turns"][0]["answer_word_range"]
    r = build(w, pol)
    assert all(i in kept_ids(r) for i in range(a, b + 1))
    harness.assert_protected_spans_kept(c, r["removed_spans"])


def test_modal_particles_stay(pol):
    w = W(*S("Wir machen das halt so und äh das geht schon gut."))
    assert candidate_ranges(w, pol) == [([6, 6], "hard_filler")]
    r = build(w, pol)
    assert {3, 9} <= kept_ids(r) and 6 not in kept_ids(r)
    interjection = W(("Wir", "A"), ("machen", "A"), ("das,", "A"), ("Ja.", "B"), ("ganz", "A"), ("anders.", "A"))
    assert candidate_ranges(interjection, pol) == []  # „ja“ ist Modalpartikel: nie entfernen


@pytest.mark.parametrize("case", harness.load_cases(), ids=lambda c: c["id"])
def test_no_candidate_contains_a_modal_particle_or_touches_a_protected_span(pol, case):
    w = case["words"]
    never = set(editorial.trim_settings(pol)["never_remove"])
    protected = [p["word_range"] for p in trim_plan.protected_spans(w, pol)]
    for c in trim_plan.removal_candidates(w, pol):
        a, b = c["word_range"]
        assert not any(dach_nlp.core_token(w[i]["text"]) in never for i in range(a, b + 1))
        assert not any(a <= q and p <= b for p, q in protected)


def test_restart_is_removed_but_functional_repetition_stays(pol):
    w = W(*S("Wir haben, äh, wir haben das dann gemacht."))
    assert ([0, 2], "restart") in candidate_ranges(w, pol)
    r = build(w, pol)
    assert kept_ids(r) == {3, 4, 5, 6, 7}
    assert r["removed_spans"][0]["kind"] == "edge"
    broken = W(*S("Wir hab- wir haben das gemacht."))
    assert ([0, 1], "restart") in candidate_ranges(broken, pol)
    assert candidate_ranges(W(*S("Nein, nein. Das stimmt so.")), pol) == []


def test_greeting_and_organisation_only_at_the_edge(pol):
    w = W(*S("Danke für die Einladung. Wir haben die Preise erhöht. Danke für die Einladung, sagt jeder."))
    cands = candidate_ranges(w, pol)
    assert ([0, 3], "greeting") in cands
    assert all(a < 4 for (a, _b), _r in cands)  # der Satz in der Mitte und der letzte Satz mit „sagt“ bleiben
    r = build(w, pol)
    assert min(kept_ids(r)) == 4 and r["local_cuts"] == 0
    assert r["removed_spans"][0]["kind"] == "edge" and r["removed_spans"][0]["removal_reason"] == "greeting"


def test_too_short_segment_cancels_the_local_cut(pol):
    w = W(*S("Wir äh haben das so gemacht."))
    r = build(w, pol)
    assert 1 in kept_ids(r) and r["local_cuts"] == 0
    assert r["skipped_candidates"][0]["skipped"].startswith("Segment kürzer als")


# -- Splices, Debatte, Dichte ----------------------------------------------------------------------


def _sentences(n: int, long_words: int = 6) -> tuple[list[dict], list[tuple[int, int]]]:
    """``n`` Sätze, gerade lang (behalten), ungerade kurz (zum Weglassen)."""
    items, ranges = [], []
    for k in range(n):
        size = long_words if k % 2 == 0 else 2
        start = len(items)
        items += [f"wort{k}x{j}" for j in range(size - 1)] + [f"ende{k}."]
        ranges.append((start, len(items) - 1))
    return W(*items), ranges


def test_two_semantic_splices_are_allowed_three_are_not(pol):
    w, sents = _sentences(7)
    ok = trim_plan.build_composition(w, 0, sents[4][1], [sents[0], sents[2], sents[4]], pol)
    assert ok["semantic_splices"] == 2 and ok["valid"], ok["issues"]
    too_many = build(w, pol, keep=[sents[0], sents[2], sents[4], sents[6]])
    assert too_many["semantic_splices"] == 3 and too_many["local_cuts"] == 0
    assert not too_many["valid"]
    assert any("Zu viele Splices (3 statt höchstens 2" in i for i in too_many["issues"])
    assert {r["kind"] for r in too_many["removed_spans"]} == {"semantic"}
    assert {r["removal_reason"] for r in too_many["removed_spans"]} == {"keep_decision"}


def test_local_cuts_are_counted_apart_from_splices(pol):
    w = W(*S("Wir haben äh das so gemacht und äh dann lief es gut."))
    r = build(w, pol)
    assert r["local_cuts"] == 2 and r["semantic_splices"] == 0 and r["valid"]


def test_density_from_zusammenhang_mindest_dichte(pol):
    w, sents = _sentences(5, long_words=3)
    whole = build(w, pol)
    assert whole["density"] == 1.0 and whole["valid"]
    sparse = build(w, pol, keep=[sents[0], sents[4]])
    assert sparse["density"] < pol.zusammenhang["mindest_dichte"]
    assert any("mindest_dichte" in i for i in sparse["issues"])
    raw = copy.deepcopy(pol.roh)
    raw["zusammenhang"]["mindest_dichte"] = 0.99
    strict = editorial.Policy(2, "t", raw)
    trimmed = trim_plan.build_composition(
        W(*S("Wir haben das im Team lange besprochen und dann umgesetzt."), gaps={4: 1.0}), 0, 9, None, strict
    )
    assert trimmed["density"] < 0.99 and any("mindest_dichte" in i for i in trimmed["issues"])


def test_debate_is_detected_in_the_composition(pol):
    w = W(("Ich", "A"), ("finde", "A"), ("das", "A"), ("falsch.", "A"), ("Ich", "B"), ("sehe", "B"), ("das", "B"), ("anders.", "B"), ("Warum", "A"), ("denn?", "A"))
    assert build(w, pol)["is_debate"] is True


# -- Ende nach dem Payoff --------------------------------------------------------------------------


def sents_of(*texts: str) -> list[Sentence]:
    return [Sentence(i, t, float(i), float(i) + 0.9, "A", (i, i)) for i, t in enumerate(texts)]


def test_reward_end_cuts_the_farewell_not_the_qualification(pol):
    s = sents_of(
        "Wir haben die Preise erhöht.",
        "Danach kamen mehr Aufträge als je zuvor.",
        "Wobei das nur bei uns so war.",
        "Danke fürs Zuhören und tschüss!",
    )
    last, cut = trim_plan.reward_end(s, 0, 3, 1, pol)
    assert last == 2
    assert cut == [{"sentence": 3, "reason": "farewell", "text": "Danke fürs Zuhören und tschüss!"}]


def test_reward_end_cuts_summary_sales_call_and_repeated_payoff(pol):
    s = sents_of(
        "Wir haben die Preise erhöht.",
        "Danach kamen mehr Aufträge als je zuvor.",
        "Mehr Aufträge als je zuvor kamen danach.",
        "Also zusammengefasst: Preise rauf.",
        "Link in der Bio.",
    )
    last, cut = trim_plan.reward_end(s, 0, 4, 1, pol)
    assert last == 1
    assert [c["reason"] for c in cut] == ["repeated_payoff", "weak_summary", "sales_call"]


def test_reward_end_never_cuts_past_a_qualification(pol):
    s = sents_of("Wir haben die Preise erhöht.", "Danach kamen mehr Aufträge.", "Tschüss!", "Aber nur bei uns.")
    assert trim_plan.reward_end(s, 0, 3, 1, pol) == (3, [])
    assert trim_plan.reward_end(s, 0, 3, None, pol) == (3, [])
    assert trim_plan.reward_end(s, 0, 3, 3, pol) == (3, [])


# -- Ergebnisformat --------------------------------------------------------------------------------


def test_removed_spans_have_the_master_prompt_fields_and_are_deterministic(pol):
    w = W(*S("Danke für die Einladung. Wir haben äh das so gemacht und dann lief es gut."), gaps={10: 0.9})
    r1, r2 = build(w, pol), build(copy.deepcopy(w), pol)
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)
    assert r1["removed_spans"]
    for r in r1["removed_spans"]:
        assert set(harness.REMOVED_SPAN_FIELDS) <= set(r)
        assert r["protected_context_check"]["passed"] is True
        assert r["source_out"] > r["source_in"]
    assert [x["output_in"] for x in r1["timeline"]][0] == 0.0
    assert r1["timeline"][-1]["output_out"] == pytest.approx(r1["duration_s"], abs=1e-3)
    comp = compose.Composition.from_json(r1["segments"])
    assert comp.validate(w, max_splices=2, debate_no_reorder=True) == []
