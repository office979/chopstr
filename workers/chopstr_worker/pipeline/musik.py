"""Musik unter den Clip legen: welches Stück, welche Stelle, wie laut.

WOZU. Ein Clip ohne Musik klingt nach Rohmaterial. Mit Musik klingt er nach einem Stück Arbeit -
und zwar schon in der ersten Sekunde, in der jemand entscheidet, ob er weiterschaut.

DIE STELLE IST DIE HALBE MIETE. Ein Musikstück ist zwei bis drei Minuten lang, der Clip dreissig
Sekunden. Welche dreissig Sekunden davon unter dem Clip liegen, entscheidet alles: ein Stück, das
mit vierzig Sekunden Aufbau beginnt, klingt am Anfang nach nichts. Deshalb ``ab_s`` - die Sekunde
IM STÜCK, an der die Wiedergabe beginnt. Wer die Musikspur in der Zeitleiste verschiebt, ändert
genau diese Zahl.

DUCKING statt Lautstärke-Raten. Musik unter Sprache ist immer zu laut oder zu leise, wenn sie eine
feste Lautstärke hat: in den Pausen zu leise, unter den Worten zu laut. ``sidechaincompress``
senkt die Musik genau dann, wenn jemand spricht, und lässt sie in den Pausen wieder hoch. Das ist
das, was ein Mensch von Hand mit Hüllkurven machen würde.

WAS HIER NICHT ENTSCHIEDEN WIRD. Welches Stück zu welchem Clip passt. Dafür braucht es ein
Sprachmodell, das den Text liest - siehe providers_llm. Solange keines angebunden ist, wählt der
Mensch im Dropdown, und diese Datei legt nur unter, was er gewählt hat.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Wie laut die Musik gegenüber der Sprache liegt, in Dezibel. -18 ist der Wert, den man aus
# Erfahrung nimmt: hörbar, aber nie im Weg. Der Nutzer kann ihn verschieben.
STANDARD_DB = -18.0
MIN_DB = -40.0
MAX_DB = 0.0

# Ein- und Ausblenden an den Rändern des Clips. Ohne sie setzt die Musik mit einem Knacks ein und
# bricht am Ende mitten im Takt ab - beides hört man sofort, auch wer nicht hinhört.
EINBLENDE_S = 0.8
AUSBLENDE_S = 1.2

# Ducking: wie stark die Musik unter der Sprache weicht.
#   threshold  ab welchem Sprachpegel gesenkt wird
#   ratio      wie stark
#   attack/release  wie schnell herunter und wieder herauf (in Millisekunden)
# Die Werte sind bewusst träge im Release: springt die Musik nach jedem Wort zurück, pumpt es.
DUCK_THRESHOLD = 0.06
DUCK_RATIO = 8.0
DUCK_ATTACK_MS = 20.0
DUCK_RELEASE_MS = 600.0


@dataclass
class Musik:
    """Was unter dem Clip liegt. ``quelle`` trennt die eigene Datei vom Katalogstück."""

    quelle: str  # "katalog" | "eigen"
    datei: str  # Ablageschlüssel oder Katalogdatei
    name: str
    ab_s: float
    lautstaerke_db: float
    ducking: bool

    def als_dict(self) -> dict[str, Any]:
        return {
            "quelle": self.quelle,
            "datei": self.datei,
            "name": self.name,
            "ab_s": round(self.ab_s, 3),
            "lautstaerke_db": round(self.lautstaerke_db, 1),
            "ducking": self.ducking,
        }


def _zahl(v: Any, ersatz: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ersatz
    return f if f == f and abs(f) != float("inf") else ersatz


def lesen(roh: Any) -> Musik | None:
    """Aus dem, was in der Datenbank steht, eine geprüfte Angabe machen - oder nichts.

    Grosszügig beim Lesen, streng beim Ergebnis: ohne Datei gibt es keine Musik, und eine
    Lautstärke ausserhalb des Bereichs wird hereingeholt statt abgewiesen. Ein Clip soll nicht
    deshalb scheitern, weil in einer alten Zeile eine Zahl zu gross steht."""
    if not isinstance(roh, dict):
        return None
    datei = str(roh.get("datei") or "").strip()
    if not datei:
        return None
    quelle = str(roh.get("quelle") or "eigen")
    if quelle not in ("katalog", "eigen"):
        quelle = "eigen"
    db = min(MAX_DB, max(MIN_DB, _zahl(roh.get("lautstaerke_db"), STANDARD_DB)))
    return Musik(
        quelle=quelle,
        datei=datei,
        name=str(roh.get("name") or "").strip() or datei,
        ab_s=max(0.0, _zahl(roh.get("ab_s"), 0.0)),
        lautstaerke_db=db,
        ducking=bool(roh.get("ducking", True)),
    )


def ffmpeg_kette(m: Musik, eingang: int, clip_dauer_s: float, sprache: str = "[ac]") -> tuple[str, str]:
    """Die Filterkette, die Musik unter die Sprache legt. Gibt (Kette, Ausgangslabel) zurück.

    Die Reihenfolge ist nicht beliebig:

    1. ``atrim`` schneidet die gewählte Stelle heraus. ``asetpts`` setzt die Zeit auf null zurück,
       sonst läge die Musik um ``ab_s`` versetzt hinter dem Clipende.
    2. ``apad`` verlängert notfalls mit Stille: ein Stück, das kürzer ist als der Clip, würde sonst
       die Mischung vorzeitig beenden.
    3. ``volume`` setzt den Grundpegel, ``afade`` die Ränder.
    4. ``sidechaincompress`` senkt die Musik, wenn gesprochen wird. Die Sprache ist dabei nur der
       Auslöser und geht NICHT durch den Filter - sie bleibt unangetastet.
    5. ``amix`` mit ``normalize=0``: die Voreinstellung halbiert beide Pegel, und dann ist die
       mühsam gesetzte Lautstärke wieder falsch.

    Gemischt wird VOR loudnorm. Andersherum wäre die Endlautheit die von Sprache allein gemessene,
    und der fertige Clip läge über dem, was die Plattformen erwarten."""
    dauer = max(clip_dauer_s, 0.1)
    aus_ab = max(dauer - AUSBLENDE_S, 0.0)
    teile = [
        f"[{eingang}:a]atrim=start={m.ab_s:.3f}:duration={dauer:.3f},"
        f"asetpts=PTS-STARTPTS,"
        f"apad=whole_dur={dauer:.3f},"
        f"volume={m.lautstaerke_db:.1f}dB,"
        f"afade=t=in:st=0:d={EINBLENDE_S:.2f},"
        f"afade=t=out:st={aus_ab:.3f}:d={AUSBLENDE_S:.2f}[mus];"
    ]
    if m.ducking:
        # Die Sprache wird zweimal gebraucht: einmal als AUSLÖSER für das Ducking, einmal in der
        # Mischung selbst. Ein Label lässt sich in ffmpeg aber nur einmal verbrauchen - ohne
        # dieses asplit bricht der Lauf mit „Cannot find a matching stream" ab.
        teile.append(f"{sprache}asplit=2[spr_a][spr_b];")
        teile.append(
            f"[mus][spr_a]sidechaincompress="
            f"threshold={DUCK_THRESHOLD}:ratio={DUCK_RATIO}:"
            f"attack={DUCK_ATTACK_MS:g}:release={DUCK_RELEASE_MS:g}[musd];"
        )
        teile.append("[spr_b][musd]amix=inputs=2:duration=first:normalize=0[amus];")
    else:
        teile.append(f"{sprache}[mus]amix=inputs=2:duration=first:normalize=0[amus];")
    return "".join(teile), "[amus]"


__all__ = [
    "AUSBLENDE_S",
    "EINBLENDE_S",
    "MAX_DB",
    "MIN_DB",
    "Musik",
    "STANDARD_DB",
    "ffmpeg_kette",
    "lesen",
]
