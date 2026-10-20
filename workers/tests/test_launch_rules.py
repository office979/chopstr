"""Regeltests zu den 16 unverhandelbaren Regeln (docs/MASTER-PROMPT-LAUNCH.md Abschnitt 5, Phase 3 Gate 3).

Je Regel mindestens ein Test, der eine Verletzung erwischt, und ein zulässiges Gegenbeispiel, das durchgeht
(Review 3: ohne Gegenbeispiel lehnt ein Prüfer einfach alles Verdächtige ab). Liegt die Prüfung in Dateien
anderer Lanes, werden die vorhandenen Funktionen nur aufgerufen. Fehlt eine Prüfung, steht dort
``pytest.xfail`` mit Regel, Lane und genauer Begründung; das ist kein Bestehen.
"""

from __future__ import annotations

import pytest

from chopstr_worker import config, editorial, providers_llm
from chopstr_worker.activities import analyze
from chopstr_worker.pipeline import (
    ausgabe_pruefung,
    captions_de,
    clip_candidate,
    compose,
    dach_nlp,
    editorial_gates,
    fidelity,
    release_gate,
    render,
    segment,
    story_engine,
    story_graph,
    trim_plan,
)
from chopstr_worker.providers_llm import LLM
from chopstr_worker.residency import Tenant
from tests.transcript_fixtures import demo_words, make_words


@pytest.fixture(autouse=True)
def _no_spacy(monkeypatch):
    monkeypatch.setattr(dach_nlp, "nlp", lambda: None)


@pytest.fixture
def v2(monkeypatch):
    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "2")
    editorial.clear_cache()
    yield editorial.load(2)
    editorial.clear_cache()


def W(text: str, speaker: str = "A", step: float = 0.3) -> list[dict]:
    return [{"text": t, "start": round(i * step, 3), "end": round(i * step + step - 0.02, 3), "speaker": speaker} for i, t in enumerate(text.split())]


def S(*items: tuple[str, str]):
    return editorial_gates.from_sentence_texts([{"speaker": spk, "text": text} for spk, text in items])


# -- Regel 1: Verbklammer, trennbare Verben, Nebensatz ---------------------------------------------------


def test_rule01_cut_inside_separable_verb_is_caught():
    w = W("Wir fangen morgen an.")
    res = dach_nlp.bracket_heuristic(w[:3], w[3:])
    assert res["open"] is True and res["signal"] == "separable_particle"


def test_rule01_cut_between_subordinator_and_verb_is_caught():
    w = W("Ich glaube, dass wir das Projekt morgen beenden.")
    assert dach_nlp.bracket_heuristic(w[:5], w[5:])["open"] is True


def test_rule01_cut_after_closed_bracket_is_permissible():
    assert dach_nlp.bracket_heuristic(W("Wir fangen morgen an."), W("Das ist gut."))["open"] is False


# -- Regel 2: keine entfernte Verneinung, Einschränkung, Bedingung -------------------------------------------


def test_rule02_removed_negation_is_caught():
    w = W("Das ist nicht der beste Weg.")
    findings = fidelity.check_cut(w, [(0, 1), (3, 5)])
    assert any(f["type"] == "negation_removed" for f in findings)


def test_rule02_cut_keeping_negation_is_permissible():
    w = W("Das ist nicht der beste Weg.")
    assert fidelity.check_cut(w, [(0, 5)]) == []


def test_rule02_condition_directly_before_the_clip_is_caught_and_title_card_is_second_choice(v2):
    words = make_words([
        ("A", "Nur bei Stammkunden bringen Rabatte etwas.", 3.0), ("A", "Rabatte bringen sofort mehr Umsatz.", 3.0),
        ("A", "Wir haben das im Laden jeden Monat gesehen.", 3.0),
    ])  # fmt: skip
    sents = segment.sentences_from_words(words, rule="v2")
    before = {"text": sents[0].text, "start_s": sents[0].start, "end_s": sents[0].end}
    res = fidelity.counter_read([{"text": s.text, "start_s": s.start, "end_s": s.end} for s in sents[1:]], before, None)
    assert "condition" in res["differs"]
    attempt = release_gate.title_card_attempt(words, sents, 1, 2, {}, v2)
    assert attempt["text"] == sents[0].text and attempt["recheck"]["passed"] is True, "nur wörtlich und erneut geprüft"


def test_rule02_clip_with_its_condition_is_permissible(v2):
    words = make_words([("A", "Nur bei Stammkunden bringen Rabatte etwas.", 3.0), ("A", "Rabatte bringen sofort mehr Umsatz.", 3.0)])
    sents = segment.sentences_from_words(words, rule="v2")
    res = fidelity.counter_read([{"text": s.text, "start_s": s.start, "end_s": s.end} for s in sents], None, None)
    assert res["differs"] == []
    assert release_gate.title_card_attempt(words, sents, 0, 1, {}, v2) is None


# -- Regel 3: kein ungelöster Verweis, der für die Kernaussage nötig ist ------------------------------------


def test_rule03_unresolved_pronoun_is_caught():
    w, s = S(("A", "Er hat damals alles hingeworfen."))
    res = editorial_gates.unresolved_pronoun(w, s, 0, 0)
    assert res["passed"] is False and res["healable"] == "front"


def test_rule03_back_reference_is_caught():
    w, s = S(("A", "Wie gesagt, so geht es nicht weiter."))
    assert editorial_gates.back_reference(w, s, 0, 0)["passed"] is False


@pytest.mark.parametrize("opening", [
    "Es gibt drei häufige Fehler beim Preis.",
    "Das Wichtigste zuerst. Plane die Woche am Sonntag.",
    "Er hat mein Leben verändert: mein Mentor Thomas.",
    "Das ist mein wichtigster Tipp: plane früh.",
])  # fmt: skip
def test_rule03_expletive_and_cataphoric_openings_are_permissible(opening):
    w, s = S(*[("A", t if t.endswith(".") else t + ".") for t in opening.split(". ")])
    assert editorial_gates.unresolved_pronoun(w, s, 0, len(s) - 1)["passed"] is True
    assert editorial_gates.back_reference(w, s, 0, len(s) - 1)["passed"] is True


def test_rule03_rule_hint_is_never_blocked_alone():
    state = release_gate.derive_review_state({"text": "[0] (A) Er hat damals alles hingeworfen.",
                                              "quality_gate_results": {"unresolved_pronoun": {"passed": False, "detail": "Pronomen ohne Bezug"}}})  # fmt: skip
    assert state["state"] == "uncertain" and state["reasons"][0]["origin"] == "rule"


# -- Regel 4: kein Ende, das eine Fortsetzung erwartet ------------------------------------------------------


def test_rule04_open_loop_end_is_caught():
    _w, s = S(("A", "Das Problem war die Planung, und zwar"))
    assert story_engine._open_loop_gate(s, 0)["passed"] is False


def test_rule04_deferred_forward_reference_is_caught():
    w, s = S(("A", "Dazu komme ich später."))
    assert editorial_gates.forward_reference(w, s, 0, 0)["passed"] is False


def test_rule04_closed_end_is_permissible():
    w, s = S(("A", "Das Problem war die Planung."))
    assert story_engine._open_loop_gate(s, 0)["passed"] is True
    assert editorial_gates.forward_reference(w, s, 0, 0)["passed"] is True


# -- Regel 5: epistemische Marker und Modalpartikeln bleiben, nur echte Füller raus -------------------------


def test_rule05_removed_epistemic_marker_is_caught(v2):
    w = W("Ich glaube das ist vielleicht der beste Weg.")
    findings = fidelity.check_cut(w, [(2, 3), (5, 8)], rule="v2", policy=v2)
    assert any(f["type"] == "protected_removed" and f["severity"] == "high" for f in findings)


def test_rule05_filler_removal_keeps_modal_particles(v2):
    cands = trim_plan.removal_candidates(W("Das ist äh halt vielleicht der beste Weg."), v2)
    assert [c["text"] for c in cands] == ["äh"], "„halt“ und „vielleicht“ bleiben"


def test_rule05_filler_needs_silence_on_both_sides(v2):
    """Regel 5 verlangt Stille auf beiden Seiten eines entfernten Füllers."""
    cands = trim_plan.removal_candidates(W("Das ist äh der beste Weg.", step=0.3), v2)
    if cands:
        pytest.xfail(
            "Regel 5: nicht implementiert, Lane P4 (trim_plan.removal_candidates). Ein Füller ohne Pause davor und "
            "danach wird als hard_filler entfernt; geprüft wird nur, dass keine lange Stille angrenzt. Wirkt heute "
            "nicht, weil die Regel trim.enabled aus ist."
        )
    assert cands == []


# -- Regel 6: Hook-Claim belegt, Verdichtung erlaubt, Bedeutung erhalten --------------------------------------

SPOKEN = "Ich habe in einer Woche rund 40.000 Euro verloren."


def test_rule06_hook_changing_attribution_and_causality_is_caught():
    issues = fidelity.hook_claim_check_v2("Diese Methode kostet dich 40.000 Euro.", SPOKEN, meaning=True)
    assert any(i.startswith("Zuschreibung") for i in issues) and any(i.startswith("Kausalität") for i in issues)


def test_rule06_invented_number_is_caught():
    assert fidelity.hook_claim_check_v2("Rund 50.000 Euro Verlust in einer Woche.", SPOKEN, meaning=True)


def test_rule06_condensed_hook_is_permissible():
    assert fidelity.hook_claim_check_v2("Rund 40.000 Euro Verlust in einer Woche.", SPOKEN, meaning=True) == []


# -- Regel 7: Teaser höchstens 6 s, ein Sprecher, markiert, kommt im Clip vor -------------------------------


def _teaser_words() -> list[dict]:
    return [{"text": f"w{i}.", "start": float(i), "end": float(i) + 0.9, "speaker": "A" if i < 6 else "B"} for i in range(10)]


def test_rule07_long_multi_speaker_teaser_is_caught():
    comp = compose.with_teaser(compose.Composition([compose.Segment(0.0, 10.0)]), 1.0, 8.0)
    problems = comp.validate(_teaser_words())
    assert any("zu lang" in p for p in problems) and any("mehrere Sprecher" in p for p in problems)


def test_rule07_unmarked_reordering_is_caught():
    comp = compose.Composition([compose.Segment(4.0, 5.0), compose.Segment(0.0, 10.0)])
    assert any("umsortiert" in p for p in comp.validate(_teaser_words()))


def test_rule07_short_marked_teaser_is_permissible():
    comp = compose.with_teaser(compose.Composition([compose.Segment(0.0, 10.0)]), 1.0, 5.0)
    assert comp.validate(_teaser_words()) == []


# -- Regel 8: Sprecherzuordnung bei Frage, Unterbrechung, Antwort -------------------------------------------

QA = (("A", "Hast du je ans Aufhören gedacht?"), ("B", "Nein, nie ernsthaft."), ("B", "Das Team hat mich getragen."))


def test_rule08_answer_without_question_is_caught():
    w, s = S(*QA)
    assert editorial_gates.speaker_turn(w, s, 1, 2)["passed"] is False


def test_rule08_question_with_answer_is_permissible():
    w, s = S(*QA)
    assert editorial_gates.speaker_turn(w, s, 0, 2)["passed"] is True


# -- Regel 9: Untertitel ------------------------------------------------------------------------------------


def test_rule09_compound_break_and_split_number_are_caught_in_legacy_rules():
    assert captions_de.hyphenate("Kundenanfragebearbeitung", 12) != ["Kunden-", "anfrage-", "bearbeitung"]


def test_rule09_v2_breaks_at_morphemes_and_keeps_numbers_together(v2):
    rules = captions_de.caption_rules(v2)
    assert captions_de.hyphenate("Kundenanfragebearbeitung", 12, rules) == ["Kunden-", "anfrage-", "bearbeitung"]
    cards = captions_de.build_cards(W("Wir sparen 3,5 Mio. Euro pro Jahr"), limit=18, words_per_card=3, rules=rules)
    texts = [" ".join(w["text"] for w in card) for card in cards]
    assert any("3,5 Mio. Euro" in t for t in texts)


def test_rule09_mixed_address_is_caught_and_consistent_is_permissible():
    assert captions_de.anrede_pruefen(W("Hast du das gesehen? Dann melden Sie sich."))["gemischt"] is True
    assert captions_de.anrede_pruefen(W("Hast du das gesehen? Dann melde dich."))["gemischt"] is False


def test_rule09_sharp_s_by_country_in_subtitles():
    if not hasattr(captions_de, "eszett_pruefen"):
        pytest.xfail(
            "Regel 9: nicht implementiert, Lane P4 (captions_de). ß/ss nach Land prüft nur copy_de.lint für Hook und "
            "Copy (CH: heiß zu heiss), die Untertitel geben den Transkripttext ohne Länderprüfung aus."
        )


# -- Regel 10: Original-Audio, nur Pegel und Fades ------------------------------------------------------------

PLAN = {"shots": [{"start": 0, "end": 4}], "segments": [{"start": 0, "end": 2}, {"start": 3, "end": 4}], "audio": {"micro_fade_ms": 20, "lufs": -14, "true_peak": -1}}
ALLOWED_AUDIO = ("asetpts", "afade", "concat", "loudnorm", "aresample")


def _audio_filters(chain: str) -> set[str]:
    import re

    return {name for groups in re.findall(r"\]([a-z_]+)=|,([a-z_]+)=|\]([a-z_]+)\[", chain) for name in groups if name}


def test_rule10_loudnorm_and_fades_only_is_permissible():
    chain = render.audio_chain(PLAN, 1, "loudnorm=I=-14:TP=-1", compressor=False)
    assert _audio_filters(chain) <= set(ALLOWED_AUDIO)


def test_rule10_other_audio_processing_is_caught():
    chain = render.audio_chain(PLAN, 1, "loudnorm=I=-14:TP=-1", compressor=True)
    extra = _audio_filters(chain) - set(ALLOWED_AUDIO)
    if extra and not hasattr(render, "audio_filters_allowed"):
        pytest.xfail(
            f"Regel 10: nicht implementiert, Lane P4 (render). Keine Prüfung verbotener Audiofilter; audio_chain fügt "
            f"bei gemessener LRA über 7 selbst {sorted(extra)} ein, und nichts lehnt das ab."
        )
    assert not extra


# -- Regel 11: sensible Themen und Humor an den Menschen ------------------------------------------------------


def test_rule11_humor_and_sensitive_topic_hold_auto_acceptance():
    assert analyze.auto_accept_blockers(["humor", "sensitive_topic"], "[0] (A) Das Team hat gelacht.") == ["humor", "sensitive_topic"]
    state = release_gate.derive_review_state({"text": "[0] (A) Das Team hat gelacht."}, ["humor"])
    assert state["state"] == "uncertain"


def test_rule11_plain_candidate_is_permissible():
    assert analyze.auto_accept_blockers(["heuristic_only"], "[0] (A) Das Team hat gelacht.") == []


# -- Regel 12: Begründung in einem Satz und Belegstellen; nicht gefunden ist kein Beweis ----------------------


def _heuristic_report(v2_policy):
    llm = LLM(Tenant(id="ws", tier="standard"), provider=providers_llm.HEURISTIC_PROVIDER, s=config.settings())
    return story_engine.run(demo_words(), {"audience": "Gründer", "platform": "linkedin"}, {}, None, llm)


def test_rule12_candidate_without_reason_is_caught(v2):
    report = _heuristic_report(v2)
    cc = dict(report.clip_candidates[0])
    assert clip_candidate.validate(cc) == []
    cc["decision_reason"] = ""
    assert any("decision_reason" in e for e in clip_candidate.validate(cc))


def test_rule12_every_candidate_has_one_sentence_why_and_spans(v2):
    report = _heuristic_report(v2)
    assert report.candidates
    for c in report.candidates:
        assert c.why.endswith(".") and c.why.count(". ") == 0, "ein Satz"
        for r in c.rubric["review_state"]["reasons"]:
            assert r["text"].endswith(".")
    assert "kein Beleg" in story_graph.CLAIM_INDEX_NOTE, "ein nicht gefundener Bezug wird nicht als Beweis ausgegeben"


# -- Regel 13: Datenvertrag Transkript -------------------------------------------------------------------------


def test_rule13_unknown_text_field_is_caught():
    with pytest.raises(ValueError):
        captions_de.check_text_field("text_raw")


def test_rule13_normalized_text_is_separate_from_spoken_words():
    w = {"text": "isch", "text_norm": "ist", "start": 0.0, "end": 0.3}
    assert captions_de.word_text(w, "text_norm") == "ist" and w["text"] == "isch"


def test_rule13_route_documents_verbatim_or_translating():
    from chopstr_worker.pipeline import transcribe

    if not any(hasattr(transcribe, n) for n in ("ROUTE_FIDELITY", "route_fidelity", "ASR_ROUTE_MODE")):
        pytest.xfail(
            "Regel 13: nicht implementiert, Lane P1 (transcribe). Je ASR-Route ist nicht dokumentiert, ob sie wortgetreu "
            "transkribiert oder überträgt, und normalize_numbers schreibt in w['text'] statt in ein eigenes Feld."
        )


# -- Regel 14: drei Ergebnisklassen ---------------------------------------------------------------------------


def test_rule14_confirmed_error_is_blocked_and_never_auto_accepted():
    rubric = {"text": "[0] (A) Rabatte bringen Umsatz.", "critic": {"confirmed": True, "heuristic": False},
              "critic_findings": [{"kind": "claim_contradicted", "severity": "fidelity", "explanation": "Widerlegt.", "sentence_refs": []}]}  # fmt: skip
    state = release_gate.derive_review_state(rubric)
    assert state["state"] == "blocked"
    assert "review_blocked" in analyze.auto_accept_blockers([], rubric["text"], "", state)


def test_rule14_uncertain_holds_and_passed_is_usable():
    text = "[0] (A) Rabatte bringen Umsatz."
    uncertain = release_gate.derive_review_state({"text": text, "quality_gate_results": {"back_reference": {"passed": False, "detail": "Rückverweis"}}})
    assert uncertain["state"] == "uncertain" and analyze.auto_accept_blockers([], text, "", uncertain) == ["review_uncertain"]
    passed = release_gate.derive_review_state({"text": text})
    assert passed["state"] == "passed" and analyze.auto_accept_blockers([], text, "", passed) == []


# -- Regel 15: weniger als zehn, auch null mit Begründung --------------------------------------------------------


def test_rule15_zero_candidates_carry_a_reason():
    report = story_engine.DetectReport()
    chapter = [segment.Sentence(0, "Hallo.", 0.0, 1.0, "A", (0, 0)), segment.Sentence(1, "Tschüss.", 1.5, 2.5, "A", (1, 1))]
    story_engine.no_viable_moment(report, 0, chapter)
    (entry,) = report.discarded
    assert entry["reason"] == "no_viable_moment" and entry["detail"]


def test_rule15_fewer_than_ten_are_not_padded(v2):
    kept, dropped, reserve = story_engine.select_with_reserve([], 10, pol=v2)
    assert (kept, dropped, reserve) == ([], [], [])


# -- Regel 16: Schnittbeschreibung und Export ---------------------------------------------------------------------


def test_rule16_output_positions_are_derived_from_the_cut():
    comp = compose.with_teaser(compose.Composition([compose.Segment(0.0, 10.0)]), 1.0, 5.0)
    tl = compose.output_timeline(comp)
    assert [(e["source_in"], e["source_out"], e["output_in"], e["output_out"]) for e in tl] == [(1.0, 5.0, 0.0, 4.0), (0.0, 10.0, 4.0, 14.0)]


def _export(**over):
    base = dict(
        datei_vorhanden=True, hat_bild=True, hat_ton=True, dauer_s=30.0, geplante_dauer_s=30.0, breite=1080, hoehe=1920,
        geplante_breite=1080, geplante_hoehe=1920, schwarzbilder=[], lufs=-16.0, ziel_lufs=-16.0, spitze_dbtp=-2.0,
        ziel_spitze_dbtp=-1.5, woerter=80, untertitelkarten=40, untertitel_eingebrannt=True,
    )  # fmt: skip
    base.update(over)
    return ausgabe_pruefung.schlimmstes(ausgabe_pruefung.pruefen(**base))


def test_rule16_export_without_sound_is_caught():
    assert _export(hat_ton=False) == "fehler"


def test_rule16_complete_export_is_permissible():
    assert _export() == "ok"


def test_rule16_repeated_approval_creates_no_duplicate():
    from chopstr_worker.workflows.clip_project import ClipProjectWorkflow

    wf = ClipProjectWorkflow()
    wf.approve("c1", "reels")
    wf.approve("c1", "reels")
    if len(wf.state.approved) > 1:
        pytest.xfail(
            "Regel 16: nicht implementiert, Lane P4 (workflows/clip_project.py). Zwei gleiche Freigaben ergeben zwei "
            "Einträge und zwei Renderaufträge; idempotent sind nur render._find_or_create_clip und auto_create_clips."
        )
    assert len(wf.state.approved) == 1
