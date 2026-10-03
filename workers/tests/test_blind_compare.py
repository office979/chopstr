"""Blindvergleich (AP11, ``eval/blind_compare.py``) und ``clip_eval --policy-version``.

Geprüft: Anonymisierung beider Bögen, Kontext in ``quellen.json``, fester Seed, gleiche Ausgabemenge und
Paarung, Verwerfungsquote gegen ``DetectReport.discarded``, Modellaufrufe am Fake-LLM, Stil-Leck-Prüfung,
Auswertung einer ausgefüllten Beispielbewertung mit Urteil, Streuung und Vorzeichentest, Fehlermeldungen.
"""

from __future__ import annotations

import copy
import json
import os
import re
from collections import Counter

import pytest

from chopstr_worker import config, editorial, providers_llm
from chopstr_worker.pipeline import dach_nlp, story_engine
from chopstr_worker.providers_llm import LLM
from chopstr_worker.residency import Tenant
from eval import blind_compare as bc
from eval import clip_eval

SUBSET = ("demo_script", "fall_negation_sentence_end", "fall_weak_material", "fall_misrecognized_number_or_name", "fall_near_duplicate_candidates")
VERSION_MARKERS = re.compile(r"\bv[12]\b|clip_policy|policy|fassung|story_engine|candidate_id|cc_[0-9a-f]|heuristi|prompt|fall_|demo_script|muster|native", re.IGNORECASE)
RATER_FILES = ("sheet", "hook_sheet", "sources", "rubric")


@pytest.fixture(autouse=True)
def _no_spacy(monkeypatch):
    monkeypatch.setattr(dach_nlp, "nlp", lambda: None)
    monkeypatch.setattr(dach_nlp, "verb_bracket_available", False)
    yield
    editorial.clear_cache()


def _sources(names=SUBSET):
    return [s for s in bc.fixture_sources() if s["name"] in names]


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(dach_nlp, "nlp", lambda: None)
        mp.setattr(dach_nlp, "verb_bracket_available", False)
        out = tmp_path_factory.mktemp("blind")
        bc.generate(_sources(), out, seed=11, k=3)
    editorial.clear_cache()
    return out


def _load(path, name):
    return json.loads((path / bc.FILES[name]).read_text(encoding="utf-8"))


def _write(path, name, doc):
    (path / bc.FILES[name]).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


# -- Synthetisches Material ------------------------------------------------------------------------


def _clip(cid: str, start: float = 0.0, end: float = 30.0, hook: str = "Satz eins.", overlay: str = "Satz eins", pattern: str = "native") -> dict:
    return {
        "candidate_id": cid, "first_sent": 0, "last_sent": 2, "start_s": start, "end_s": end, "total": 9.0,
        "segmente": [{"von_s": start, "bis_s": end, "rolle": "body"}], "text": f"Clip {cid.rsplit('_', 1)[-1]}. Satz eins.", "dauer_s": round(end - start, 2),
        "hook": {"gesprochen": hook, "text": overlay, "muster": pattern, "befunde": 0, "ganzer_satz": True},
    }  # fmt: skip


def _synthetic_run(version: str, clips: list[dict], reasons: list, passed: bool | None, proposals: int | None = None) -> dict:
    entries = [r if isinstance(r, dict) else {"reason": r} for r in reasons]
    events = sum(1 for e in entries if e.get("reason") in bc.RUN_EVENT_REASONS)
    props = len(clips) + len(entries) - events if proposals is None else proposals
    native = sum(1 for c in clips if c["hook"]["muster"] == "native")
    return {
        "variante": version, "fassung": 1 if version == "v1" else 2, "schalter": {}, "quelle": "q", "quelle_stunden": 0.25,
        "vorschlaege": props, **bc.discard_summary(entries, props), "modellaufrufe": 2 * len(clips) + 3, "modellaufrufe_je_prompt": {}, "laufzeit_s": 0.1,
        "hooks": {"gesamt": len(clips), "native": native, "ohne_overlay": sum(1 for c in clips if not c["hook"]["text"]),
                  "ganzer_satz": len(clips), "mit_befund": 0},
        "editorial_v1": None if passed is None else {"bestanden": passed, "gruende": [] if passed else ["Segment endet auf verbotenem Out-Point „nicht“"]},
        "angeboten": clips, "clip_candidates": [],
    }  # fmt: skip


def _v1_clip(cid, start=0.0, end=30.0):
    return _clip(cid, start, end, hook="Du kennst das sicher: Satz eins.", overlay="Kennst du das? Satz eins", pattern="identity_call")


def _synthetic_dir(tmp_path, pairing="ueberdeckung", tolerance=0.0):
    """Zwei Quellen mit bekannten Zahlen; Bögen und Schlüssel aus ``make_pairs``."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    runs = {
        "fall_a": {
            "v1": _synthetic_run("v1", [_v1_clip("cc_a1", 0, 30), _v1_clip("cc_a2", 40, 70), _v1_clip("cc_a3", 80, 100)], ["gate", "too_long", {"stage": "search"}], False),
            "v2": _synthetic_run("v2", [_clip("cc_b1", 41, 69), _clip("cc_b2", 1, 29, overlay="")],
                                ["gate", {"reason": "duplicate_payoff", "detail": "same_span"}, {"reason": "duplicate_payoff", "detail": "same_opening"}], True),
            "v2_basis": _synthetic_run("v2", [_clip("cc_c1", 0, 30, pattern="identity_call")], ["gate"], True),
            "v2_hooks": _synthetic_run("v2", [_clip("cc_d1", 0, 30, overlay="")], [], True),
        },
        "fall_b": {
            "v1": _synthetic_run("v1", [_v1_clip("cc_a4"), _v1_clip("cc_a5", 50, 80)], [], True),
            "v2": _synthetic_run("v2", [_clip("cc_b3"), _clip("cc_b4", 50, 80)], ["overlap", "budget_exhausted"], True),
            "v2_basis": _synthetic_run("v2", [_clip("cc_c2", pattern="identity_call")], [], True),
            "v2_hooks": _synthetic_run("v2", [_clip("cc_d2")], [], True),
        },
        "quelle_leer": {
            "v1": _synthetic_run("v1", [], [], None, proposals=0),
            "v2": _synthetic_run("v2", [], [], None, proposals=0),
            "v2_basis": _synthetic_run("v2", [], [], None, proposals=0),
            "v2_hooks": _synthetic_run("v2", [], [], None, proposals=0),
        },
    }  # fmt: skip
    sheet, hook_sheet, key = bc.make_pairs(runs, seed=3, pairing=pairing)
    key["erfolgskriterium"] = bc.success_criterion(tolerance)
    variants = [
        {"name": "v1", "fassung": 1, "gruppe": None, "schalter": {}},
        {"name": "v2", "fassung": 2, "gruppe": None, "schalter": {}},
        {"name": "v2_basis", "fassung": 2, "gruppe": "basis", "schalter": {"hook.native_spoken": False}},
        {"name": "v2_hooks", "fassung": 2, "gruppe": "hooks", "schalter": {"hook.native_spoken": True}},
    ]  # fmt: skip
    run_doc = {"hinweis": "", "provider": "local-heuristic", "k": 3, "brief": {}, "varianten": variants,
               "gebaute_schalter": ["hook.native_spoken"], "stil_leck": bc.style_leak(runs, key), "quellen": runs}  # fmt: skip
    sources_doc = bc.sources_document([{"name": n, "words": [], "medien": None} for n in runs], {}, key, sheet)
    for kind, doc in (("sheet", sheet), ("hook_sheet", hook_sheet), ("key", key), ("run", run_doc), ("rubric", bc.rubric_template()), ("sources", sources_doc)):
        _write(tmp_path, kind, doc)
    return tmp_path


def _fill(out, v1_value=2, v2_value=3, preference_for="v2"):
    """Bögen ausfüllen: jede Seite bekommt den Wert ihrer Fassung, Natürlichkeit bleibt leer."""
    key = _load(out, "key")
    for kind, key_pairs, criteria in (("sheet", key["paare"], bc.CRITERIA), ("hook_sheet", key["hook_paare"], bc.HOOK_CRITERIA)):
        sheet = _load(out, kind)
        for pair in sheet["paare"]:
            mapping = key_pairs[pair["paar_id"]]
            for side in ("A", "B"):
                pair["bewertung"][side] = dict.fromkeys(criteria, v2_value if mapping[side] == "v2" else v1_value)
            if kind == "sheet":
                for side in ("A", "B"):
                    pair["bewertung"][side]["natuerlichkeit"] = None
            pair["bewertung"]["praeferenz"] = "A" if mapping["A"] == preference_for else "B"
        sheet["paare"][0]["bewertung"]["praeferenz"] = "gleich"
        _write(out, kind, sheet)


# -- Anonymisierung -------------------------------------------------------------------------------


def _check_rater_files(out) -> None:
    for kind in RATER_FILES:
        text = (out / bc.FILES[kind]).read_text(encoding="utf-8")
        match = VERSION_MARKERS.search(text) if kind != "rubric" else None
        assert not match, (kind, match)
    for pair in _load(out, "sheet")["paare"]:
        assert set(pair) == {"paar_id", "quelle", "kontext", "A", "B", "bewertung"}
        assert re.fullmatch(r"Q\d{2}", pair["quelle"])
        for side in ("A", "B"):
            assert set(pair[side]) == {"ausgabe", "text", "segmente", "dauer_s"}
        assert set(pair["bewertung"]["A"]) == set(bc.CRITERIA) == set(pair["bewertung"]["B"])
    for pair in _load(out, "hook_sheet")["paare"]:
        assert pair["paar_id"].startswith("H")
        for side in ("A", "B"):
            assert set(pair[side]) == {"hook_gesprochen", "hook_text", "clip_text"}
        assert set(pair["bewertung"]["A"]) == set(bc.HOOK_CRITERIA)


def test_rater_files_carry_no_version_and_no_hook_in_the_clip_sheet(tmp_path):
    out = _synthetic_dir(tmp_path)
    assert len(_load(out, "sheet")["paare"]) == 4 and len(_load(out, "hook_sheet")["paare"]) == 4
    _check_rater_files(out)
    clip_text = (out / bc.FILES["sheet"]).read_text(encoding="utf-8")
    assert "Du kennst das sicher" not in clip_text and "Kennst du das" not in clip_text
    run = (out / bc.FILES["run"]).read_text(encoding="utf-8")
    assert "cc_a1" in run and "fall_a" in run


def test_generated_rater_files_carry_no_version(generated):
    _check_rater_files(generated)


def test_key_holds_mapping_and_neutral_source_names(generated):
    sheet, hooks, key = _load(generated, "sheet"), _load(generated, "hook_sheet"), _load(generated, "key")
    assert set(key["paare"]) == {p["paar_id"] for p in sheet["paare"]}
    assert set(key["hook_paare"]) == {p["paar_id"] for p in hooks["paare"]}
    for entry in [*key["paare"].values(), *key["hook_paare"].values()]:
        assert {entry["A"], entry["B"]} == {"v1", "v2"}
        assert key["quellen"][entry["quelle_neutral"]] == entry["quelle"]
    assert set(key["quellen"].values()) == set(SUBSET)
    assert key["erfolgskriterium"]["kriterien"] == ["quellentreue", "eigenstaendigkeit"]
    assert "Nicht an die Bewertenden" in _load(generated, "run")["hinweis"]


def test_output_label_groups_one_version_per_source(generated):
    sheet, key = _load(generated, "sheet"), _load(generated, "key")
    labels: dict[tuple[str, str], set[str]] = {}
    for pair in sheet["paare"]:
        for side in ("A", "B"):
            labels.setdefault((pair["quelle"], key["paare"][pair["paar_id"]][side]), set()).add(pair[side]["ausgabe"])
    assert all(len(v) == 1 for v in labels.values())
    for source in {s for s, _v in labels}:
        assert labels.get((source, "v1")) != labels.get((source, "v2"))


# -- Kontext (quellen.json) -----------------------------------------------------------------------


def test_context_is_the_same_for_both_sides_and_present(generated):
    sheet, sources = _load(generated, "sheet"), _load(generated, "sources")["quellen"]
    assert sheet["paare"]
    for pair in sheet["paare"]:
        first, last = pair["kontext"]["saetze"]
        numbers = {s["nr"] for s in sources[pair["kontext"]["quelle"]]["saetze"]}
        assert set(range(first, last + 1)) <= numbers
        for side in ("A", "B"):
            for seg in pair[side]["segmente"]:
                inside = [s for s in sources[pair["quelle"]]["saetze"] if first <= s["nr"] <= last]
                assert inside[0]["von_s"] <= seg["von_s"] + 0.01 and seg["bis_s"] - 0.01 <= inside[-1]["bis_s"]


def test_long_sources_only_carry_context_and_media(tmp_path):
    from tests.transcript_fixtures import long_script, make_words

    words = make_words(long_script(1, sentences_per_chapter=60, sentence_s=6.0))
    sources = [{"name": "lang", "words": words, "case": None, "medien": {"quelle_id": "u1", "storage_key": "sources/u1.mp4"}}]
    bc.generate(sources, tmp_path, seed=1, k=2, switches=False)
    doc = _load(tmp_path, "sources")["quellen"]["Q01"]
    assert doc["medien"] == {"quelle_id": "u1", "storage_key": "sources/u1.mp4"}
    assert doc["umfang"].startswith("plus/minus 5")
    assert 0 < len(doc["saetze"]) < 60
    for pair in _load(tmp_path, "sheet")["paare"]:
        first, last = pair["kontext"]["saetze"]
        assert last - first >= 2 * bc.CONTEXT_SENTENCES


# -- Seed -----------------------------------------------------------------------------------------


def test_fixed_seed_is_reproducible(tmp_path):
    for name in ("a", "b"):
        bc.generate(_sources(), tmp_path / name, seed=11, k=3, switches=False)
    for kind in (*RATER_FILES, "key"):
        assert (tmp_path / "a" / bc.FILES[kind]).read_bytes() == (tmp_path / "b" / bc.FILES[kind]).read_bytes(), kind


def test_other_seed_changes_order_or_sides():
    runs = {f"q{i}": {"v1": {"angeboten": [_clip(f"a{i}{r}", 40 * r, 40 * r + 30) for r in range(2)]},
                      "v2": {"angeboten": [_clip(f"b{i}{r}", 40 * r, 40 * r + 30) for r in range(2)]}} for i in range(6)}  # fmt: skip
    first = bc.make_pairs(runs, seed=1)
    assert first == bc.make_pairs(runs, seed=1)
    assert first != bc.make_pairs(runs, seed=2)


# -- Ausgabemenge und Paarung ---------------------------------------------------------------------


def test_same_output_amount_per_source():
    runs = {
        "q1": {"v1": {"angeboten": [_clip("a1"), _clip("a2", 40, 70), _clip("a3", 80, 100)]}, "v2": {"angeboten": [_clip("b1")]}},
        "q2": {"v1": {"angeboten": []}, "v2": {"angeboten": [_clip("b2")]}},
        "q3": {"v1": {"angeboten": [_clip("a4"), _clip("a5", 40, 70)]}, "v2": {"angeboten": [_clip("b3"), _clip("b4", 40, 70)]}},
    }  # fmt: skip
    sheet, hook_sheet, key = bc.make_pairs(runs, seed=5)
    per_source = Counter(e["quelle"] for e in key["paare"].values())
    assert per_source == {"q1": 1, "q3": 2}
    assert Counter(e["quelle"] for e in key["hook_paare"].values()) == per_source
    assert sorted((s["quelle"], s["version"], s["rang"]) for s in key["nicht_gepaart"]) == [("q1", "v1", 2), ("q1", "v1", 3), ("q2", "v2", 1)]
    assert len(sheet["paare"]) == len(hook_sheet["paare"]) == 3


def test_pairing_by_overlap_or_rank():
    a = [_clip("a1", 0, 30), _clip("a2", 50, 80)]
    b = [_clip("b1", 49, 81), _clip("b2", 1, 29)]
    assert bc.match_pairs(a, b, "ueberdeckung") == [(0, 1, 1.0), (1, 0, 1.0)]
    assert [(i, j) for i, j, _ov in bc.match_pairs(a, b, "rang")] == [(0, 0), (1, 1)]
    with pytest.raises(SystemExit, match="paarung"):
        bc.match_pairs(a, b, "zufall")


def test_generated_pairs_respect_the_smaller_output(generated):
    run, key = _load(generated, "run"), _load(generated, "key")
    assert key["paarung"] == "ueberdeckung"
    for name, runs in run["quellen"].items():
        n = min(len(runs["v1"]["angeboten"]), len(runs["v2"]["angeboten"]))
        assert len(runs["v1"]["angeboten"]) <= 3 and len(runs["v2"]["angeboten"]) <= 3
        assert sum(1 for e in key["paare"].values() if e["quelle"] == name) == n


# -- Verwerfungsquote und Modellaufrufe ------------------------------------------------------------


def test_rejection_rate_separates_duplicates_and_events():
    discarded = [
        {"reason": "gate", "first_sent": 0, "last_sent": 3}, {"reason": "gate"}, {"reason": "too_short", "stage": "search"},
        {"reason": "promise_unfulfilled", "opening_sent": 4, "stage": "search"}, {"stage": "search"},
        {"reason": "duplicate_payoff", "detail": "same_span", "stage": "search"}, {"reason": "duplicate_payoff", "detail": "same_opening"},
        {"reason": "duplicate", "first_sent": 0, "last_sent": 5}, {"reason": "budget_exhausted"},
        {"reason": "llm_budget", "stage": "propose", "first_sent": 0, "last_sent": 9},
    ]  # fmt: skip
    summary = bc.discard_summary(discarded, proposals=13)
    assert summary["nenner"] == 10
    assert summary["verworfen"] == {
        "gate": {"anzahl": 2, "quote": 0.2},
        "ohne_grund/search": {"anzahl": 1, "quote": 0.1},
        "promise_unfulfilled": {"anzahl": 1, "quote": 0.1},
        "too_short": {"anzahl": 1, "quote": 0.1},
    }
    assert summary["verworfen_gesamt"] == 5
    assert summary["dubletten"] == {"duplicate": 1, "duplicate_payoff/same_opening": 1, "duplicate_payoff/same_span": 1}
    assert summary["laufereignisse"] == {"budget_exhausted": 1, "llm_budget": 1}
    assert bc.discard_summary([], proposals=0) == {"nenner": 0, "verworfen": {}, "verworfen_gesamt": 0, "dubletten": {}, "laufereignisse": {}}
    assert bc.reason_label("overlap") == "Überdeckung (overlap)"
    assert bc.reason_label("too_short") == "zu kurz (too_short)"
    assert bc.reason_label("gate") == "Tor (gate)"
    assert bc.reason_label("duplicate_payoff") == "Dublette, gleicher Payoff (duplicate_payoff)"
    assert bc.reason_label("duplicate_payoff/same_span") == "Dublette, gleicher Payoff, gleiche Spanne (duplicate_payoff/same_span)"
    assert bc.reason_label("ohne_grund/search") == "ohne Grundangabe, Stufe Suche (ohne_grund/search)"
    assert bc.reason_label("critic:distortion") == "Kritiker: distortion (critic:distortion)"
    assert bc.reason_label("neu") == "unbekannter Grund (neu)"


@pytest.mark.parametrize("version", [1, 2])
def test_rejection_rate_of_a_run_matches_report_discarded(version):
    source = _sources(("demo_script",))[0]
    variant = bc.Variant(f"v{version}", version)
    run = bc.run_variant(variant, source, dict(bc.DEFAULT_BRIEF), providers_llm.HEURISTIC_PROVIDER, 1)
    with bc.policy_variant(variant):
        llm = LLM(Tenant(id="t", tier="standard"), provider=providers_llm.HEURISTIC_PROVIDER, s=config.settings())
        report = story_engine.run(copy.deepcopy(source["words"]), dict(bc.DEFAULT_BRIEF), {}, None, llm, max_candidates=1)
    codes = Counter(bc.discard_code(d) for d in report.discarded)
    duplicates = {c: n for c, n in codes.items() if c.split("/", 1)[0] in bc.DUPLICATE_REASONS}
    events = {c: n for c, n in codes.items() if c in bc.RUN_EVENT_REASONS}
    rejected = {c: n for c, n in codes.items() if c not in duplicates and c not in events}
    denominator = report.proposals - sum(duplicates.values())
    assert run["vorschlaege"] == report.proposals and run["nenner"] == denominator
    assert run["dubletten"] == duplicates and run["laufereignisse"] == events
    assert {r: v["anzahl"] for r, v in run["verworfen"].items()} == rejected
    assert run["verworfen_gesamt"] == sum(rejected.values())
    for reason, v in run["verworfen"].items():
        assert v["quote"] == round(rejected[reason] / denominator, 4)
    assert "unbekannt" not in json.dumps(run["verworfen"])
    spans = {(c["first_sent"], c["last_sent"]) for c in run["angeboten"]}
    assert spans == {(c.first_sent, c.last_sent) for c in report.candidates}


def test_model_calls_are_counted_at_the_llm():
    """Ein Fake-LLM zählt jeden strukturierten Aufruf selbst; der Lauf muss dieselbe Zahl berichten."""
    seen: list[str] = []

    class CountingLLM(LLM):
        def structured(self, system, user, schema, tool_name, prompt_version, job_type="llm_score"):
            seen.append(prompt_version)
            return super().structured(system, user, schema, tool_name, prompt_version, job_type)

    def factory(provider, settings, sink):
        return CountingLLM(Tenant(id="t", tier="standard"), provider=provider, s=settings, cost_sink=sink)

    run = bc.run_variant(bc.Variant("v1", 1), _sources(("demo_script",))[0], dict(bc.DEFAULT_BRIEF), providers_llm.HEURISTIC_PROVIDER, 3, factory)
    assert seen and run["modellaufrufe"] == len(seen)
    assert run["modellaufrufe_je_prompt"] == dict(sorted(Counter(seen).items()))
    assert any(p.startswith("hooks_") for p in seen)
    assert run["hooks"]["gesamt"] == len(run["angeboten"])


def test_hook_platform_comes_from_the_brief(monkeypatch):
    real = bc.copy_engine.write_copy
    seen = []

    def spy(llm, text, brand, platforms=(), **kw):
        seen.append((brand.platform, tuple(platforms)))
        return real(llm, text, brand, platforms=platforms, **kw)

    monkeypatch.setattr(bc.copy_engine, "write_copy", spy)
    bc.run_variant(bc.Variant("v1", 1), _sources(("demo_script",))[0], {"platform": "tiktok"}, providers_llm.HEURISTIC_PROVIDER, 1)
    assert seen and all(s == ("tiktok", ("tiktok",)) for s in seen)


# -- Stil-Leck ------------------------------------------------------------------------------------


def test_style_leak_warns_on_hook_prefix_and_missing_overlay(tmp_path):
    leak = _load(_synthetic_dir(tmp_path), "run")["stil_leck"]
    text = " ".join(leak["warnungen"])
    assert "Hook-Bogen, gesprochener Hook beginnt mit „du kennst das“" in text
    assert leak["merkmale"]["v1"]["praefix_gesprochen"]["du kennst das"] == 1.0
    assert leak["wenige_paare"] is True


def test_style_leak_is_quiet_for_alike_material():
    runs = {"q": {"v1": {"angeboten": [_clip("a1"), _clip("a2", 40, 70)]}, "v2": {"angeboten": [_clip("b1"), _clip("b2", 40, 70)]}}}
    _sheet, _hooks, key = bc.make_pairs(runs, seed=1)
    assert bc.style_leak(runs, key)["warnungen"] == []


# -- Auswertung -----------------------------------------------------------------------------------


def test_sign_test():
    assert bc.sign_test(5, 0) == 0.0625
    assert bc.sign_test(3, 3) == 1.0
    assert bc.sign_test(0, 0) is None


def test_evaluation_of_a_filled_rating(tmp_path):
    out = _synthetic_dir(tmp_path)
    _fill(out)
    res = bc.evaluate(out)
    clip = res["clip"]
    assert clip["paare"] == clip["bewertete_paare"] == 4
    assert clip["mittel"]["v1"]["quellentreue"] == 2.0 and clip["mittel"]["v2"]["quellentreue"] == 3.0
    assert clip["streuung"]["v1"]["quellentreue"] == 0.0 and clip["streuung"]["v1"]["natuerlichkeit"] is None
    assert clip["mittel"]["v1"]["natuerlichkeit"] is None and clip["anzahl"]["v2"]["eigenstaendigkeit"] == 4
    assert clip["praeferenz"] == {"v1": 0, "v2": 3, "gleich": 1, "offen": 0}
    assert clip["vorzeichentest_p"] == 0.25
    assert res["hook"]["mittel"]["v2"]["deckung"] == 3.0
    assert res["urteil"]["urteil"] == "Erfüllt"
    assert [(i["quelle"], i["version"], i["rang"]) for i in res["nicht_gepaart"]] == [("fall_a", "v1", 3)]
    v1, v2 = res["varianten"]["v1"], res["varianten"]["v2"]
    assert v1["verworfen"] == {"gate": {"anzahl": 1, "quote": 0.125}, "ohne_grund/search": {"anzahl": 1, "quote": 0.125},
                               "too_long": {"anzahl": 1, "quote": 0.125}}  # fmt: skip
    assert v1["nenner"] == 8 and v2["nenner"] == 6 and v2["vorschlaege"] == 8
    assert v2["verwerfungsquote"] == 0.3333
    assert v2["dubletten"] == {"duplicate_payoff/same_opening": 1, "duplicate_payoff/same_span": 1}
    assert v2["laufereignisse"] == {"budget_exhausted": 1}
    assert v1["ohne_vorschlag"] == ["quelle_leer"] and v2["ohne_kandidat"] == ["quelle_leer"]
    assert v1["bestehensquote"] == 0.5 and v2["bestehensquote"] == 1.0

    report = bc.report_markdown(res)
    assert bc.NOTE in report
    assert "–" not in report and "—" not in report and " - " not in report
    assert report.index("Quellen ohne Vorschlag und ohne Kandidat") < report.index("Erfolgskriterium") < report.index("## Clips")
    for line in (
        "| ohne Vorschlag (Stufe 2 liefert nichts) | 1: quelle_leer | 1: quelle_leer |",
        "**Urteil: Erfüllt**",
        "| Quellentreue | 2,00 (0,00, n = 4) | 3,00 (0,00, n = 4) |",
        "| Natürlichkeit | nicht bewertet (keine, n = 0) | nicht bewertet (keine, n = 0) |",
        "Präferenz: v1 0, v2 3, gleich 1, offen 0. Vorzeichentest (zweiseitig, ohne Gleichstände): p = 0,250.",
        "| Tor (gate) | 1 (12,5 %) | 1 (16,7 %) |",
        "| zu lang (too_long) | 1 (12,5 %) | 0 |",
        "| ohne Grundangabe, Stufe Suche (ohne_grund/search) | 1 (12,5 %) | 0 |",
        "| Überdeckung (overlap) | 0 | 1 (16,7 %) |",
        "| gesamt | 3 von 8 (37,5 %) | 2 von 6 (33,3 %) |",
        "Vorschläge vor dem Abzug der Dubletten: v1 8, v2 8.",
        "| Dublette, gleicher Payoff, gleiche Spanne (duplicate_payoff/same_span) | 0 | 1 |",
        "| gesamt | 0 | 2 |",
        "| Modellbudget erschöpft (budget_exhausted) | 0 | 1 |",
        "**Warnung: Die Verblindung ist gefährdet.**",
        "| Hooks | hook.native_spoken (ja) | 2 | 0,0 % | 17,3 | 2 von 2 (100,0 %) | 1 von 2 (50,0 %) | 2 von 2 (100,0 %) | 0 von 2 (0,0 %) | 2 von 2 |",
        "| Basis | keiner | 2 | 33,3 % | 17,3 | 0 von 2 (0,0 %) | 0 von 2 (0,0 %) | 2 von 2 (100,0 %) | 0 von 2 (0,0 %) | 2 von 2 |",
    ):
        assert line in report, line


def test_verdict_not_met_and_not_rated(tmp_path):
    out = _synthetic_dir(tmp_path / "schlechter")
    _fill(out, v1_value=3, v2_value=2, preference_for="v1")
    assert bc.evaluate(out)["urteil"]["urteil"] == "Nicht erfüllt"
    tolerant = _synthetic_dir(tmp_path / "toleranz", tolerance=1.0)
    _fill(tolerant, v1_value=3, v2_value=2, preference_for="v1")
    assert bc.evaluate(tolerant)["urteil"]["urteil"] == "Erfüllt"
    empty = _synthetic_dir(tmp_path / "leer")
    res = bc.evaluate(empty)
    assert res["urteil"]["urteil"] == "Nicht bewertet"
    assert "**Urteil: Nicht bewertet**" in bc.report_markdown(res)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda s: s["paare"][0]["bewertung"]["A"].update(quellentreue=5), "kein Wert 0 bis 4"),
        (lambda s: s["paare"][0]["bewertung"]["A"].update(quellentreue=True), "kein Wert 0 bis 4"),
        (lambda s: s["paare"][0]["bewertung"]["A"].update(wow=3), "unbekanntes Kriterium 'wow'"),
        (lambda s: s["paare"][0].update(paar_id="P999"), "P999: paar_id fehlt im Schlüssel"),
        (lambda s: s["paare"][0]["bewertung"].update(praeferenz="v2"), "praeferenz 'v2'"),
        (lambda s: s["paare"][0]["bewertung"].update(praeferenz="A"), "Präferenz ohne Bewertung"),
    ],
)
def test_evaluation_errors_are_clear(tmp_path, mutate, message):
    out = _synthetic_dir(tmp_path)
    sheet = _load(out, "sheet")
    mutate(sheet)
    _write(out, "sheet", sheet)
    with pytest.raises(SystemExit, match=re.escape(message)):
        bc.evaluate(out)


def test_cli_writes_report(generated, tmp_path, capsys):
    for name in ("sheet", "hook_sheet", "key", "run"):
        (tmp_path / bc.FILES[name]).write_bytes((generated / bc.FILES[name]).read_bytes())
    bc.main(["--auswerten", str(tmp_path)])
    text = (tmp_path / bc.FILES["report"]).read_text(encoding="utf-8")
    assert text.startswith("# Blindvergleich v1 gegen v2")
    assert "**Urteil: Nicht bewertet**" in text
    assert "Bericht geschrieben" in capsys.readouterr().out


# -- Raster, Schalter, Fälle -----------------------------------------------------------------------


def test_rubric_template_has_anchors_0_to_4(generated):
    rubric = _load(generated, "rubric")
    assert list(rubric["kriterien"]) == [
        "quellentreue", "eigenstaendigkeit", "einstieg", "aufbau", "abschluss", "natuerlichkeit", "duplikate", "manuelle_nacharbeit",
    ]  # fmt: skip
    assert list(rubric["hook_kriterien"]) == ["deckung", "klarheit", "einstieg", "ton"]
    for spec in [*rubric["kriterien"].values(), *rubric["hook_kriterien"].values()]:
        assert list(spec["anker"]) == ["0", "1", "2", "3", "4"]
        assert all(text.strip() for text in spec["anker"].values())
    blob = json.dumps(rubric, ensure_ascii=False)
    assert "–" not in blob and "—" not in blob


def test_switch_variants_are_built_from_policy_overrides():
    variants = {v.name: v for v in bc.switch_variants({"cut.padding": True}, {"bewertung.modus_v2": "sortieren"})}
    assert variants["v2_kuerzung"].rules == (("trim.enabled", True),)
    assert variants["v2_kombination"].rules == (("trim.enabled", True),)
    assert variants["v2_basis"].rules == () and variants["v2_hooks"].rules == ()
    assert variants["v2_override"].rules == (("bewertung.modus_v2", "sortieren"),)
    assert dict(variants["v2_basis"].overrides) == dict.fromkeys(["gates.discard_hard", "hook.native_spoken", "search.payoff_first", "trim.enabled"], False)
    assert dict(variants["v2_hooks"].overrides)["hook.native_spoken"] is True
    assert dict(variants["v2_hooks"].overrides)["trim.enabled"] is False
    assert all(dict(variants["v2_kombination"].overrides).values())
    assert dict(variants["v2_override"].overrides) == {"cut.padding": True}


def test_policy_variant_applies_and_restores(monkeypatch):
    monkeypatch.setenv(editorial.POLICY_VERSION_ENV, "1")
    monkeypatch.delenv("EDITORIAL_DIR", raising=False)
    variant = bc.Variant("x", 2, (("hook.native_spoken", False), ("trim.enabled", True)), rules=(("trim.enabled", True), ("bewertung.modus_v2", "sortieren")))
    with bc.policy_variant(variant) as pol:
        assert pol.version == 2 and editorial.load().version == 2
        assert pol.roh["implementation"]["hook"]["native_spoken"] is False
        assert pol.roh["implementation"]["trim"]["enabled"] is True
        assert pol.roh["trim"]["enabled"] is True and pol.roh["bewertung"]["modus_v2"] == "sortieren"
        assert pol.hook_native_spoken is False
    assert os.environ[editorial.POLICY_VERSION_ENV] == "1"
    assert "EDITORIAL_DIR" not in os.environ
    assert editorial.load().version == 1


def test_parse_overrides():
    assert bc.parse_overrides(["trim.enabled=true"], "hook.native_spoken=false, ") == ({"hook.native_spoken": False, "trim.enabled": True}, {})
    switches, rules = bc.parse_overrides(["regel:trim.enabled=true", "regel:bewertung.modus_v2=sortieren"], "regel:hook.allow_partial_opening=true")
    assert switches == {} and rules == {"trim.enabled": True, "bewertung.modus_v2": "sortieren", "hook.allow_partial_opening": True}
    assert bc.parse_overrides(["regel:gates.discard_hard=false"]) == ({}, {"gates.discard_hard": False})
    for bad in ("trim.enabled=ja", "laenge.ziel_s=true", "regel:laenge.ziel_s=30", "regel:bewertung.modus_v2=raten", "regel:trim.enabled=ja"):
        with pytest.raises(SystemExit, match="ungültig"):
            bc.parse_overrides([bad])


def test_kuerzung_variant_removes_what_the_basis_keeps():
    """Ohne die Regel trim.enabled wäre die Variante Kürzung gleich der Basis (nur der Schalter stand an)."""
    variants = {v.name: v for v in bc.switch_variants()}
    source = _sources(("demo_script",))[0]
    runs = {n: bc.run_variant(variants[n], source, dict(bc.DEFAULT_BRIEF), providers_llm.HEURISTIC_PROVIDER, 5) for n in ("v2_basis", "v2_kuerzung")}
    removed = {n: [r for c in run["clip_candidates"] for r in c["removed_spans"]] for n, run in runs.items()}
    assert removed["v2_basis"] == []
    assert removed["v2_kuerzung"]
    assert runs["v2_kuerzung"]["regeln"] == {"trim.enabled": True}


def test_case_result_for_weak_material():
    case = next(s["case"] for s in bc.fixture_sources() if s["name"] == "fall_weak_material")
    assert case["expected"]["expect_reject"]["value"] is True
    assert bc.case_result(case, [], {}, {}) == {"bestanden": True, "gruende": []}
    res = bc.case_result(case, [{"candidate_id": "c1", "segments": [], "removed_spans": []}], {"c1": {}}, {})
    assert res["bestanden"] is False and "Verwerfen erwartet" in res["gruende"][0]


def test_whole_sentence():
    assert bc.whole_sentence("Preise sind Positionierung.", "Was ich gelernt habe. Preise sind Positionierung. Ende.")
    assert not bc.whole_sentence("Preise sind", "Preise sind Positionierung.")
    assert not bc.whole_sentence("", "Text.")


# -- clip_eval --------------------------------------------------------------------------------------


def test_clip_eval_use_policy_version(monkeypatch):
    monkeypatch.setenv(editorial.POLICY_VERSION_ENV, "1")
    assert clip_eval.use_policy_version(None) == "clip_policy_v1"
    assert clip_eval.use_policy_version(2) == "clip_policy_v2"
    assert os.environ[editorial.POLICY_VERSION_ENV] == "2" and editorial.load().version == 2
    with pytest.raises(SystemExit, match="erlaubt sind 1 und 2"):
        clip_eval.use_policy_version(3)


def test_clip_eval_summary_pause_share_and_median():
    def row(length, pause=None):
        g = {"laenge_s": length, "satzanfang": True, "satzende": True, "beginnt_mit_rueckverweis": False, "verneinung_am_rand": False}
        if pause is not None:
            g["grenze_nur_aus_pause"] = pause
        return {"grenzen": g}

    summary = clip_eval.zusammenfassung([row(10.0, []), row(20.0, ["Ende"]), row(30.0, []), row(41.0, ["Anfang", "Ende"])])
    assert summary["grenze_nur_aus_pause_anteil"] == 0.5
    assert summary["laenge_median_s"] == 25.0
    v1 = clip_eval.zusammenfassung([row(10.0), row(20.0), row(30.0)])
    assert "grenze_nur_aus_pause_anteil" not in v1 and v1["laenge_median_s"] == 20.0
