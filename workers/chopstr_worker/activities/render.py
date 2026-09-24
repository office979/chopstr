"""Activity ``render_pack`` (Phase 3): aus einem angenommenen Kandidaten ein postbares Paket rendern.

Ablauf nach ``packages/schema/CLIPS.md``: Clip-Zeile finden oder anlegen, ``rendering``, Copy (Hook-Version 1
per ``copy_engine``, falls keine existiert; sonst die höchste Version, auch manuelle), Reframe, Captions auf der
Ausgabe-Timeline, ffmpeg-Encode, Provenienz (C2PA nur mit c2patool, sonst ``skipped`` mit Grund), Upload nach
``derived`` (``renders/<clip_id>/<hash>.*``), ``caption_versions``, Spalten in ``clips``, ``rendered``.
Fehler: ``failed`` plus ``render_error`` (deutsch). Events ``step = 'render'`` mit ``progress`` je Schritt
(copy, reframe, captions, encode, provenance). Idempotent über den Hash aus Plan, Hook-Version und
Transkriptversion: existiert die MP4 unter diesem Hash und ist sie am Clip eingetragen, wird nicht neu gerendert.

Marke (Phase 4): Font-Assets des Markenprofils (``brand_profiles.ci.fonts.primary_asset_id`` oder
``secondary_asset_id`` in ``brand_assets``) werden aus dem Storage nach ``WORKER_WORK_DIR/fonts/<sha>.<ext>`` geladen,
der Familienname steht als ``Fontname`` in der ASS und im Plan (``captions.font``), die Datei geht als ``fontfile``
in ``drawtext``. Fehlt der Font, bleibt Inter mit Hinweis in ``notes``. Logo (``ci.logo_asset_id``) mit
``ci.watermark.enabled`` wird als PNG-Wasserzeichen unten rechts gelegt (SVG wird übersprungen).

Phase 5c: ``clips.reframe_override`` geht als ``reframe_override`` an ``plan_reframe`` (Folien-Crop ``slide_pip``
oder erzwungene Strategie; Abweichungen zwischen Erkennung und Nutzung stehen in ``notes``).
``brand_profiles.caption_style.caption_text_field`` (``text`` | ``text_norm``, Default ``text``) wählt die Wortform
der Captions (Schweizerdeutsch-Beta, Entscheidung P2).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from temporalio import activity

from .. import costlog, db, decision_log, events, ingest, usage
from ..pipeline import (
    captions_de,
    compliance,
    compose,
    copy_de,
    copy_engine,
    fidelity,
    reframe,
    render,
    render_plan,
)
from ..providers_llm import LLM
from ..residency import Tenant
from . import common

log = logging.getLogger("chopstr.activities.render")

STEP_RENDER = "render"
PLATFORMS = copy_engine.PLATFORMS
RENDER_PREFIX = "renders"
CONTENT_TYPES = {"mp4": "video/mp4", "srt": "application/x-subrip", "vtt": "text/vtt", "jpg": "image/jpeg", "ass": "text/plain"}

SQL_CANDIDATE = "select id, source_id, segments, rubric, risk_flags, start_s, end_s from candidates where id = %s"
SQL_BRAND_EXTRA = (
    "select p.gender_mode, p.banned_phrases, p.tone_adjectives, p.default_platform, p.caption_preset, p.caption_style, "
    "s.rights_status, s.source_owner, s.source_title, s.source_url, p.ci "
    "from sources s left join brand_profiles p on p.id = s.brand_profile_id where s.id = %s"
)
SQL_ASSET = "select id, kind, name, storage_key, mime_type, sha256, font_family, font_weight from brand_assets where id = %s"
FONT_EXTS = {".ttf", ".otf", ".woff2", ".woff"}
NOTE_FONT_MISSING = "Marken-Font fehlt, Inter verwendet"
NOTE_LOGO_SVG = "Logo im SVG-Format wird übersprungen, für das Wasserzeichen ein PNG hochladen"
SQL_CLIP = (
    "select id, status, aspect, composition, title_card, ad_label, ai_features, speaker_positions, file_key "
    "from clips where candidate_id = %s and platform = %s order by created_at desc limit 1"
)
SQL_HOOK = (
    "select id, version, origin, spoken_hook, onscreen_hook, pattern, post_captions, cta "
    "from hook_versions where clip_id = %s order by version desc limit 1"
)
SQL_CAPTION_MAX = "select coalesce(max(version), 0) from caption_versions where clip_id = %s"
SQL_REFRAME_OVERRIDE = "select reframe_override from clips where id = %s"
NOTE_OVERRIDE_UNREADABLE = "Reframe-Override konnte nicht gelesen werden (Migration 0005 eingespielt?), Automatik verwendet"
SQL_CAPTION_STYLE = "select caption_style from clips where id = %s"
SQL_ZEITMARKEN = "select zeitmarken from clips where id = %s"
NOTE_MARKEN_UNREADABLE = "Zeitmarken konnten nicht gelesen werden (Migration 0009 eingespielt?), Automatik verwendet"
NOTE_STYLE_UNREADABLE = "Untertitel-Stil des Clips konnte nicht gelesen werden (Migration 0008 eingespielt?), Markenprofil verwendet"


def _json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _load_candidate(ctx: common.Context, candidate_id: str) -> dict[str, Any]:
    row = db.fetch_one(ctx.conn, SQL_CANDIDATE, (candidate_id,))
    if row is None:
        raise LookupError(f"Kandidat {candidate_id} nicht gefunden")
    cid, source_id, segments, rubric, risk_flags, start_s, end_s = row
    return {
        "id": str(cid),
        "source_id": str(source_id),
        "segments": list(_json(segments, [])),
        "rubric": dict(_json(rubric, {}) or {}),
        "risk_flags": list(_json(risk_flags, []) or []),
        "start_s": float(start_s) if start_s is not None else None,
        "end_s": float(end_s) if end_s is not None else None,
    }


def _load_brand_extra(ctx: common.Context, source_id: str) -> dict[str, Any]:
    row = db.fetch_one(ctx.conn, SQL_BRAND_EXTRA, (source_id,))
    keys = [
        "gender_mode", "banned_phrases", "tone_adjectives", "default_platform", "caption_preset", "caption_style",
        "rights_status", "source_owner", "source_title", "source_url", "ci",
    ]  # fmt: skip
    out = dict(zip(keys, row)) if row else {}
    out["gender_mode"] = out.get("gender_mode") or "neutral"
    out["banned_phrases"] = list(out.get("banned_phrases") or [])
    out["tone_adjectives"] = list(out.get("tone_adjectives") or [])
    out["default_platform"] = out.get("default_platform") or "linkedin"
    # Kein Ersatzwert: NULL heißt „keine ausdrückliche Wahl“ und muss so bei caption_preset_for
    # ankommen, sonst gewinnt der ruhige LinkedIn-Stil wieder im Hochformat (Migration 0007).
    out["caption_preset"] = out.get("caption_preset") or None
    out["caption_style"] = dict(_json(out.get("caption_style"), {}) or {})
    out["rights_status"] = out.get("rights_status") or "own"
    out["ci"] = dict(_json(out.get("ci"), {}) or {})
    return out


def _load_asset(ctx: common.Context, asset_id: str | None) -> dict[str, Any] | None:
    if not asset_id:
        return None
    row = db.fetch_one(ctx.conn, SQL_ASSET, (str(asset_id),))
    if row is None:
        return None
    keys = ["id", "kind", "name", "storage_key", "mime_type", "sha256", "font_family", "font_weight"]
    out = dict(zip(keys, row))
    out["id"] = str(out["id"])
    return out


def _fetch_asset(ctx: common.Context, asset: dict[str, Any], folder: str) -> Path:
    """Lädt ein Asset nach ``WORKER_WORK_DIR/<folder>/<sha>.<ext>`` (Cache über den Hash, idempotent)."""
    key = str(asset["storage_key"])
    ext = Path(key).suffix.lower() or ""
    sha = str(asset.get("sha256") or "").strip() or hashlib.sha256(key.encode("utf-8")).hexdigest()
    local = ctx.work_dir / folder / f"{sha}{ext}"
    if not local.is_file():
        ctx.store.download_to("derived", key, local)
    return local


def brand_assets_for(ctx: common.Context, ci: dict[str, Any]) -> dict[str, Any]:
    """Font und Logo des Markenprofils aus ``ci`` auflösen und lokal bereitstellen.

    Liefert ``font_path``, ``font_family``, ``font_asset_id``, ``fonts_dir``, ``logo_path``, ``logo_asset_id``,
    ``watermark`` (Einstellung aus ``ci.watermark``) und deutsche ``notes`` für alles, was fehlt."""
    fonts = dict(ci.get("fonts") or {})
    wm = dict(ci.get("watermark") or {})
    out: dict[str, Any] = {
        "font_path": None, "font_family": None, "font_asset_id": None, "fonts_dir": None,
        "logo_path": None, "logo_asset_id": None, "watermark": wm, "notes": [],
    }  # fmt: skip
    font_id = fonts.get("primary_asset_id") or fonts.get("secondary_asset_id")
    if font_id:
        asset = _load_asset(ctx, str(font_id))
        family = str((asset or {}).get("font_family") or "").strip()
        if asset is None or asset.get("kind") != "font" or Path(str(asset["storage_key"])).suffix.lower() not in FONT_EXTS:
            out["notes"].append(NOTE_FONT_MISSING)
        elif not family:
            out["notes"].append("Marken-Font ohne Familienname, Inter verwendet")
        else:
            try:
                path = _fetch_asset(ctx, asset, "fonts")
            except Exception as exc:
                log.warning("brand font download failed asset=%s error=%s", asset["id"], exc.__class__.__name__)
                out["notes"].append(NOTE_FONT_MISSING)
            else:
                out.update(font_path=path, font_family=family, font_asset_id=asset["id"], fonts_dir=path.parent)
    logo_id = ci.get("logo_asset_id")
    if logo_id and bool(wm.get("enabled")):
        asset = _load_asset(ctx, str(logo_id))
        if asset is None:
            out["notes"].append("Logo-Asset fehlt, kein Wasserzeichen")
        else:
            is_svg = Path(str(asset["storage_key"])).suffix.lower() == ".svg" or "svg" in str(asset.get("mime_type") or "")
            if is_svg:
                out["notes"].append(NOTE_LOGO_SVG)
            else:
                try:
                    out["logo_path"] = _fetch_asset(ctx, asset, "brand")
                    out["logo_asset_id"] = asset["id"]
                except Exception as exc:
                    log.warning("brand logo download failed asset=%s error=%s", asset["id"], exc.__class__.__name__)
                    out["notes"].append("Logo-Asset konnte nicht geladen werden, kein Wasserzeichen")
    return out


def ad_label_for(brief: dict, country: str) -> str | None:
    if brief.get("is_ad"):
        return copy_de.AD_LABELS.get((country or "AT").upper(), "Werbung")
    return None


SQL_CLIP_BY_ID = (
    "select id, status, aspect, composition, title_card, ad_label, ai_features, speaker_positions, file_key "
    "from clips where id = %s and candidate_id = %s and platform = %s"
)


def parse_destination(destination: str) -> tuple[str, str | None]:
    """``"tiktok"`` oder ``"tiktok:<clip_id>"`` (gezielter Render eines Clips, z. B. Variante B im Hook-A/B)."""
    platform, _, clip_id = (destination or "").partition(":")
    return platform.strip(), (clip_id.strip() or None)


def _find_or_create_clip(ctx: common.Context, cand: dict, src: dict, destination: str, clip_id: str | None = None) -> dict[str, Any]:
    if clip_id:
        row = db.fetch_one(ctx.conn, SQL_CLIP_BY_ID, (clip_id, cand["id"], destination))
        if row is None:
            raise LookupError(f"Clip {clip_id} gehört nicht zu Kandidat {cand['id']} und Ziel {destination}")
    else:
        row = db.fetch_one(ctx.conn, SQL_CLIP, (cand["id"], destination))
    if row is not None:
        cid, status, aspect, composition, title_card, ad_label, ai_features, speaker_positions, file_key = row
        if status not in ("draft", "failed", "rendered", "approved"):
            log.warning("render clip=%s status=%s wird trotzdem gerendert", cid, status)
        return {
            "id": str(cid),
            "status": status,
            "aspect": aspect or render_plan.aspect_for_platform(destination),
            "composition": list(_json(composition, []) or []) or list(cand["segments"]),
            "title_card": title_card,
            "ad_label": ad_label,
            "ai_features": list(ai_features or []),
            "speaker_positions": _json(speaker_positions, None),
            "file_key": file_key,
            "created": False,
        }
    aspect = render_plan.aspect_for_platform(destination)
    title_card = (cand["rubric"].get("suggested_title_card") or "").strip() or None
    ad_label = ad_label_for(dict(src.get("brief") or {}), src.get("country") or "AT")
    inserted = db.insert(
        ctx.conn,
        "clips",
        returning="id",
        source_id=cand["source_id"],
        candidate_id=cand["id"],
        platform=destination,
        destination=destination,
        aspect=aspect,
        composition=db.jsonb(cand["segments"]),
        title_card=title_card,
        ad_label=ad_label,
        status="draft",
    )
    return {
        "id": str(inserted[0]),
        "status": "draft",
        "aspect": aspect,
        "composition": list(cand["segments"]),
        "title_card": title_card,
        "ad_label": ad_label,
        "ai_features": [],
        "speaker_positions": None,
        "file_key": None,
        "created": True,
    }


def _load_reframe_override(ctx: common.Context, clip_id: str) -> tuple[str | None, str | None]:
    """``clips.reframe_override`` (Phase 5c) lesen. Liefert (Override, Hinweis). Ohne Spalte (Migration 0005
    fehlt) oder bei einem Lesefehler läuft die Automatik weiter, der Hinweis landet in ``notes``."""
    try:
        row = db.fetch_one(ctx.conn, SQL_REFRAME_OVERRIDE, (clip_id,))
    except Exception as exc:
        log.warning("reframe_override not readable clip=%s error=%s", clip_id, exc.__class__.__name__)
        return None, NOTE_OVERRIDE_UNREADABLE
    value = str(row[0]).strip() if row and row[0] else ""
    if not value:
        return None, None
    if value not in reframe.STRATEGIES:
        return None, f"Unbekannter Reframe-Override {value!r} ignoriert"
    return value, None


def _load_caption_style(ctx: common.Context, clip_id: str) -> tuple[dict, str | None]:
    """``clips.caption_style`` lesen. Liefert (Stil, Hinweis).

    Ohne Spalte oder bei einem Lesefehler gilt weiter der Stil des Markenprofils. Ein Stil darf
    keinen Render verhindern, er ist Geschmack und nicht Inhalt."""
    try:
        row = db.fetch_one(ctx.conn, SQL_CAPTION_STYLE, (clip_id,))
    except Exception as exc:
        log.warning("caption_style not readable clip=%s error=%s", clip_id, exc.__class__.__name__)
        return {}, NOTE_STYLE_UNREADABLE
    wert = _json(row[0], {}) if row else {}
    return dict(wert or {}), None


def caption_style_zusammen(marke: dict | None, clip: dict | None) -> dict:
    """Markenstil und Clipstil uebereinanderlegen, der Clip sticht.

    Der Markenstil ist die Hausschrift, der Clipstil die Ausnahme fuer diesen einen Ausschnitt. Wer
    am Clip nichts eingestellt hat, bekommt unveraendert das, was vorher galt."""
    return {**(marke or {}), **(clip or {})}


def caption_basis_preset(destination: str, extra: dict, aspect: str | None, style: dict | None) -> str:
    """Welches Preset die Grundlage ist. Eine Wahl im Clipstil sticht alles andere."""
    gewaehlt = str((style or {}).get("preset") or "").strip()
    if gewaehlt in captions_de.PRESETS:
        return gewaehlt
    return caption_preset_for(destination, extra, aspect)


def _load_zeitmarken(ctx: common.Context, clip_id: str) -> tuple[list[dict], str | None]:
    """``clips.zeitmarken`` lesen: die Entscheidungen von Hand aus der Zeitleiste.

    Ohne Spalte oder bei einem Lesefehler laeuft die Automatik weiter. Eine fehlende Marke kostet
    Genauigkeit, ein abgebrochener Render kostet den ganzen Clip."""
    try:
        row = db.fetch_one(ctx.conn, SQL_ZEITMARKEN, (clip_id,))
    except Exception as exc:
        log.warning("zeitmarken not readable clip=%s error=%s", clip_id, exc.__class__.__name__)
        return [], NOTE_MARKEN_UNREADABLE
    wert = _json(row[0], []) if row else []
    return [m for m in (wert or []) if isinstance(m, dict)], None


def caption_schrift(style: dict | None, marken_font: str | None) -> tuple[str | None, str | None]:
    """Welche Schrift die Untertitel bekommen, und ein Hinweis falls die Datei fehlt.

    Reihenfolge: eine Wahl am Clip sticht, sonst der Marken-Font aus den Assets, sonst das Preset.
    Fehlt die Datei zur gewaehlten Schrift im Fontordner, faellt libass stillschweigend auf
    irgendetwas zurueck - das sieht dann aus wie ein Fehler im Render. Deshalb pruefen wir es hier
    und sagen es, statt es passieren zu lassen."""
    gewaehlt = str((style or {}).get("font") or "").strip()
    if not gewaehlt:
        return marken_font, None
    if gewaehlt not in captions_de.schrift_namen():
        return marken_font, f"Unbekannte Schrift {gewaehlt!r} ignoriert"
    datei = captions_de.schrift_datei(gewaehlt)
    ordner = render.default_fonts_dir()
    if datei and not (ordner / datei).is_file():
        return marken_font, f"Schriftdatei {datei} fehlt in {ordner}, es bleibt bei der Vorgabe"
    return gewaehlt, None


def caption_text_field_for(style: dict | None) -> str:
    """``caption_style.caption_text_field`` des Markenprofils: ``text`` (Default) oder ``text_norm``."""
    value = str((style or {}).get("caption_text_field") or "text").strip()
    return value if value in captions_de.TEXT_FIELDS else "text"


def _load_hook(ctx: common.Context, clip_id: str) -> dict[str, Any] | None:
    row = db.fetch_one(ctx.conn, SQL_HOOK, (clip_id,))
    if row is None:
        return None
    hid, version, origin, spoken, onscreen, pattern, post_captions, cta = row
    return {
        "id": str(hid),
        "version": int(version),
        "origin": origin,
        "spoken_hook": spoken or "",
        "onscreen_hook": onscreen or "",
        "pattern": pattern or "",
        "post_captions": dict(_json(post_captions, {}) or {}),
        "cta": cta or "",
    }


def _write_hook_version(ctx: common.Context, clip_id: str, copy: copy_engine.CopyResult) -> dict[str, Any]:
    row = copy.to_row()
    inserted = db.insert(
        ctx.conn,
        "hook_versions",
        returning="id",
        clip_id=clip_id,
        version=1,
        spoken_hook=row["spoken_hook"],
        onscreen_hook=row["onscreen_hook"],
        pattern=row["pattern"],
        variants=db.jsonb(row["variants"]),
        post_captions=db.jsonb(row["post_captions"]),
        cta=row["cta"],
        lint_notes=db.jsonb(row["lint_notes"]),
        claim_issues=db.jsonb(row["claim_issues"]),
        origin="llm",
        model_id=row["model_id"],
        prompt_version=row["prompt_version"],
    )
    return {
        "id": str(inserted[0]) if inserted else "",
        "version": 1,
        "origin": "llm",
        "spoken_hook": row["spoken_hook"],
        "onscreen_hook": row["onscreen_hook"],
        "pattern": row["pattern"],
        "post_captions": row["post_captions"],
        "cta": row["cta"],
    }


def clip_words(words: list[dict], segments: list[dict]) -> list[dict]:
    """Wörter innerhalb der Segmente, in Abspielreihenfolge (Teaser doppelt, wie im Clip zu hören)."""
    out = []
    for seg in segments:
        s0, s1 = float(seg["start"]), float(seg["end"])
        out.extend(w for w in words if s0 <= float(w["start"]) and float(w["end"]) <= s1)
    return out


def fidelity_warnings(words: list[dict], segments: list[dict], cand_start: float | None, cand_end: float | None) -> list[dict]:
    """``fidelity.check_cut`` über den Kandidatenbereich: was die Komposition weglässt, wird geprüft."""
    body = sorted((s for s in segments if s.get("role", "body") != "teaser"), key=lambda s: float(s["start"]))
    if not body:
        return []
    c0 = cand_start if cand_start is not None else float(body[0]["start"])
    c1 = cand_end if cand_end is not None else float(body[-1]["end"])
    cand = [w for w in words if c0 <= float(w["start"]) and float(w["end"]) <= c1]
    if not cand:
        return []
    kept: list[tuple[int, int]] = []
    for seg in body:
        idx = [i for i, w in enumerate(cand) if float(seg["start"]) <= float(w["start"]) and float(w["end"]) <= float(seg["end"])]
        if idx:
            kept.append((idx[0], idx[-1]))
    return fidelity.check_cut(cand, kept) if kept else []


# Wortweise Presets je Plattform, wenn hochkant gerendert wird. LinkedIn hat kein eigenes
# Wort-Preset, im Hochformat bekommt es deshalb das von Reels (gleiche Safe Zone, gleiche Schrift).
PORTRAIT_WORD_PRESET = {
    "tiktok": "tiktok_words",
    "reels": "reels_words",
    "shorts": "shorts_words",
    "linkedin": "reels_words",
}


def caption_preset_for(destination: str, extra: dict, aspect: str | None = None) -> str:
    """Untertitel-Stil für diesen Clip.

    Reihenfolge: eine ausdrückliche Wahl im Markenprofil schlägt alles. Sonst entscheidet das
    Format, nicht die Plattform — ein hochkanter Clip bekommt wortweise Untertitel, auch wenn die
    Zielplattform LinkedIn ist. Seit dem Wegfall der Auswahl entstehen alle Clips in 9:16, und der
    ruhige LinkedIn-Stil (mehrere Wörter, zwei Zeilen) wirkt dort wie ein Fehler statt wie eine
    Entscheidung. Im Querformat bleibt es beim bisherigen Plattform-Default.
    """
    if destination == extra.get("default_platform") and extra.get("caption_preset") in captions_de.PRESETS:
        return str(extra["caption_preset"])
    if aspect == "9:16":
        return PORTRAIT_WORD_PRESET.get(destination, "reels_words")
    return captions_de.PLATFORM_DEFAULT_PRESET.get(destination, "linkedin_static")


def _ensure_local_source(ctx: common.Context, src: dict) -> Path:
    key = common.require(src, "storage_key", "Original")
    ext = Path(key).suffix or ".mp4"
    local = ctx.source_dir(src["id"]) / f"original{ext}"
    if not local.is_file():
        ctx.store.download_to("sources", key, local)
    return local


def _provenance(ctx: common.Context, mp4: Path, title: str, clip: dict, extra: dict) -> tuple[dict[str, Any], Path]:
    ai_features = list(clip.get("ai_features") or [])
    prov: dict[str, Any] = {
        "c2pa": "skipped",
        "reason": None,
        "ai_label_required": compliance.needs_visible_ai_label(ai_features),
        "ai_features": ai_features,
        "source_credit": None,
        "ad_label": clip.get("ad_label"),
    }
    if extra.get("rights_status") == "third_party":
        prov["source_credit"] = compliance.source_credit(extra.get("source_owner"), extra.get("source_title"), extra.get("source_url"))
    final = mp4
    if compliance.c2patool_available():
        signed = mp4.with_name(mp4.stem + ".signed.mp4")
        try:
            compliance.sign_mp4(str(mp4), str(signed), title, ai_features)
            prov["c2pa"] = "signed"
            final = signed
        except Exception as exc:
            prov["c2pa"] = "failed"
            prov["reason"] = f"Signatur fehlgeschlagen: {str(exc)[:200]}"
    else:
        prov["reason"] = "c2patool nicht installiert"
    return prov, final


def run_render_pack(ctx: common.Context, candidate_id: str, destination: str) -> str:
    """Rendert das Paket für ``(candidate_id, destination)`` und gibt die ``clips``-ID zurück."""
    destination, clip_id_hint = parse_destination(destination)
    if destination not in PLATFORMS:
        raise ValueError(f"Unbekanntes Ziel {destination!r} (erlaubt: {', '.join(PLATFORMS)})")
    t0 = time.monotonic()
    cand = _load_candidate(ctx, candidate_id)
    source_id = cand["source_id"]
    src = db.load_source(ctx.conn, source_id)
    extra = _load_brand_extra(ctx, source_id)
    clip = _find_or_create_clip(ctx, cand, src, destination, clip_id_hint)
    clip_id = clip["id"]
    db.update(ctx.conn, "clips", {"id": clip_id}, status="rendering", destination=destination, render_error=None)

    with events.step(ctx.conn, source_id, STEP_RENDER, f"Render für {destination} gestartet", fail_status=None) as st:
        try:
            _render(ctx, st, cand, src, extra, clip, destination, t0)
        except BaseException as exc:
            msg = events.failure_message(STEP_RENDER, exc)
            db.update(ctx.conn, "clips", {"id": clip_id}, status="failed", render_error=msg)
            raise
    return clip_id


def _render(ctx: common.Context, st: events.StepContext, cand: dict, src: dict, extra: dict, clip: dict, destination: str, t0: float) -> None:
    s = ctx.settings
    conn = ctx.conn
    clip_id = clip["id"]
    source_id = src["id"]
    brand = copy_de.BrandProfile(
        address=src.get("address") or "du",
        country=src.get("country") or "AT",
        gender_mode=extra["gender_mode"],
        banned_phrases=extra["banned_phrases"],
        protected_terms=list(src.get("protected_terms") or []),
        tone_adjectives=extra["tone_adjectives"],
        platform=destination,
    )
    segments = render_plan.normalize_segments(clip["composition"])
    comp = compose.Composition.from_json(segments)
    aspect = clip["aspect"]
    out_w, out_h = render_plan.output_size(aspect)

    # 1) Copy
    st.progress(0.05, "Copy: Hooks und Post-Texte", clip_id=clip_id, phase="copy")
    common.heartbeat("render", "copy")
    tv_id, tv_version, words = common.load_transcript(ctx, source_id)
    text = " ".join(str(w["text"]) for w in clip_words(words, segments))
    hook = _load_hook(ctx, clip_id)
    llm_usage: list[dict] = []
    llm_provider = None
    if hook is None:
        tenant = Tenant(id=src["workspace_id"], tier=src["tier"], allow_us_subprocessors=bool(src.get("allow_us_subprocessors")))
        llm = LLM(tenant, cost_sink=usage.llm_sink(conn, src["workspace_id"], llm_usage), s=s)
        if not llm.model():
            raise RuntimeError(
                f"Kein Sprachmodell für Provider {llm.provider} konfiguriert "
                "(BEDROCK_MODEL_ID, MISTRAL_MODEL oder SELFHOST_LLM_MODEL setzen, für Entwicklung LLM_PROVIDER=local-heuristic)"
            )
        llm_provider = llm.provider
        copy = copy_engine.write_copy(llm, text, brand, PLATFORMS, s)
        hook = _write_hook_version(ctx, clip_id, copy)
        try:
            decision_log.record_copy_result(
                ctx.conn, src["workspace_id"], clip_id, copy,
                brand_profile_id=src.get("brand_profile_id"), source_id=source_id, candidate_id=cand["id"], platform=destination,
            )  # fmt: skip
        except Exception as exc:  # Decision Log darf den Render nie stoppen
            log.warning("decision log copy failed clip=%s error=%s", clip_id, exc.__class__.__name__)

    # 2) Reframe
    st.progress(0.2, "Reframe: Sprecherpositionen und Shots", clip_id=clip_id, phase="reframe")
    common.heartbeat("render", "reframe")
    local_src = _ensure_local_source(ctx, src)
    # Geometrie immer aus der echten Datei, nie aus DB-Metadaten (die können veraltet oder falsch sein)
    src_probe = ingest.probe(str(local_src))
    if (src.get("width"), src.get("height")) != (src_probe.width, src_probe.height):
        log.warning(
            "source geometry differs from db source=%s db=%sx%s file=%sx%s",
            src["id"], src.get("width"), src.get("height"), src_probe.width, src_probe.height,
        )
    src = {**src, "width": src_probe.width, "height": src_probe.height, "fps": src_probe.fps or src.get("fps")}
    override, override_note = _load_reframe_override(ctx, clip_id)
    zeitmarken, marken_note = _load_zeitmarken(ctx, clip_id)
    rf = reframe.plan_reframe(
        str(local_src), segments, words, clip.get("speaker_positions"), aspect,
        src_w=src_probe.width, src_h=src_probe.height, out_size=(out_w, out_h), reframe_override=override,
        zeitmarken=zeitmarken,
    )  # fmt: skip
    if override_note:
        rf.notes.append(override_note)
    if marken_note:
        rf.notes.append(marken_note)
    speaker_positions = clip.get("speaker_positions") or (rf.speaker_positions or None)

    # 3) Captions auf der Ausgabe-Timeline
    st.progress(0.35, "Captions auf der Ausgabe-Timeline", clip_id=clip_id, phase="captions")
    common.heartbeat("render", "captions")
    out_words = compose.remap_words(words, comp)
    clip_style, style_note = _load_caption_style(ctx, clip_id)
    if style_note:
        rf.notes.append(style_note)
    style = caption_style_zusammen(extra.get("caption_style") or {}, clip_style)
    preset_name = caption_basis_preset(destination, extra, aspect, style)
    # Erst auf die Ausgabegroesse rechnen, dann den Stil auflegen: die eingestellten Werte gelten
    # fuer 1080x1920, weil die Oberflaeche in dieser Groesse zeigt.
    preset = captions_de.style_anwenden(
        captions_de.scaled_preset(preset_name, out_w, out_h), style, out_h / captions_de.H
    )
    text_field = caption_text_field_for(style)
    cards = captions_de.cards_for(out_words, preset, text_field=text_field)
    cps = captions_de.cps_warnings(
        captions_de.build_cards(out_words, preset.max_chars, preset.max_lines, text_field, preset.words_per_card, preset.all_caps),
        text_field=text_field,
    )
    fid = fidelity_warnings(words, segments, cand.get("start_s"), cand.get("end_s"))
    hook_override = style.get("hook_overlay") if isinstance(style.get("hook_overlay"), bool) else None
    audio_preset = style.get("audio_preset") if style.get("audio_preset") in render_plan.AUDIO_PRESETS else "master"
    brand_assets = brand_assets_for(ctx, extra.get("ci") or {})
    caption_font, schrift_note = caption_schrift(style, brand_assets["font_family"])
    if schrift_note:
        rf.notes.append(schrift_note)
    plan = render_plan.build_plan(
        platform=destination,
        aspect=aspect,
        segments=segments,
        reframe_result=rf,
        # Das ANGEWENDETE Preset, nicht sein Name: sonst trägt der Plan die Vorgaben statt dessen,
        # was wirklich gesetzt wurde, und der Idempotenz-Hash merkt eine Stiländerung nicht.
        caption_preset=preset,
        caption_preset_skaliert=True,
        caption_cards=len(cards),
        sources={"storage_key": src["storage_key"], "transcript_version": tv_version, "hook_version": hook["version"], "candidate_id": cand["id"]},
        src_fps=src.get("fps"),
        title_card=clip.get("title_card"),
        onscreen_hook=hook["onscreen_hook"],
        hook_overlay=hook_override,
        audio_preset=audio_preset,
        caption_font=caption_font,
        brand={
            "font_asset_id": brand_assets["font_asset_id"],
            "logo_asset_id": brand_assets["logo_asset_id"],
            "watermark": brand_assets["watermark"],
        },
        caption_text_field=text_field,
        zeitmarken=zeitmarken,
    )
    try:
        decision_log.record_reframe_strategy(
            ctx.conn, src["workspace_id"], clip_id, plan,
            override=(plan.get("reframe") or {}).get("override"), source_id=source_id, candidate_id=cand["id"],
            brand_profile_id=src.get("brand_profile_id"),
        )  # fmt: skip
    except Exception as exc:
        log.warning("decision log reframe failed clip=%s error=%s", clip_id, exc.__class__.__name__)
    h = render_plan.plan_hash(plan, hook["version"], tv_version)
    keys = {ext: f"{RENDER_PREFIX}/{clip_id}/{h}.{ext}" for ext in ("mp4", "srt", "vtt", "jpg", "ass")}
    keys["streifen"] = f"{RENDER_PREFIX}/{clip_id}/{h}.streifen.jpg"
    duration = render_plan.plan_duration(plan)

    if clip.get("file_key") == keys["mp4"] and ctx.store.exists("derived", keys["mp4"]):
        db.update(conn, "clips", {"id": clip_id}, status="rendered", render_error=None, destination=destination)
        st.finish("Render bereits vorhanden, Schritt übersprungen", skipped=True, clip_id=clip_id, file_key=keys["mp4"], hash=h)
        return

    # 4) Encode
    st.progress(0.5, "Encode: Schnitt, Reframe, Untertitel, Lautheit", clip_id=clip_id, phase="encode")
    common.heartbeat("render", "encode")
    work = ctx.source_dir(source_id) / RENDER_PREFIX / clip_id
    work.mkdir(parents=True, exist_ok=True)
    paths = render.write_captions(
        out_words, preset, (out_w, out_h), work, h, font_family=caption_font, text_field=text_field
    )
    mp4 = work / f"{h}.mp4"
    fonts_dir = brand_assets["fonts_dir"] or s.render_fonts_dir or None
    def einmal_rendern():
        return render.render_from_plan(
            plan, local_src, paths["ass"], mp4,
            fonts_dir=fonts_dir, x264_preset=s.render_x264_preset,
            font_path=brand_assets["font_path"], logo_path=brand_assets["logo_path"],
        )  # fmt: skip

    result = einmal_rendern()
    # Ein beschaedigter Bildstrom kommt vor, selten und ohne erkennbares Muster: zwei von vierzehn
    # Dateien auf der Platte waren betroffen, beide liessen sich mit unveraendertem Plan sauber neu
    # rendern. Eine Ursache habe ich nicht gefunden; ffmpeg lief jedes Mal mit Erfolg durch.
    #
    # Deshalb hier das, was gegen einen zeitweisen Fehler hilft: einmal wiederholen. Bleibt der
    # Schaden, ist er nicht zufaellig, und dann soll der Render scheitern statt eine Datei
    # auszuliefern, die mittendrin stehenbleibt.
    wiederholt = False
    schaden = render.bitstrom_pruefen(mp4)
    if schaden:
        log.warning("clip=%s beschaedigter Bildstrom, wird einmal wiederholt: %s", clip_id, schaden[0])
        result = einmal_rendern()
        wiederholt = True
        schaden = render.bitstrom_pruefen(mp4)
        if schaden:
            raise RuntimeError(f"Der Render ist zweimal beschaedigt herausgekommen: {schaden[0]}")

    notes = [*rf.notes, *brand_assets["notes"], *result.notes]
    if wiederholt:
        notes.append("Der Bildstrom war beschaedigt, der Render wurde einmal wiederholt")
    loud = render.measure_loudness(mp4)
    loudness = {"integrated_lufs": loud["integrated_lufs"], "true_peak_dbtp": loud["true_peak_dbtp"], "preset": plan["audio"]["preset"]}
    # Der Bildstrom ist oben schon geprueft worden; ihn hier noch einmal zu dekodieren waere
    # dieselbe Arbeit zweimal.
    checks = render.regression_checks(mp4, duration, out_w, out_h, bitstrom=False)
    notes.extend(f"Regressionstest: {c}" for c in checks)
    poster = work / f"{h}.jpg"
    render.make_poster(mp4, poster, 1.0)
    # Einzelbilder fuer die Zeitleiste. Faellt das aus, fehlt nur der Filmstreifen; der Clip ist
    # fertig, und ihn deswegen scheitern zu lassen waere falsch herum.
    streifen = work / f"{h}.streifen.jpg"
    streifen_meta = render.make_filmstreifen(mp4, streifen)
    if streifen_meta is None:
        notes.append("Filmstreifen konnte nicht erzeugt werden, die Zeitleiste zeigt keine Einzelbilder")

    probe = ingest.probe(mp4)

    # 5) Provenienz
    st.progress(0.85, "Provenienz und Upload", clip_id=clip_id, phase="provenance")
    common.heartbeat("render", "provenance")
    prov, final_mp4 = _provenance(ctx, mp4, str(src.get("title") or "Clip"), clip, extra)

    ctx.store.put_file("derived", keys["mp4"], final_mp4, CONTENT_TYPES["mp4"])
    ctx.store.put_file("derived", keys["srt"], paths["srt"], CONTENT_TYPES["srt"])
    ctx.store.put_file("derived", keys["vtt"], paths["vtt"], CONTENT_TYPES["vtt"])
    ctx.store.put_file("derived", keys["jpg"], poster, CONTENT_TYPES["jpg"])
    if streifen_meta is not None:
        ctx.store.put_file("derived", keys["streifen"], streifen, CONTENT_TYPES["jpg"])
    ctx.store.put_file("derived", keys["ass"], paths["ass"], CONTENT_TYPES["ass"])

    db.update(
        conn,
        "clips",
        {"id": clip_id},
        file_key=keys["mp4"],
        srt_key=keys["srt"],
        vtt_key=keys["vtt"],
        poster_key=keys["jpg"],
        filmstrip_key=keys["streifen"] if streifen_meta is not None else None,
        filmstrip_meta=db.jsonb(streifen_meta) if streifen_meta is not None else None,
        duration_s=probe.duration_s,
        width=probe.width,
        height=probe.height,
        fps=probe.fps,
        loudness=db.jsonb(loudness),
        provenance=db.jsonb(prov),
        render_plan=db.jsonb(plan),
        cps_warnings=db.jsonb(cps),
        fidelity_warnings=db.jsonb(fid),
        speaker_positions=db.jsonb(speaker_positions) if speaker_positions else None,
        destination=destination,
        status="rendered",
        rendered_at=datetime.now(UTC),
        render_error=None,
    )
    row = db.fetch_one(conn, SQL_CAPTION_MAX, (clip_id,))
    next_version = int(row[0] if row else 0) + 1
    db.insert(
        conn,
        "caption_versions",
        returning="id",
        clip_id=clip_id,
        version=next_version,
        preset=preset.name,
        cards=db.jsonb(cards),
        ass_key=keys["ass"],
        srt_key=keys["srt"],
        cps_warnings=db.jsonb(cps),
        origin="auto",
    )
    usage.book_render(conn, src["workspace_id"])
    costlog.record(
        conn,
        costlog.Cost(
            workspace_id=src["workspace_id"],
            source_id=source_id,
            clip_id=clip_id,
            job_type="render",
            provider="selfhost-eu",
            model_id=None,
            source_minutes=duration / 60.0,
            cpu_seconds=time.monotonic() - t0,
            storage_bytes=Path(final_mp4).stat().st_size,
            llm_input_tokens=sum(int(u.get("in", 0)) for u in llm_usage),
            llm_output_tokens=sum(int(u.get("out", 0)) for u in llm_usage),
        ),
        s,
    )
    st.finish(
        f"Clip für {destination} gerendert ({duration:.1f} s, {loudness['integrated_lufs']:.1f} LUFS)",
        clip_id=clip_id,
        file_key=keys["mp4"],
        hash=h,
        duration_s=probe.duration_s,
        width=probe.width,
        height=probe.height,
        fps=probe.fps,
        loudness=loudness,
        c2pa=prov["c2pa"],
        hook_version=hook["version"],
        hook_origin=hook["origin"],
        transcript_version=tv_version,
        reframe=plan["reframe"],
        captions_burned=result.captions_burned,
        overlays_drawn=result.title_card_drawn or result.hook_overlay_drawn,
        watermark_drawn=result.watermark_drawn,
        font=plan["captions"]["font"],
        caption_text_field=text_field,
        reframe_override=override,
        brand=plan["brand"],
        compressor=result.compressor,
        cps_warnings=len(cps),
        fidelity_warnings=len(fid),
        regression_warnings=checks,
        notes=notes,
        llm_provider=llm_provider,
        cached=False,
    )


@activity.defn(name="render_pack")
def render_pack(candidate_id: str, destination: str) -> str:
    ctx = common.open_context()
    try:
        return run_render_pack(ctx, candidate_id, destination)
    finally:
        ctx.close()


__all__ = [
    "PLATFORMS",
    "RENDER_PREFIX",
    "STEP_RENDER",
    "ad_label_for",
    "brand_assets_for",
    "caption_preset_for",
    "caption_text_field_for",
    "clip_words",
    "fidelity_warnings",
    "render_pack",
    "run_render_pack",
]
