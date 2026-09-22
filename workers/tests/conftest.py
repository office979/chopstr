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
            "id": wid, "tier": tier, "allow_us_subprocessors": False,
            "deletion_requested_at": None, "deletion_scheduled_for": None,
        }  # fmt: skip
        row.update(fields)
        self.workspaces[wid] = row
        return wid

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
                s["original_filename"], s["mime_type"], s["size_bytes"],
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
