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
    brain.moments = lambda sents: [{"first_sent": 0, "last_sent": 3, "structure": "loop", "why": "x"}]
    brain.rubrics[(0, 3)] = {"needs_earlier_context": True, "suggested_title_card": "Nach dem Preisfehler 2019"}
    c = story_engine.detect(demo_words(), BRIEF, {}, None, llm)[0]
    assert c.rubric["repair"]["failed"] is True and c.rubric["repair"]["rounds"] == 0  # Satz 0 hat keinen Vorgänger
    assert c.gates["standalone"] == {"passed": False, "detail": "Einstieg braucht Vorwissen"}
    assert c.gate_passed is False
    assert c.rubric["suggested_title_card"] == "Nach dem Preisfehler 2019"
    assert c.why.startswith("Ausschnitt von")
    assert "Einstieg braucht Vorwissen" in c.why


def test_deterministic_gates_open_loop_and_fidelity(brain, llm):
    brain.moments = lambda sents: [{"first_sent": 8, "last_sent": 10, "structure": "decision_story", "why": "x"}]
    c = story_engine.detect(demo_words(), BRIEF, {}, None, llm)[0]
    assert c.gates["no_open_loop"] == {"passed": False, "detail": "endet auf „aber“"}
    assert c.gates["fidelity"] == {"passed": False, "detail": "endet direkt vor „allerdings“"}
    assert c.gates["standalone"]["passed"] is True
    assert c.gate_passed is False
    assert "endet auf einem offenen Konnektor" in c.why and "endet direkt vor einer Relativierung" in c.why
    assert c.story_graph_flags == []
    assert "keine spätere Relativierung gefunden" in c.why


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

    # zu lang nach Reparatur: Grenzen wachsen über 90 Sekunden
    words = make_words(long_script(1, sentences_per_chapter=10, sentence_s=12.0))
    brain.moments = lambda sents: [{"first_sent": 1, "last_sent": 7, "structure": "loop", "why": "x"}]
    brain.rubrics[(1, 7)] = {"needs_earlier_context": True}
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
    assert [(c.first_sent, c.last_sent) for c in kept] == [(0, 2), (3, 4)]
    assert dropped == [{"reason": "overlap", "first_sent": 0, "last_sent": 1, "total": 6.0}]
