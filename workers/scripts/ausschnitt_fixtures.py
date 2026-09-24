"""Feste Werte aus dem Renderer, gegen die die Spiegelung in TypeScript prueft.

Die Ausschnitt-Rechnung steht zweimal da: hier im Worker und in apps/web/lib/clips/ausschnitt.ts,
damit die Vorschau sofort zeigt, was eine Aenderung bewirkt. Zwei Stellen laufen mit der Zeit
auseinander. Deshalb prueft der Test drueben nicht gegen erdachte Werte, sondern gegen die Datei,
die dieses Skript erzeugt.

Neu erzeugen nach jeder Aenderung an crop_geometry, crop_origin, plan_shots_aus_zielen oder
blickraum_anker:

    cd workers && .venv/bin/python -m scripts.ausschnitt_fixtures > ../apps/web/tests/fixtures-ausschnitt.json
"""

from __future__ import annotations

import json

from chopstr_worker.pipeline import reframe, tracking


def main() -> None:
    faelle = []
    for src_w, src_h in ((3840, 2160), (1920, 1080), (1080, 1920)):
        for out in ((1080, 1920), (1080, 1350)):
            for cx, zoom, anker in (
                (None, 1.0, 0.5),
                (960.0, 1.0, 0.5),
                (2582.0, 1.0, 2 / 3),
                (1306.0, 1.3, 1 / 3),
                (100.0, 1.6, 2 / 3),
                (3700.0, 1.6, 1 / 3),
            ):
                z = tracking.Ziel(
                    0.0, 5.0, cx, src_h * 0.45 if cx is not None else None, anker, "sprecher", 300.0, [], zoom
                )  # fmt: skip
                shots = reframe.plan_shots_aus_zielen(
                    [{"start": 0.0, "end": 5.0, "role": "body"}], [[z]], src_w, src_h, out[0], out[1]
                )  # fmt: skip
                s = shots[0]
                faelle.append({
                    "src": [src_w, src_h], "out": list(out), "cx": cx, "cy": z.cy, "zoom": zoom, "anker": anker,
                    "erwartet": {"x": s.crop_x, "y": s.crop_y, "w": s.crop_w, "h": s.crop_h},
                })  # fmt: skip

    anker_faelle = [
        {"cx": cx, "breite": breite, "andere": andere, "erwartet": round(tracking.blickraum_anker(cx, breite, andere), 6)}
        for cx, breite, andere in (
            (400.0, 1920, []),
            (1500.0, 1920, []),
            (960.0, 1920, []),
            (1000.0, 3840, [2000.0, 2600.0]),
            (2600.0, 3840, [700.0, 1300.0]),
            (1100.0, 3840, [700.0, 1400.0, 2100.0, 3000.0]),
        )
    ]  # fmt: skip
    print(json.dumps({"ausschnitt": faelle, "anker": anker_faelle}, indent=1))


if __name__ == "__main__":
    main()
