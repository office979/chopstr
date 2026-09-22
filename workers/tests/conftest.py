"""Gemeinsame Fixtures: Umgebungsvariablen, lokaler Storage, Fake-DB (ohne Postgres)."""

from __future__ import annotations

import os
import shutil
import sys
import uuid
from pathlib import Path

import pytest

WORKERS_ROOT = Path(__file__).resolve().parents[1]
if str(WORKERS_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKERS_ROOT))

# Testumgebung: kein S3, kein Redis, keine Modelle. Vor dem ersten Import von config setzen.
os.environ.pop("S3_ENDPOINT", None)
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ASR_MODEL_DE", "")
os.environ.setdefault("ASR_MODEL_CH", "")
os.environ.setdefault("ASR_DEVICE", "cpu")
os.environ.setdefault("EGRESS_ALLOWLIST", "")

from chopstr_worker import config, storage  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_settings(tmp_path, monkeypatch):
    """Jeder Test bekommt frische Settings und einen eigenen lokalen Storage."""
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("WORKER_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.delenv("S3_ENDPOINT", raising=False)
    config.reload()
    yield
    config.reload()


@pytest.fixture
def local_store() -> storage.Storage:
    return storage.Storage(config.settings())


def ffmpeg_present() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


requires_ffmpeg = pytest.mark.skipif(not ffmpeg_present(), reason="ffmpeg/ffprobe nicht installiert")


class FakeCursor:
    def __init__(self, rows, rowcount: int | None = None):
        self.rows = rows
        self.rowcount = len(rows) if rowcount is None else rowcount

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class FakeDB:
    """Minimaler Ersatz für eine psycopg-Verbindung: kennt genau die Abfragen des Workers."""

    def __init__(self):
        self.sources: dict[str, dict] = {}
        self.workspaces: dict[str, dict] = {}
        self.brand_profiles: dict[str, dict] = {}
        self.events: list[dict] = []
        self.job_costs: list[dict] = []
        self.transcript_versions: list[dict] = []
        self.candidates: list[dict] = []
        self.clips: dict[str, dict] = {}
        self.hook_versions: list[dict] = []
        self.caption_versions: list[dict] = []
        self.guest_approvals: list[dict] = []
        self.transcript_corrections: list[dict] = []
        # Phase 4
        self.deletion_jobs: dict[str, dict] = {}
        self.usage_periods: dict[str, dict] = {}
        self.subscriptions: dict[str, dict] = {}
        self.brand_assets: dict[str, dict] = {}
        self.audit_log: list[dict] = []
        # Phase 5
        self.outbox_events: list[dict] = []
        self.webhook_endpoints: dict[str, dict] = {}
        self.webhook_deliveries: dict[str, dict] = {}
        self.publications: dict[str, dict] = {}
        self.platform_connections: dict[str, dict] = {}
        self.performance_feedback: list[dict] = []
        self.decision_log: list[dict] = []
        self.hook_pattern_stats: dict[tuple[str, str], dict] = {}
        self.weekly_reports: dict[str, dict] = {}
        self.users: dict[str, dict] = {}
        self.workspace_members: list[dict] = []
        self.plans: dict[str, dict] = {
            "starter": {"code": "starter", "included_hours": 4, "overage_eur_per_hour": 9.0},
            "pro": {"code": "pro", "included_hours": 12, "overage_eur_per_hour": 7.5},
            "agency": {"code": "agency", "included_hours": 40, "overage_eur_per_hour": 6.0},
            "sovereign": {"code": "sovereign", "included_hours": 40, "overage_eur_per_hour": 6.0},
        }
        self.status_history: list[tuple[str, str]] = []
        self.statements: list[tuple[str, tuple]] = []
        self.closed = False

    # -- Testhelfer ----------------------------------------------------------------------------
    def add_workspace(self, tier: str = "standard", **fields) -> str:
        wid = str(uuid.uuid4())
        row = {
            "id": wid, "name": "Workspace", "tier": tier, "allow_us_subprocessors": False,
            "deletion_requested_at": None, "deletion_scheduled_for": None, "weekly_report_enabled": True,
        }  # fmt: skip
        row.update(fields)
        self.workspaces[wid] = row
        return wid

    # -- Phase 5 -------------------------------------------------------------------------------
    def add_webhook_endpoint(self, workspace_id: str, url: str, events: list[str], secret: str = "whsec_test", **fields) -> str:
        row = {"id": str(uuid.uuid4()), "workspace_id": workspace_id, "url": url, "secret": secret, "events": list(events), "active": True}
        row.update(fields)
        self.webhook_endpoints[row["id"]] = row
        return row["id"]

    def add_connection(self, workspace_id: str, platform: str = "linkedin", **fields) -> str:
        row = {"id": str(uuid.uuid4()), "workspace_id": workspace_id, "brand_profile_id": None, "platform": platform, "account_label": platform, "status": "connected", "capabilities": {}}
        row.update(fields)
        self.platform_connections[row["id"]] = row
        return row["id"]

    def add_publication(self, workspace_id: str, clip_id: str, platform: str = "linkedin", **fields) -> str:
        row = {
            "id": str(uuid.uuid4()), "workspace_id": workspace_id, "clip_id": clip_id, "connection_id": None, "platform": platform,
            "status": "scheduled", "scheduled_for": None, "external_id": None, "external_url": None, "published_at": None,
            "metrics": None, "error": None, "metrics_fetched_at": None,
        }  # fmt: skip
        row.update(fields)
        self.publications[row["id"]] = row
        return row["id"]

    def add_feedback(self, workspace_id: str, clip_id: str | None, publication_id: str | None, platform: str = "linkedin", metric_window: str = "7d", **fields) -> str:
        row = {
            "id": str(uuid.uuid4()), "workspace_id": workspace_id, "clip_id": clip_id, "publication_id": publication_id, "platform": platform,
            "metric_window": metric_window, "views": None, "likes": None, "comments": None, "shares": None, "saves": None, "follows": None,
            "avg_watch_time_s": None, "retention_curve": None, "follows_per_1k": None, "saves_per_1k": None, "account_median_views": None,
            "outlier_score": None, "reward": None, "fetched_at": len(self.performance_feedback),
        }  # fmt: skip
        row.update(fields)
        self.performance_feedback.append(row)
        return row["id"]

    def add_user(self, email: str, **fields) -> str:
        row = {"id": str(uuid.uuid4()), "email": email, "display_name": None}
        row.update(fields)
        self.users[row["id"]] = row
        return row["id"]

    def add_member(self, workspace_id: str, user_id: str | None, role: str = "editor", email: str | None = None) -> None:
        self.workspace_members.append({"workspace_id": workspace_id, "user_id": user_id, "role": role, "email": email})

    def add_subscription(self, workspace_id: str, plan_code: str = "starter", **fields) -> str:
        row = {"id": str(uuid.uuid4()), "workspace_id": workspace_id, "plan_code": plan_code, "status": "trialing"}
        row.update(fields)
        self.subscriptions[row["id"]] = row
        return row["id"]

    def add_brand_asset(self, workspace_id: str, brand_profile_id: str, kind: str, storage_key: str, **fields) -> str:
        row = {
            "id": str(uuid.uuid4()), "workspace_id": workspace_id, "brand_profile_id": brand_profile_id, "kind": kind,
            "name": storage_key.rsplit("/", 1)[-1], "storage_key": storage_key, "mime_type": None, "sha256": None,
            "font_family": None, "font_weight": None,
        }  # fmt: skip
        row.update(fields)
        self.brand_assets[row["id"]] = row
        return row["id"]

    def add_deletion_job(self, workspace_id: str, entity: str, entity_id: str, reason: str = "user_request", **fields) -> str:
        row = {
            "id": str(uuid.uuid4()), "workspace_id": workspace_id, "entity": entity, "entity_id": entity_id, "reason": reason,
            "requested_by": None, "status": "queued", "keys_deleted": [], "rows_deleted": {}, "error": None, "finished_at": None,
        }  # fmt: skip
        row.update(fields)
        self.deletion_jobs[row["id"]] = row
        return row["id"]

    def add_guest_approval(self, clip_id: str, **fields) -> str:
        row = {"id": str(uuid.uuid4()), "clip_id": clip_id, "token": uuid.uuid4().hex, "decision": None}
        row.update(fields)
        self.guest_approvals.append(row)
        return row["id"]

    def add_transcript_correction(self, source_id: str, **fields) -> str:
        row = {"id": str(uuid.uuid4()), "source_id": source_id, "from_version": 1, "word_index": 0, "old_text": "a", "new_text": "b"}
        row.update(fields)
        self.transcript_corrections.append(row)
        return row["id"]

    def add_source(self, workspace_id: str, storage_key: str, **extra) -> str:
        sid = str(uuid.uuid4())
        row = {
            "id": sid, "workspace_id": workspace_id, "storage_key": storage_key, "audio_key": None, "proxy_key": None,
            "sha256": None, "duration_s": None, "width": None, "height": None, "fps": None, "expected_speakers": None,
            "brief": {}, "status": "uploaded", "status_message": None, "title": "Test", "original_filename": "test.mp4",
            "mime_type": None, "size_bytes": None, "brand_profile_id": None,
            "temporal_workflow_id": None, "delete_after": None, "deleted_at": None,
        }  # fmt: skip
        row.update(extra)
        self.sources[sid] = row
        return sid

    def add_brand_profile(self, workspace_id: str, **fields) -> str:
        pid = str(uuid.uuid4())
        row = {
            "id": pid, "workspace_id": workspace_id, "asr_variant": "de", "brand_vocab": [], "protected_terms": [],
            "country": "AT", "address": "du", "learned_weights": None, "ci": {},
        }  # fmt: skip
        row.update(fields)
        self.brand_profiles[pid] = row
        return pid

    def add_transcript_version(self, source_id: str, words: list[dict], **fields) -> str:
        vs = [r["version"] for r in self.transcript_versions if r["source_id"] == source_id]
        row = {
            "id": str(uuid.uuid4()), "source_id": source_id, "version": (max(vs) if vs else 0) + 1, "origin": "asr",
            "asr_model_id": "dummy/model", "asr_variant": "de", "diarizer_id": None, "language": "de",
            "words": words, "stats": {},
        }  # fmt: skip
        row.update(fields)
        self.transcript_versions.append(row)
        return row["id"]

    def add_candidate(self, source_id: str, segments: list[dict], **fields) -> str:
        row = {
            "id": str(uuid.uuid4()), "source_id": source_id, "version": 1, "segments": segments,
            "start_s": min(float(x["start"]) for x in segments), "end_s": max(float(x["end"]) for x in segments),
            "rubric": {"suggested_title_card": ""}, "risk_flags": [], "human_verdict": None,
        }  # fmt: skip
        row.update(fields)
        self.candidates.append(row)
        return row["id"]

    def add_clip(self, source_id: str, candidate_id: str, platform: str, segments: list[dict], **fields) -> str:
        row = {
            "id": str(uuid.uuid4()), "source_id": source_id, "candidate_id": candidate_id, "platform": platform,
            "destination": platform, "aspect": "4:5" if platform == "linkedin" else "9:16", "composition": segments,
            "title_card": None, "ad_label": None, "ai_features": [], "speaker_positions": None, "status": "draft",
            "file_key": None, "render_plan": None, "created_at": len(self.clips),
        }  # fmt: skip
        row.update(fields)
        self.clips[row["id"]] = row
        return row["id"]

    def add_hook_version(self, clip_id: str, **fields) -> str:
        vs = [r["version"] for r in self.hook_versions if r["clip_id"] == clip_id]
        row = {
            "id": str(uuid.uuid4()), "clip_id": clip_id, "version": (max(vs) if vs else 0) + 1, "origin": "manual",
            "spoken_hook": "", "onscreen_hook": "", "pattern": None, "post_captions": {}, "cta": None,
        }  # fmt: skip
        row.update(fields)
        self.hook_versions.append(row)
        return row["id"]

    @staticmethod
    def _insert_row(sql: str, params: tuple) -> dict:
        cols = sql.split("(", 1)[1].split(")", 1)[0].replace("\n", " ").split(",")
        row = {c.strip(): _unwrap(v) for c, v in zip(cols, params)}
        row["id"] = str(uuid.uuid4())
        return row

    @staticmethod
    def _apply_update(sql: str, params: tuple, row: dict) -> None:
        set_part = sql.split("set", 1)[1].split("where", 1)[0]
        cols = [c.split("=")[0].strip() for c in set_part.split(",")]
        for c, v in zip(cols, params[: len(cols)]):
            row[c] = _unwrap(v)

    # -- psycopg-ähnliche API ------------------------------------------------------------------
    def execute(self, sql: str, params=None):
        params = tuple(params or ())
        self.statements.append((sql, params))
        q = " ".join(sql.split()).lower()
        if q.startswith("insert into pipeline_events"):
            source_id, step, status, progress, message, payload = params
            self.events.append({"source_id": source_id, "step": step, "status": status, "progress": progress, "message": message, "payload": _unwrap(payload)})
            return FakeCursor([])
        if q.startswith("insert into job_costs"):
            cols = sql.split("(", 1)[1].split(")", 1)[0].replace("\n", " ").split(",")
            self.job_costs.append({c.strip(): v for c, v in zip(cols, params)})
            return FakeCursor([])
        if q.startswith("insert into transcript_versions"):
            cols = sql.split("(", 1)[1].split(")", 1)[0].replace("\n", " ").split(",")
            row = {c.strip(): _unwrap(v) for c, v in zip(cols, params)}
            row["id"] = str(uuid.uuid4())
            self.transcript_versions.append(row)
            return FakeCursor([(row["id"],)])
        if q.startswith("select coalesce(max(version), 0) from transcript_versions"):
            vs = [r["version"] for r in self.transcript_versions if r["source_id"] == params[0]]
            return FakeCursor([(max(vs) if vs else 0,)])
        if q.startswith("select id, version, words from transcript_versions"):
            rows = sorted((r for r in self.transcript_versions if r["source_id"] == params[0]), key=lambda r: -r["version"])
            return FakeCursor([(r["id"], r["version"], r["words"]) for r in rows[:1]])
        if q.startswith("insert into candidates"):
            cols = sql.split("(", 1)[1].split(")", 1)[0].replace("\n", " ").split(",")
            row = {c.strip(): _unwrap(v) for c, v in zip(cols, params)}
            row["id"] = str(uuid.uuid4())
            row.setdefault("human_verdict", None)
            self.candidates.append(row)
            return FakeCursor([(row["id"],)])
        if q.startswith("delete from candidates where source_id = %s and human_verdict is null"):
            self.candidates = [c for c in self.candidates if not (c["source_id"] == params[0] and c.get("human_verdict") is None)]
            return FakeCursor([])
        if q.startswith("update sources set"):
            set_part = sql.split("set", 1)[1].split("where", 1)[0]
            cols = [c.split("=")[0].strip() for c in set_part.split(",")]
            sid = params[-1]
            if sid in self.sources:
                for c, v in zip(cols, params[: len(cols)]):
                    self.sources[sid][c] = _unwrap(v)
                    if c == "status":
                        self.status_history.append((sid, _unwrap(v)))
            return FakeCursor([])
        if q.startswith("select id, source_id, segments, rubric, risk_flags, start_s, end_s from candidates"):
            c = next((c for c in self.candidates if c["id"] == params[0]), None)
            if c is None:
                return FakeCursor([])
            return FakeCursor([(c["id"], c["source_id"], c["segments"], c.get("rubric"), c.get("risk_flags"), c.get("start_s"), c.get("end_s"))])
        if q.startswith("select p.gender_mode"):
            src = self.sources.get(params[0])
            if src is None:
                return FakeCursor([])
            p = self.brand_profiles.get(src.get("brand_profile_id")) or {}
            return FakeCursor([(
                p.get("gender_mode"), p.get("banned_phrases"), p.get("tone_adjectives"), p.get("default_platform"),
                p.get("caption_preset"), p.get("caption_style"), src.get("rights_status"), src.get("source_owner"),
                src.get("source_title"), src.get("source_url"), p.get("ci"),
            )])  # fmt: skip
        if q.startswith("select id, status, aspect, composition, title_card, ad_label, ai_features, speaker_positions, file_key from clips"):
            if "where id = %s" in q:  # gezielter Render eines Clips (Ziel "plattform:clip_id")
                rows = [c for c in self.clips.values() if c["id"] == params[0] and c["candidate_id"] == params[1] and c["platform"] == params[2]]
            else:
                rows = sorted((c for c in self.clips.values() if c["candidate_id"] == params[0] and c["platform"] == params[1]), key=lambda c: -c["created_at"])
            return FakeCursor([(c["id"], c["status"], c["aspect"], c["composition"], c["title_card"], c["ad_label"], c["ai_features"], c["speaker_positions"], c["file_key"]) for c in rows[:1]])
        if q.startswith("insert into clips"):
            row = self._insert_row(sql, params)
            row.setdefault("ai_features", [])
            row.setdefault("speaker_positions", None)
            row.setdefault("file_key", None)
            row.setdefault("status", "draft")
            row["created_at"] = len(self.clips)
            self.clips[row["id"]] = row
            return FakeCursor([(row["id"],)])
        if q.startswith("update clips set"):
            cid = params[-1]
            if cid in self.clips:
                self._apply_update(sql, params, self.clips[cid])
            return FakeCursor([])
        if q.startswith("select id, version, origin, spoken_hook, onscreen_hook, pattern, post_captions, cta from hook_versions"):
            rows = sorted((r for r in self.hook_versions if r["clip_id"] == params[0]), key=lambda r: -r["version"])
            return FakeCursor([(r["id"], r["version"], r["origin"], r["spoken_hook"], r["onscreen_hook"], r["pattern"], r["post_captions"], r["cta"]) for r in rows[:1]])
        if q.startswith("insert into hook_versions"):
            row = self._insert_row(sql, params)
            self.hook_versions.append(row)
            return FakeCursor([(row["id"],)])
        if q.startswith("select coalesce(max(version), 0) from caption_versions"):
            vs = [r["version"] for r in self.caption_versions if r["clip_id"] == params[0]]
            return FakeCursor([(max(vs) if vs else 0,)])
        if q.startswith("insert into caption_versions"):
            row = self._insert_row(sql, params)
            self.caption_versions.append(row)
            return FakeCursor([(row["id"],)])
        handled = self._execute_phase4(sql, q, params)
        if handled is not None:
            return handled
        handled = self._execute_phase5(sql, q, params)
        if handled is not None:
            return handled
        handled = self._execute_local_worker(q, params)
        if handled is not None:
            return handled
        if q.startswith("select s.id, s.workspace_id"):
            sid = params[0]
            s = self.sources.get(sid)
            if s is None:
                return FakeCursor([])
            p = self.brand_profiles.get(s.get("brand_profile_id")) or {}
            w = self.workspaces[s["workspace_id"]]
            row = (
                s["id"], s["workspace_id"], s["storage_key"], s["audio_key"], s["proxy_key"], s["sha256"], s["duration_s"],
                s["width"], s["height"], s["fps"], s["expected_speakers"], s["brief"], s["status"], s["title"],
                s["original_filename"], s["mime_type"], s["size_bytes"], s.get("brand_profile_id"),
                p.get("asr_variant"), p.get("brand_vocab"), p.get("protected_terms"), p.get("country"), p.get("address"),
                p.get("learned_weights"), w["tier"], w["allow_us_subprocessors"],
            )  # fmt: skip
            return FakeCursor([row])
        raise AssertionError(f"FakeDB kennt diese Abfrage nicht: {sql[:80]}")

    # -- Phase 4: Löschung, Verbrauch, Marken-Assets ------------------------------------------
    def _execute_phase4(self, sql: str, q: str, params: tuple):
        # Verbrauch
        if q.startswith("select p.code, p.included_hours, p.overage_eur_per_hour from subscriptions"):
            sub = next((s for s in self.subscriptions.values() if s["workspace_id"] == params[0]), None)
            plan = self.plans.get(sub["plan_code"]) if sub else None
            return FakeCursor([(plan["code"], plan["included_hours"], plan["overage_eur_per_hour"])] if plan else [])
        if q.startswith("select code, included_hours, overage_eur_per_hour from plans"):
            plan = self.plans.get(params[0])
            return FakeCursor([(plan["code"], plan["included_hours"], plan["overage_eur_per_hour"])] if plan else [])
        if q.startswith("select id, included_minutes, used_source_minutes, overage_minutes from usage_periods"):
            rows = [r for r in self.usage_periods.values() if r["workspace_id"] == params[0] and r["period_start"] == params[1]]
            return FakeCursor([(r["id"], r["included_minutes"], r["used_source_minutes"], r["overage_minutes"]) for r in rows])
        if q.startswith("insert into usage_periods"):
            row = self._insert_row(sql, params)
            for k, v in (("used_source_minutes", 0.0), ("render_count", 0), ("llm_input_tokens", 0), ("llm_output_tokens", 0), ("overage_minutes", 0.0), ("overage_eur", 0.0)):
                row.setdefault(k, v)
            self.usage_periods[row["id"]] = row
            return FakeCursor([(row["id"],)])
        if q.startswith("update usage_periods set render_count = render_count + 1"):
            self.usage_periods[params[0]]["render_count"] += 1
            return FakeCursor([], rowcount=1)
        if q.startswith("update usage_periods set llm_input_tokens = llm_input_tokens + %s"):
            row = self.usage_periods[params[2]]
            row["llm_input_tokens"] += int(params[0])
            row["llm_output_tokens"] += int(params[1])
            return FakeCursor([], rowcount=1)
        if q.startswith("update usage_periods set"):
            pid = params[-1]
            if pid in self.usage_periods:
                self._apply_update(sql, params, self.usage_periods[pid])
            return FakeCursor([], rowcount=1)
        # Marken-Assets
        if q.startswith("select id, kind, name, storage_key, mime_type, sha256, font_family, font_weight from brand_assets"):
            a = self.brand_assets.get(params[0])
            return FakeCursor([(a["id"], a["kind"], a["name"], a["storage_key"], a["mime_type"], a["sha256"], a["font_family"], a["font_weight"])] if a else [])
        if q.startswith("select id, brand_profile_id, storage_key from brand_assets where brand_profile_id"):
            rows = [a for a in self.brand_assets.values() if a["brand_profile_id"] == params[0]]
            return FakeCursor([(a["id"], a["brand_profile_id"], a["storage_key"]) for a in rows])
        if q.startswith("select id, brand_profile_id, storage_key from brand_assets where workspace_id"):
            rows = [a for a in self.brand_assets.values() if a["workspace_id"] == params[0]]
            return FakeCursor([(a["id"], a["brand_profile_id"], a["storage_key"]) for a in rows])
        if q.startswith("delete from brand_assets where brand_profile_id"):
            return self._delete_dict(self.brand_assets, lambda a: a["brand_profile_id"] == params[0])
        if q.startswith("delete from brand_assets where workspace_id"):
            return self._delete_dict(self.brand_assets, lambda a: a["workspace_id"] == params[0])
        # Löschaufträge und Audit
        if q.startswith("select id, workspace_id, entity, entity_id, reason, requested_by, status from deletion_jobs"):
            j = self.deletion_jobs.get(params[0])
            return FakeCursor([(j["id"], j["workspace_id"], j["entity"], j["entity_id"], j["reason"], j["requested_by"], j["status"])] if j else [])
        if q.startswith("insert into deletion_jobs"):
            row = self._insert_row(sql, params)
            for k, v in (("keys_deleted", []), ("rows_deleted", {}), ("error", None), ("finished_at", None)):
                row.setdefault(k, v)
            self.deletion_jobs[row["id"]] = row
            return FakeCursor([(row["id"],)])
        if q.startswith("update deletion_jobs set"):
            jid = params[-1]
            if jid in self.deletion_jobs:
                self._apply_update(sql, params, self.deletion_jobs[jid])
            return FakeCursor([], rowcount=1)
        if q.startswith("insert into audit_log"):
            self.audit_log.append(self._insert_row(sql, params))
            return FakeCursor([], rowcount=1)
        # Quellen und Clips für die Löschung
        if q.startswith("select id, workspace_id, storage_key, audio_key, proxy_key, temporal_workflow_id, status from sources"):
            s = self.sources.get(params[0])
            return FakeCursor([(s["id"], s["workspace_id"], s["storage_key"], s["audio_key"], s["proxy_key"], s.get("temporal_workflow_id"), s["status"])] if s else [])
        if q.startswith("select workspace_id from sources where id"):
            s = self.sources.get(params[0])
            return FakeCursor([(s["workspace_id"],)] if s else [])
        if q.startswith("select id from sources where workspace_id = %s and status <> 'deleted'"):
            return FakeCursor([(s["id"],) for s in self.sources.values() if s["workspace_id"] == params[0] and s["status"] != "deleted"])
        if q.startswith("select id from sources where delete_after < %s"):
            open_ids = {j["entity_id"] for j in self.deletion_jobs.values() if j["entity"] == "source" and j["status"] in ("queued", "running")}
            rows = [s for s in self.sources.values() if s.get("delete_after") and s["delete_after"] < params[0] and s["status"] != "deleted" and s["id"] not in open_ids]
            rows.sort(key=lambda s: s["delete_after"])
            return FakeCursor([(s["id"],) for s in rows[: int(params[1])]])
        if q.startswith("select id from workspaces where deletion_requested_at is not null"):
            open_ids = {j["entity_id"] for j in self.deletion_jobs.values() if j["entity"] == "workspace" and j["status"] in ("queued", "running")}
            rows = [w for w in self.workspaces.values() if w.get("deletion_requested_at") and w.get("deletion_scheduled_for") and w["deletion_scheduled_for"] < params[0] and w["id"] not in open_ids]
            rows.sort(key=lambda w: w["deletion_scheduled_for"])
            return FakeCursor([(w["id"],) for w in rows[: int(params[1])]])
        if q.startswith("select id, file_key, srt_key, vtt_key, poster_key from clips where source_id"):
            rows = [c for c in self.clips.values() if c["source_id"] == params[0]]
            return FakeCursor([(c["id"], c.get("file_key"), c.get("srt_key"), c.get("vtt_key"), c.get("poster_key")) for c in rows])
        if q.startswith("select id, source_id, file_key, srt_key, vtt_key, poster_key, status from clips where id"):
            c = self.clips.get(params[0])
            return FakeCursor([(c["id"], c["source_id"], c.get("file_key"), c.get("srt_key"), c.get("vtt_key"), c.get("poster_key"), c["status"])] if c else [])
        if q.startswith("select ass_key, srt_key from caption_versions where clip_id"):
            return FakeCursor([(r.get("ass_key"), r.get("srt_key")) for r in self.caption_versions if r["clip_id"] == params[0]])
        if q.startswith("select payload from pipeline_events where source_id"):
            return FakeCursor([(e["payload"],) for e in self.events if e["source_id"] == params[0] and e["payload"] is not None])
        if q.startswith("delete from "):
            return self._delete_rows(q, params)
        return None

    # -- Phase 5: Outbox, Webhooks, Publishing, Decision Log, Lernen, Wochenreport --------------
    def _execute_phase5(self, sql: str, q: str, params: tuple):
        # Outbox und Webhooks
        if q.startswith("insert into outbox_events"):
            row = self._insert_row(sql, params)
            row["id"] = len(self.outbox_events) + 1
            row.setdefault("processed_at", None)
            row["created_at"] = _dt(len(self.outbox_events))
            self.outbox_events.append(row)
            return FakeCursor([(row["id"],)])
        if q.startswith("select workspace_id, title, status_message from sources where id"):
            src = self.sources.get(params[0])
            return FakeCursor([(src["workspace_id"], src["title"], src.get("status_message"))] if src else [])
        if q.startswith("select c.source_id, c.platform, c.duration_s, c.render_error, s.workspace_id, s.title from clips c"):
            c = self.clips.get(params[0])
            if c is None:
                return FakeCursor([])
            src = self.sources[c["source_id"]]
            return FakeCursor([(c["source_id"], c["platform"], c.get("duration_s"), c.get("render_error"), src["workspace_id"], src["title"])])
        if q.startswith("select id, workspace_id, event, entity, entity_id, payload, created_at from outbox_events"):
            rows = [e for e in self.outbox_events if e.get("processed_at") is None][: int(params[0])]
            return FakeCursor([(e["id"], e["workspace_id"], e["event"], e["entity"], e["entity_id"], e["payload"], e["created_at"]) for e in rows])
        if q.startswith("update outbox_events set"):
            for e in self.outbox_events:
                if e["id"] == params[-1]:
                    self._apply_update(sql, params, e)
            return FakeCursor([], rowcount=1)
        if q.startswith("select id, events from webhook_endpoints where workspace_id"):
            rows = [e for e in self.webhook_endpoints.values() if e["workspace_id"] == params[0] and e["active"]]
            return FakeCursor([(e["id"], e["events"]) for e in rows])
        if q.startswith("insert into webhook_deliveries"):
            row = self._insert_row(sql, params)
            row.setdefault("response_code", None)
            row.setdefault("error", None)
            row.setdefault("delivered_at", None)
            row["created_at"] = _dt(len(self.webhook_deliveries))
            self.webhook_deliveries[row["id"]] = row
            return FakeCursor([(row["id"],)])
        if q.startswith("select d.id, d.endpoint_id, d.event, d.payload, d.attempt, d.status, d.created_at, e.url, e.secret, e.active, e.workspace_id from webhook_deliveries d"):
            d = self.webhook_deliveries.get(params[0])
            if d is None:
                return FakeCursor([])
            e = self.webhook_endpoints[d["endpoint_id"]]
            return FakeCursor([(d["id"], d["endpoint_id"], d["event"], d["payload"], d["attempt"], d["status"], d["created_at"], e["url"], e["secret"], e["active"], e["workspace_id"])])
        if q.startswith("select id from webhook_deliveries where status = 'pending' and next_attempt_at <= %s"):
            rows = [d for d in self.webhook_deliveries.values() if d["status"] == "pending" and d["next_attempt_at"] <= params[0]]
            rows.sort(key=lambda d: d["next_attempt_at"])
            return FakeCursor([(d["id"],) for d in rows[: int(params[1])]])
        if q.startswith("update webhook_deliveries set"):
            d = self.webhook_deliveries.get(params[-1])
            if d is not None:
                self._apply_update(sql, params, d)
            return FakeCursor([], rowcount=1)
        # Publishing
        if q.startswith("select p.id, coalesce(p.workspace_id, s.workspace_id), p.clip_id, p.connection_id"):
            p = self.publications.get(params[0])
            if p is None:
                return FakeCursor([])
            c = self.clips[p["clip_id"]]
            src = self.sources[c["source_id"]]
            return FakeCursor([(
                p["id"], p.get("workspace_id") or src["workspace_id"], p["clip_id"], p.get("connection_id"), p["platform"], p["status"],
                p.get("scheduled_for"), p.get("external_id"), p.get("external_url"), p.get("published_at"), p.get("metrics"), p.get("error"),
                c["status"], c.get("candidate_id"), c.get("guest_approval_required", False), c["source_id"], src.get("brand_profile_id"),
            )])  # fmt: skip
        if q.startswith("select human_verdict from candidates where id"):
            c = next((c for c in self.candidates if c["id"] == params[0]), None)
            return FakeCursor([(c.get("human_verdict"),)] if c else [])
        if q.startswith("select decision from guest_approvals where clip_id"):
            rows = [g for g in self.guest_approvals if g["clip_id"] == params[0]]
            return FakeCursor([(rows[-1].get("decision"),)] if rows else [])
        if q.startswith("update publications set"):
            p = self.publications.get(params[-1])
            if p is not None:
                self._apply_update(sql, params, p)
            return FakeCursor([], rowcount=1)
        if q.startswith("select id from performance_feedback where publication_id = %s and metric_window = %s"):
            rows = [f for f in self.performance_feedback if f["publication_id"] == params[0] and f["metric_window"] == params[1]]
            return FakeCursor([(f["id"],) for f in rows[:1]])
        if q.startswith("insert into performance_feedback"):
            row = self._insert_row(sql, params)
            row.setdefault("fetched_at", len(self.performance_feedback))
            self.performance_feedback.append(row)
            return FakeCursor([(row["id"],)])
        if q.startswith("update performance_feedback set"):
            for f in self.performance_feedback:
                if f["id"] == params[-1]:
                    self._apply_update(sql, params, f)
            return FakeCursor([], rowcount=1)
        if q.startswith("select f.views, f.follows_per_1k, f.saves_per_1k from performance_feedback f join publications p"):
            ws, platform, conn_id, pub_id, limit = params
            rows = []
            for f in self.performance_feedback:
                p = self.publications.get(f["publication_id"]) if f.get("publication_id") else None
                if f["workspace_id"] != ws or f["platform"] != platform or f["metric_window"] != "7d" or f["publication_id"] == pub_id:
                    continue
                if p is None or str(p.get("connection_id") or "") != conn_id:
                    continue
                rows.append(f)
            rows.sort(key=lambda f: f["fetched_at"], reverse=True)
            return FakeCursor([(f["views"], f["follows_per_1k"], f["saves_per_1k"]) for f in rows[: int(limit)]])
        # Decision Log
        if q.startswith("insert into decision_log"):
            row = self._insert_row(sql, params)
            row["created_at"] = _dt(len(self.decision_log))
            self.decision_log.append(row)
            return FakeCursor([(row["id"],)])
        if q.startswith("select features from decision_log where candidate_id = %s and decision_type = 'candidate_scored'"):
            rows = [d for d in self.decision_log if d.get("candidate_id") == params[0] and d["decision_type"] == "candidate_scored"]
            return FakeCursor([(rows[-1]["features"],)] if rows else [])
        if q.startswith("select chosen from decision_log where clip_id = %s and decision_type = 'hook_selected'"):
            rows = [d for d in self.decision_log if d.get("clip_id") == params[0] and d["decision_type"] == "hook_selected"]
            return FakeCursor([(rows[-1]["chosen"],)] if rows else [])
        if q.startswith("select decision_type, features, chosen from decision_log where brand_profile_id"):
            rows = [d for d in self.decision_log if d.get("brand_profile_id") == params[0] and d["decision_type"] in ("hook_variant_shown", "hook_selected")]
            return FakeCursor([(d["decision_type"], d["features"], d["chosen"]) for d in rows])
        # Lernen
        if q.startswith("select c.id, c.rubric, c.human_verdict from candidates c join sources s"):
            rows = [c for c in self.candidates if c.get("human_verdict") and (self.sources.get(c["source_id"]) or {}).get("brand_profile_id") == params[0]]
            return FakeCursor([(c["id"], c.get("rubric"), c["human_verdict"]) for c in rows])
        if q.startswith("select cl.candidate_id, max(f.reward) from performance_feedback f join clips cl"):
            best: dict[str, float] = {}
            for f in self.performance_feedback:
                cl = self.clips.get(f.get("clip_id") or "")
                if cl is None or f["metric_window"] != "7d" or f.get("reward") is None or not cl.get("candidate_id"):
                    continue
                if (self.sources.get(cl["source_id"]) or {}).get("brand_profile_id") != params[0]:
                    continue
                best[cl["candidate_id"]] = max(best.get(cl["candidate_id"], float("-inf")), float(f["reward"]))
            return FakeCursor(list(best.items()))
        if q.startswith("select f.clip_id, f.reward from performance_feedback f join clips cl"):
            rows = []
            for f in self.performance_feedback:
                cl = self.clips.get(f.get("clip_id") or "")
                if cl is None or f["metric_window"] != "7d" or f.get("reward") is None:
                    continue
                if (self.sources.get(cl["source_id"]) or {}).get("brand_profile_id") != params[0]:
                    continue
                rows.append((f["clip_id"], f["reward"]))
            return FakeCursor(rows)
        if q.startswith("select workspace_id from brand_profiles where id"):
            p = self.brand_profiles.get(params[0])
            return FakeCursor([(p["workspace_id"],)] if p else [])
        if q.startswith("update brand_profiles set"):
            p = self.brand_profiles.get(params[-1])
            if p is not None:
                self._apply_update(sql, params, p)
            return FakeCursor([], rowcount=1)
        if q.startswith("select shown, chosen, reward_sum, reward_n from hook_pattern_stats where brand_profile_id = %s and pattern = %s"):
            r = self.hook_pattern_stats.get((params[0], params[1]))
            return FakeCursor([(r["shown"], r["chosen"], r["reward_sum"], r["reward_n"])] if r else [])
        if q.startswith("select pattern, shown, chosen, reward_sum, reward_n from hook_pattern_stats where brand_profile_id"):
            rows = [r for (b, _p), r in self.hook_pattern_stats.items() if b == params[0]]
            return FakeCursor([(r["pattern"], r["shown"], r["chosen"], r["reward_sum"], r["reward_n"]) for r in rows])
        if q.startswith("insert into hook_pattern_stats"):
            row = self._insert_row(sql, params)
            self.hook_pattern_stats[(row["brand_profile_id"], row["pattern"])] = row
            return FakeCursor([], rowcount=1)
        if q.startswith("update hook_pattern_stats set"):
            r = self.hook_pattern_stats.get((params[-2], params[-1]))
            if r is not None:
                self._apply_update(sql, params, r)
            return FakeCursor([], rowcount=1)
        if q.startswith("select pattern from hook_versions where clip_id"):
            rows = sorted((r for r in self.hook_versions if r["clip_id"] == params[0]), key=lambda r: -r["version"])
            return FakeCursor([(rows[0].get("pattern"),)] if rows else [])
        if q.startswith("select distinct s.brand_profile_id from sources s join candidates c"):
            ids = []
            for c in self.candidates:
                src = self.sources.get(c["source_id"]) or {}
                if c.get("human_verdict") and src.get("brand_profile_id") and src["brand_profile_id"] not in ids:
                    ids.append(src["brand_profile_id"])
            return FakeCursor([(i,) for i in ids])
        # Wochenreport
        if q.startswith("select f.clip_id, f.publication_id, f.platform, f.views, f.follows_per_1k, f.saves_per_1k, f.reward from performance_feedback f"):
            ws, start, end = params
            rows = [f for f in self.performance_feedback if f["workspace_id"] == ws and f["metric_window"] == "7d" and f.get("clip_id") and _in_window(f["fetched_at"], start, end)]
            return FakeCursor([(f["clip_id"], f["publication_id"], f["platform"], f["views"], f["follows_per_1k"], f["saves_per_1k"], f["reward"]) for f in rows])
        if q.startswith("select c.title_card, c.platform, c.candidate_id, c.duration_s, s.title from clips c"):
            c = self.clips.get(params[0])
            if c is None:
                return FakeCursor([])
            src = self.sources[c["source_id"]]
            return FakeCursor([(c.get("title_card"), c["platform"], c.get("candidate_id"), c.get("duration_s"), src["title"])])
        if q.startswith("select id from weekly_reports where workspace_id = %s and week_start = %s"):
            rows = [r for r in self.weekly_reports.values() if r["workspace_id"] == params[0] and r["week_start"] == params[1]]
            return FakeCursor([(r["id"],) for r in rows[:1]])
        if q.startswith("insert into weekly_reports"):
            row = self._insert_row(sql, params)
            row.setdefault("sent_at", None)
            self.weekly_reports[row["id"]] = row
            return FakeCursor([(row["id"],)])
        if q.startswith("update weekly_reports set"):
            r = self.weekly_reports.get(params[-1])
            if r is not None:
                self._apply_update(sql, params, r)
            return FakeCursor([], rowcount=1)
        if q.startswith("select coalesce(u.email, m.email) from workspace_members m"):
            rows = []
            for m in self.workspace_members:
                if m["workspace_id"] != params[0] or m["role"] not in ("owner", "admin"):
                    continue
                u = self.users.get(m.get("user_id") or "")
                rows.append(((u or {}).get("email") or m.get("email"),))
            return FakeCursor(rows)
        if q.startswith("select id, name from workspaces where weekly_report_enabled"):
            return FakeCursor([(w["id"], w.get("name")) for w in self.workspaces.values() if w.get("weekly_report_enabled", True)])
        return None

    # -- Lokaler Testmodus (local_worker.py): Warteschlangen per Status ------------------------
    def _execute_local_worker(self, q: str, params: tuple):
        if q.startswith("select id from sources where status = 'uploaded'"):
            rows = [s for s in self.sources.values() if s["status"] == "uploaded"]
            rows.sort(key=lambda s: s.get("created_at", 0))
            return FakeCursor([(s["id"],) for s in rows[: int(params[0])]])
        if q.startswith("select status, status_message from sources where id"):
            s = self.sources.get(params[0])
            return FakeCursor([(s["status"], s.get("status_message"))] if s else [])
        if q.startswith("select c.id, c.candidate_id, c.platform from clips c join candidates k"):
            accepted = {c["id"] for c in self.candidates if c.get("human_verdict") == "accepted"}
            rows = [c for c in self.clips.values() if c["status"] == "draft" and c.get("candidate_id") in accepted]
            rows.sort(key=lambda c: c["created_at"])
            return FakeCursor([(c["id"], c["candidate_id"], c["platform"]) for c in rows[: int(params[0])]])
        if q.startswith("select id from deletion_jobs where status = 'queued'"):
            rows = [j for j in self.deletion_jobs.values() if j["status"] == "queued"]
            return FakeCursor([(j["id"],) for j in rows[: int(params[0])]])
        if q.startswith("select id from publications where status = 'scheduled'"):
            rows = [p for p in self.publications.values() if p["status"] == "scheduled" and p.get("scheduled_for") is not None and p["scheduled_for"] <= params[0]]
            rows.sort(key=lambda p: p["scheduled_for"])
            return FakeCursor([(p["id"],) for p in rows[: int(params[1])]])
        return None

    @staticmethod
    def _delete_dict(table: dict, pred) -> FakeCursor:
        gone = [k for k, v in table.items() if pred(v)]
        for k in gone:
            del table[k]
        return FakeCursor([], rowcount=len(gone))

    def _delete_rows(self, q: str, params: tuple) -> FakeCursor | None:
        sid = params[0]
        clip_ids = {c["id"] for c in self.clips.values() if c["source_id"] == sid}
        by_clip = "where clip_id in (select id from clips where source_id = %s)" in q
        by_clip_id = "where clip_id = %s" in q

        def _clip_pred(r):
            return (r["clip_id"] in clip_ids) if by_clip else (r["clip_id"] == sid)

        for table in ("caption_versions", "hook_versions", "guest_approvals"):
            if q.startswith(f"delete from {table} ") and (by_clip or by_clip_id):
                rows = getattr(self, table)
                kept = [r for r in rows if not _clip_pred(r)]
                n = len(rows) - len(kept)
                setattr(self, table, kept)
                return FakeCursor([], rowcount=n)
        if q.startswith("delete from clips where source_id = %s"):
            return self._delete_dict(self.clips, lambda c: c["source_id"] == sid)
        for table in ("candidates", "transcript_corrections", "transcript_versions"):
            if q.startswith(f"delete from {table} where source_id = %s"):
                rows = getattr(self, table)
                kept = [r for r in rows if r["source_id"] != sid]
                n = len(rows) - len(kept)
                setattr(self, table, kept)
                return FakeCursor([], rowcount=n)
        if q.startswith("delete from pipeline_events where source_id = %s"):
            kept = [e for e in self.events if e["source_id"] != sid]
            n = len(self.events) - len(kept)
            self.events = kept
            return FakeCursor([], rowcount=n)
        return None

    def close(self):
        self.closed = True

    # -- Auswertung ----------------------------------------------------------------------------
    def events_for(self, step: str) -> list[dict]:
        return [e for e in self.events if e["step"] == step]

    def statuses(self, step: str) -> list[str]:
        return [e["status"] for e in self.events_for(step)]


def _dt(n: int):
    """Deterministischer Zeitstempel für Fake-Zeilen (Reihenfolge = Einfügereihenfolge)."""
    from datetime import UTC, datetime, timedelta

    return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=n)


def _in_window(value, start, end) -> bool:
    """Fake-``fetched_at`` kann ein Zähler oder ein datetime sein; Zähler gelten als „in dieser Woche“."""
    from datetime import datetime

    if isinstance(value, datetime):
        return start <= value < end
    return True


def _unwrap(v):
    """psycopg Jsonb-Wrapper zurück zum Python-Wert."""
    if v is None:
        return None
    obj = getattr(v, "obj", None)
    return obj if obj is not None else v


@pytest.fixture
def fake_db() -> FakeDB:
    return FakeDB()


@pytest.fixture
def fake_context(fake_db, local_store, tmp_path):
    """Activity-Kontext ohne Postgres/S3."""
    from chopstr_worker.activities import common

    ctx = common.Context(conn=fake_db, store=local_store, settings=config.settings(), work_dir=tmp_path / "work")
    ctx.work_dir.mkdir(parents=True, exist_ok=True)
    common.set_context_factory(lambda: ctx)
    yield ctx
    common._OVERRIDE.clear()


def make_test_video(path: Path, seconds: float = 3.0, with_video: bool = True) -> Path:
    """Erzeugt per ffmpeg lavfi ein kleines Testvideo mit Ton (Sinus 440 Hz)."""
    import subprocess

    cmd = ["ffmpeg", "-y", "-nostdin", "-v", "error"]
    if with_video:
        cmd += ["-f", "lavfi", "-i", f"testsrc=size=640x360:rate=25:duration={seconds}"]
    cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}"]
    if with_video:
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast"]
    cmd += ["-c:a", "aac", "-shortest", str(path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return path
