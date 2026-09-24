"""Story-Engine mit Fake-LLM (Monkeypatch auf ``LLM.structured``): keine Modelle, kein Netz."""

from __future__ import annotations

import importlib.util

import pytest

from chopstr_worker import config, editorial, heuristic_llm
from chopstr_worker.pipeline import segment, story_engine, story_score
from chopstr_worker.providers_llm import LLM
from chopstr_worker.residency import Tenant
from tests.transcript_fixtures import demo_words, long_script, make_words

BRIEF = {"audience": "Gründer im DACH-Raum", "wanted": "Fehler, Zahlen", "exclude": "Werbung", "platform": "linkedin"}
# Die Gewichte stehen nicht mehr im Test, sondern in der redaktionellen Grundlage. Der erwartete
# Gesamtwert rechnet sich daraus, sonst müsste dieser Test bei jeder Änderung an der Grundlage
# nachgezogen werden, obwohl er gar nicht die Gewichte prüft.
DEFAULT_SCORES = {"hook": 8, "payoff": 7, "specificity": 9, "tension": 6, "audience_fit": 7}
DEFAULT_WEIGHTS = story_score.weights()
DEFAULT_TOTAL = round(sum(DEFAULT_SCORES[k] * DEFAULT_WEIGHTS[k] for k in DEFAULT_SCORES), 2)


def default_rubric(sents: list[dict]) -> dict:
    first = " ".join(sents[0]["text"].split()[:5])
    return {
        "unresolved_references": [],
        "needs_earlier_context": False,
        "ends_before_answer": False,
        **{k: v for k, v in DEFAULT_SCORES.items()},
        **{f"{k}_evidence": first for k in DEFAULT_SCORES},
        "is_humor": False,
        "sensitive_topic": False,
        "suggested_title_card": "",
        "why": "Fake-Rubrik.",
    }  # fmt: skip


class FakeBrain:
    """Antworten pro Tool; ``rubrics`` überschreibt Felder für eine Spanne (first_sent, last_sent)."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.propose_calls: list[list[dict]] = []
        self.moments = lambda sents: []
        self.rubrics: dict[tuple[int, int], dict] = {}
        self.confirm = {"misleading_without": True, "reason": "Der spätere Satz beschränkt die Aussage auf eine Branche.", "repair": "extend"}

    def structured(self, system, user, schema, tool_name, prompt_version, job_type="llm_score"):
        self.calls.append((tool_name, prompt_version))
        sents = heuristic_llm.parse_numbered(user)
        if tool_name == "propose_moments":
            self.propose_calls.append(sents)
            return {"moments": self.moments(sents)}
        if tool_name == "score_clip":
            r = default_rubric(sents)
            r.update(self.rubrics.get((sents[0]["idx"], sents[-1]["idx"]), {}))
            return r
        if tool_name == "confirm_qualification":
            return dict(self.confirm)
        raise AssertionError(tool_name)


@pytest.fixture
def brain(monkeypatch) -> FakeBrain:
    b = FakeBrain()

    def fake_structured(self_llm, system, user, schema, tool_name, prompt_version, job_type="llm_score"):
        return b.structured(system, user, schema, tool_name, prompt_version, job_type)

    monkeypatch.setattr(LLM, "structured", fake_structured)
    return b


@pytest.fixture
def llm(monkeypatch) -> LLM:
    monkeypatch.setenv("LLM_PROVIDER", "selfhost-eu")
    monkeypatch.setenv("SELFHOST_LLM_BASE_URL", "https://llm.intern")
    monkeypatch.setenv("SELFHOST_LLM_MODEL", "test-model")
    config.reload()
    return LLM(Tenant(id="ws", tier="standard"), s=config.settings())


def test_full_flow_row_matches_contract(brain, llm):
    brain.moments = lambda sents: [{"first_sent": 0, "last_sent": 3, "structure": "tension_first", "why": "Fehler mit Zahl."}]
    words = demo_words()
    report = story_engine.run(words, BRIEF, {"country": "AT"}, {"seeds": [3]}, llm)
    assert report.chapters == 1 and report.chapters_with_seeds == 1 and report.proposals == 1
    assert report.prompt_versions == ["propose_moments_v1", "score_clip_v2", "story_graph_confirm_v1"]
    assert len(report.candidates) == 1
    c = report.candidates[0]
    sents = segment.sentences_from_words(words)
    assert (c.first_sent, c.last_sent) == (0, 3)
    assert c.segments == [{"start": sents[0].start, "end": sents[3].end, "role": "body"}]
    assert c.start_s == sents[0].start and c.end_s == sents[3].end
    assert c.structure == "tension_first"
    assert c.model_id == "test-model" and c.prompt_version == "score_clip_v2"
    # Die Gesamtwertung kommt jetzt aus der redaktionellen Grundlage, nicht mehr aus den alten
    # fuenf Kriterien: sie traegt alle sieben und den Laengenabzug.
    pol = editorial.load()
    assert c.rubric["policy_version"] == editorial.policy_version()
    assert set(c.rubric["rubric_points"]) == {k.schluessel for k in pol.kriterien}
    assert c.total == pytest.approx(story_engine.policy_total({"rubric_points": c.rubric["rubric_points"]}, c.duration_s))
    assert 0.0 <= c.total <= pol.punkte_gesamt
    assert c.gate_passed is True

    r = c.rubric
    assert r["contract"] == "candidates_v1"
    assert set(r["scores"]) == {"hook", "payoff", "specificity", "tension", "audience_fit"}
    assert r["scores"]["hook"] == {
        "value": 8,
        "weight": round(DEFAULT_WEIGHTS["hook"], 4),
        "evidence": "Ehrlich gesagt war das der",
    }
    assert r["speakers"] == ["SPEAKER_00"] and r["duration_s"] == pytest.approx(c.duration_s)
    assert r["text"].startswith("[0] (SPEAKER_00) Ehrlich gesagt")
    assert r["repair"] == {"rounds": 0, "expanded_front": 0, "expanded_back": 0, "failed": False}
    assert r["proposal_why"] == "Fehler mit Zahl." and r["parent_id"] is None
    for key in ("unresolved_references", "needs_earlier_context", "ends_before_answer", "is_humor", "sensitive_topic", "suggested_title_card"):
        assert key in r

    g = c.gates
    assert list(g) == ["standalone", "fidelity", "sentence_boundaries", "verb_bracket", "no_open_loop"]
    assert g["standalone"] == {"passed": True, "detail": "keine offenen Verweise"}
    assert g["sentence_boundaries"]["passed"] and g["fidelity"]["passed"] and g["no_open_loop"]["passed"]
    # Die Verbklammer-Prüfung braucht spaCy. Ohne spaCy meldet das Gate available = False und lässt
    # durch, mit spaCy prüft es wirklich. Beides ist gültig; der Test darf nicht an der Umgebung hängen.
    assert g["verb_bracket"]["passed"] is True
    assert g["verb_bracket"]["available"] is (importlib.util.find_spec("spacy") is not None)

    # Story-Graph: Satz 6 relativiert, das Fake-LLM bestätigt
    assert len(c.story_graph_flags) == 1
    f = c.story_graph_flags[0]
    assert f["sentence_idx"] == 6 and f["marker"] == "das heißt aber nicht"
    assert f["confirmed"] is True and f["repair"] == "extend" and f["reason"].startswith("Der spätere Satz")
    assert set(f) == {"sentence_idx", "seconds_after", "marker", "text", "overlap", "confirmed", "reason", "repair", "suggestion"}
    assert ("confirm_qualification", "story_graph_confirm_v1") in brain.calls

    assert c.risk_flags == ["claim"]  # 40 Prozent, 2019: Zahlen im Clip
    assert c.why.startswith(f"Kernaussage in {round(c.duration_s)} Sekunden vollständig, Einstieg mit klarer Gegenposition")
    assert f"aber {round(f['seconds_after'])} Sekunden später relativiert der Sprecher die Aussage" in c.why
    assert c.why.endswith("passt für LinkedIn.")
    assert "–" not in c.why and "—" not in c.why
    row = c.to_row()
    assert set(row) == {
        "segments", "start_s", "end_s", "first_sent", "last_sent", "structure", "rubric", "gates", "story_graph_flags",
        "risk_flags", "total", "gate_passed", "why", "model_id", "prompt_version",
    }  # fmt: skip
    assert story_engine.CandidateResult.from_row(row) == c


def test_repair_extends_to_front_when_context_missing(brain, llm):
    brain.moments = lambda sents: [{"first_sent": 1, "last_sent": 3, "structure": "payoff_first", "why": "x"}]
    brain.rubrics[(1, 3)] = {"needs_earlier_context": True}
    cands = story_engine.detect(demo_words(), BRIEF, {}, None, llm)
    assert len(cands) == 1
    c = cands[0]
    assert (c.first_sent, c.last_sent) == (0, 3)
    assert c.rubric["repair"] == {"rounds": 1, "expanded_front": 1, "expanded_back": 0, "failed": False}
    assert c.gate_passed is True
    assert [t for t, _ in brain.calls if t == "score_clip"] == ["score_clip", "score_clip"]


def test_repair_failure_is_kept_with_title_card_hint(brain, llm):
    """Der Kandidat wird nicht mehr angeboten (gerissenes Tor), aber der Bericht zeigt ihn weiter."""
    brain.moments = lambda sents: [{"first_sent": 0, "last_sent": 3, "structure": "loop", "why": "x"}]
    brain.rubrics[(0, 3)] = {"needs_earlier_context": True, "suggested_title_card": "Nach dem Preisfehler 2019"}
    bericht = story_engine.run(demo_words(), BRIEF, {}, None, llm)
    assert bericht.candidates == [], "ein Kandidat mit gerissenem Tor darf nicht angeboten werden"
    c = bericht.verworfen[0]
    assert c.rubric["repair"]["failed"] is True and c.rubric["repair"]["rounds"] == 0  # Satz 0 hat keinen Vorgänger
    assert c.gates["standalone"] == {"passed": False, "detail": "Einstieg braucht Vorwissen"}
    assert c.gate_passed is False
    assert c.rubric["suggested_title_card"] == "Nach dem Preisfehler 2019"
    assert c.why.startswith("Ausschnitt von")
    assert "Einstieg braucht Vorwissen" in c.why


def test_deterministic_gates_open_loop_and_fidelity():
    """Die Tore selbst, ohne den ganzen Lauf.

    Frueher ging dieser Test ueber ``run``. Das taugt nicht mehr: ein Abschnitt, der auf „aber"
    endet, wird jetzt nach hinten verlaengert, bis er das nicht mehr tut - genau darum geht es bei
    der Kontextzugabe. Geprueft wird hier also die Feststellung des Mangels, nicht was danach
    damit geschieht.
    """
    w = demo_words()
    sents = segment.sentences_from_words(w)
    g = story_engine.deterministic_gates(w, sents, 8, 10, {})
    assert g["no_open_loop"] == {"passed": False, "detail": "endet auf „aber“"}
    assert g["fidelity"] == {"passed": False, "detail": "endet direkt vor „allerdings“"}
    assert g["standalone"]["passed"] is True


def test_story_graph_without_verdict_stays_unconfirmed(brain, llm):
    brain.moments = lambda sents: [{"first_sent": 0, "last_sent": 3, "structure": "loop", "why": "x"}]
    brain.confirm = {"misleading_without": None, "reason": "Ohne Sprachmodell nicht prüfbar", "repair": "none"}
    c = story_engine.detect(demo_words(), BRIEF, {}, None, llm)[0]
    f = c.story_graph_flags[0]
    assert f["confirmed"] is None and f["repair"] is None
    assert "möglicherweise relativiert der Sprecher" in c.why and "ungeprüft" in c.why

    brain.confirm = {"misleading_without": False, "reason": "Anderes Thema", "repair": "none"}
    c2 = story_engine.detect(demo_words(), BRIEF, {}, None, llm)[0]
    assert c2.story_graph_flags[0]["confirmed"] is False and c2.story_graph_flags[0]["repair"] is None
    assert "keine spätere Relativierung gefunden" in c2.why


def test_length_limits_discard_with_reason(brain, llm):
    brain.moments = lambda sents: [
        {"first_sent": 5, "last_sent": 5, "structure": "loop", "why": "zu kurz"},
        {"first_sent": 0, "last_sent": 3, "structure": "loop", "why": "ok"},
    ]
    report = story_engine.run(demo_words(), BRIEF, {}, None, llm)
    assert [c.first_sent for c in report.candidates] == [0]
    assert len(report.discarded) == 1
    d = report.discarded[0]
    assert (d["reason"], d["first_sent"], d["last_sent"]) == ("too_short", 5, 5)
    assert d["duration_s"] == pytest.approx(4.0, abs=0.05)
    assert not any(t == "score_clip" and i == 0 for i, (t, _) in enumerate(brain.calls))  # kurzer Vorschlag wird nicht bewertet

    # Schon der Vorschlag ist zu lang: ein Abschnitt waechst nur, er schrumpft nie, also faellt er
    # ohne Modellanfrage durch.
    words = make_words(long_script(1, sentences_per_chapter=10, sentence_s=12.0))
    brain.moments = lambda sents: [{"first_sent": 1, "last_sent": 7, "structure": "loop", "why": "x"}]
    report = story_engine.run(words, BRIEF, {}, None, llm)
    assert report.candidates == []
    assert report.discarded[0]["reason"] == "too_long"

    # Erst die Reparatur macht ihn zu lang: 5 Saetze zu 12 s sind 60 s und damit erlaubt, nach dem
    # Erweitern um einen Satz nach vorne sind es 72 s und damit ueber der harten Grenze von 70.
    brain.moments = lambda sents: [{"first_sent": 1, "last_sent": 5, "structure": "loop", "why": "x"}]
    brain.rubrics[(1, 5)] = {"needs_earlier_context": True}
    report = story_engine.run(words, BRIEF, {}, None, llm)
    assert report.candidates == []
    assert report.discarded[0]["reason"] == "too_long_after_repair"
    assert report.discarded[0]["first_sent"] == 0


def test_limit_twenty_and_seeded_chapters_first(brain, llm):
    words = make_words(long_script(25))
    sents = segment.sentences_from_words(words)
    chapters = segment.chapterize(sents)
    assert len(chapters) >= 20

    def two_per_chapter(sents_in_prompt):
        a = sents_in_prompt[0]["idx"]
        return [
            {"first_sent": a, "last_sent": a + 1, "structure": "payoff_first", "why": "x"},
            {"first_sent": a + 3, "last_sent": a + 4, "structure": "how_to_list", "why": "x"},
        ]

    brain.moments = two_per_chapter
    brain.confirm = {"misleading_without": False, "reason": "-", "repair": "none"}
    seed_chapter = chapters[10]
    progress: list[tuple[int, int, int]] = []
    report = story_engine.run(
        words, BRIEF, {}, {"seeds": [seed_chapter[0].start + 5.0]}, llm, on_progress=lambda d, t, n: progress.append((d, t, n))
    )
    assert report.chapters == len(chapters) and report.chapters_with_seeds == 1
    assert brain.propose_calls[0][0]["idx"] == seed_chapter[0].idx  # Kapitel mit Seed zuerst
    assert report.proposals == 2 * len(chapters)
    assert len(report.candidates) == story_engine.MAX_CANDIDATES
    assert [c.start_s for c in report.candidates] == sorted(c.start_s for c in report.candidates)
    assert sum(1 for d in report.discarded if d["reason"] == "limit") == 2 * len(chapters) - 20
    assert progress[0][:2] == (1, len(chapters)) and progress[-1] == (len(chapters), len(chapters), 2 * len(chapters))


def test_learned_weights_override_when_valid(brain, llm):
    brain.moments = lambda sents: [{"first_sent": 0, "last_sent": 3, "structure": "loop", "why": "x"}]
    brain.confirm = {"misleading_without": False, "reason": "-", "repair": "none"}
    only_hook = {"hook": 1.0, "payoff": 0.0, "specificity": 0.0, "tension": 0.0, "audience_fit": 0.0}
    c = story_engine.detect(demo_words(), BRIEF, {"learned_weights": only_hook}, None, llm)[0]
    # Gelernte Gewichte wirken weiterhin auf die angezeigten Gewichte der alten fuenf Kriterien.
    assert c.rubric["scores"]["hook"]["weight"] == 1.0 and c.rubric["scores"]["payoff"]["weight"] == 0.0

    invalid = {"hook": 0.9, "payoff": 0.9, "specificity": 0.1, "tension": 0.1, "audience_fit": 0.1}
    c2 = story_engine.detect(demo_words(), BRIEF, {"learned_weights": invalid}, None, llm)[0]
    assert c2.rubric["scores"]["hook"]["weight"] != 0.9  # ungueltig, Vorgabe greift

    # ABER: auf die Gesamtwertung wirken sie seit der redaktionellen Grundlage NICHT mehr. Die
    # Rangfolge entscheidet policy_total ueber die sieben Kriterien der Grundlage. Das ist eine
    # bewusste Folge und keine Panne: Die Lernschleife zieht ihr Signal aus angenommenen gegen
    # abgelehnte Kandidaten, und seit der Auswahlschritt entfaellt, gibt es keine Ablehnungen mehr.
    # Solange das so ist, waere ein gelerntes Gewicht ein Gewicht aus dem Nichts.
    assert c.total == pytest.approx(c2.total)
    incomplete = {"hook": 0.5, "payoff": 0.5}
    assert story_engine.resolve_weights(incomplete) == story_engine.resolve_weights(None)
    assert story_engine.resolve_weights("kaputt") == story_engine.resolve_weights(None)


def test_chapter_order_and_overlap_suppression():
    words = make_words(long_script(3, sentences_per_chapter=5, sentence_s=50.0))
    sents = segment.sentences_from_words(words)
    chapters = segment.chapterize(sents)
    order = story_engine.chapter_order(chapters, [chapters[-1][0].start + 1.0])
    assert [i for i, _, _ in order] == [len(chapters) - 1, *range(len(chapters) - 1)]
    assert order[0][2] is True and all(has is False for _, _, has in order[1:])

    def cand(first, last, total, passed=True):
        return story_engine.CandidateResult(
            segments=[], start_s=sents[first].start, end_s=sents[last].end, first_sent=first, last_sent=last,
            structure="loop", rubric={}, gates={}, story_graph_flags=[], risk_flags=[], total=total,
            gate_passed=passed, why="", model_id="m", prompt_version="score_clip_v1",
        )  # fmt: skip

    kept, dropped = story_engine.select_best([cand(0, 1, 6.0), cand(0, 2, 7.0), cand(3, 4, 9.0, passed=False)], limit=5)
    # (3, 4) reisst ein Tor und wird deshalb gar nicht mehr angeboten, (0, 1) steckt in (0, 2).
    assert [(c.first_sent, c.last_sent) for c in kept] == [(0, 2)]
    gruende = {d["reason"] for d in dropped}
    assert gruende == {"overlap", "gate"}


# -- Ueberlappung: Anteil am kuerzeren, nicht IoU --------------------------------------------------
def _spanne(start, ende, total=8.0):
    return story_engine.CandidateResult(
        segments=[], start_s=start, end_s=ende, first_sent=0, last_sent=1,
        structure="loop", rubric={}, gates={}, story_graph_flags=[], risk_flags=[], total=total,
        gate_passed=True, why="", model_id="m", prompt_version="score_clip_v2",
    )  # fmt: skip


def test_gemeinsamer_anteil_misst_am_kuerzeren():
    # Der kurze Abschnitt steckt ganz im langen: 1,0, egal wie lang der lange ist.
    assert story_engine.gemeinsamer_anteil(10.0, 20.0, 0.0, 100.0) == 1.0
    assert story_engine.gemeinsamer_anteil(0.0, 10.0, 10.0, 20.0) == 0.0
    assert story_engine.gemeinsamer_anteil(0.0, 10.0, 5.0, 15.0) == 0.5


def test_der_fall_aus_dem_echten_video():
    """An BP CW gemessen: 0 bis 19,6 s neben 9,9 bis 87,9 s.

    Die Haelfte des kurzen Clips steckt im langen. IoU ist dabei nur 9,7 / 87,9 = 0,11 und blieb
    weit unter jeder sinnvollen Schwelle, also standen beide Clips nebeneinander in der Liste.
    """
    anteil = story_engine.gemeinsamer_anteil(0.0, 19.6, 9.9, 87.9)
    assert anteil == pytest.approx(0.49, abs=0.01)
    iou = 9.7 / 87.9
    assert iou < 0.12, "zum Vergleich: so klein war das alte Mass"

    kept, dropped = story_engine.select_best([_spanne(0.0, 19.6, 6.0), _spanne(9.9, 87.9, 9.0)], limit=5)
    assert len(kept) == 1, "der halb enthaltene Clip muss weichen"
    assert kept[0].start_s == 9.9
    assert dropped and dropped[0]["reason"] == "overlap"


def test_ein_ganz_enthaltener_kurzer_clip_weicht_immer():
    kept, _ = story_engine.select_best([_spanne(30.0, 45.0, 6.0), _spanne(0.0, 70.0, 9.0)], limit=5)
    assert [c.start_s for c in kept] == [0.0]


def test_zwei_clips_die_sich_kaum_beruehren_bleiben_beide():
    """Ein kurzes Ueberlappen an der Naht ist kein Wiederholen."""
    kept, _ = story_engine.select_best([_spanne(0.0, 40.0, 9.0), _spanne(38.0, 78.0, 8.0)], limit=5)
    assert len(kept) == 2


def test_benachbarte_clips_ohne_ueberlappung_bleiben_beide():
    kept, _ = story_engine.select_best([_spanne(0.0, 30.0, 9.0), _spanne(30.0, 60.0, 8.0)], limit=5)
    assert len(kept) == 2


# -- Satzgrenzen: das Tor prueft jetzt wirklich ----------------------------------------------------
def test_endet_satz_erkennt_abschluss():
    assert story_engine._endet_satz("Punkt.")
    assert story_engine._endet_satz("Wirklich?")
    assert story_engine._endet_satz("Nie!")
    assert not story_engine._endet_satz("leckerer,")
    assert not story_engine._endet_satz("Druck")


def test_auslassungspunkte_sind_kein_satzende():
    """An BP CW gemessen: ein Clip endete auf „…", einer 3,3 Sekunden langen Pause im Transkript.

    Die Auslassungspunkte markieren ein Abreissen, keinen abgeschlossenen Gedanken. Wer nur auf das
    letzte Zeichen schaut, haelt den Punkt darin faelschlich fuer ein Satzende.
    """
    assert not story_engine._endet_satz("…")
    assert not story_engine._endet_satz("dass dieser Druck …")
    assert not story_engine._endet_satz("Moment...")


def test_satzgrenzen_gate_faengt_den_schnitt_vor_aber():
    """Der echte Fall: „...finde Broetchen auch deutlich leckerer," und dann Schnitt."""
    woerter = [
        {"text": "Ich", "start": 0.0, "end": 0.2, "speaker": "SPEAKER_00"},
        {"text": "finde", "start": 0.2, "end": 0.4, "speaker": "SPEAKER_00"},
        {"text": "leckerer,", "start": 0.4, "end": 0.8, "speaker": "SPEAKER_00"},
        {"text": "aber", "start": 2.0, "end": 2.3, "speaker": "SPEAKER_00"},
    ]
    sents = [story_engine.Sentence(idx=0, text="Ich finde leckerer,", start=0.0, end=0.8, word_range=(0, 2), speaker="SPEAKER_00")]
    g = story_engine._satzgrenzen_gate(woerter, sents, 0, 0)
    assert g["passed"] is False
    assert "leckerer," in g["detail"]


def test_satzgrenzen_gate_laesst_einen_sauberen_schnitt_durch():
    woerter = [
        {"text": "Das", "start": 0.0, "end": 0.2, "speaker": "SPEAKER_00"},
        {"text": "stimmt.", "start": 0.2, "end": 0.6, "speaker": "SPEAKER_00"},
    ]
    sents = [story_engine.Sentence(idx=0, text="Das stimmt.", start=0.0, end=0.6, word_range=(0, 1), speaker="SPEAKER_00")]
    assert story_engine._satzgrenzen_gate(woerter, sents, 0, 0)["passed"] is True



# -- Kontextzugabe: lieber sieben Sekunden laenger als sinnlos ------------------------------------
def test_ein_clip_der_vor_dem_aber_endet_wird_verlaengert_statt_verworfen():
    """Der Fall aus BP CW: „...finde Broetchen auch deutlich leckerer," und dann Schnitt.

    Die Laenge entscheidet, aber nicht gegen den Sinn. Statt den Clip wegzuwerfen, waechst er nach
    hinten, bis das „aber" mit drin ist.
    """
    w = demo_words()
    sents = segment.sentences_from_words(w)
    vorher = story_engine.deterministic_gates(w, sents, 8, 10, {})
    assert not vorher["no_open_loop"]["passed"], "Satz 10 endet auf „aber“, sonst prueft der Test nichts"

    neu, zugabe = story_engine.kontext_verlaengern(w, sents, 8, 10, {})
    assert neu > 10, "der Abschnitt haette wachsen muessen"
    assert zugabe is not None
    assert zugabe["sekunden"] <= 7.0
    assert "no_open_loop" in zugabe["behoben"]
    nachher = story_engine.deterministic_gates(w, sents, 8, neu, {})
    assert all(g["passed"] for g in nachher.values())


def test_ohne_mangel_wird_nicht_verlaengert():
    """Die Zugabe ist kein Freibrief, den Clip „noch etwas voller" zu machen."""
    w = demo_words()
    sents = segment.sentences_from_words(w)
    assert all(g["passed"] for g in story_engine.deterministic_gates(w, sents, 0, 3, {}).values())
    neu, zugabe = story_engine.kontext_verlaengern(w, sents, 0, 3, {})
    assert (neu, zugabe) == (3, None)


def test_die_zugabe_hoert_bei_sieben_sekunden_auf():
    """Ein Mangel, der nur mit mehr als der Zugabe zu heilen waere, bleibt ungeheilt."""
    w = demo_words()
    sents = segment.sentences_from_words(w)
    lang = [s for s in sents]
    # Kuenstlich: der naechste Satz liegt weiter weg als die Zugabe erlaubt.
    verschoben = segment.Sentence(
        idx=lang[11].idx, text=lang[11].text, start=lang[10].end + 20.0, end=lang[10].end + 26.0,
        speaker=lang[11].speaker, word_range=lang[11].word_range,
    )  # fmt: skip
    kuenstlich = [*lang[:11], verschoben, *lang[12:]]
    neu, zugabe = story_engine.kontext_verlaengern(w, kuenstlich, 8, 10, {})
    assert (neu, zugabe) == (10, None)


def test_die_harte_grenze_gilt_wirklich():
    """78 Sekunden sind raus, 77 mit Grund sind drin, 71 ohne Grund nicht."""
    assert story_engine._length_reason(78.0, mit_zugabe=True) == "too_long"
    assert story_engine._length_reason(77.0, mit_zugabe=True) is None
    assert story_engine._length_reason(71.0, mit_zugabe=False) == "too_long"
    assert story_engine._length_reason(70.0, mit_zugabe=False) is None
    assert story_engine._length_reason(17.9) == "too_short"
    assert story_engine._length_reason(18.0) is None


def test_der_vorfilter_verwirft_nur_das_aussichtslose():
    """Ein zu kurzer Vorschlag, den die Reparatur retten kann, muss bewertet werden duerfen."""
    w = demo_words()
    sents = segment.sentences_from_words(w)
    # 1..3 sind 17,6 s und damit unter der Grenze, 0..3 waeren 23,4 s.
    assert story_engine._duration(sents, 1, 3) < 18.0
    assert story_engine._vorfilter_grund(sents, 1, 3) is None


def test_beide_grenzen_der_zugabe_gelten():
    """Sekunden UND Satzzahl. An BP CW gemessen: der naechste Satz lag 8,9 s entfernt und damit
    ausserhalb der sieben Sekunden, obwohl es nur ein Satz gewesen waere."""
    w = demo_words()
    sents = segment.sentences_from_words(w)
    from chopstr_worker import editorial

    pol = editorial.load()
    assert pol.kontext_zugabe_s > 0 and pol.kontext_zugabe_saetze > 0

    # Ein Satz, der innerhalb der Sekundengrenze liegt, heilt.
    neu, zugabe = story_engine.kontext_verlaengern(w, sents, 8, 10, {})
    assert zugabe is not None and zugabe["sekunden"] <= pol.kontext_zugabe_s

    # Derselbe Fall, aber der naechste Satz liegt weiter weg als die Sekundengrenze erlaubt.
    weit = segment.Sentence(
        idx=sents[11].idx, text=sents[11].text, start=sents[10].end + pol.kontext_zugabe_s + 1.0,
        end=sents[10].end + pol.kontext_zugabe_s + 5.0, speaker=sents[11].speaker, word_range=sents[11].word_range,
    )  # fmt: skip
    assert story_engine.kontext_verlaengern(w, [*sents[:11], weit, *sents[12:]], 8, 10, {}) == (10, None)
