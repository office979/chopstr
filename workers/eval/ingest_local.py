"""Lokale Videodatei als Quelle in die Datenbank eintragen (Eval und Baseline-Läufe ohne Web-Upload).

    cd workers && .venv/bin/python -m eval.ingest_local <datei.mp4> --title "..." [--brief '{"audience": ...}']
                                      [--speakers 2] [--brand <brand_profile_id>] [--workspace <id>]

Legt die Datei im Quell-Speicher ab (``uploads/<uuid>.<ext>``, lokaler Ordner oder S3 je nach Umgebung),
schreibt die ``sources``-Zeile mit ``status = 'uploaded'`` und gibt die Quell-ID aus. Danach verarbeitet
``python -m chopstr_worker.local_worker --once`` die Quelle wie einen Upload aus dem Web (Phase 0 des
Launch-Auftrags, ``docs/MASTER-PROMPT-LAUNCH.md``). Rechtestatus ist ``own``: nur eigenes Material.

Ohne ``--workspace`` wird der einzige Workspace genommen (lokaler Seed); bei mehreren ist die Angabe Pflicht.
Ohne ``--brand`` das erste Markenprofil des Workspace, wenn es genau eines gibt, sonst keines.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import uuid
from pathlib import Path

from chopstr_worker import config, db, storage


def ingest(
    path: Path,
    *,
    title: str,
    brief: dict | None = None,
    speakers: int = 1,
    brand_profile_id: str | None = None,
    workspace_id: str | None = None,
    settings: config.Settings | None = None,
) -> str:
    """Datei ablegen und ``sources``-Zeile anlegen; gibt die Quell-ID zurück."""
    s = settings or config.settings()
    if not path.is_file():
        raise FileNotFoundError(path)
    conn = db.connect(s.database_url)
    try:
        if workspace_id is None:
            rows = conn.execute("select id from workspaces order by created_at").fetchall()
            if len(rows) != 1:
                raise SystemExit(f"{len(rows)} Workspaces gefunden, --workspace ist Pflicht")
            workspace_id = str(rows[0][0])
        if brand_profile_id is None:
            rows = conn.execute(
                "select id from brand_profiles where workspace_id = %s order by created_at", (workspace_id,)
            ).fetchall()
            brand_profile_id = str(rows[0][0]) if len(rows) == 1 else None
        user = conn.execute(
            "select user_id from workspace_members where workspace_id = %s order by accepted_at nulls last limit 1",
            (workspace_id,),
        ).fetchone()
        retention = conn.execute("select retention_days from workspaces where id = %s", (workspace_id,)).fetchone()
        days = int(retention[0]) if retention and retention[0] is not None else 30
        source_id = str(uuid.uuid4())
        ext = path.suffix.lower() or ".mp4"
        key = f"uploads/{source_id}{ext}"
        mime = mimetypes.guess_type(path.name)[0] or "video/mp4"
        storage.Storage(s).put_file("sources", key, path, content_type=mime)
        db.insert(
            conn,
            "sources",
            id=source_id,
            workspace_id=workspace_id,
            brand_profile_id=brand_profile_id,
            title=title,
            original_filename=path.name,
            mime_type=mime,
            size_bytes=path.stat().st_size,
            storage_key=key,
            rights_status="own",
            expected_speakers=speakers,
            brief=json.dumps(brief or {}),
            status="uploaded",
            created_by=str(user[0]) if user else None,
            rights_confirmed_by=str(user[0]) if user else None,
        )
        conn.execute(
            "update sources set rights_confirmed_at = now(), delete_after = now() + make_interval(days => %s) where id = %s",
            (days, source_id),
        )
        conn.commit()
        return source_id
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("datei")
    ap.add_argument("--title", required=True)
    ap.add_argument("--brief", default="{}", help="JSON, Felder audience, wanted, exclude, platform, is_ad")
    ap.add_argument("--speakers", type=int, default=1)
    ap.add_argument("--brand", default=None)
    ap.add_argument("--workspace", default=None)
    args = ap.parse_args(argv)
    brief = json.loads(args.brief)
    if not isinstance(brief, dict):
        raise SystemExit("--brief muss ein JSON-Objekt sein")
    source_id = ingest(
        Path(args.datei), title=args.title, brief=brief, speakers=args.speakers,
        brand_profile_id=args.brand, workspace_id=args.workspace,
    )
    print(source_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
