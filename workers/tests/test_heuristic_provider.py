"""Heuristik-Provider ``local-heuristic``: deterministisch, schema-konform, ohne Netz und ohne Residency-Hook."""

from __future__ import annotations

import pytest

from chopstr_worker import config, editorial, heuristic_llm, providers_llm, residency
from chopstr_worker.pipeline import segment, story_engine, story_graph, story_score
from chopstr_worker.providers_llm import LLM
from chopstr_worker.residency import Tenant
from tests.transcript_fixtures import demo_words

BRIEF = {"audience": "Gründer", "wanted": "Zahlen", "exclude": "Werbung", "platform": "linkedin"}


@pytest.fixture(autouse=True, params=[1, 2], ids=["policy_v1", "policy_v2"])
def active_policy(request, monkeypatch):
    """AP0b: Der Heuristik-Provider läuft unter beiden Fassungen der Grundlage gleich."""
    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", str(request.param))
    editorial.clear_cache()
    yield request.param
    editorial.clear_cache()


@pytest.fixture
def no_network(monkeypatch):
    """Jeder Weg ins Netz (Host-Prüfung, HTTP-Client, boto3) würde den Test sofort abbrechen."""

    def boom(*a, **kw):
        raise AssertionError("Heuristik-Provider darf nie ins Netz oder in den Residency-Hook")

    monkeypatch.setattr(residency, "assert_eu_host", boom)
    monkeypatch.setattr(residency, "guarded_client", boom)
    monkeypatch.setattr(residency, "guarded_async_client", boom)


def _llm(tier: str = "standard") -> LLM:
    return LLM(Tenant(id="ws", tier=tier), provider=providers_llm.HEURISTIC_PROVIDER, s=config.settings())


def test_provider_is_allowed_for_both_tiers_and_selected_by_env(monkeypatch):
    assert "local-heuristic" in residency.EU_OK and "local-heuristic" in residency.NON_US_CHAIN
    assert _llm("standard").model() == "heuristic-v1"
    assert _llm("sovereign").model() == "heuristic-v1"
    assert _llm().is_heuristic is True
    monkeypatch.setenv("LLM_PROVIDER", "local-heuristic")
    config.reload()
    assert providers_llm.select_provider(Tenant(id="ws", tier="standard")) == "local-heuristic"
    assert providers_llm.select_provider(Tenant(id="ws", tier="sovereign")) == "local-heuristic"


def test_propose_is_deterministic_and_schema_conform(no_network):
    """Unter beiden Fassungen der Pfad vor AP5: Fassung 2 nutzt propose_moments_v2 erst mit dem Schalter
    implementation.search.payoff_first (AP5, H1)."""
    llm = _llm()
    sents = segment.sentences_from_words(demo_words())
    pol = unwired(editorial.load())
    m1 = story_score.propose(sents, BRIEF, llm, policy=pol)
    m2 = story_score.propose(sents, BRIEF, llm, policy=pol)
    assert m1 == m2
    # Wie viele Vorschlaege ein Kapitel liefert, steht in der Grundlage (`ausbeute`) und richtet
    # sich nach seiner Laenge. Unter Fassung 1 bleiben es die frueheren hoechstens drei.
    _soll = editorial.load().vorschlaege_fuer(sents[-1].end - sents[0].start)
    assert 1 <= len(m1) <= _soll
    valid = {s.idx for s in sents}
    spans = []
    for m in m1:
        assert m["first_sent"] in valid and m["last_sent"] in valid and m["first_sent"] <= m["last_sent"]
        assert m["structure"] in story_score.STRUCTURES
        assert m["why"].startswith("Heuristik ohne Sprachmodell")
        assert m["prompt_version"] == "propose_moments_v1"
        est = heuristic_llm.estimate_seconds([{"text": s.text} for s in sents[m["first_sent"] : m["last_sent"] + 1]])
        assert 15.0 <= est <= 60.0
        spans.append((m["first_sent"], m["last_sent"]))
    for a, b in spans:
        for c, d in spans:
            # Ueberlappende Zuschnitte sind ausdruecklich erlaubt: derselbe Moment darf in zwei
            # Varianten angeboten werden, der Clipper waehlt. Was gelten muss, ist der
            # Mindestabstand der Anker - sonst entstuende fuer jeden Satz ein eigener Vorschlag.
            # Zu Aehnliches sortiert `select_best` spaeter ueber `ausbeute.ueberlappung_max` aus.
            assert abs(a - c) >= heuristic_llm.ANKER_MINDESTABSTAND_SAETZE or (a, b) == (c, d)


def test_score_fields_ranges_and_grounded_evidence(no_network):
    llm = _llm()
    sents = segment.sentences_from_words(demo_words())
    costs = []
    llm.cost_sink = costs.append
    r = story_score.score(sents[0:4], BRIEF, llm)
    for k in story_score.RUBRIC_SCHEMA["required"]:
        assert k in r
    for k in ("hook", "payoff", "specificity", "tension", "audience_fit"):
        assert isinstance(r[k], int) and 0 <= r[k] <= 10
    assert r["ungrounded_evidence"] == []  # Belege sind wörtliche Satzanfänge
    assert r["model_id"] == "heuristic-v1" and r["prompt_version"] == ("score_clip_v3" if editorial.load().version >= 2 else "score_clip_v2")
    assert r["is_humor"] is False and r["gate_passed"] is True
    assert r["specificity"] >= 6  # 40 Prozent, 2019, 30 Prozent
    assert costs and costs[0]["in"] == 0 and costs[0]["provider"] == "local-heuristic"
    assert story_score.score(sents[0:4], BRIEF, llm)["total"] == r["total"]

    # Frage am Anfang und Open-Loop-Ende werden erkannt.
    # Sätze 12 bis 13 beginnen mit der Frage eines ANDEREN Sprechers („Was würdest du heute anders
    # machen?“, SPEAKER_01). Seit die Heuristik aus der redaktionellen Grundlage liest, ist das kein
    # Hook mehr, sondern Anlauf (einstieg.keine_gastgeberfrage). Früher stand hier
    # ``r2["hook"] >= r["hook"] - 1``; die Erwartung ist mit der Regel gekippt.
    r2 = story_score.score(sents[12:14], BRIEF, llm)
    assert r2["gastgeberfrage"] is True
    assert r2["hook"] < r["hook"]
    r3 = story_score.score(sents[9:11], BRIEF, llm)
    assert r3["ends_before_answer"] is True and r3["gate_passed"] is False
    r4 = story_score.score(sents[9:10], BRIEF, llm)
    assert r4["needs_earlier_context"] is True  # „Und dann ...“


def test_confirm_returns_no_verdict(no_network):
    out = story_graph.confirm(_llm(), "Kernaussage", "Das heißt aber nicht, dass das gilt.", 21.0)
    assert out["misleading_without"] is None
    assert out["repair"] == "none" and out["reason"]
    assert out["prompt_version"] == "story_graph_confirm_v1"


def test_engine_with_heuristic_marks_results(no_network, active_policy):
    report = story_engine.run(demo_words(), BRIEF, {}, {"seeds": [2]}, _llm("sovereign"))
    # Fassung 2 mit verdrahteter Suche und Kritiker (AP6b)
    overview = ["episode_overview_v1", "critique_clip_v1"] if active_policy == 2 else []
    score_clip = "score_clip_v2" if active_policy == 1 else "score_clip_v3"  # AP9
    assert report.prompt_versions == [f"propose_moments_v{1 if active_policy == 1 else 2}", score_clip, "story_graph_confirm_v1", *overview]
    assert report.provider == "local-heuristic" and report.model_id == "heuristic-v1"
    assert report.candidates, report.discarded
    for c in report.candidates:
        assert c.model_id == "heuristic-v1"
        assert c.prompt_version == score_clip
        assert c.rubric["policy_version"] == f"clip_policy_v{active_policy}"
        if active_policy == 2:  # AP9: die Heuristik misst keinen Teilwert nach Master-Prompt 19
            sub = c.rubric["anchor_subscores"]
            assert sub["source"] == "heuristic" and sub["calibration"] == "uncalibrated"
            assert all(sub["values"][k] is None for k in story_score.EDITORIAL_SUBSCORE_KEYS)
        assert "heuristic_only" in c.risk_flags
        assert c.why.endswith("Bewertung ohne Sprachmodell.")
        assert 12.0 <= c.duration_s <= 90.0
        for f in c.story_graph_flags:
            assert f["confirmed"] is None


def test_unknown_tool_raises_and_parse_ignores_noise():
    with pytest.raises(RuntimeError, match="kennt das Tool"):
        heuristic_llm.answer("unknown_tool", "x")
    parsed = heuristic_llm.parse_numbered("Zielgruppe: x\n[3] (SPEAKER_01) Hallo Welt.\nkein Satz\n[4] (?) Noch einer?")
    assert parsed == [{"idx": 3, "speaker": "SPEAKER_01", "text": "Hallo Welt."}, {"idx": 4, "speaker": "?", "text": "Noch einer?"}]
    assert heuristic_llm.propose_moments("nur Text ohne Sätze") == {"moments": []}


def test_write_hooks_v2_has_no_invented_framings():
    """AP6a: Mit hooks_v2 (Clip in Begrenzern) nur wörtliche Auszüge aus dem Clip, keine eigene Rahmung wie
    „Das Gegenteil stimmt:“; mit hooks_v1 bleibt die Rahmung (Fassung 1 unverändert)."""
    from chopstr_worker import prompts

    clip = (
        "Wir haben 40 Prozent Marge verloren. Aber das gilt nicht für jede Firma. "
        "Was würdest du heute anders machen? Der Fehler war ein falsches Preismodell."
    )
    user = prompts.load("hooks", 2).render(address="DU", country="AT", platform="tiktok", protected_terms=[], clip_text=clip)
    out = heuristic_llm.write_hooks(user)["variants"]
    assert [v["pattern"] for v in out] == list(heuristic_llm.HOOK_PATTERNS)
    for v in out:
        for key, limit in (("spoken", heuristic_llm.SPOKEN_MAX_WORDS), ("onscreen", heuristic_llm.ONSCREEN_MAX_WORDS)):
            assert v[key] in clip and len(v[key].split()) <= limit, v
            assert not v[key].startswith(("Das Gegenteil", "Du kennst", "Was dahinter", "Dieser Fehler", "Das Ergebnis"))
    # je Muster ein anderer Satz, solange der Clip Sätze hat; „Aber das gilt …“ beginnt mit Rückbezug und zählt nicht
    assert len({v["onscreen"] for v in out}) == 3
    old = heuristic_llm.write_hooks(prompts.load("hooks", 1).render(address="DU", country="AT", platform="tiktok", protected_terms=[], clip_text=clip))
    assert old["variants"][1]["spoken"].startswith("Das Gegenteil stimmt:")


# -- AP5: propose_moments_v2 und episode_overview ----------------------------------------------------
@pytest.fixture
def policy_v2(monkeypatch):
    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "2")
    editorial.clear_cache()
    yield editorial.load()
    editorial.clear_cache()


def wired_v2() -> editorial.Policy:
    """Fassung 2 mit eingeschaltetem implementation.search.payoff_first (wie nach der Verdrahtung)."""
    import copy

    base = editorial.load(2)
    roh = copy.deepcopy(base.roh)
    roh["implementation"]["search"]["payoff_first"] = True
    return editorial.Policy(version=2, stand=base.stand, roh=roh)


def unwired(pol: editorial.Policy) -> editorial.Policy:
    """Fassung 2 mit ausgeschaltetem implementation.search.payoff_first (Rollback); Fassung 1 unverändert."""
    import copy

    if pol.version < 2:
        return pol
    roh = copy.deepcopy(pol.roh)
    roh["implementation"]["search"]["payoff_first"] = False
    return editorial.Policy(version=pol.version, stand=pol.stand, roh=roh)


def test_v2_without_switch_proposes_like_v1(no_network):
    """H1: Fassung 2 mit Schalter aus liefert dieselben Vorschläge wie Fassung 1 (Prompt v1, Anker)."""
    sents = segment.sentences_from_words(demo_words())
    v1 = story_score.propose(sents, BRIEF, _llm(), policy=editorial.load(1))
    v2 = story_score.propose(sents, BRIEF, _llm(), policy=unwired(editorial.load(2)))
    assert v1 == v2 and {m["prompt_version"] for m in v2} == {"propose_moments_v1"}


def test_v2_prompt_is_parsed_and_uses_payoff_search(no_network, policy_v2):
    """Die Heuristik erkennt den Kapitelblock in Begrenzern; Übersicht, Seeds und Policy sind kein Transkript."""
    from chopstr_worker import prompts

    sents = segment.sentences_from_words(demo_words())
    user = prompts.load_pinned("propose_moments", policy_v2).render(
        audience="x", wanted="x", exclude="x", platform="linkedin", policy=story_score.propose_policy_text(policy_v2),
        episode_overview='{"claims": [{"sent": 99}]}', seeds="Sekunde 3, Satz 0: [7] (X) kein Satz", chapter_numbered=segment.numbered(sents),
    )  # fmt: skip
    out = heuristic_llm.answer("propose_moments", user)
    assert out["moments"]
    valid = {s.idx for s in sents}
    for m in out["moments"]:
        assert m["first_sent"] in valid and m["last_sent"] in valid
        assert m["why"].startswith("Heuristik ohne Sprachmodell: Payoff in Satz")
        assert m["viewer_promise"] is None and m["central_idea"] is None
    kept, dropped = story_score.validate_moments_v2(out, valid)
    assert dropped == [] and len(kept) == len(out["moments"])
    # Der Weg über story_score.propose (verdrahtet) kommt zum selben Ergebnis.
    assert [(m["first_sent"], m["last_sent"]) for m in story_score.propose(sents, BRIEF, _llm(), policy=wired_v2())] == [
        (m["first_sent"], m["last_sent"]) for m in out["moments"]
    ]


def test_v1_prompt_path_is_unchanged_under_the_heuristic():
    """Ohne Kapitelblock (propose_moments_v1) bleiben Anker und höchstens drei Momente."""
    sents = segment.sentences_from_words(demo_words())
    text = segment.numbered(sents)
    out = heuristic_llm.propose_moments(text)
    assert 1 <= len(out["moments"]) <= 3
    assert set(out["moments"][0]) == {"first_sent", "last_sent", "structure", "why"}


def test_v2_weak_material_gives_no_moment(no_network, policy_v2):
    from tests.editorial_v1 import harness

    case = harness.load_case("weak_material")
    sents = segment.sentences_from_words(case["words"], rule="v2")
    assert story_score.propose(sents, BRIEF, _llm(), policy=wired_v2()) == []


def test_overview_marks_itself_and_leaves_unknowns_null(no_network, policy_v2):
    sents = segment.sentences_from_words(demo_words())
    ov = story_score.overview(sents, _llm())
    assert ov["heuristic"] is True and ov["search_only"] is True and ov["prompt_version"] == "episode_overview_v1"
    assert ov["topics"] is None and ov["dependencies"] is None
    assert all(s["role"] is None for s in ov["speakers"])
    assert {s["speaker"] for s in ov["speakers"]} == {"SPEAKER_00", "SPEAKER_01"}
    assert all(c["summary"] is None for c in ov["claims"]) and 8 in {c["sent"] for c in ov["claims"]}
    assert all(e["supports_sent"] is None for e in ov["evidence"]) and {1, 3} <= {e["sent"] for e in ov["evidence"]}
    assert {x["sent"] for x in ov["limitations"]} == {11}  # „Allerdings …“
    assert all(x["limits_sent"] is None for x in ov["limitations"])


@pytest.mark.parametrize(("cid", "humor"), [("punchline_setup", True), ("conditional_recommendation", False)])
def test_humor_is_flagged_under_v2_only(no_network, active_policy, cid, humor):
    """Pointe mit Setup (payoff_search) setzt is_humor ab Fassung 2; damit risk_flags humor und menschliche
    Prüfung (P27). Fassung 1 bleibt unverändert (is_humor false)."""
    import copy

    from tests.editorial_v1 import harness

    case = harness.load_case(cid)
    sents = segment.sentences_from_words(case["words"], rule="v2")
    assert heuristic_llm.score_clip(segment.numbered(sents))["is_humor"] is (humor and active_policy == 2)
    if active_policy == 2:
        report = story_engine.run(copy.deepcopy(case["words"]), BRIEF, {}, None, _llm())
        assert report.candidates
        for c in report.candidates:
            assert ("humor" in c.risk_flags) is humor
            if humor:
                harness.assert_humor_flagged(case, {"risk_flags": c.risk_flags, "rubric": c.rubric})


def test_laugh_reaction_of_the_other_speaker_flags_humor(policy_v2):
    text = "[0] (A) Am Ende kam nur ein einziger Besucher an den Stand.\n[1] (B) Haha.\n[2] (A) Das war unsere ganze Messe."
    assert heuristic_llm.score_clip(text)["is_humor"] is True
    assert heuristic_llm.score_clip(text.replace("Haha.", "Okay."))["is_humor"] is False
