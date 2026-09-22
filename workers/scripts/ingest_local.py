"""Eine lokale Videodatei als Quelle registrieren, ohne die Web-Oberfläche.

    python -m scripts.ingest_local /pfad/zum/video.mp4 --title "Mein Video"

Macht dasselbe wie der direkte Upload der Web-App (``apps/web/app/api/uploads/direct/route.ts``):
Datei nach ``LOCAL_STORAGE_DIR/<sources-bucket>/uploads/<uuid><ext>`` kopieren, SHA-256 bilden und eine
Zeile in ``sources`` mit ``status = 'uploaded'`` anlegen. Den Rest erledigt der laufende lokale Worker
(``python -m chopstr_worker.local_worker``), der genau diesen Status abholt.

Gedacht für Entwicklung und Abnahme auf der eigenen Maschine. Workspace, Nutzer und Markenprofil kommen
aus der Datenbank (das jüngste vorhandene), angelegt von ``scripts/local-stack.sh start``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import uuid
from pathlib import Path

from chopstr_worker import db, ingest

SOURCES_BUCKET = os.environ.get("S3_BUCKET_SOURCES", "chopstr-sources")


def storage_root() -> Path:
    raw = os.environ.get("LOCAL_STORAGE_DIR")
    if not raw:
        raise SystemExit("LOCAL_STORAGE_DIR fehlt. Erst 'source scripts/local_env.sh' ausführen.")
    return Path(raw).resolve()


def pick_owner(conn) -> tuple[str, str | None, str | None]:
    """Workspace, Markenprofil und Nutzer aus der Datenbank (jeweils der jüngste Eintrag)."""
    row = db.fetch_one(conn, "select id from workspaces order by created_at limit 1")
    if not row:
        raise SystemExit("Kein Workspace vorhanden. Erst 'scripts/local-stack.sh start' laufen lassen.")
    workspace_id = str(row[0])
    brand = db.fetch_one(
        conn,
        "select id from brand_profiles where workspace_id = %s order by created_at limit 1",
        (workspace_id,),
    )
    user = db.fetch_one(
        conn,
        "select user_id from workspace_members where workspace_id = %s order by created_at limit 1",
        (workspace_id,),
    )
    return workspace_id, (str(brand[0]) if brand else None), (str(user[0]) if user else None)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lokale Videodatei als Quelle registrieren")
    ap.add_argument("video", help="Pfad zur Video- oder Audiodatei")
    ap.add_argument("--title", default=None, help="Titel (Default: Dateiname ohne Endung)")
    ap.add_argument("--speakers", type=int, default=None, help="Erwartete Sprecheranzahl")
    args = ap.parse_args(argv)

    src = Path(args.video).expanduser().resolve()
    if not src.is_file():
        raise SystemExit(f"Datei nicht gefunden: {src}")

    title = args.title or src.stem
    root = storage_root()
    uploads = root / SOURCES_BUCKET / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)

    new_id = uuid.uuid4()
    ext = src.suffix or ".mp4"
    target = uploads / f"{new_id}{ext}"
    storage_key = f"uploads/{new_id}{ext}"

    print(f"Kopiere {src.name} ({src.stat().st_size / 1e6:.0f} MB) nach {target}")
    shutil.copy2(src, target)
    sha = ingest.sha256_file(target)
    print(f"SHA-256 {sha[:16]}…")

    with db.connect() as conn:
        workspace_id, brand_id, user_id = pick_owner(conn)
        source_id = db.insert(
            conn,
            "sources",
            returning="id",
            id=new_id,
            workspace_id=workspace_id,
            brand_profile_id=brand_id,
            title=title,
            original_filename=src.name,
            mime_type="video/mp4",
            size_bytes=target.stat().st_size,
            sha256=sha,
            storage_key=storage_key,
            rights_status="own",
            rights_confirmed_by=user_id,
            expected_speakers=args.speakers,
            brief=db.jsonb({}),
            status="uploaded",
            created_by=user_id,
        )
        conn.commit()

    print(f"Quelle angelegt: {source_id}")
    print("Der laufende Worker holt sie beim nächsten Durchlauf ab (alle 3 Sekunden).")
    print(f"Weboberfläche: http://localhost:3000/projekte/{source_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
