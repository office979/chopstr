"""T2 S6: Trainings-Workflow ``python -m eval.train`` mit gemockten Modellen, synthetischer Gold-Fixture, ohne Netz,
ohne Postgres und ohne Medien (Transkript statt ASR)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval import train

from .test_tiered_engine import FakeTiers
from .transcript_fixtures import demo_words

GOLD = Path(__file__).resolve().parents[1] / "eval" / "gold" / "fixtures" / "synthetic_v1.json"


class TrainFake(FakeTiers):
    """Wie ``FakeTiers`` plus Richter: Haiku sagt 6 (nahe der Schwelle), der zweite Durchgang 9 (Abweichung),
    die Eskalation 8."""

    def __init__(self, *a, temperature=None, **kw):
        super().__init__(*a, **kw)
        self.temperature = temperature

    def with_tier(self, tier, **kw):
        f = TrainFake(self.spans, tier, self.log, self.edit, temperature=kw.get("temperature"))
        return f

    def structured(self, system, user, schema, tool_name, prompt_version, job_type="llm_score", policy_block=None, cache_prefix=None, stage=None):
        if tool_name == "judge_clip":
            self.log.append({"tier": self.tier, "tool": tool_name, "stage": stage, "user": user, "prompt": prompt_version,
                             "policy_block": None, "cache_prefix": None})  # fmt: skip
            v = {"judge": 6, "judge_escalate": 8}.get(self.tier, 6)
            if stage == "judge_second":
                v = 9
            return {"hook": v, "context": 7, "payoff": 7, "copy": 7, "verdict": "equal", "reason": "Test."}
        return super().structured(system, user, schema, tool_name, prompt_version, job_type, policy_block, cache_prefix, stage)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("CHOPSTR_ENGINE", raising=False)
    fake = TrainFake(spans=[(0, 3), (4, 5), (12, 15)])
    monkeypatch.setattr(train, "make_llm", lambda provider, s, ledger, cache, scope: fake)
    src = tmp_path / "quelle.mp4"
    src.write_bytes(b"kein echtes video")
    tr = tmp_path / "transkript.json"
    tr.write_text(json.dumps({"words": demo_words()}), encoding="utf-8")
    return {"tmp": tmp_path, "fake": fake, "src": src, "tr": tr, "cache": tmp_path / "cache", "jobs": tmp_path / "jobs"}


def _job(env) -> Path:
    rc = train.main([
        "--cache-dir", str(env["cache"]), "job", "create", "--source", str(env["src"]), "--brief", "Fehler mit Zahlen",
        "--gold", "synth-fehler-preis,synth-andersrum", "--gold-file", str(GOLD), "--transcript", str(env["tr"]),
        "--name", "synth-job", "--out-dir", str(env["jobs"]),
    ])  # fmt: skip
    assert rc == 0
    return env["jobs"] / "synth-job.json"


def _run(env, capsys) -> Path:
    job = _job(env)
    capsys.readouterr()
    assert train.main(["--cache-dir", str(env["cache"]), "run", "--job", str(job), "--mm-provider", "none", "--skip-media", "--run-id", "r1"]) == 0
    return Path(capsys.readouterr().out.strip().splitlines()[-1])


def test_gold_cli_validate_and_stats(capsys):
    assert train.main(["gold", "validate", "--gold", str(GOLD)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["valid"] == 3 and out["ready_for_compare"] == 2 and not out["problems"]
    assert train.main(["gold", "stats", "--gold", str(GOLD)]) == 0
    assert json.loads(capsys.readouterr().out)["clips"] == 3


def test_job_file_has_only_metadata_and_cache_refs(env):
    job = json.loads(_job(env).read_text(encoding="utf-8"))
    assert job["version"] == "train_job_v1" and job["source"]["kind"] == "file"
    assert job["source"]["path"] is None and job["source"]["suffix"] == ".mp4"  # außerhalb des Repos kein Name
    assert str(env["tmp"]) not in json.dumps(job)  # kein absoluter Pfad in der Job-Datei
    assert job["transcript"] == "cache:transcript.json" and job["gold"] == ["synth-fehler-preis", "synth-andersrum"]
    assert job["gold_file"] == "workers/eval/gold/fixtures/synthetic_v1.json"
    assert job["brief"]["platform"] == "tiktok"
    cdir = env["cache"] / job["source"]["cache_ref"]
    assert (cdir / "source.json").is_file() and (cdir / "transcript.json").is_file()


def test_run_writes_clips_costs_and_meta_into_cache(env, capsys):
    rdir = _run(env, capsys)
    assert rdir.parent.parent.parent == env["cache"]
    clips = json.loads((rdir / "clips.json").read_text())["clips"]
    assert clips and all(c["rank"] >= 1 and c["title"] for c in clips)
    spans = {(c["first_sent"], c["last_sent"]) for c in clips}
    assert (0, 3) in spans
    meta = json.loads((rdir / "meta.json").read_text())
    assert meta["engine"] == "tiered_engine_v1" and meta["policy"] == "clip_policy_v2" and meta["mm"]["source"] == "local"
    assert meta["models"]["prefilter"] == "fake-prefilter" and meta["models"]["editor"] == "fake-editor"
    costs = json.loads((rdir / "costs.json").read_text())
    assert "eur_per_source_hour" in costs and costs["source_hours"]
    assert (rdir / "report.json").is_file() and (rdir / "events.json").is_file()


def test_compare_hits_recall_boundaries_and_judge_escalation(env, capsys):
    rdir = _run(env, capsys)
    assert train.main(["--cache-dir", str(env["cache"]), "compare", "--run", str(rdir)]) == 0
    cmp_ = json.loads((rdir / "compare.json").read_text())
    m = cmp_["metrics"]
    assert m["gold_n"] == 2 and m["hits"] == 2
    # Die Gates heilen den kurzen Kandidaten nach vorn (Kontext), daher ein Startfehler bei einem der beiden Treffer
    assert m["recall@3"] == 1.0 and m["boundary_start"]["n"] == 2 and m["iou_mean"] > 0.5
    assert {p["gold_id"] for p in cmp_["pairs"]} == {"synth-fehler-preis", "synth-andersrum"}
    assert all(p["basis"] in ("span", "segments") and p["multi_segment"] is False for p in cmp_["pairs"])
    assert m["multi_segment_gold"] == 0.0  # synthetische Fixture hat keine verdichteten Gold-Clips
    # Haiku 6 ist strittig, der zweite Durchgang weicht ab, also Eskalation an Sonnet mit 8
    j = cmp_["judges"][0]
    assert j["passes"] == ["judge", "judge_second", "judge_escalate"] and j["escalated"] is True and j["final"]["hook"] == 8
    tiers = [c["tier"] for c in env["fake"].calls("judge_clip")]
    assert "judge" in tiers and "judge_escalate" in tiers
    ref = next(c for c in env["fake"].calls("judge_clip") if "Referenz (veröffentlichter Clip" in c["user"])
    assert "mistake_with_consequence" in ref["user"] or "result_with_open_cause" in ref["user"]
    assert m["judge_escalated"] == len(cmp_["judges"]) and m["judge_hook"] == 8.0


def test_compare_without_judge_and_without_gold(env, capsys, tmp_path):
    rdir = _run(env, capsys)
    assert train.main(["--cache-dir", str(env["cache"]), "compare", "--run", str(rdir), "--no-judge", "--ids", "gibt-es-nicht"]) == 0
    m = json.loads((rdir / "compare.json").read_text())["metrics"]
    assert m["gold_n"] == 0 and m["recall@3"] is None and m["precision@3"] is None and m["boundary_start"] is None
    assert "judge_hook" not in m


def test_scorecard_and_history_only_metrics(env, capsys):
    rdir = _run(env, capsys)
    train.main(["--cache-dir", str(env["cache"]), "compare", "--run", str(rdir)])
    hist = env["tmp"] / "history.jsonl"
    assert train.main(["scorecard", "--run", str(rdir), "--history", str(hist)]) == 0
    md = (rdir / "scorecard.md").read_text()
    assert "| recall@3 | 1,000 |" in md and "EUR je Quellstunde" in md
    line = json.loads(hist.read_text().splitlines()[-1])
    assert line["run_id"] == "r1" and line["metrics"]["hits"] == 2
    text = json.dumps(line, ensure_ascii=False)
    assert "teuerste Fehler" not in text and "Ehrlich gesagt" not in text  # kein Transkript, keine Copy


def test_export_ranking_and_preferences(env, capsys):
    rdir = _run(env, capsys)
    train.main(["--cache-dir", str(env["cache"]), "compare", "--run", str(rdir), "--no-judge"])
    out = env["tmp"] / "rank.jsonl"
    assert train.main(["export", "--format", "ranking", "--run", str(rdir), "--out", str(out)]) == 0
    rows = [json.loads(x) for x in out.read_text().splitlines()]
    assert rows and {"features", "label", "judge", "views"} <= set(rows[0]) and "text" not in rows[0]
    assert any(r["label"]["gold_hit"] for r in rows)
    pref = env["tmp"] / "pref.jsonl"
    assert train.main(["export", "--format", "preferences", "--run", str(rdir), "--out", str(pref)]) == 0
    pairs = [json.loads(x) for x in pref.read_text().splitlines()]
    assert all(p["reason"] in ("gold_hit", "judge_margin") for p in pairs)


def test_feed_writes_store_and_refuses_main_db(env, capsys):
    rdir = _run(env, capsys)
    train.main(["--cache-dir", str(env["cache"]), "compare", "--run", str(rdir), "--no-judge"])
    store = env["tmp"] / "feed.jsonl"
    assert train.main(["feed", "--run", str(rdir), "--gold", str(GOLD), "--store", str(store)]) == 0
    fed = json.loads(store.read_text().splitlines()[-1])
    assert fed["rows"] >= 1 and fed["hook_patterns"]["mistake_with_consequence"]["chosen"] == 1
    assert fed["weights_reliable"] is False  # zu wenige Zeilen für belastbare Gewichte
    for url in ("postgres://u@127.0.0.1:5499/test", "postgres://u@localhost:6543/chopstr", "postgresql://u@db/chopstr?x=1",
                "postgresql://h:5432/x?dbname=chopstr", "postgresql://chopstr@localhost", "postgresql://u@h/x?port=5499",
                "postgresql://u@h/x?service=main"):
        with pytest.raises(SystemExit, match="verweigert"):
            train.main(["feed", "--run", str(rdir), "--db", url, "--brand-profile", "b"])
    with pytest.raises(SystemExit):
        train.assert_db_allowed("mysql://x")
    train.assert_db_allowed("postgres://u@localhost:6543/chopstr_test")


def test_match_and_metrics_units():
    clips = [{"rank": 1, "start_s": 0.0, "end_s": 20.0, "duration_s": 20.0}, {"rank": 2, "start_s": 100.0, "end_s": 110.0, "duration_s": 10.0}]
    gold = [{"id": "g", "source": {"start_s": 2.0, "end_s": 22.0}}, {"id": "h", "source": {"start_s": 300.0, "end_s": 330.0}}]
    m = train.match(clips, gold, 0.5, 10.0)
    assert m["pairs"] == [(0, 0, pytest.approx(18 / 22, abs=1e-4))]
    met = train.ranking_metrics(clips, gold, m)
    assert met["recall@3"] == 0.5 and met["precision@3"] == 0.5
    assert met["boundary_start"]["median_s"] == -2.0 and met["length_delta"]["median_s"] == 0.0
    # Mitte ± 10 s zählt auch bei kleiner Überlappung
    assert train.is_hit({"start_s": 0.0, "end_s": 60.0}, {"source": {"start_s": 25.0, "end_s": 40.0}}, 0.5, 10.0)[0] is True
    assert met["multi_segment_gold"] == 0.0 and met["segment_coverage_mean"] is None and met["hits_by_segments_only"] == 0


def _seg_gold(gid: str, start: float, end: float, segs: list | None) -> dict:
    return {"id": gid, "source": {"start_s": start, "end_s": end, "segments": segs}}


def test_multi_segment_gold_span_and_union():
    # Verdichteter Gold-Clip: drei Quellstellen (5 + 2 + 20 s) über 193 s Spanne, wie yt_83tlc0q-ls8 im DACH-Set
    g = _seg_gold("g", 1264.8, 1458.4, [[1264.8, 1270.3], [1282.2, 1284.3], [1438.1, 1457.7]])
    assert train.gold_span(g) == (1264.8, 1458.4)
    assert train.gold_segments(g) == [(1264.8, 1270.3), (1282.2, 1284.3), (1438.1, 1457.7)]
    # Zusammenhängender Schnitt über die ganze Spanne: Treffer über die Spanne, alle Quellstellen enthalten,
    # gegen die Vereinigung aber nur kleine IoU (genau der Abstand zur verdichteten Referenz)
    d = train.hit_detail({"start_s": 1260.0, "end_s": 1460.0}, g, 0.5, 10.0)
    assert d["hit"] and d["basis"] == "span" and d["coverage"] == 1.0 and d["iou_segments"] < 0.2 and d["multi_segment"]
    # Nur der Payoff-Teil (letzte Stelle): Spanne verfehlt, Treffer über die Vereinigung (IoU 19,6 / 27,6)
    d2 = train.hit_detail({"start_s": 1438.0, "end_s": 1458.0}, g, 0.5, 10.0)
    assert d2["basis"] == "segments" and d2["hit"] and d2["coverage"] == pytest.approx(19.6 / 27.2, abs=1e-3)
    d3 = train.hit_detail({"start_s": 1000.0, "end_s": 1030.0}, g, 0.5, 10.0)
    assert d3["hit"] is False and d3["basis"] is None and d3["coverage"] == 0.0


def test_gold_segments_merges_and_falls_back():
    assert train.gold_segments(_seg_gold("a", 0.0, 30.0, None)) == [(0.0, 30.0)]
    # Clip-Reihenfolge darf von der Quellreihenfolge abweichen (umgestellt), überlappende Stellen werden vereinigt
    assert train.gold_segments(_seg_gold("b", 0.0, 30.0, [[20.0, 30.0], [0.0, 5.0], [4.0, 8.0]])) == [(0.0, 8.0), (20.0, 30.0)]
    # Ohne start_s/end_s: Gesamtspanne aus den Quellstellen
    assert train.gold_span({"id": "c", "source": {"start_s": None, "end_s": None, "segments": [[50.0, 55.0], [10.0, 12.0]]}}) == (10.0, 55.0)


def test_multi_segment_metrics():
    gold = [
        _seg_gold("multi", 100.0, 200.0, [[100.0, 110.0], [190.0, 200.0]]),
        _seg_gold("single", 400.0, 430.0, [[400.0, 430.0]]),
        _seg_gold("plain", 600.0, 620.0, None),
        _seg_gold("multi2", 900.0, 1000.0, [[900.0, 905.0], [995.0, 1000.0]]),
    ]
    clips = [
        {"rank": 1, "start_s": 100.0, "end_s": 200.0, "duration_s": 100.0},  # ganze Spanne von "multi"
        {"rank": 2, "start_s": 401.0, "end_s": 430.0, "duration_s": 29.0},
    ]
    m = train.match(clips, gold, 0.5, 10.0)
    met = train.ranking_metrics(clips, gold, m)
    assert met["multi_segment_gold"] == 0.5  # 2 von 4 Gold-Clips aus mehreren Stellen
    assert met["multi_segment_hits"] == 1 and met["segment_coverage_mean"] == 1.0
    assert met["boundary_start"]["median_s"] == 0.5 and met["recall@3"] == 0.5
    assert m["details"][(0, 0)]["iou_segments"] == pytest.approx(0.2) and m["details"][(0, 0)]["basis"] == "span"
    assert "aus 2 Quellstellen verdichtet" in train.judge_rubric({**gold[0], "breakdown": {"edits": {"compression": 5.0}}})
    assert "verdichtet" not in train.judge_rubric({**gold[1], "breakdown": {}})
