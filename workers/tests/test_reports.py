"""Wochenreport: mit und ohne Daten, Textbausteine ohne Gedankenstriche, Speicherung, Mail an owner/admin."""

from __future__ import annotations

from datetime import date, datetime

import httpx
import pytest

from chopstr_worker import config, internal_api
from chopstr_worker.activities import reports

SEGS = [{"start": 0.0, "end": 30.0, "role": "body"}]


@pytest.fixture
def mail(monkeypatch):
    sent: list[dict] = []
    state = {"ok": True}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        if not state["ok"]:
            return httpx.Response(500, json={"error": {"message": "Mailserver weg"}})
        sent.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setenv("INTERNAL_API_SECRET", "s")
    config.reload()
    monkeypatch.setattr(internal_api, "client", lambda s=None, **kw: httpx.Client(transport=httpx.MockTransport(handler), base_url="http://web:3000"))
    return sent, state


@pytest.fixture
def workspace(fake_db, fake_context, mail):
    wid = fake_db.add_workspace(name="Agentur Nord")
    owner = fake_db.add_user("owner@example.com")
    fake_db.add_member(wid, owner, "owner")
    fake_db.add_member(wid, None, "admin", email="admin@example.com")
    fake_db.add_member(wid, fake_db.add_user("editor@example.com"), "editor")
    fake_context.settings = config.settings()
    return wid


def test_report_without_data(fake_db, fake_context, workspace, mail):
    sent, _state = mail
    out = reports.run_build_weekly_report(fake_context, workspace, "2026-09-14")
    assert out["clips"] == 0 and out["sent"] is True and out["recipients"] == 2
    row = fake_db.weekly_reports[out["report_id"]]
    assert row["week_start"] == date(2026, 9, 14) and row["report"]["note"] == "keine Publikationen mit Metriken" and row["sent_at"] is not None
    assert row["report"]["best"] == [] and row["report"]["week_end"] == "2026-09-20"
    assert sorted(sent[0]["to"]) == ["admin@example.com", "owner@example.com"]
    assert "Wochenreport 2026-09-14 bis 2026-09-20" in sent[0]["subject"] and "keine Publikationen mit Metriken" in sent[0]["text"]
    # zweiter Lauf derselben Woche: Upsert, keine zweite Zeile
    reports.run_build_weekly_report(fake_context, workspace, date(2026, 9, 14))
    assert len(fake_db.weekly_reports) == 1 and len(sent) == 2


def _clip(fake_db, wid, sid, follows_per_1k: float, duration: float, hook: int, pattern: str, structure: str = "hook_build_payoff", platform: str = "tiktok"):
    cand = fake_db.add_candidate(sid, [{"start": 0.0, "end": duration, "role": "body"}])
    cid = fake_db.add_clip(sid, cand, platform, SEGS, status="rendered", title_card=f"Clip {pattern} {duration:.0f}", duration_s=duration)
    fake_db.decision_log.append({
        "workspace_id": wid, "candidate_id": cand, "clip_id": None, "decision_type": "candidate_scored",
        "features": {"structure": structure, "duration_s": duration, "platform": platform, "scores": {"hook": hook, "payoff": 7, "specificity": 6, "tension": 5, "audience_fit": 6}},
        "chosen": {}, "created_at": len(fake_db.decision_log),
    })  # fmt: skip
    fake_db.decision_log.append({"workspace_id": wid, "candidate_id": None, "clip_id": cid, "decision_type": "hook_selected", "features": {}, "chosen": {"pattern": pattern}, "created_at": len(fake_db.decision_log)})
    pub = fake_db.add_publication(wid, cid, platform, status="published")
    fake_db.add_feedback(wid, cid, pub, platform=platform, views=1000, follows_per_1k=follows_per_1k, saves_per_1k=1.0, reward=1.0)
    return cid


def test_report_with_data_ranks_and_explains(fake_db, fake_context, workspace, mail):
    sent, _state = mail
    sid = fake_db.add_source(workspace, "uploads/in.mp4", title="Talk")
    best1 = _clip(fake_db, workspace, sid, 12.0, 32.0, 8, "contrarian")
    best2 = _clip(fake_db, workspace, sid, 9.0, 28.0, 7, "results_first", structure="decision_story")
    best3 = _clip(fake_db, workspace, sid, 7.0, 40.0, 7, "contrarian")
    mid = _clip(fake_db, workspace, sid, 4.0, 45.0, 6, "identity_call")
    weak_long = _clip(fake_db, workspace, sid, 1.0, 85.0, 7, "open_loop", platform="linkedin")
    weak_hook = _clip(fake_db, workspace, sid, 0.5, 30.0, 3, "identity_call")
    weak_pattern = _clip(fake_db, workspace, sid, 2.0, 30.0, 7, "mistake_warning")
    # Fremder Workspace und anderes Fenster dürfen nicht auftauchen
    other = fake_db.add_workspace()
    osid = fake_db.add_source(other, "uploads/o.mp4")
    _clip(fake_db, other, osid, 99.0, 30.0, 9, "contrarian")
    fake_db.add_feedback(workspace, best1, None, metric_window="6h", views=5, follows_per_1k=99.0)

    out = reports.run_build_weekly_report(fake_context, workspace, "2026-09-14")
    report = fake_db.weekly_reports[out["report_id"]]["report"]
    assert report["clips"] == 7 and report["note"] is None
    assert [b["clip_id"] for b in report["best"]] == [best1, best2, best3]
    assert [w["clip_id"] for w in report["weakest"]] == [weak_hook, weak_long, weak_pattern]
    assert mid not in {e["clip_id"] for e in report["best"] + report["weakest"]}
    b = report["best"][0]
    assert b["features"] == {"structure": "hook_build_payoff", "hook_pattern": "contrarian", "duration_s": 32.0, "platform": "tiktok", "scores": {"hook": 8, "payoff": 7, "specificity": 6, "tension": 5, "audience_fit": 6}}
    assert b["cause"].startswith("Struktur Hook, Aufbau, Payoff, Hook-Muster Gegenposition, 32 Sekunden auf TikTok: 12,0 Follower je 1.000 Views")
    assert "Serie" in b["change"]
    by_id = {w["clip_id"]: w for w in report["weakest"]}
    assert "zu lang" in by_id[weak_long]["cause"] and "kürzen" in by_id[weak_long]["change"] and "LinkedIn" in by_id[weak_long]["cause"]
    assert "schwacher Einstieg (Hook 3 von 10)" in by_id[weak_hook]["cause"] and "Variante B" in by_id[weak_hook]["change"]
    assert "nicht unter den besten Mustern" in by_id[weak_pattern]["cause"] and "Gegenposition" in by_id[weak_pattern]["change"]
    for e in report["best"] + report["weakest"]:
        for key in ("cause", "change"):
            assert "–" not in e[key] and "—" not in e[key] and e[key].endswith(".")
    text = sent[-1]["text"]
    assert "Beste Clips nach Folgequote:" in text and "Schwächste Clips:" in text and "Clip contrarian 32" in text
    assert "–" not in text and "—" not in text
    assert out["sent"] is True and fake_db.weekly_reports[out["report_id"]]["sent_at"] is not None


def test_few_clips_and_missing_features(fake_db, fake_context, workspace, mail):
    sid = fake_db.add_source(workspace, "uploads/in.mp4", title="Talk")
    cand = fake_db.add_candidate(sid, SEGS)
    cid = fake_db.add_clip(sid, cand, "reels", SEGS, status="rendered")
    pub = fake_db.add_publication(workspace, cid, "reels", status="published")
    fake_db.add_feedback(workspace, cid, pub, platform="reels", views=100, follows_per_1k=3.0)
    fake_db.add_feedback(workspace, cid, pub, platform="reels", views=100, follows_per_1k=None)  # ohne Folgequote ignoriert
    out = reports.run_build_weekly_report(fake_context, workspace, "2026-09-14")
    report = fake_db.weekly_reports[out["report_id"]]["report"]
    assert report["clips"] == 1 and len(report["best"]) == 1 and report["weakest"] == []
    e = report["best"][0]
    assert e["title"] == "Talk" and e["features"]["structure"] is None and e["features"]["duration_s"] is None
    assert "Länge unbekannt" in e["cause"] and "unbekannt" in e["cause"]


def test_mail_failure_keeps_report(fake_db, fake_context, workspace, mail):
    _sent, state = mail
    state["ok"] = False
    out = reports.run_build_weekly_report(fake_context, workspace, "2026-09-14")
    assert out["sent"] is False and out["report_id"] in fake_db.weekly_reports
    assert fake_db.weekly_reports[out["report_id"]]["sent_at"] is None


def test_no_recipients_and_workspace_list(fake_db, fake_context, mail):
    sent, _state = mail
    wid = fake_db.add_workspace()
    fake_db.add_workspace(weekly_report_enabled=False)
    out = reports.run_build_weekly_report(fake_context, wid, "2026-09-14")
    assert out["sent"] is False and out["recipients"] == 0 and sent == []
    assert reports.run_find_report_workspaces(fake_context) == [wid]


def test_week_helpers():
    assert reports.previous_week_start(datetime(2026, 9, 21, 7, 0)) == date(2026, 9, 14)  # Montag
    assert reports.previous_week_start(date(2026, 9, 27)) == date(2026, 9, 14)  # Sonntag
    start, end = reports.week_bounds(date(2026, 9, 14))
    assert start.isoformat() == "2026-09-14T00:00:00+00:00" and end.isoformat() == "2026-09-21T00:00:00+00:00"
