"""Einen Moment annehmen und Clips anlegen, ohne die Web-Oberfläche.

    python -m scripts.accept_local --source <uuid> --platform tiktok
    python -m scripts.accept_local --source <uuid> --platform tiktok --original-format

Spiegelt ``repo.createClips`` aus ``apps/web/lib/repo/postgres.ts``: setzt ``human_verdict = 'accepted'``
am Kandidaten und legt je Zielplattform eine ``clips``-Zeile mit ``status = 'draft'`` an. Der laufende
lokale Worker rendert alles, was ``draft`` ist und dessen Kandidat angenommen wurde.

``--original-format`` entspricht dem ausgeschalteten Hochformat-Schalter in der Oberfläche: der Clip
behält das Seitenverhältnis der Quelle, statt auf das Plattformformat beschnitten zu werden.

Gedacht für Entwicklung und Abnahme auf der eigenen Maschine. Die Oberfläche bleibt der reguläre Weg;
dieses Skript existiert, damit die Renderkette ohne Browser geprüft werden kann.
"""

from __future__ import annotations

import argparse
import sys

from chopstr_worker import db

PLATFORM_ASPECT = {"tiktok": "9:16", "reels": "9:16", "shorts": "9:16", "linkedin": "4:5"}
ASPECT_RATIOS = [("9:16", 9 / 16), ("4:5", 4 / 5), ("1:1", 1.0), ("16:9", 16 / 9)]


def aspect_for_source(width: int | None, height: int | None) -> str | None:
    """Nächstgelegenes unterstütztes Seitenverhältnis (Spiegel von aspectForSource in presets.ts)."""
    if not width or not height:
        return None
    ratio = width / height
    return min(ASPECT_RATIOS, key=lambda item: abs(item[1] - ratio))[0]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Moment annehmen und Clips anlegen (lokal)")
    ap.add_argument("--source", required=True, help="Quellen-ID")
    ap.add_argument("--platform", default="tiktok", choices=sorted(PLATFORM_ASPECT), help="Zielplattform")
    ap.add_argument("--candidate", default=None, help="Kandidaten-ID (Default: der bestbewertete)")
    ap.add_argument(
        "--original-format",
        action="store_true",
        help="Hochformat aus: der Clip behält das Format der Quelle",
    )
    args = ap.parse_args(argv)

    with db.connect() as conn:
        src = db.fetch_one(conn, "select width, height, title from sources where id = %s", (args.source,))
        if not src:
            raise SystemExit(f"Quelle nicht gefunden: {args.source}")
        width, height, title = src

        if args.candidate:
            cand = db.fetch_one(
                conn,
                "select id, segments, rubric from candidates where id = %s and source_id = %s",
                (args.candidate, args.source),
            )
        else:
            cand = db.fetch_one(
                conn,
                """select id, segments, rubric from candidates
                   where source_id = %s and human_verdict is distinct from 'edited'
                   order by gate_passed desc, total desc nulls last limit 1""",
                (args.source,),
            )
        if not cand:
            raise SystemExit("Kein Kandidat vorhanden. Lief die Analyse schon durch?")
        candidate_id, segments, rubric = cand

        if args.original_format:
            aspect = aspect_for_source(width, height) or PLATFORM_ASPECT[args.platform]
        else:
            aspect = PLATFORM_ASPECT[args.platform]

        title_card = (rubric or {}).get("suggested_title_card") or None
        if title_card:
            title_card = title_card.strip() or None

        db.update(conn, "candidates", {"id": candidate_id}, human_verdict="accepted")

        existing = db.fetch_one(
            conn,
            "select id from clips where candidate_id = %s and platform = %s order by created_at desc limit 1",
            (candidate_id, args.platform),
        )
        if existing:
            clip_id = existing[0]
            db.update(conn, "clips", {"id": clip_id}, status="draft", aspect=aspect)
            print(f"Vorhandener Clip {clip_id} zurückgesetzt auf draft, Format {aspect}")
        else:
            clip_id = db.insert(
                conn,
                "clips",
                returning="id",
                source_id=args.source,
                candidate_id=candidate_id,
                platform=args.platform,
                destination=args.platform,
                aspect=aspect,
                composition=db.jsonb(segments),
                title_card=title_card,
                status="draft",
            )
            print(f"Clip angelegt: {clip_id}")
        conn.commit()

    print(f"Video „{title}“ ({width}x{height}) → {args.platform}, Format {aspect}")
    print("Der laufende Worker rendert beim nächsten Durchlauf.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
