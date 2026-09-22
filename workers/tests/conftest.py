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
    def __init__(self, rows):
        self.rows = rows

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
        self.status_history: list[tuple[str, str]] = []
        self.statements: list[tuple[str, tuple]] = []
        self.closed = False

    # -- Testhelfer ----------------------------------------------------------------------------
    def add_workspace(self, tier: str = "standard") -> str:
        wid = str(uuid.uuid4())
        self.workspaces[wid] = {"id": wid, "tier": tier, "allow_us_subprocessors": False}
        return wid

    def add_source(self, workspace_id: str, storage_key: str, **extra) -> str:
        sid = str(uuid.uuid4())
        row = {
            "id": sid, "workspace_id": workspace_id, "storage_key": storage_key, "audio_key": None, "proxy_key": None,
            "sha256": None, "duration_s": None, "width": None, "height": None, "fps": None, "expected_speakers": None,
            "brief": {}, "status": "uploaded", "status_message": None, "title": "Test", "original_filename": "test.mp4",
            "mime_type": None, "size_bytes": None, "brand_profile_id": None,
        }  # fmt: skip
        row.update(extra)
        self.sources[sid] = row
        return sid

    def add_brand_profile(self, workspace_id: str, **fields) -> str:
        pid = str(uuid.uuid4())
        row = {
            "id": pid, "workspace_id": workspace_id, "asr_variant": "de", "brand_vocab": [], "protected_terms": [],
            "country": "AT", "address": "du", "learned_weights": None,
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
