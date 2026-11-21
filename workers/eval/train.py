"""Trainings-Workflow (T2): ``python -m eval.train <befehl>`` im Ordner ``workers``.

Läuft ohne Postgres und ohne Temporal direkt über die Pipeline-Funktionen. Alle Zwischenergebnisse (Audio, Proxy,
Transkript, Heatmap, Ereignisse, Modellantworten) liegen im Cache ``.local/eval-cache/<hash>/`` (gitignored). Im Repo
stehen nur Job-Dateien (Metadaten) und Kennzahlen (``eval/results/training/history.jsonl``), nie Medien und nie
Transkripte Dritter.

Befehle:

  gold validate|stats      Gold-Set prüfen bzw. zählen (``eval/gold``)
  job create               Job-Datei unter ``eval/jobs/`` anlegen (Quelle, Briefing, Gold-IDs)
  run --job                Ingest, ASR (oder vorhandenes Transkript), Heatmap, MM-Scan, Engine, Copy; ``--render`` optional
  compare --run            Momenttreffer gegen Gold, Recall/Precision@K, Grenzfehler, Richter (Haiku, Eskalation Sonnet)
  scorecard --run          Markdown und JSON je Lauf, Verlauf in ``history.jsonl``
  export --format          JSONL für Ranking (``ranking``) oder Präferenzpaare (``preferences``)
  feed --run               Ergebnisse in die Lernschleife (Datei-Ablage oder ``--db``, nie Port 5499 oder DB ``chopstr``)

Modelle kommen aus ENV (``LLM_PROVIDER``, ``CHOPSTR_MODEL_*``, ``CHOPSTR_MM_PROVIDER``) oder ``--provider`` und
``--mm-provider``. Ohne Key: ``--provider local-heuristic`` (kein Modell) oder ``--provider claude-cli`` (nur
Entwicklung, Abo, 0 €). Anthropic und Gemini AI Studio brauchen ``CHOPSTR_ALLOW_NON_EU_PROVIDERS=1``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from chopstr_worker import config, costlog, editorial, prompts, providers_mm
from chopstr_worker.pipeline import mm_scan, signals, story_engine, tiered_engine
from chopstr_worker.providers_llm import LLM
from chopstr_worker.residency import Tenant
from chopstr_worker.result_cache import ResultCache

from .gold import validate as gold_validate

log = logging.getLogger("chopstr.eval.train")

WORKERS = Path(__file__).resolve().parents[1]
REPO = WORKERS.parent
DEFAULT_CACHE = REPO / ".local" / "eval-cache"
JOBS_DIR = WORKERS / "eval" / "jobs"
GOLD_DIR = WORKERS / "eval" / "gold"
HISTORY = WORKERS / "eval" / "results" / "training" / "history.jsonl"
JOB_VERSION = "train_job_v1"
RUN_VERSION = "train_run_v1"
# Interner Eval-Mandant: eigenes Material und öffentliche Clips, Zustimmung zu US-Unterauftragnehmern gilt hier;
# der Opt-in CHOPSTR_ALLOW_NON_EU_PROVIDERS bleibt trotzdem Pflicht.
TENANT = Tenant(id="eval-training", tier=config.TIER_STANDARD, allow_us_subprocessors=True)
# Hauptdatenbank des lokalen Stacks: ``feed`` schreibt dort nie hin
FORBIDDEN_DB_PORT = 5499
FORBIDDEN_DB_NAME = "chopstr"
JUDGE_KEYS = ("hook", "context", "payoff", "copy")
JUDGE_THRESHOLD = 6.0
JUDGE_MARGIN = 1.0
JUDGE_DISAGREE = 2.0


# -- Hilfen -----------------------------------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel(path: Path) -> str | None:
    """Pfad relativ zum Repo, wenn er darin liegt; sonst ``None`` (Pfad und Dateiname bleiben lokal im Cache)."""
    try:
        return str(Path(path).resolve().relative_to(REPO))
    except ValueError:
        return None


def _is_url(ref: str) -> bool:
    return bool(re.match(r"^https?://", str(ref or "")))


def cache_root(args: argparse.Namespace | None = None) -> Path:
    raw = getattr(args, "cache_dir", None) or os.environ.get("CHOPSTR_EVAL_CACHE", "")
    return Path(raw) if raw else DEFAULT_CACHE


def make_llm(provider: str | None, s: config.Settings, ledger: costlog.RunLedger, cache: ResultCache, scope: str) -> Any:
    """Sprachmodell des Laufs (Tests ersetzen diese Funktion). Residency und Produktionssperre prüft ``LLM``."""
    return LLM(TENANT, s=s, provider=provider or None, cost_sink=ledger, result_cache=cache, cache_scope=scope, max_tokens=4000)


def make_mm(name: str | None, s: config.Settings, ledger: costlog.RunLedger) -> providers_mm.MMProvider:
    return providers_mm.select_mm(TENANT, s=s, provider=name or None, cost_sink=ledger)


# -- gold ---------------------------------------------------------------------------------------------------------
def _gold_path(args: argparse.Namespace) -> Path:
    if getattr(args, "gold", None):
        return Path(args.gold)
    default = GOLD_DIR / "dach_v1.json"
    if not default.is_file():
        raise SystemExit("Kein Gold-Set: --gold <datei> angeben (eval/gold/dach_v1.json fehlt noch)")
    return default


def cmd_gold(args: argparse.Namespace) -> int:
    clips = gold_validate.load_set(_gold_path(args))
    if args.action == "validate":
        rep = gold_validate.validate_set(clips)
        out = {k: rep[k] for k in ("version", "clips", "valid", "ready_for_compare", "completeness_mean")}
        out["problems"] = [{"id": r["id"], "errors": r["errors"]} for r in rep["results"] if r["errors"]]
        out["warnings"] = [{"id": r["id"], "warnings": r["warnings"]} for r in rep["results"] if r["warnings"]]
        out["incomplete"] = [{"id": r["id"], "completeness": r["completeness"], "missing_core": r["missing_core"]}
                             for r in rep["results"] if r["missing_core"]]  # fmt: skip
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 1 if out["problems"] else 0
    print(json.dumps(gold_validate.stats(clips), ensure_ascii=False, indent=2))
    return 0


# -- job ----------------------------------------------------------------------------------------------------------
def parse_brief(raw: str) -> dict[str, Any]:
    """Briefing als Text, JSON-Datei oder Textdatei; Plattform Standard ``tiktok``."""
    p = Path(raw)
    if raw and len(raw) < 1024 and p.is_file():
        text = p.read_text(encoding="utf-8")
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return {"platform": "tiktok", **data}
        except json.JSONDecodeError:
            pass
        raw = text
    return {"audience": "", "wanted": str(raw).strip(), "exclude": "", "platform": "tiktok"}


def cmd_job_create(args: argparse.Namespace) -> int:
    ref = str(args.source)
    root = cache_root(args)
    if _is_url(ref):
        sha = hashlib.sha256(ref.encode("utf-8")).hexdigest()
        source = {"kind": "url", "url": ref, "cache_ref": sha[:16]}
    else:
        path = Path(ref).expanduser()
        if not path.is_file():
            raise SystemExit(f"Quelle {ref} nicht gefunden")
        sha = sha256_file(path)
        source = {"kind": "file", "path": _rel(path), "suffix": path.suffix.lower(), "sha256": sha, "cache_ref": sha[:16],
                  "size_bytes": path.stat().st_size}
        # Der absolute Pfad bleibt lokal im Cache, nie in der Job-Datei (das Repo ist öffentlich)
        _write_json(root / sha[:16] / "source.json", {"path": str(path.resolve()), "sha256": sha})
    job_id = args.name or f"job-{datetime.now(UTC).strftime('%Y%m%d')}-{source['cache_ref'][:8]}"
    job = {
        "version": JOB_VERSION, "id": job_id, "created_at": _now(), "source": source, "brief": parse_brief(args.brief),
        "gold": [x for x in (args.gold_ids or "").split(",") if x.strip()], "gold_file": _rel(Path(args.gold_file)) if args.gold_file else None,
        "transcript": _rel(Path(args.transcript)) if args.transcript else None,
    }  # fmt: skip
    if args.transcript:
        # Transkripte Dritter gehören in den Cache, nicht ins Repo; die Job-Datei nennt nur die Referenz
        _write_json(root / source["cache_ref"] / "transcript.json", _load_words(Path(args.transcript)))
        job["transcript"] = "cache:transcript.json"
    out_dir = Path(args.out_dir) if args.out_dir else JOBS_DIR
    path = _write_json(out_dir / f"{job_id}.json", job)
    print(str(path))
    return 0


def _load_words(path: Path) -> list[dict]:
    data = _read_json(path)
    words = data.get("words") if isinstance(data, dict) else data
    if not isinstance(words, list) or not all(isinstance(w, dict) and {"text", "start", "end"} <= set(w) for w in words):
        raise SystemExit(f"{path}: erwartet eine Wortliste [{{text, start, end, speaker?}}] oder {{'words': [...]}}")
    return words


# -- run ----------------------------------------------------------------------------------------------------------
def resolve_media(job: dict, root: Path) -> Path | None:
    """Lokale Mediendatei der Quelle: Datei aus dem Job, sonst Download der URL in den Cache (yt-dlp)."""
    src = job["source"]
    cdir = root / src["cache_ref"]
    if src["kind"] == "file":
        meta = cdir / "source.json"
        cands = [Path(_read_json(meta)["path"])] if meta.is_file() else []
        if src.get("path"):
            cands.append(REPO / src["path"])
        for c in cands:
            if c.is_file():
                return c
        raise SystemExit(f"Quelldatei für Job {job['id']} nicht gefunden (Cache-Referenz {src['cache_ref']})")
    existing = sorted(cdir.glob("media.*"))
    if existing:
        return existing[0]
    ytdlp = shutil.which("yt-dlp")
    if not ytdlp:
        raise SystemExit("URL-Quelle braucht yt-dlp im PATH (Download nur in den Cache .local/eval-cache)")
    cdir.mkdir(parents=True, exist_ok=True)
    subprocess.run([ytdlp, "-f", "bv*[height<=720]+ba/b[height<=720]", "-o", str(cdir / "media.%(ext)s"), src["url"]], check=True)
    existing = sorted(cdir.glob("media.*"))
    return existing[0] if existing else None


def _transcript(job: dict, root: Path, media: Path | None, s: config.Settings, timings: dict) -> list[dict]:
    cdir = root / job["source"]["cache_ref"]
    ref = job.get("transcript")
    if ref:
        p = cdir / ref.split(":", 1)[1] if str(ref).startswith("cache:") else REPO / ref
        return _load_words(p)
    cached = cdir / "asr_words.json"
    if cached.is_file():
        return _read_json(cached)
    if media is None:
        raise SystemExit("Weder Transkript noch Medien vorhanden")
    from chopstr_worker.pipeline import transcribe as asr

    wav = _audio(media, cdir)
    if wav is None:
        raise SystemExit("ASR braucht ffmpeg für die Audiospur")
    t0 = time.monotonic()
    res = asr.transcribe(str(wav), variant=str(job.get("brief", {}).get("asr_variant") or "de"), s=s)
    timings["asr_s"] = round(time.monotonic() - t0, 2)
    words = [dict(w) for w in res.words]
    _write_json(cached, words)
    return words


def _audio(media: Path | None, cdir: Path) -> Path | None:
    if media is None or not shutil.which("ffmpeg"):
        return None
    wav = cdir / "audio16k.wav"
    if not wav.is_file():
        from chopstr_worker import ingest

        ingest.extract_audio(media, wav)
    return wav


def _annotate(words: list[dict], pol: editorial.Policy) -> list[dict]:
    """Satzgrenzen, Füllwörter und Negation wie ``fuse_and_nlp`` (ohne Diarisierung, ohne Datenbank)."""
    from chopstr_worker.pipeline import dach_nlp
    from chopstr_worker.pipeline import transcribe as asr

    words = [dict(w) for w in words]
    if all("sentence_idx" in w for w in words):
        return words
    asr.normalize_numbers(words)
    rule = dach_nlp.resolve_sentence_rule(words, editorial.sentence_rule(pol))
    max_s, max_words = editorial.sentence_limits(pol)
    dach_nlp.annotate(words, rule=rule, max_s=max_s, max_words=max_words)
    return words


def _heat(words: list[dict], wav: Path | None, cdir: Path) -> dict:
    key = cdir / ("heat_audio.json" if wav else "heat_text.json")
    if key.is_file():
        return _read_json(key)
    if wav is not None:
        audio = signals.audio_heatmap(str(wav))
        payload = signals.to_payload(signals.combined(str(wav), words, audio=audio), audio=audio)
    else:
        end = max((float(w["end"]) for w in words), default=0.0)
        payload = signals.to_payload(signals.text_heatmap(words, max(1, math.ceil(end))))
    return _write_json(key, payload) and payload


def clip_rows(report: story_engine.DetectReport) -> list[dict]:
    """Clips des Laufs als JSON (Rang nach ``total``), mit den Merkmalen für Export und Vergleich."""
    rows = []
    for rank, c in enumerate(sorted(report.candidates, key=lambda x: -x.total), start=1):
        t = c.rubric.get("tiered") or {}
        ed, pf = t.get("editor") or {}, t.get("prefilter") or {}
        rows.append({
            "rank": rank, "start_s": round(c.start_s, 3), "end_s": round(c.end_s, 3), "duration_s": round(c.end_s - c.start_s, 3),
            "first_sent": c.first_sent, "last_sent": c.last_sent, "total": c.total, "gate_passed": c.gate_passed,
            "structure": c.structure, "why": c.why, "risk_flags": c.risk_flags,
            "scores": {k: (v.get("value") if isinstance(v, dict) else v) for k, v in (c.rubric.get("scores") or {}).items()},
            "hook": ed.get("hook"), "title": ed.get("title") or c.rubric.get("suggested_title_card"), "onscreen_text": ed.get("onscreen_text"),
            "post_text": ed.get("post_text"), "editor_local": bool(ed.get("local")), "cut_inside_sentence": ed.get("cut_inside_sentence"),
            "prefilter": {k: pf.get(k) for k in ("type", "score", "rank_score", "source")},
            "events": [{k: e.get(k) for k in ("t_start", "type", "intensity", "source")} for e in (t.get("events") or [])],
            "text": c.rubric.get("text", ""),
        })  # fmt: skip
    return rows


def cmd_run(args: argparse.Namespace) -> int:
    job = _read_json(Path(args.job))
    if job.get("version") != JOB_VERSION:
        raise SystemExit(f"{args.job}: keine Job-Datei {JOB_VERSION}")
    pol = editorial.load(int(args.policy_version)) if args.policy_version else editorial.load()
    with _policy_env(pol.version):
        return _run(args, job, pol)


def _run(args: argparse.Namespace, job: dict, pol: editorial.Policy) -> int:
    s = config.settings()
    root = cache_root(args)
    cdir = root / job["source"]["cache_ref"]
    cdir.mkdir(parents=True, exist_ok=True)
    timings: dict[str, float] = {}
    t_all = time.monotonic()
    ledger = costlog.RunLedger(
        budget_eur=args.budget_eur if args.budget_eur is not None else None,
        budget_tokens=args.budget_tokens if args.budget_tokens is not None else None, s=s,
    )  # fmt: skip
    cache = ResultCache(root=cdir / "results")
    scope = str(job["source"].get("sha256") or job["source"]["cache_ref"])
    media = None
    if not (job.get("transcript") and args.skip_media):
        try:
            media = resolve_media(job, root)
        except SystemExit:
            if not job.get("transcript"):
                raise
    t0 = time.monotonic()
    words = _annotate(_transcript(job, root, media, s, timings), pol)
    wav = _audio(media, cdir)
    heat = _heat(words, wav, cdir)
    timings["prep_s"] = round(time.monotonic() - t0, 2)
    duration = float(words[-1]["end"]) if words else 0.0

    t0 = time.monotonic()
    mm = make_mm(args.mm_provider, s, ledger)
    mm_cfg = mm_scan.settings_from_policy(pol) if pol.version >= 2 else {**mm_scan.DEFAULTS}
    scan = mm_scan.scan(words, heat, mm, mm_cfg, video=media, duration_s=duration, work_dir=cdir / "mm", cache=cache,
                        cache_scope=scope, ledger=ledger, policy=pol)  # fmt: skip
    timings["mm_scan_s"] = round(time.monotonic() - t0, 2)

    t0 = time.monotonic()
    llm = make_llm(args.provider, s, ledger, cache, scope)
    report = tiered_engine.run(words, job.get("brief") or {}, job.get("brand") or {}, heat, llm, events=scan["events"],
                               ledger=ledger, policy=pol, duration_s=duration)  # fmt: skip
    timings["engine_s"] = round(time.monotonic() - t0, 2)
    run_id = args.run_id or f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
    rdir = cdir / "runs" / run_id
    clips = clip_rows(report)
    if args.render and media is not None:
        t0 = time.monotonic()
        for c in clips:
            c["render"] = render_clip(media, c, rdir / "renders")
        timings["render_s"] = round(time.monotonic() - t0, 2)
    timings["total_s"] = round(time.monotonic() - t_all, 2)
    meta = {
        "version": RUN_VERSION, "run_id": run_id, "job_id": job["id"], "job": _rel(Path(args.job)), "created_at": _now(),
        "source": {k: job["source"].get(k) for k in ("kind", "url", "path", "cache_ref", "sha256")}, "duration_s": round(duration, 2),
        "policy": editorial.policy_version(pol.version), "engine": report.engine, "provider": getattr(llm, "provider", None),
        "models": report.search.get("tiered", {}).get("models"), "mm": {k: scan[k] for k in ("source", "provider", "model", "skipped")},
        "mm_events": len(scan["events"]), "prompt_versions": report.prompt_versions, "timings": timings, "gold": job.get("gold") or [],
        "gold_file": job.get("gold_file"), "clips": len(clips), "tiered": report.search.get("tiered"), "result_cache": cache.stats(),
    }  # fmt: skip
    _write_json(rdir / "meta.json", meta)
    _write_json(rdir / "clips.json", {"version": RUN_VERSION, "clips": clips})
    _write_json(rdir / "report.json", report.to_json())
    _write_json(rdir / "costs.json", ledger.summary(duration))
    _write_json(rdir / "events.json", scan)
    print(str(rdir))
    return 0


class _policy_env:
    """Die Pipeline liest die aktive Fassung aus ``CHOPSTR_POLICY_VERSION``; für den Lauf gilt die gewählte."""

    def __init__(self, version: int):
        self.version, self.old = str(version), None

    def __enter__(self):
        self.old = os.environ.get(editorial.POLICY_VERSION_ENV)
        os.environ[editorial.POLICY_VERSION_ENV] = self.version
        prompts.clear_cache()

    def __exit__(self, *exc):
        if self.old is None:
            os.environ.pop(editorial.POLICY_VERSION_ENV, None)
        else:
            os.environ[editorial.POLICY_VERSION_ENV] = self.old
        prompts.clear_cache()


def render_clip(media: Path, clip: dict, out_dir: Path) -> dict:
    """Einfacher Render für die Sichtung (9:16 mittig, ohne Captions und Branding): nur in den Cache."""
    if not shutil.which("ffmpeg"):
        return {"ok": False, "reason": "ffmpeg fehlt"}
    out = out_dir / f"clip_{clip['rank']:02d}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-ss", f"{clip['start_s']:.3f}", "-to", f"{clip['end_s']:.3f}", "-i", str(media),
        "-vf", "crop='min(iw,ih*9/16)':ih,scale=1080:1920", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", str(out),
    ]  # fmt: skip
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=900)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "reason": exc.__class__.__name__}
    return {"ok": True, "file": out.name}


# -- compare ------------------------------------------------------------------------------------------------------
def iou(a0: float, a1: float, b0: float, b1: float) -> float:
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    union = max(a1, b1) - min(a0, b0)
    return inter / union if union > 0 else 0.0


def gold_span(gold: dict) -> tuple[float, float]:
    """Gesamtspanne der Fundstelle: ``source.start_s`` bis ``end_s``, sonst erste bis letzte Quellstelle."""
    src = gold.get("source") or {}
    if src.get("start_s") is not None and src.get("end_s") is not None:
        return float(src["start_s"]), float(src["end_s"])
    segs = gold_validate.segments(gold)
    return min(a for a, _b in segs), max(b for _a, b in segs)


def gold_segments(gold: dict) -> list[tuple[float, float]]:
    """Vereinigung der Quellstellen (sortiert, überlappende zusammengelegt); ohne ``segments`` die Gesamtspanne."""
    segs = sorted(gold_validate.segments(gold)) or [gold_span(gold)]
    merged = [segs[0]]
    for a, b in segs[1:]:
        if a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def is_multi_segment(gold: dict) -> bool:
    return len(gold_validate.segments(gold)) > 1


def hit_detail(pred: dict, gold: dict, iou_min: float, center_s: float) -> dict[str, Any]:
    """Treffer gegen die Gesamtspanne (IoU oder Mitte ± ``center_s``) oder gegen die Vereinigung der Quellstellen
    (IoU). ``coverage`` ist der Anteil der Quellstellen-Sekunden, die der Vorschlag enthält: ein zusammenhängender
    Schnitt kann einen verdichteten Gold-Clip nur über die Spanne treffen, nie in der Länge."""
    p0, p1 = float(pred["start_s"]), float(pred["end_s"])
    g0, g1 = gold_span(gold)
    o = iou(p0, p1, g0, g1)
    mid = abs((p0 + p1) / 2.0 - (g0 + g1) / 2.0)
    span_hit = o >= iou_min or mid <= center_s
    segs = gold_segments(gold)
    seg_len = sum(b - a for a, b in segs)
    inter = sum(max(0.0, min(p1, b) - max(p0, a)) for a, b in segs)
    union = (p1 - p0) + seg_len - inter
    o_seg = inter / union if union > 0 else 0.0
    seg_hit = o_seg >= iou_min
    basis = "span" if span_hit else ("segments" if seg_hit else None)
    return {"hit": span_hit or seg_hit, "iou": round(o, 4), "iou_segments": round(o_seg, 4),
            "coverage": round(inter / seg_len, 4) if seg_len > 0 else None, "basis": basis, "multi_segment": is_multi_segment(gold)}  # fmt: skip


def is_hit(pred: dict, gold: dict, iou_min: float, center_s: float) -> tuple[bool, float]:
    d = hit_detail(pred, gold, iou_min, center_s)
    return d["hit"], d["iou"]


def gold_for_run(meta: dict, gold: list[dict]) -> list[dict]:
    """Gold-Clips derselben Quelle: IDs aus dem Job oder gleiche Quell-URL; nur vergleichbare (mit Zeiten)."""
    ids = set(meta.get("gold") or [])
    url = (meta.get("source") or {}).get("url")
    out = []
    for g in gold:
        if not isinstance(g, dict) or gold_validate.validate_record(g)["ready_for_compare"] is False:
            continue
        if (ids and g.get("id") in ids) or (not ids and url and (g.get("source") or {}).get("url") == url):
            out.append(g)
    return out


def match(clips: list[dict], gold: list[dict], iou_min: float = 0.5, center_s: float = 10.0) -> dict[str, Any]:
    """Gieriges Paaren nach IoU der Gesamtspanne, dann der Quellstellen (jeder Gold-Clip und jeder Vorschlag
    höchstens einmal). ``details`` trägt je Paar Grundlage des Treffers und Abdeckung der Quellstellen."""
    pairs, details = [], {}
    for i, p in enumerate(clips):
        for j, g in enumerate(gold):
            d = hit_detail(p, g, iou_min, center_s)
            if d["hit"]:
                details[(i, j)] = d
                g0, g1 = gold_span(g)
                pairs.append((d["iou"], d["iou_segments"], -abs((p["start_s"] + p["end_s"]) / 2 - (g0 + g1) / 2), i, j))
    used_p, used_g, matched = set(), set(), []
    for o, _o_seg, _neg_mid, i, j in sorted(pairs, reverse=True):
        if i in used_p or j in used_g:
            continue
        used_p.add(i)
        used_g.add(j)
        matched.append((i, j, o))
    return {"pairs": matched, "pred_hit": used_p, "gold_hit": used_g, "details": {(i, j): details[(i, j)] for i, j, _o in matched}}


def ranking_metrics(clips: list[dict], gold: list[dict], m: dict, ks: tuple[int, ...] = (3, 5, 10)) -> dict[str, Any]:
    ranks = {i: int(clips[i]["rank"]) for i in range(len(clips))}
    out: dict[str, Any] = {}
    for k in (*ks, len(clips)):
        top = {i for i in range(len(clips)) if ranks[i] <= k}
        hit_p = len(top & m["pred_hit"])
        hit_g = sum(1 for i, j, _o in m["pairs"] if i in top)
        key = "all" if k == len(clips) and k not in ks else str(k)
        # Ohne Gold zur Quelle ist Precision nicht messbar, nicht 0
        out[f"precision@{key}"] = round(hit_p / len(top), 4) if top and gold else None
        out[f"recall@{key}"] = round(hit_g / len(gold), 4) if gold else None
    spans = {j: gold_span(g) for j, g in enumerate(gold)}
    errs_s = [float(clips[i]["start_s"]) - spans[j][0] for i, j, _o in m["pairs"]]
    errs_e = [float(clips[i]["end_s"]) - spans[j][1] for i, j, _o in m["pairs"]]
    lens = [float(clips[i]["duration_s"]) - (spans[j][1] - spans[j][0]) for i, j, _o in m["pairs"]]

    def agg(xs: list[float]) -> dict | None:
        if not xs:
            return None
        return {"mean_abs_s": round(sum(abs(x) for x in xs) / len(xs), 3), "median_s": round(statistics.median(xs), 3), "n": len(xs)}

    out["boundary_start"] = agg(errs_s)
    out["boundary_end"] = agg(errs_e)
    out["length_delta"] = agg(lens)
    out["iou_mean"] = round(sum(o for _i, _j, o in m["pairs"]) / len(m["pairs"]), 4) if m["pairs"] else None
    # Verdichtete Gold-Clips (mehrere Quellstellen): unsere Engine schneidet bisher nur zusammenhängende Spannen
    multi = [j for j, g in enumerate(gold) if is_multi_segment(g)]
    out["multi_segment_gold"] = round(len(multi) / len(gold), 4) if gold else None
    det = m.get("details") or {}
    cov = [det[(i, j)]["coverage"] for i, j, _o in m["pairs"] if j in multi and det.get((i, j), {}).get("coverage") is not None]
    out["multi_segment_hits"] = sum(1 for _i, j, _o in m["pairs"] if j in multi)
    out["segment_coverage_mean"] = round(sum(cov) / len(cov), 4) if cov else None
    out["hits_by_segments_only"] = sum(1 for d in det.values() if d["basis"] == "segments")
    return out


JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        **{k: {"type": "integer", "minimum": 0, "maximum": 10} for k in JUDGE_KEYS},
        "verdict": {"type": "string", "enum": ["better", "equal", "worse", "unrated"]},
        "reason": {"type": "string"},
    },
    "required": [*JUDGE_KEYS, "verdict", "reason"],
}


def judge_rubric(gold: dict | None) -> str:
    """Rubrik aus dem Gold-Breakdown, sonst referenzfrei (dann ``verdict`` ``unrated``)."""
    if not gold:
        return ("Keine Referenz: bewerte den Clip für sich nach Hook in den ersten drei Sekunden, verständlichem Kontext ohne "
                "Vorwissen, eingelöster Auflösung und sachlicher, zutreffender Copy. verdict ist unrated.")  # fmt: skip
    b = gold.get("breakdown") or {}
    parts = [
        f"Hook-Typ der Referenz: {b.get('hook_type') or '-'}; Hook der ersten 3 s: {b.get('hook_text_first_3s') or '-'}",
        f"Einstieg: {(b.get('cut_in') or {}).get('kind') or '-'}; Ausstieg: {(b.get('cut_out') or {}).get('kind') or '-'}",
        f"Kontext: {b.get('context_setup') or '-'}; Auflösung: {b.get('payoff') or '-'} ({b.get('payoff_type') or '-'})",
        f"Struktur: {b.get('structure') or '-'}; On-Screen-Text: {b.get('onscreen_text') or '-'}; Copy-Muster: {b.get('copy_pattern') or '-'}",
        f"Titel der Referenz: {(gold.get('clip') or {}).get('title') or '-'}",
    ]
    if is_multi_segment(gold):
        comp = (b.get("edits") or {}).get("compression")
        parts.append(f"Schnitt: aus {len(gold_validate.segments(gold))} Quellstellen verdichtet"
                     + (f" (Kompression {comp})" if comp is not None else ""))  # fmt: skip
    return "Referenz (veröffentlichter Clip derselben Stelle):\n- " + "\n- ".join(parts)


def _judge_items(clips: list[dict], gold: list[dict], m: dict, prompt: Any, system: str) -> list[dict]:
    gold_of = {i: gold[j] for i, j, _o in m["pairs"]}
    items = []
    for i, c in enumerate(clips):
        user = prompt.render(
            rubric=judge_rubric(gold_of.get(i)), clip_text=mm_scan.strip_pseudo(str(c.get("text") or ""))[:4000],
            hook=(c.get("hook") or {}).get("text") or "-", title=c.get("title") or "-", onscreen_text=c.get("onscreen_text") or "-",
            post_text=json.dumps(c.get("post_text") or {}, ensure_ascii=False),
        )  # fmt: skip
        items.append({"id": i, "system": system, "user": user, "schema": JUDGE_SCHEMA, "tool_name": prompt.tool or "judge_clip",
                      "prompt_version": prompt.prompt_version, "job_type": "llm_score", "stage": "judge"})  # fmt: skip
    return items


def _contested(a: dict, b: dict | None = None) -> bool:
    """Strittig: ein Wert nahe der Schwelle oder zwei Haiku-Durchläufe weichen deutlich ab."""
    near = any(abs(float(a.get(k, 0)) - JUDGE_THRESHOLD) <= JUDGE_MARGIN for k in JUDGE_KEYS)
    if b is None:
        return near
    return any(abs(float(a.get(k, 0)) - float(b.get(k, 0))) >= JUDGE_DISAGREE for k in JUDGE_KEYS)


def run_judges(clips: list[dict], gold: list[dict], m: dict, llm: Any, batch: bool = False, ledger: Any = None) -> list[dict]:
    """Richter je Clip: Haiku; strittig nach dem ersten Durchgang ein zweiter Haiku-Durchgang (andere Temperatur),
    strittig danach (Abweichung) Eskalation an Sonnet (``judge_escalate``). Budget erreicht: der Rest bleibt unbewertet."""
    if not clips:
        return []
    pol = editorial.load(2) if "judge_clip" not in editorial.load().prompt_pins else editorial.load()
    prompt = prompts.load_pinned("judge_clip", pol)
    system = prompts.load_pinned("system_editor", pol).render()
    items = _judge_items(clips, gold, m, prompt, system)
    judge = llm.with_tier("judge") if hasattr(llm, "with_tier") else llm
    try:
        if ledger is not None:
            ledger.check("judge")
        first = judge.structured_many(items, batch=batch) if hasattr(judge, "structured_many") else [
            judge.structured(it["system"], it["user"], it["schema"], it["tool_name"], it["prompt_version"], stage="judge") for it in items
        ]
    except costlog.BudgetExceeded:
        return [{"status": "budget_exhausted"} for _ in clips]
    out = []
    for n, (it, a) in enumerate(zip(items, first)):
        if isinstance(a, Exception):
            out.append({"status": "error", "detail": str(a)[:200]})
            continue
        res = {"status": "ok", "final": a, "passes": ["judge"], "escalated": False}
        try:
            if _contested(a):
                if ledger is not None:
                    ledger.check("judge")
                second_llm = judge.with_tier("judge", temperature=0.7) if hasattr(judge, "with_tier") else judge
                b = second_llm.structured(it["system"], it["user"] + "\n\n(Zweiter Durchgang.)", it["schema"], it["tool_name"],
                                          it["prompt_version"], stage="judge_second")  # fmt: skip
                res["passes"].append("judge_second")
                res["second"] = b
                if _contested(a, b):
                    if ledger is not None:
                        ledger.check("judge_escalate")
                    esc = llm.with_tier("judge_escalate") if hasattr(llm, "with_tier") else llm
                    res["final"] = esc.structured(it["system"], it["user"], it["schema"], it["tool_name"], it["prompt_version"],
                                                  stage="judge_escalate")  # fmt: skip
                    res["passes"].append("judge_escalate")
                    res["escalated"] = True
                else:
                    res["final"] = {k: (a[k] + b[k]) / 2.0 if k in JUDGE_KEYS else a[k] for k in a}
        except costlog.BudgetExceeded:
            res["budget_stop"] = True
        res["clip"] = n
        out.append(res)
    return out


def cmd_compare(args: argparse.Namespace) -> int:
    rdir = Path(args.run)
    meta, clips = _read_json(rdir / "meta.json"), _read_json(rdir / "clips.json")["clips"]
    gold_file = Path(args.gold) if args.gold else (REPO / meta["gold_file"] if meta.get("gold_file") else None)
    all_gold = gold_validate.load_set(gold_file) if gold_file and gold_file.is_file() else []
    if args.ids:
        meta = {**meta, "gold": [x for x in args.ids.split(",") if x]}
    gold = gold_for_run(meta, all_gold)
    m = match(clips, gold, args.iou, args.center_s)
    metrics = ranking_metrics(clips, gold, m)
    metrics["gold_n"], metrics["pred_n"], metrics["hits"] = len(gold), len(clips), len(m["pairs"])
    judges: list[dict] = []
    ledger = costlog.RunLedger(s=config.settings())
    if not args.no_judge:
        root = rdir.parents[1]
        llm = make_llm(args.provider, config.settings(), ledger, ResultCache(root=root / "results"), str(meta["source"].get("sha256") or ""))
        judges = run_judges(clips, gold, m, llm, batch=args.batch, ledger=ledger)
        ok = [j for j in judges if j.get("status") == "ok"]
        for k in JUDGE_KEYS:
            vals = [float(j["final"][k]) for j in ok if k in j["final"]]
            metrics[f"judge_{k}"] = round(sum(vals) / len(vals), 3) if vals else None
        metrics["judge_escalated"] = sum(1 for j in ok if j.get("escalated"))
        metrics["judge_reference_free"] = sum(1 for n in range(len(clips)) if n not in m["pred_hit"])
    out = {
        "version": "train_compare_v1", "run_id": meta["run_id"], "created_at": _now(),
        "params": {"iou": args.iou, "center_s": args.center_s, "batch": bool(args.batch), "judge": not args.no_judge},
        "gold_ids": [g["id"] for g in gold], "metrics": metrics,
        "pairs": [{"clip": i, "gold_id": gold[j]["id"], "iou": o, **{k: m["details"][(i, j)][k] for k in ("iou_segments", "coverage", "basis", "multi_segment")}}
                  for i, j, o in m["pairs"]],  # fmt: skip
        "judges": judges, "judge_costs": ledger.summary(),
    }  # fmt: skip
    _write_json(rdir / "compare.json", out)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


# -- scorecard ----------------------------------------------------------------------------------------------------
def scorecard(rdir: Path) -> dict[str, Any]:
    meta, costs = _read_json(rdir / "meta.json"), _read_json(rdir / "costs.json")
    cmp_ = _read_json(rdir / "compare.json") if (rdir / "compare.json").is_file() else {"metrics": {}}
    jc = cmp_.get("judge_costs") or {}
    hours = (float(meta.get("duration_s") or 0) / 3600.0) or None
    eur = float(costs.get("eur") or 0.0) + float(jc.get("eur") or 0.0)
    tokens = int(costs.get("tokens") or 0) + int(jc.get("tokens") or 0)
    # Abo-Läufe (claude-cli) kosten 0 €; das API-Äquivalent zeigt, was derselbe Lauf zum Listenpreis kosten würde
    api_eq = float(costs.get("eur_api_equivalent", eur) or 0.0) + float(jc.get("eur_api_equivalent", jc.get("eur") or 0.0) or 0.0)
    notes = list(dict.fromkeys([*(costs.get("notes") or []), *(jc.get("notes") or [])]))
    return {
        "version": "train_scorecard_v1", "run_id": meta["run_id"], "job_id": meta["job_id"], "created_at": meta["created_at"],
        "source_ref": meta["source"].get("cache_ref"), "duration_s": meta.get("duration_s"), "policy": meta.get("policy"),
        "engine": meta.get("engine"), "provider": meta.get("provider"), "models": meta.get("models"), "mm": (meta.get("mm") or {}).get("source"),
        "prompt_versions": meta.get("prompt_versions"), "clips": meta.get("clips"), "metrics": cmp_.get("metrics") or {},
        "eur": round(eur, 6), "tokens": tokens, "eur_per_source_hour": round(eur / hours, 4) if hours else None,
        "tokens_per_source_hour": round(tokens / hours, 1) if hours else None, "billing": costs.get("billing"),
        "eur_api_equivalent": round(api_eq, 6), "eur_api_equivalent_per_source_hour": round(api_eq / hours, 4) if hours else None,
        "cost_notes": notes,
        "skipped": costs.get("skipped"), "runtime_s": (meta.get("timings") or {}).get("total_s"),
    }  # fmt: skip


def scorecard_md(sc: dict[str, Any]) -> str:
    m = sc["metrics"]

    def f(v: Any) -> str:
        if v is None:
            return "nicht messbar"
        if isinstance(v, float):
            return f"{v:.3f}".replace(".", ",")
        if isinstance(v, dict):
            return ", ".join(f"{k} {f(x)}" for k, x in v.items())
        return str(v)

    lines = [
        f"# Scorecard {sc['run_id']}", "",
        f"Job {sc['job_id']}, Quelle {sc['source_ref']}, {f(sc['duration_s'])} s, Richtlinie {sc['policy']}, Engine {sc['engine']}, "
        f"Provider {sc['provider']}, Scan {sc['mm']}.", "",
        "| Kennzahl | Wert |", "|---|---|",
    ]  # fmt: skip
    for key in ("gold_n", "pred_n", "hits", "recall@3", "recall@5", "recall@10", "precision@3", "precision@5", "precision@10",
                "iou_mean", "boundary_start", "boundary_end", "length_delta", "multi_segment_gold", "multi_segment_hits",
                "segment_coverage_mean", *[f"judge_{k}" for k in JUDGE_KEYS], "judge_escalated"):  # fmt: skip
        if key in m:
            lines.append(f"| {key} | {f(m[key])} |")
    lines += [
        f"| EUR gesamt | {f(sc['eur'])} |", f"| EUR je Quellstunde | {f(sc['eur_per_source_hour'])} |",
        f"| EUR API-Äquivalent | {f(sc.get('eur_api_equivalent'))} |",
        f"| EUR API-Äquivalent je Quellstunde | {f(sc.get('eur_api_equivalent_per_source_hour'))} |",
        f"| Tokens je Quellstunde | {f(sc['tokens_per_source_hour'])} |", f"| Laufzeit s | {f(sc['runtime_s'])} |", "",
    ]  # fmt: skip
    if sc.get("skipped"):
        lines.append("Übersprungen wegen Budget: " + ", ".join(str(x.get("stage")) for x in sc["skipped"]))
    for note in sc.get("cost_notes") or []:
        lines.append(f"Hinweis Kosten: {note}")
    models = sc.get("models") or {}
    lines.append("Modelle: " + ", ".join(f"{k} {v}" for k, v in models.items()) + ".")
    return "\n".join(lines) + "\n"


def cmd_scorecard(args: argparse.Namespace) -> int:
    rdir = Path(args.run)
    sc = scorecard(rdir)
    _write_json(rdir / "scorecard.json", sc)
    (rdir / "scorecard.md").write_text(scorecard_md(sc), encoding="utf-8")
    hist = Path(args.history) if args.history else HISTORY
    hist.parent.mkdir(parents=True, exist_ok=True)
    # Nur Kennzahlen: keine Texte, keine Transkripte, keine Medien
    line = {k: sc[k] for k in ("run_id", "job_id", "created_at", "source_ref", "duration_s", "policy", "engine", "provider", "models",
                               "prompt_versions", "clips", "metrics", "eur", "tokens", "eur_per_source_hour", "tokens_per_source_hour",
                               "eur_api_equivalent", "runtime_s")}  # fmt: skip
    with hist.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    print(str(rdir / "scorecard.md"))
    return 0


# -- export -------------------------------------------------------------------------------------------------------
def _runs(args: argparse.Namespace) -> list[Path]:
    if args.run:
        return [Path(r) for r in args.run]
    return sorted(p.parent for p in cache_root(args).glob("*/runs/*/meta.json"))


def export_rows(rdir: Path, with_text: bool = False) -> list[dict]:
    meta, clips = _read_json(rdir / "meta.json"), _read_json(rdir / "clips.json")["clips"]
    cmp_ = _read_json(rdir / "compare.json") if (rdir / "compare.json").is_file() else {}
    pair_of = {p["clip"]: p for p in cmp_.get("pairs") or []}
    judge_of = {j.get("clip", n): j for n, j in enumerate(cmp_.get("judges") or [])}
    rows = []
    for n, c in enumerate(clips):
        j = judge_of.get(n) or {}
        p = pair_of.get(n)
        row = {
            "run_id": meta["run_id"], "source_ref": meta["source"].get("cache_ref"), "policy": meta.get("policy"), "engine": meta.get("engine"),
            "candidate": n, "rank": c["rank"],
            "features": {
                "duration_s": c["duration_s"], "start_rel": round(c["start_s"] / max(1.0, float(meta.get("duration_s") or 1.0)), 4),
                "total": c["total"], "gate_passed": c["gate_passed"], "scores": c.get("scores"), "prefilter": c.get("prefilter"),
                "events": len(c.get("events") or []), "event_types": sorted({e["type"] for e in c.get("events") or []}),
                "hook_words": len(str((c.get("hook") or {}).get("text") or "").split()), "editor_local": c.get("editor_local"),
                "structure": c.get("structure"),
            },
            "label": {"gold_hit": p is not None, "gold_id": p["gold_id"] if p else None, "iou": p["iou"] if p else None},
            "judge": (j.get("final") if j.get("status") == "ok" else None),
            "views": None,
        }  # fmt: skip
        if with_text:
            row["text"] = c.get("text")
            row["copy"] = {"title": c.get("title"), "hook": (c.get("hook") or {}).get("text"), "post_text": c.get("post_text")}
        rows.append(row)
    return rows


def preference_pairs(rows: list[dict]) -> list[dict]:
    """Paare innerhalb eines Laufs: Gold-Treffer vor Nicht-Treffer; ohne Gold höhere Richter-Summe vor niedrigerer."""

    def judge_sum(r: dict) -> float | None:
        return sum(float(r["judge"][k]) for k in JUDGE_KEYS) if r.get("judge") else None

    out = []
    by_run: dict[str, list[dict]] = {}
    for r in rows:
        by_run.setdefault(r["run_id"], []).append(r)
    for run_id, rs in by_run.items():
        for a in rs:
            for b in rs:
                if a is b:
                    continue
                reason = None
                if a["label"]["gold_hit"] and not b["label"]["gold_hit"]:
                    reason = "gold_hit"
                elif a["label"]["gold_hit"] == b["label"]["gold_hit"]:
                    ja, jb = judge_sum(a), judge_sum(b)
                    if ja is not None and jb is not None and ja - jb >= 4.0:
                        reason = "judge_margin"
                if reason:
                    out.append({"run_id": run_id, "chosen": a["candidate"], "rejected": b["candidate"], "reason": reason,
                                "chosen_features": a["features"], "rejected_features": b["features"]})  # fmt: skip
    return out


def cmd_export(args: argparse.Namespace) -> int:
    rows = [r for d in _runs(args) for r in export_rows(d, with_text=args.with_text)]
    data = rows if args.format == "ranking" else preference_pairs(rows)
    out = Path(args.out) if args.out else cache_root(args) / "exports" / f"{args.format}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for r in data:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{out} ({len(data)} Zeilen)")
    return 0


# -- feed ---------------------------------------------------------------------------------------------------------
def assert_db_allowed(url: str) -> None:
    """Hart: nie die Hauptdatenbank (Port 5499 oder Datenbankname ``chopstr``).

    Geprüft wird, was libpq tatsächlich nehmen würde: Pfad, Query-Parameter ``dbname``/``port``, ohne Pfad der
    Benutzername, ohne Port ``PGPORT``, ohne Name ``PGDATABASE``; ``service=`` ist nicht prüfbar und verboten.
    ``cmd_feed`` prüft nach dem Verbinden zusätzlich ``current_database()`` und ``inet_server_port()``."""
    from urllib.parse import parse_qs

    parts = urlsplit(url)
    if parts.scheme not in ("postgres", "postgresql"):
        raise SystemExit("--db braucht eine postgres://-URL")
    query = {k.lower(): v[-1] for k, v in parse_qs(parts.query).items()}
    if "service" in query or "host" in query:
        raise SystemExit("feed verweigert: service= und host= in der URL sind nicht prüfbar")
    try:
        port = int(query.get("port") or parts.port or os.environ.get("PGPORT") or 5432)
    except ValueError:
        raise SystemExit("feed verweigert: Port nicht lesbar") from None
    name = query.get("dbname") or unquote(parts.path.lstrip("/")) or os.environ.get("PGDATABASE") or unquote(parts.username or "")
    if port == FORBIDDEN_DB_PORT or name == FORBIDDEN_DB_NAME:
        raise SystemExit("feed verweigert: Port 5499 bzw. Datenbank 'chopstr' ist die Hauptdatenbank")


def assert_connection_allowed(conn: Any) -> None:
    """Nach dem Verbinden: die Datenbank selbst fragen, bevor etwas geschrieben wird."""
    from chopstr_worker import db

    row = db.fetch_one(conn, "select current_database(), inet_server_port()")
    if row and (str(row[0]) == FORBIDDEN_DB_NAME or (row[1] is not None and int(row[1]) == FORBIDDEN_DB_PORT)):
        raise SystemExit("feed verweigert: verbunden mit der Hauptdatenbank (chopstr bzw. Port 5499)")


def feed_summary(rows: list[dict], gold: list[dict]) -> dict[str, Any]:
    """Rubrik-Gewichte (Ridge wie ``learning.fit_rubric_weights``, Gold-Treffer als angenommen) und Hook-Muster."""
    from chopstr_worker import learning

    fit_rows = []
    for r in rows:
        scores = (r["features"] or {}).get("scores")
        if not scores or any(scores.get(k) is None for k in story_engine.SCORE_KEYS):
            continue
        fit_rows.append({"scores": {k: float(scores[k]) for k in story_engine.SCORE_KEYS},
                         "verdict": "accepted" if r["label"]["gold_hit"] else "rejected"})  # fmt: skip
    weights = learning.fit_rubric_weights(fit_rows, min_n=min(learning.MIN_DECISIONS, max(2, len(fit_rows))))
    gold_by_id = {g.get("id"): g for g in gold if isinstance(g, dict)}
    hooks: dict[str, dict[str, int]] = {}
    for g in gold:
        ht = ((g.get("breakdown") or {}).get("hook_type") if isinstance(g, dict) else None) or None
        if ht:
            hooks.setdefault(ht, {"shown": 0, "chosen": 0})["shown"] += 1
    for r in rows:
        gid = r["label"]["gold_id"]
        ht = ((gold_by_id.get(gid) or {}).get("breakdown") or {}).get("hook_type") if gid else None
        if ht:
            hooks.setdefault(ht, {"shown": 0, "chosen": 0})["chosen"] += 1
    return {"rows": len(fit_rows), "weights": weights, "hook_patterns": hooks, "weights_reliable": len(fit_rows) >= learning.MIN_DECISIONS}


def cmd_feed(args: argparse.Namespace) -> int:
    if args.db:
        assert_db_allowed(args.db)
    rows = [r for d in _runs(args) for r in export_rows(d)]
    gold = gold_validate.load_set(Path(args.gold)) if args.gold else []
    summary = feed_summary(rows, gold)
    summary["created_at"], summary["runs"] = _now(), sorted({r["run_id"] for r in rows})
    if args.db:
        if not args.brand_profile:
            raise SystemExit("--db braucht --brand-profile <uuid>")
        from chopstr_worker import db, learning

        with db.connect(args.db) as conn:
            assert_connection_allowed(conn)
            for pattern, st in summary["hook_patterns"].items():
                learning.update_hook_stats(conn, args.brand_profile, pattern, shown=st["shown"], chosen=st["chosen"])
            conn.commit()
        print(f"Hook-Muster in {urlsplit(args.db).hostname} geschrieben ({len(summary['hook_patterns'])})")
    store = Path(args.store) if args.store else cache_root(args) / "learning" / "feed.jsonl"
    store.parent.mkdir(parents=True, exist_ok=True)
    with store.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


# -- CLI ----------------------------------------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m eval.train", description=__doc__.split("\n\n")[0])
    p.add_argument("--cache-dir", help="Cache-Ordner, Standard .local/eval-cache")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gold", help="Gold-Set prüfen oder zählen")
    g.add_argument("action", choices=["validate", "stats"])
    g.add_argument("--gold", help="Gold-Datei, Standard eval/gold/dach_v1.json")
    g.set_defaults(func=cmd_gold)

    j = sub.add_parser("job", help="Job-Datei anlegen")
    j.add_argument("action", choices=["create"])
    j.add_argument("--source", required=True, help="Videodatei oder URL")
    j.add_argument("--brief", required=True, help="Briefing als Text oder Datei (JSON oder Text)")
    j.add_argument("--gold", dest="gold_ids", help="Gold-IDs, kommagetrennt")
    j.add_argument("--gold-file", help="Gold-Datei, auf die sich die IDs beziehen")
    j.add_argument("--transcript", help="Vorhandenes Transkript (Wortliste), ersetzt die ASR; wird in den Cache kopiert")
    j.add_argument("--name", help="Job-ID, Standard aus Datum und Hash")
    j.add_argument("--out-dir", help="Zielordner, Standard eval/jobs")
    j.set_defaults(func=cmd_job_create)

    r = sub.add_parser("run", help="Pipeline ohne Postgres und Temporal")
    r.add_argument("--job", required=True)
    r.add_argument("--provider", help="LLM-Provider (anthropic, claude-cli, local-heuristic, bedrock-eu ...), Standard LLM_PROVIDER")
    r.add_argument("--mm-provider", help="gemini, mock oder none, Standard CHOPSTR_MM_PROVIDER")
    r.add_argument("--policy-version", type=int, default=2)
    r.add_argument("--budget-eur", type=float)
    r.add_argument("--budget-tokens", type=int)
    r.add_argument("--render", action="store_true", help="Clips einfach rendern (nur Cache)")
    r.add_argument("--skip-media", action="store_true", help="Mit Transkript im Job ohne Mediendatei laufen")
    r.add_argument("--run-id")
    r.set_defaults(func=cmd_run)

    c = sub.add_parser("compare", help="Lauf gegen Gold und Richter")
    c.add_argument("--run", required=True)
    c.add_argument("--gold")
    c.add_argument("--ids", help="Gold-IDs, kommagetrennt (sonst aus dem Job oder über die Quell-URL)")
    c.add_argument("--iou", type=float, default=0.5)
    c.add_argument("--center-s", type=float, default=10.0)
    c.add_argument("--provider")
    c.add_argument("--batch", action="store_true", help="Richter über die Batch-API (Anthropic)")
    c.add_argument("--no-judge", action="store_true")
    c.set_defaults(func=cmd_compare)

    s = sub.add_parser("scorecard", help="Scorecard und Verlauf")
    s.add_argument("--run", required=True)
    s.add_argument("--history", help="Verlauf, Standard eval/results/training/history.jsonl")
    s.set_defaults(func=cmd_scorecard)

    e = sub.add_parser("export", help="JSONL für Ranking- oder Präferenzdaten")
    e.add_argument("--format", choices=["ranking", "preferences"], required=True)
    e.add_argument("--run", action="append", help="Laufordner, mehrfach; ohne Angabe alle im Cache")
    e.add_argument("--out")
    e.add_argument("--with-text", action="store_true", help="Clip-Text und Copy mitschreiben (nur in den Cache, nie ins Repo)")
    e.set_defaults(func=cmd_export)

    f = sub.add_parser("feed", help="Ergebnisse in die Lernschleife")
    f.add_argument("--run", action="append")
    f.add_argument("--gold")
    f.add_argument("--store", help="Datei-Ablage, Standard .local/eval-cache/learning/feed.jsonl")
    f.add_argument("--db", help="postgres://-URL einer Test-Datenbank (nie Port 5499 oder DB chopstr)")
    f.add_argument("--brand-profile")
    f.set_defaults(func=cmd_feed)
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
