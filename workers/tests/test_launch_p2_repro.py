"""Lane P2 (Launch Phase 2): Reproduzierbarkeit von ``story_engine.run`` mit Heuristik-Provider (Gate 2 verlangt
mindestens 4 von 5 gleiche Läufe) und Kontext der Episodenübersicht für Stufe 2 (Vorschlag).

Geprüft wird im selben Prozess und über zwei Prozesse mit verschiedenem ``PYTHONHASHSEED``: ein Ergebnis, das von
der Iterationsreihenfolge einer Menge aus Zeichenketten abhinge, fiele nur über Prozesse hinweg auf."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import yaml

from chopstr_worker import config, editorial, providers_llm
from chopstr_worker.pipeline import payoff_search, signals, story_engine
from chopstr_worker.providers_llm import LLM
from chopstr_worker.residency import Tenant
from tests.test_launch_p2_chapters import HIRING, PRICING, _script
from tests.test_launch_p2_heat import CALM_SCRIPT
from tests.test_story_engine import BRIEF, SEARCH_ON, SEARCH_SCRIPT, brain, llm, wired  # noqa: F401
from tests.transcript_fixtures import demo_words, make_words

WORKERS = Path(__file__).resolve().parents[1]
ALL_ON = {
    "chapters.topic_shift.enabled": True,
    "heat.text_v2": True,
    "ranking.pairwise.enabled": True,
}


def _heuristic() -> LLM:
    return LLM(Tenant(id="ws", tier="standard"), provider=providers_llm.HEURISTIC_PROVIDER, s=config.settings())


def _inputs() -> list[tuple[list[dict], dict | None]]:
    calm = make_words(CALM_SCRIPT)
    audio = np.zeros(int(np.ceil(calm[-1]["end"])) + 1, dtype=np.float32)
    audio[2:5] = 2.0
    heat = signals.to_payload(signals.combined("", calm, audio=audio), audio=audio)
    preise = json.loads((WORKERS / "tests" / "fixtures" / "real_preise.json").read_text(encoding="utf-8"))["words"]
    return [(demo_words(), None), (calm, heat), (preise, None), (make_words(_script((PRICING, 15), (HIRING, 20))), None)]


def _offered(report: story_engine.DetectReport) -> list[tuple]:
    return [(e["first_sent"], e["last_sent"], e["start_s"], e["end_s"], e["rank"]) for e in report.funnel["offered"]]


def test_two_runs_give_the_same_offered_spans_and_ranks(wired):  # noqa: F811
    wired(**ALL_ON)
    offered, compared = 0, 0
    for words, heat in _inputs():
        first = story_engine.run(words, BRIEF, {}, json.loads(json.dumps(heat)) if heat else None, _heuristic())
        second = story_engine.run(words, BRIEF, {}, json.loads(json.dumps(heat)) if heat else None, _heuristic())
        assert _offered(first) == _offered(second)
        assert json.dumps(first.to_json(), sort_keys=True, ensure_ascii=False) == json.dumps(second.to_json(), sort_keys=True, ensure_ascii=False)
        data = first.to_json()
        assert story_engine.DetectReport.from_json(data).to_json() == data
        assert "ranking" in data and "yield" in data and "funnel" in data
        offered += len(first.candidates)
        compared = max(compared, first.ranking["compared"])
    # Die Fälle decken angebotene Kandidaten, den Paarvergleich mit Heuristik und null Kandidaten ab.
    assert offered >= 3 and compared >= 3


SCRIPT = """
import hashlib, json, sys
from chopstr_worker import config, providers_llm
from chopstr_worker.pipeline import dach_nlp, story_engine
from chopstr_worker.providers_llm import LLM
from chopstr_worker.residency import Tenant
dach_nlp.nlp = lambda: None
cases = json.load(open(sys.argv[1], encoding="utf-8"))
heur = LLM(Tenant(id="ws", tier="standard"), provider=providers_llm.HEURISTIC_PROVIDER, s=config.settings())
out = []
for words, heat in cases:
    report = story_engine.run(words, {"audience": "Gründer"}, {}, heat, heur)
    out.append(hashlib.sha256(json.dumps(report.to_json(), sort_keys=True, ensure_ascii=False).encode()).hexdigest())
print(json.dumps(out))
"""


def test_runs_in_two_processes_with_different_hash_seeds_are_identical(tmp_path):
    for path in editorial.policy_dir().glob("clip_policy_v*.yaml"):
        (tmp_path / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    target = tmp_path / "clip_policy_v2.yaml"
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    for dotted, value in ALL_ON.items():
        node = data
        *parents, leaf = dotted.split(".")
        for part in parents:
            node = node[part]
        node[leaf] = value
    target.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps(_inputs(), ensure_ascii=False), encoding="utf-8")
    digests = []
    for seed in ("0", "4711"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "EDITORIAL_DIR": str(tmp_path), "CHOPSTR_POLICY_VERSION": "2",
               "LOCAL_STORAGE_DIR": str(tmp_path / "s"), "WORKER_WORK_DIR": str(tmp_path / "w")}  # fmt: skip
        env.pop("S3_ENDPOINT", None)
        res = subprocess.run([sys.executable, "-c", SCRIPT, str(cases)], cwd=WORKERS, env=env, capture_output=True, text=True, timeout=300)
        assert res.returncode == 0, res.stderr[-2000:]
        digests.append(json.loads(res.stdout.strip().splitlines()[-1]))
    assert digests[0] == digests[1]
    assert len(digests[0]) == len(_inputs())


def test_episode_overview_is_context_for_the_proposal(brain, llm, wired, monkeypatch):  # noqa: F811
    """Befund zu Aufgabe 4: die Übersicht je Kapitel (``story_score.overview``) steht schon heute als Kontext im
    Vorschlags-Prompt (``propose_moments_v2``, Begrenzer ``episode_overview``), unter Fassung 2 mit Suche."""
    wired(**SEARCH_ON)
    monkeypatch.setattr(
        payoff_search, "search_moments",
        lambda chapter, pol, heat=None, gate_fn=None, words=None: {"proposals": [], "rejected": [], "duplicates": [], "payoffs": [], "openings": []},
    )  # fmt: skip
    users: dict[str, list[str]] = {}
    original = brain.structured

    def structured(system, user, schema, tool_name, prompt_version, job_type="llm_score"):
        users.setdefault(tool_name, []).append(user)
        if tool_name == "episode_overview":
            out = original(system, user, schema, tool_name, prompt_version, job_type)
            out["claims"] = [{"sent": 2, "text": "UEBERSICHT-BEHAUPTUNG-ZUR-ENTSCHEIDUNG"}]
            return out
        return original(system, user, schema, tool_name, prompt_version, job_type)

    brain.structured = structured
    report = story_engine.run(make_words(SEARCH_SCRIPT), BRIEF, {}, None, llm)
    (propose_user,) = users["propose_moments"]
    block = propose_user[propose_user.index("<episode_overview>") : propose_user.index("</episode_overview>")]
    assert "UEBERSICHT-BEHAUPTUNG-ZUR-ENTSCHEIDUNG" in block
    assert report.overviews[0]["claims"][0]["text"] == "UEBERSICHT-BEHAUPTUNG-ZUR-ENTSCHEIDUNG"
    assert len(users["episode_overview"]) == 1


def test_heuristic_runs_the_overview_but_no_model_proposal_reads_it(wired):  # noqa: F811
    """Befund zu Aufgabe 4: mit dem Heuristik-Provider entsteht die Übersicht (Bericht), aber kein Modellvorschlag
    liest sie (P47); sie wirkt dort nicht auf die Auswahl."""
    wired(**SEARCH_ON)
    report = story_engine.run(make_words(SEARCH_SCRIPT), BRIEF, {}, None, _heuristic())
    assert report.overviews and report.overviews[0]["heuristic"] is True
    assert {c["model_skipped"] for c in report.search["chapters"]} == {"heuristic"}
