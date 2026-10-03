"""AP7: Remove- und Keep-Logik (``pipeline/trim_plan.py``) unter Policy v2, Abschnitt ``trim``.

Schutzbereiche werden nie entfernt, nur technische Pausen gekürzt und nie auf null, Modalpartikeln
bleiben, eine einsilbige Antwort zwischen zwei Fragen ist kein Einwurf, höchstens zwei semantische
Splices, das Ende nach dem Payoff wird gekappt, eine Einschränkung nie, und die Dichte aus
``zusammenhang.mindest_dichte`` gilt für die Komposition.
"""

from __future__ import annotations

import copy
import json
import re

import pytest

from chopstr_worker import editorial
from chopstr_worker.pipeline import compose, dach_nlp, fidelity, trim_plan
from chopstr_worker.pipeline.clip_candidate import RemovedSpan
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


def SPEC(spec: str, word_s: float = WORD_S, gap: float = GAP_S) -> list[dict]:
    """Wörter aus einer Kurzschreibweise: ``@B`` wechselt den Sprecher, ``[0.9]`` setzt die Pause davor."""
    out, spk, pending = [], "A", None
    for tok in spec.split():
        if tok.startswith("@"):
            spk = tok[1:]
            continue
        m = re.fullmatch(r"\[(\d+(?:\.\d+)?)\]", tok)
        if m:
            pending = float(m.group(1))
            continue
        t = out[-1]["end"] + (pending if pending is not None else gap) if out else 0.0
        pending = None
        out.append({"text": tok, "start": round(t, 3), "end": round(t + word_s, 3), "speaker": spk})
    return out


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
    """Der Schalter ist verdrahtet (implementation.trim.enabled true), die Regel trim.enabled bleibt bis
    zum Blindvergleich false; zusammen bleibt die Kürzung aus."""
    cfg = editorial.trim_settings(pol)
    assert cfg["enabled"] is False
    assert pol.roh["trim"]["enabled"] is False
    assert pol.roh["implementation"]["trim"]["enabled"] is True
    assert "trim.enabled" in editorial.V2_IMPLEMENTED_SWITCHES
    assert "trim" in editorial.V2_RULE_SECTIONS
    assert cfg["max_semantic_splices"] == 2 and cfg["debate_no_reorder"] is True
    assert cfg["pause_target_s"] == 0.25 and cfg["long_silence_s"] == 1.5
    assert cfg["min_density"] == pol.zusammenhang["mindest_dichte"]


def test_trim_enabled_needs_rule_and_switch(pol):
    raw = copy.deepcopy(pol.roh)
    raw["trim"]["enabled"] = True
    assert editorial.trim_settings(editorial.Policy(2, "t", raw))["enabled"] is True
    raw["implementation"]["trim"]["enabled"] = False  # Rollback über den Schalter
    assert editorial.trim_settings(editorial.Policy(2, "t", raw))["enabled"] is False
    raw["implementation"]["trim"]["enabled"] = True
    raw["trim"]["enabled"] = False  # Rollback über die Regel
    assert editorial.trim_settings(editorial.Policy(2, "t", raw))["enabled"] is False


@pytest.mark.parametrize(
    ("path", "value", "match"),
    [
        (("trim", "max_semantic_splices"), 3, "E6 nicht lockern"),
        (("trim", "debate_no_reorder"), False, "Debatten nie umordnen"),
        (("trim", "pause_target_s"), 0, "nie auf null"),
        (("trim", "removal", "fillers"), "soft", "P3"),
        (("trim", "removal", "never_remove"), ["halt", "ja"], "P3"),
        (("trim", "pause_classes", "dramatic_before"), ["number", "negation"], "RK 7"),
        (("trim", "pause_classes", "reaction_after"), ["question"], "RK 7"),
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
    assert len(paths) == 23
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
        ("Churn heißt, dass Kunden abspringen.", "definition", "heißt, dass"),
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
    assert cond["word_range"] == [2, 6]  # Rand vorn, bis zum Satzende „dokumentiert.“, nie in den nächsten Satz
    assert cond["lock_range"] == [2, 4]  # Auslöser „wenn“ mit je einem Wort Rand
    neg = next(p for p in trim_plan.protected_spans(W(*S("Das ist nicht gut.")), pol) if p["type"] == "negation")
    assert neg["word_range"] == [1, 3]


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Das hat bei uns äh nicht funktioniert und jetzt äh machen wir es anders.", "negation"),
        ("Ja, aber nur, wenn äh ihr vorher dokumentiert. Jetzt sind wir äh deutlich schneller.", "condition"),
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
    w = W(*S("Wir haben das im Team lange besprochen und dann umgesetzt."), gaps={4: 0.9})
    assert pause_after(w, 4, pol)["class"] == "technical"
    r = build(w, pol)
    a, b = r["segments"]
    assert b["start"] - a["end"] > 0
    silence = (w[5]["start"] - b["start"]) + (a["end"] - w[4]["end"])
    assert silence == pytest.approx(0.25, abs=1e-3)
    assert r["local_cuts"] == 1 and r["semantic_splices"] == 0
    assert r["removed_spans"][0]["removal_reason"] == "technical_pause"
    assert r["removed_spans"][0]["source_out"] - r["removed_spans"][0]["source_in"] == pytest.approx(0.65, abs=1e-3)


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
    in_sentence = W(*S("Das ist ja äh ganz einfach so."))
    assert not [r for r, _reason in candidate_ranges(in_sentence, pol) if r[0] <= 2 <= r[1]]  # „ja“ im Satz bleibt
    interjection = W(("Wir", "A"), ("machen", "A"), ("das,", "A"), ("Ja.", "B"), ("ganz", "A"), ("anders.", "A"))
    assert candidate_ranges(interjection, pol) == [([3, 3], "backchannel")]  # Einwurf, keine Modalpartikel im Satz


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
    assert r["removed_spans"][0]["protected_context_check"]["detail"]["kind"] == "edge"
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
    assert r["removed_spans"][0]["protected_context_check"]["detail"]["kind"] == "edge"
    assert r["removed_spans"][0]["removal_reason"] == "greeting"


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
    assert {r["protected_context_check"]["detail"]["kind"] for r in too_many["removed_spans"]} == {"semantic"}
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
    one_cut = trim_plan.build_composition(w, 0, len(w) - 1, [sents[0], (sents[2][0], sents[4][1])], strict)
    assert one_cut["density"] < 0.99 and any("mindest_dichte" in i for i in one_cut["issues"])
    assert one_cut["density"] >= pol.zusammenhang["mindest_dichte"]


def test_density_ignores_local_cuts():
    pol = editorial.load(2)
    spec = (
        "Wir haben das Produkt [0.9] gründlich getestet und dann [0.9] im Team besprochen und danach [0.9] beim "
        "Kunden vorgestellt und anschließend [0.9] noch einmal verbessert und dann [0.9] ausgeliefert."
    )
    w = SPEC(spec)
    r = build(w, pol)
    assert r["local_cuts"] == 4 and r["density"] == 1.0 and r["valid"]  # vor „ausgeliefert.“ entfällt der Schnitt (Mindestsegment)


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
        "Schreibt mir für ein kostenloses Erstgespräch.",
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
        assert set(r) == set(harness.REMOVED_SPAN_FIELDS)
        RemovedSpan(**r)
        assert r["protected_context_check"]["passed"] is True
        assert r["source_out"] > r["source_in"]
    assert [x["output_in"] for x in r1["timeline"]][0] == 0.0
    assert r1["timeline"][-1]["output_out"] == pytest.approx(r1["duration_s"], abs=1e-3)
    comp = compose.Composition.from_json(r1["segments"])
    assert comp.validate(w, max_splices=2, debate_no_reorder=True) == []


# == Review AP7: Proben als Regressionstests ==========================================================
#
# Schreibweise der erwarteten Ergebnisse: entfernte Wörter stehen in eckigen Klammern.


def marked(words, result) -> str:
    kept = kept_ids(result)
    return " ".join(w["text"] if i in kept else f"[{w['text']}]" for i, w in enumerate(words))


PROTECTION_PROBES = [
    ("P01", "Das haben wir ohne äh Vertrag gemacht und äh dann lief es weiter gut.",
     "Das haben wir ohne äh Vertrag gemacht und [äh] dann lief es weiter gut."),
    ("P02", "Alle Kunden außer äh den Großkunden sind geblieben und äh das war wichtig.",
     "Alle Kunden außer äh den Großkunden sind geblieben und [äh] das war wichtig."),
    ("P03", "Das gilt bloß äh für Neukunden und äh das wissen viele nicht so genau.",
     "Das gilt bloß äh für Neukunden und [äh] das wissen viele nicht so genau."),
    ("P04", "Wir haben lediglich äh drei Kunden verloren und äh das war es dann auch.",
     "Wir haben lediglich äh drei Kunden verloren und [äh] das war es dann auch."),
    ("P05", "Das Problem war der Preis äh sondern äh die Lieferzeit war das Problem.",
     "Das Problem war der Preis äh sondern äh die Lieferzeit war das Problem."),
    ("P06", "Wir haben weniger Werbung gemacht und äh trotzdem äh mehr verkauft am Ende.",
     "Wir haben weniger Werbung gemacht und äh trotzdem äh mehr verkauft am Ende."),
    ("P07", "Wir sind zwar äh langsamer geworden aber äh die Qualität ist gestiegen.",
     "Wir sind zwar äh langsamer geworden aber äh die Qualität ist gestiegen."),
    ("P08", "Nein äh das haben wir so nie gemacht und äh das würden wir auch lassen.",
     "Nein äh das haben wir so nie gemacht und [äh] das würden wir auch lassen."),
    ("P09", "Falls äh der Kunde zustimmt dann äh machen wir das so weiter.",
     "Falls äh der Kunde zustimmt dann [äh] machen wir das so weiter."),
    ("P10", "Im Vergleich zu äh früher haben wir jetzt äh doppelt so viele Kunden.",
     "Im Vergleich zu äh früher haben wir jetzt äh doppelt so viele Kunden."),
    ("P11", "Das waren äh ungefähr vierzig Kunden und äh die haben alle gekündigt.",
     "Das waren äh ungefähr vierzig Kunden und [äh] die haben alle gekündigt."),
    ("P12", "Mein Chef sagt äh das lohnt sich nicht und äh ich sehe das genauso.",
     "Mein Chef sagt äh das lohnt sich nicht und [äh] ich sehe das genauso."),
    ("P13", "Drei Monate äh beziehungsweise vier und äh dann war das Projekt fertig.",
     "Drei Monate äh beziehungsweise vier und [äh] dann war das Projekt fertig."),
    ("P14", "Churn heißt äh dass Kunden abspringen und äh das kostet richtig Geld.",
     "Churn heißt äh dass Kunden abspringen und [äh] das kostet richtig Geld."),
    ("P15", "Damals äh hatten wir kaum Geld und äh trotzdem haben wir investiert.",
     "Damals äh hatten wir kaum Geld und äh trotzdem haben wir investiert."),
]  # fmt: skip


@pytest.mark.parametrize(("pid", "spec", "expected"), PROTECTION_PROBES, ids=[x[0] for x in PROTECTION_PROBES])
def test_review_probe_filler_next_to_a_trigger_stays(pol, pid, spec, expected):
    w = SPEC(spec)
    r = build(w, pol)
    assert marked(w, r) == expected
    kept = [tuple(x) for x in r["kept_word_ranges"]]
    assert not [x for x in fidelity.check_cut(w, kept, rule="v2", policy=pol) if x["type"].startswith("protected")]


OMITTED = [
    ("G1", "Das gilt lediglich für Neukunden.", "high"),
    ("G2", "Das gilt bloß für Neukunden.", "high"),
    ("G3", "Das ist zwar teuer gewesen.", "high"),
    ("G4", "Trotzdem sind alle geblieben.", "high"),
    ("G5", "Aber die Marge ist gesunken.", "high"),
    ("G6", "Das gilt nur für Neukunden.", "high"),
    ("F1", "Heute ist übrigens Dienstag.", "medium"),
    ("F2", "Ich bin seit acht Uhr hier im Studio.", "medium"),
    ("F3", "Ich hole mir noch einen Kaffee.", None),
    ("F4", "Mein Hund heißt Bello.", None),
    ("F5", "Das Studio ist etwa hier um die Ecke.", "medium"),
    ("F6", "Mein Kollege sagt immer Hallo.", "medium"),
]


@pytest.mark.parametrize(("pid", "mid", "severity"), OMITTED, ids=[x[0] for x in OMITTED])
def test_review_probe_omitted_sentence_with_or_without_relation(pol, pid, mid, severity):
    w = SPEC("Wir haben die Preise deutlich erhöht. " + mid + " Danach kamen mehr Aufträge als vorher.")
    n2 = 6 + len(mid.split())
    kept = [(0, 5), (n2, len(w) - 1)]
    found = [x for x in fidelity.check_cut(w, kept, rule="v2", policy=pol) if x["type"].startswith("protected")]
    expected = {"high": "protected_removed", "medium": "protected_omitted"}.get(severity)
    assert [x["type"] for x in found] == ([expected] if expected else [])
    r = build(w, pol, keep=kept)
    assert any("Schutzbereich" in i for i in r["issues"]) is (severity == "high")


def test_review_probe_margin_stays_in_its_sentence(pol):
    w = SPEC("Wir haben lange überlegt. Das Wetter war schön. Wenn der Kunde zustimmt, machen wir weiter.")
    assert fidelity.check_cut(w, [(0, 3), (8, len(w) - 1)], rule="v2", policy=pol) == []
    r = build(w, pol, keep=[(0, 3), (8, len(w) - 1)])
    assert r["valid"] and r["semantic_splices"] == 1
    w = SPEC("Das Wetter war schön. Nicht alle Kunden waren aber begeistert davon.")
    assert [x for x in fidelity.check_cut(w, [(4, len(w) - 1)], rule="v2", policy=pol) if x["type"].startswith("protected")] == []


def test_review_probe_keep_decision_inside_a_sentence_is_semantic(pol):
    w = SPEC("Wir haben die Preise, und das war im Team sehr umstritten gewesen, am Ende deutlich erhöht.")
    r = build(w, pol, keep=[(0, 3), (12, len(w) - 1)])
    assert (r["semantic_splices"], r["local_cuts"]) == (1, 0)
    detail = r["removed_spans"][0]["protected_context_check"]["detail"]
    assert detail["kind"] == "semantic" and r["removed_spans"][0]["removal_reason"] == "keep_decision"


def test_review_probe_filler_sentence_is_a_local_seam(pol):
    w = SPEC("Das war teuer. Äh. Aber es hat sich gelohnt. Äh. Und zwar richtig. Äh. Am Ende waren alle froh.")
    r = build(w, pol)
    assert r["semantic_splices"] == 0 and r["local_cuts"] == 3 and r["valid"]
    assert [x["removal_reason"] for x in r["removed_spans"]] == ["hard_filler"] * 3


PAUSE_PROBES = [
    ("Q01", "Am Ende hatten wir [0.9] vierzig Kunden mehr als im Jahr davor.", 3, "dramatic"),
    ("Q02", "Am Ende hatten wir [0.9] 40 Prozent mehr Umsatz im Jahr.", 3, "dramatic"),
    ("Q03", "Und dann haben wir [0.9] nichts mehr davon gehört bis heute.", 3, "dramatic"),
    ("Q04", "Wir wollten aufgeben. [0.9] Doch dann kam der Anruf vom Kunden.", 2, "dramatic"),
    ("Q05", "Alles lief nach Plan. [0.8] Nur der Kunde hat nicht bezahlt am Ende.", 3, "dramatic"),
    ("Q06", "Was glaubst du, was dann passiert ist? [0.8] Er hat einfach aufgelegt am Telefon.", 6, "reaction"),
    ("Q07", "Und dann ist mein Vater [1.2] gestorben und wir mussten den Betrieb übernehmen.", 4, "dramatic"),
    ("Q08", "Mein Vater ist gestorben. [1.4] Wir mussten den Betrieb sofort übernehmen.", 3, "orientation"),
    ("Q09", "Ich zeige Ihnen das jetzt einmal am Werkstück. [2.5] So hält das ganz ohne Leim.", 7, "demonstration"),
    ("Q10", "Ich lege das Brett hier [1.6] genau auf die Kante und dann drücke ich.", 4, "dramatic"),
    ("Q11", "Unser Stand war direkt neben den Toiletten. [0.8] Der einzige Besucher fragte nach dem Klo. @B Haha.", 6, "dramatic"),
    ("Q14", "Unser Stand war direkt neben den Toiletten. [0.8] Der einzige Besucher fragte nach dem Klo.", 6, "technical"),
]  # fmt: skip


@pytest.mark.parametrize(("pid", "spec", "after", "cls"), PAUSE_PROBES, ids=[x[0] for x in PAUSE_PROBES])
def test_review_probe_pause_classes(pol, pid, spec, after, cls):
    w = SPEC(spec)
    p = pause_after(w, after, pol)
    assert p["class"] == cls, p["reason"]
    r = build(w, pol)
    assert (next(x for x in r["pauses"] if x["after_word"] == after)["action"] == "trimmed") is (cls == "technical")


def test_review_probe_dense_pauses_respect_the_minimum_segment(pol):
    r = build(SPEC("Wir haben [0.6] das dann [0.6] im Team [0.6] lange besprochen [0.6] und dann umgesetzt."), pol)
    assert r["local_cuts"] == 4
    r = build(SPEC("Also wir [0.7] haben [0.7] das [0.7] dann [0.7] so gemacht und es lief gut."), pol)
    assert all(s["end"] - s["start"] >= editorial.trim_settings(pol)["min_segment_s"] for s in r["segments"])


REMOVAL_PROBES = [
    ("R01", "Das ist halt so und eigentlich ja auch doch mal schon richtig gewesen äh oder.", []),
    ("R02", "Bei der EM haben wir richtig viel verkauft im ganzen Sommer.", []),
    ("R03", "Wir haben das Projekt @B Genau. @A dann ganz anders aufgesetzt als geplant.", [("backchannel", "Genau.")]),
    ("R04", "Wir haben das Projekt @B Ja. @A dann ganz anders aufgesetzt als geplant.", [("backchannel", "Ja.")]),
    ("R05", "@H Machst du das wieder? @G Klar. @H Und warum genau?", []),
    ("R06", "@H Du meinst also, die Preise waren zu hoch. @G Genau. @H Und was habt ihr dann gemacht?", []),
    ("R07", "Wir haben, wir haben wirklich alles versucht und es hat nicht gereicht.", []),
    ("R08", "Viel, viel besser lief es nach dem Umbau der ganzen Halle.", []),
    ("R09", "Wir haben, äh, wir haben das dann ganz anders gemacht.", [("restart+hard_filler", "Wir haben, äh,")]),
    ("R10", "Der Grund war… der Preis. Mehr nicht.", []),
    ("R11", "Wir hab- wir haben das dann so gemacht wie besprochen.", [("restart", "Wir hab-")]),
    ("R12", "Hallo zusammen, unser größter Kunde hat letzte Woche gekündigt. Wir mussten sofort reagieren und haben umgebaut.",
     [("greeting", "Hallo zusammen,")]),
    ("R13", "Hallo zusammen. Unser größter Kunde hat gekündigt. Wir mussten sofort reagieren und haben umgebaut.",
     [("greeting", "Hallo zusammen.")]),
    ("R14", "Unser größter Kunde hat gekündigt. Herzlich willkommen übrigens. Wir mussten sofort reagieren.", []),
    ("R15", "Danke für die Einladung. Wenn ich ehrlich bin, war das ein hartes Jahr für uns.",
     [("greeting", "Danke für die Einladung.")]),
    ("R16", "Bevor wir anfangen, kurz zur Technik. Wir haben die Preise verdoppelt und trotzdem mehr verkauft.",
     [("organisational", "Bevor wir anfangen, kurz zur Technik.")]),
    ("R17", "Ich habe ähm [1.6] ich habe damals einen Fehler gemacht.", []),
    ("R18", "Wir haben das Projekt dann @B Hm? @A ja ganz anders aufgesetzt.", []),
    ("R19", "Wir haben danach die Preise angepasst und den Leistungsumfang begrenzt. Das hat geholfen. Können wir kurz eine Pause machen?",
     [("organisational", "Können wir kurz eine Pause machen?")]),
    ("R20", "Wir haben danach die Preise angepasst und den Leistungsumfang begrenzt. Das hat geholfen. Danke erstmal, das war der wichtigste Schritt für uns überhaupt.", []),
    ("R21", "Die, die das gemacht haben, wissen das genau. Danach haben wir die Preise angepasst.", []),
    ("R22", "Der, der zuerst kommt, bekommt den Auftrag. Danach haben wir die Preise angepasst.", []),
    ("R23", "Wer, wer hat das eigentlich entschieden? Danach haben wir die Preise angepasst.", []),
    ("R24", "@H Habt ihr das bereut? @G Nein. @H Warum nicht?", []),
    ("R25", "Warum, warum macht man so etwas überhaupt? Danach haben wir die Preise angepasst.", []),
]  # fmt: skip


@pytest.mark.parametrize(("pid", "spec", "expected"), REMOVAL_PROBES, ids=[x[0] for x in REMOVAL_PROBES])
def test_review_probe_removals(pol, pid, spec, expected):
    w = SPEC(spec)
    r = build(w, pol)
    got = [(x["removal_reason"], x["protected_context_check"]["detail"]["text"]) for x in r["removed_spans"]]
    assert got == expected
    assert r["valid"], r["issues"]


def test_review_probe_hm_question_and_abbreviations_are_no_fillers():
    assert trim_plan.is_hard_filler({"text": "äh,"}) and trim_plan.is_hard_filler({"text": "Ähm."})
    for text in ("EM", "EM.", "Hm?", "HM"):
        assert not trim_plan.is_hard_filler({"text": text}), text


TAIL_PROBES = [
    ("E01", ["Danke fürs Zuhören und bis bald!"], 1, ["farewell"]),
    ("E02", ["Unterm Strich: Preise rauf, Aufträge rauf."], 1, ["weak_summary"]),
    ("E03", ["Wenn ihr mehr wissen wollt, Link in der Bio."], 2, []),
    ("E04", ["Schreibt mir für ein kostenloses Erstgespräch."], 1, ["sales_call"]),
    ("E05", ["Das gilt lediglich für Neukunden, also bis bald."], 2, []),
    ("E06", ["Wie gesagt, das klappt bloß bei kleinen Teams."], 2, []),
    ("E07", ["Wie gesagt, das klappt nur bei kleinen Teams."], 2, []),
    ("E11", ["Am Ende haben dreimal so viele Leute abonniert."], 2, []),
    ("E12", ["Zusammengefasst war das zwar riskant, aber richtig."], 2, []),
    ("E13", ["Kurz gesagt: Es war teuer und hat sich trotzdem gelohnt."], 2, []),
    ("E14", ["Kurz gesagt, wenn der Kunde mitzieht, lohnt es sich."], 2, []),
    ("E15", ["Aber nur bei uns.", "Tschüss!"], 2, ["farewell"]),
]


@pytest.mark.parametrize(("pid", "tail", "last", "reasons"), TAIL_PROBES, ids=[x[0] for x in TAIL_PROBES])
def test_review_probe_reward_end(pol, pid, tail, last, reasons):
    s = sents_of("Wir haben die Preise erhöht.", "Danach kamen mehr Aufträge als je zuvor.", *tail)
    new_last, cut = trim_plan.reward_end(s, 0, len(s) - 1, 1, pol)
    assert new_last == last and [c["reason"] for c in cut] == reasons


@pytest.mark.parametrize(
    ("pid", "texts"),
    [
        ("E08", ("Wir haben dann die Preise erhöht.", "Die Preise erhöht, um 20.")),
        ("E09", ("Am Ende hat der Kunde gekündigt.", "Gekündigt hat der Kunde, nicht wir.")),
        ("E10", ("Am Ende hat der Kunde gekündigt.", "Der Kunde hat gekündigt, zum ersten Mal überhaupt.")),
    ],
)
def test_review_probe_functional_repetition_is_no_repeated_payoff(pol, pid, texts):
    assert trim_plan.reward_end(sents_of(*texts), 0, 1, 0, pol) == (1, [])


DEBATE_PROBES = [
    ("D1", "@H Wie habt ihr das gemacht? @G Wir haben die Preise erhöht und mehr verkauft.", False),
    ("D2", "@H Wie habt ihr das gemacht? @G Wir haben die Preise erhöht. @H Und die Kunden?", False),
    ("D3", "@G Wir haben die Preise @H Okay. @G erhöht und mehr verkauft.", False),
    ("D4", "@A Das ist falsch. @B Nein, das stimmt. @A Ist es nicht.", True),
    ("D5", "@G Wir haben die Preise @H Mhm. @G erhöht und @H Genau. @G mehr verkauft.", False),
    ("D6", "@G Wir haben die Preise @H Ja, ja, klar. @G erhöht und mehr verkauft.", False),
    ("D7", "Wir haben die Preise erhöht.", False),
]


@pytest.mark.parametrize(("pid", "spec", "debate"), DEBATE_PROBES, ids=[x[0] for x in DEBATE_PROBES])
def test_review_probe_is_debate(pid, spec, debate):
    w = SPEC(spec)
    assert compose.is_debate(w, 0, len(w) - 1) is debate


def test_review_probe_teaser_rules_in_debate_and_interview():
    w = SPEC("@A Das ist falsch. @B Nein, das stimmt so nicht. @A Ist es doch nicht.")
    teased = compose.Composition([
        compose.Segment(w[0]["start"], w[2]["end"] + 0.05, "teaser"), compose.Segment(w[0]["start"] - 0.05, w[-1]["end"] + 0.08),
    ])  # fmt: skip
    assert teased.validate(w, max_splices=2, debate_no_reorder=True) == ["Debatte: kein Teaser, die Reihenfolge des Gesprächs bleibt (E6)"]
    assert teased.validate(w) == []
    w2 = SPEC("@H Wie habt ihr das gemacht? @G Wir haben die Preise erhöht. Das war mutig.")
    interview = compose.Composition([compose.Segment(w2[5]["start"], w2[9]["end"], "teaser"), compose.Segment(w2[0]["start"], w2[-1]["end"])])
    assert interview.validate(w2, max_splices=2, debate_no_reorder=True) == []
    swapped = compose.Composition([compose.Segment(w[7]["start"], w[-1]["end"]), compose.Segment(w[0]["start"], w[6]["end"])])
    assert "Debatte: Body-Segmente umgestellt, Debatten nie umordnen (E6)" in swapped.validate(w, max_splices=2, debate_no_reorder=True)


def test_review_probe_timeline_and_midpoint_remap(pol):
    w = SPEC("Wir haben äh das im Team [1.0] lange besprochen und äh dann umgesetzt. Danach lief es [0.9] deutlich besser als vorher.")
    r = build(w, pol)
    tl = r["timeline"]
    assert all(abs(a["output_out"] - b["output_in"]) < 1e-9 for a, b in zip(tl, tl[1:]))
    assert tl[-1]["output_out"] == pytest.approx(r["duration_s"], abs=1e-3)
    comp = compose.Composition.from_json(r["segments"])
    out = compose.remap_words(w, comp, by_midpoint=True)
    assert [x["text"] for x in out] == [w[i]["text"] for i in sorted(kept_ids(r))]
    assert all(x["start"] <= y["start"] for x, y in zip(out, out[1:]))
    assert all(0 <= x["start"] <= x["end"] <= r["duration_s"] + 1e-6 for x in out)


def test_review_probe_no_audible_rest_of_a_removed_filler(pol):
    w = SPEC("Wir haben das ähm dann im Team lange besprochen und umgesetzt.", word_s=0.4, gap=0.0)
    r = build(w, pol)
    a = w[3]
    assert r["removed_spans"][0]["protected_context_check"]["detail"]["text"] == "ähm"
    assert all(min(s["end"], a["end"]) - max(s["start"], a["start"]) <= 0 for s in r["segments"])


def test_review_probe_output_timeline_random_is_deterministic():
    import random

    rnd = random.Random(1)
    for _ in range(300):
        segs, t = [], 0.0
        for _k in range(rnd.randint(1, 6)):
            a = t + rnd.uniform(0, 2)
            b = a + rnd.uniform(0.01, 3)
            segs.append(compose.Segment(round(a, 3), round(b, 3)))
            t = b
        c = compose.Composition(segs)
        t1 = compose.output_timeline(c)
        assert t1 == compose.output_timeline(compose.Composition.from_json(c.to_json()))
        assert all(abs(x["output_out"] - y["output_in"]) < 1e-12 for x, y in zip(t1, t1[1:]))
        assert abs(t1[-1]["output_out"] - c.duration) <= 0.0005 * len(segs) + 1e-9


def test_review_probe_temporal_triggers(pol):
    for text, trigger in [
        ("Letzte Woche hat er gekündigt.", "Letzte Woche"),
        ("Gestern kam der Anruf.", "Gestern"),
        ("Vor zwei Jahren war das anders.", "Vor zwei Jahren"),
        ("Nächstes Jahr bauen wir an.", "Nächstes Jahr"),
    ]:
        spans = [p for p in trim_plan.protected_spans(SPEC(text), pol) if p["type"] == "temporal"]
        assert spans and spans[0]["text"] == trigger, text


# -- Folgepunkte aus dem Review der Verdrahtung ---------------------------------------------------------


def test_check_cut_v2_negations_follow_the_trim_list():
    w = SPEC("Wir haben die Preise erhöht. Kurz gesagt, wir rechnen jetzt alles noch zweimal durch.")
    cut = [(0, 4)]
    assert any(x["type"] == "negation_removed" for x in fidelity.check_cut(w, cut))  # v1 unverändert
    assert any(x["type"] == "negation_removed" for x in fidelity.check_cut(w, cut, rule="v1"))
    assert not any(x["type"] == "negation_removed" for x in fidelity.check_cut(w, cut, rule="v2"))
    w = SPEC("Wir haben die Preise erhöht. Das hat nicht geklappt.")
    v2 = next(x for x in fidelity.check_cut(w, [(0, 4)], rule="v2") if x["type"] == "negation_removed")
    assert v2["severity"] == "high" and v2["detail"] == ["nicht"]
    assert "noch" not in trim_plan.NEGATION_TRIGGERS and "nein" in trim_plan.NEGATION_TRIGGERS


def test_pauses_in_and_right_after_a_correction_sentence_are_dramatic(pol):
    w = SPEC(
        "Wir hatten damals [0.6] vierzehn Leute im Team. Wir haben dann stattdessen [0.6] Newsletter gemacht. "
        "Ich muss das [0.6] korrigieren. Es waren vier [0.6] Newsletter. Danach lief [0.6] alles ruhig weiter."
    )
    classes = {p["after_word"]: (p["class"], p["reason"]) for p in trim_plan.classify_pauses(w, None, pol)}
    assert classes[2][0] == "dramatic" and "Zahl" in classes[2][1]  # vor „vierzehn“
    assert classes[10] == ("dramatic", "Pause im Korrektursatz")  # nach „stattdessen“
    assert classes[15] == ("dramatic", "Pause im Korrektursatz")  # „Ich muss das [0,6] korrigieren.“
    assert classes[19] == ("dramatic", "Pause im Korrektursatz")  # Satz unmittelbar nach der Korrektur
    assert classes[22] == ("technical", "technische Leerstelle")  # zwei Sätze danach wieder technisch
    spans = [p for p in trim_plan.protected_spans(w, pol) if p["type"] == "correction"]
    assert any(p["text"] == "stattdessen" for p in spans)
