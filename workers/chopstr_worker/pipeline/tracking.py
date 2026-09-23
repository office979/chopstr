"""Wer ist im Bild, wo sitzt er, und wann wechselt die Kamera.

Reine Entscheidungslogik, ohne Videozugriff und damit vollständig ohne Datei testbar. Das Lesen der
Frames bleibt in ``reframe.py``; hierher kommen nur Zahlen.

Drei Aufgaben:

1. KAMERAWECHSEL. Bisher hat ``face_centers`` alle Gesichter eines Clips in eine Punktwolke geworfen
   und die Zeit verworfen. Das setzt eine feste Kamera voraus. Schneidet die Quelle zwischen Totale
   und Naheinstellung, landen Gesichter aus unvereinbaren Bildern im selben Cluster, und der
   Ausschnitt zeigt anschliessend irgendetwas zwischen beiden. Deshalb wird zuerst in Einstellungen
   zerlegt und erst darin geclustert.

2. WER SPRICHT. Ohne Sprechertrennung über den Ton bleibt das Bild. Wessen Mund sich während einer
   gesprochenen Stelle bewegt, ist der Sprecher. Das funktioniert auch in einer Totale mit mehreren
   Personen, wo der Ton allein nicht sagen kann, wo im Bild jemand sitzt.

3. DRITTELREGEL, waagerecht. Senkrecht sass die Gesichtsmitte schon immer bei 37 Prozent der Höhe.
   Waagerecht wurde bisher stumpf zentriert. Wer am linken Bildrand sitzt, schaut in der Regel nach
   rechts; ihn mittig zu setzen nimmt ihm den Blickraum und schneidet das Gegenüber an.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Ein Bildwechsel gilt als Schnitt, wenn sich die Farbverteilung stärker ändert als das. Der Wert
# ist bewusst hoch: ein übersehener Schnitt kostet einen unruhigen Ausschnitt, ein erfundener
# Schnitt zerlegt eine ruhige Einstellung in Stücke und macht alles schlimmer.
SCHNITT_SCHWELLE = 0.45

# Kürzere Einstellungen werden mit der vorigen verschmolzen. Unter dieser Dauer ist keine
# verlässliche Sitzposition zu gewinnen, und der Ausschnitt würde springen.
MIN_EINSTELLUNG_S = 0.8

# Mundbewegung: Wer in einem Fenster deutlich mehr Bewegung zeigt als der ruhigste, gilt als
# Sprecher. Liegen alle dicht beieinander, ist keine Entscheidung möglich und es bleibt bei None.
SPRECHER_VORSPRUNG = 1.6

# Waagerechte Drittelregel: Wie weit muss jemand aus der Bildmitte sitzen, damit ein Blickraum
# angelegt wird. In Anteilen der Quellbreite.
BLICKRAUM_AB = 0.08
DRITTEL = 1.0 / 3.0


@dataclass
class Abtastung:
    """Ein Abtastzeitpunkt: was war zu sehen, und wie stark hat es sich zum Vorbild geändert."""

    t: float
    boxen: list[tuple[int, int, int, int]] = field(default_factory=list)
    # Unterschied der Farbverteilung zum vorigen Abtastpunkt, 0 bis 1. None beim ersten.
    bildwechsel: float | None = None
    # Bewegung in der Mundregion je Box, gleiche Reihenfolge wie ``boxen``.
    mundbewegung: list[float] = field(default_factory=list)


@dataclass
class Einstellung:
    """Ein Abschnitt zwischen zwei Kameraschnitten."""

    start_s: float
    ende_s: float
    abtastungen: list[Abtastung] = field(default_factory=list)

    @property
    def dauer_s(self) -> float:
        return self.ende_s - self.start_s


# -- Kamerawechsel ---------------------------------------------------------------------------------
def schnitte_finden(abtastungen: list[Abtastung], schwelle: float = SCHNITT_SCHWELLE) -> list[int]:
    """Indizes der Abtastpunkte, an denen eine neue Einstellung beginnt (ohne den ersten)."""
    return [i for i, a in enumerate(abtastungen) if i > 0 and a.bildwechsel is not None and a.bildwechsel >= schwelle]


def in_einstellungen_teilen(
    abtastungen: list[Abtastung],
    schwelle: float = SCHNITT_SCHWELLE,
    min_dauer_s: float = MIN_EINSTELLUNG_S,
) -> list[Einstellung]:
    """Abtastpunkte in Einstellungen zerlegen und zu kurze mit der vorigen verschmelzen.

    Das Verschmelzen ist wichtig: Ein Blitzlicht, ein Kameraruckler oder ein harter Helligkeits-
    wechsel erzeugt sonst eine Einstellung von zwei Abtastpunkten, aus der keine Sitzposition
    ableitbar ist.
    """
    if not abtastungen:
        return []
    grenzen = [0, *schnitte_finden(abtastungen, schwelle), len(abtastungen)]
    roh: list[Einstellung] = []
    for a, b in zip(grenzen, grenzen[1:]):
        teil = abtastungen[a:b]
        if not teil:
            continue
        roh.append(Einstellung(start_s=teil[0].t, ende_s=teil[-1].t, abtastungen=teil))

    zusammen: list[Einstellung] = []
    for e in roh:
        if zusammen and e.dauer_s < min_dauer_s:
            vor = zusammen[-1]
            vor.ende_s = e.ende_s
            vor.abtastungen.extend(e.abtastungen)
        else:
            zusammen.append(e)
    # Eine zu kurze erste Einstellung kann erst hinterher verschmolzen werden.
    if len(zusammen) > 1 and zusammen[0].dauer_s < min_dauer_s:
        erste, zweite = zusammen[0], zusammen[1]
        zweite.start_s = erste.start_s
        zweite.abtastungen = [*erste.abtastungen, *zweite.abtastungen]
        zusammen = zusammen[1:]
    return zusammen


# -- Sitzpositionen je Einstellung -----------------------------------------------------------------
def positionen(einstellung: Einstellung, n_max: int = 3) -> list[tuple[float, float]]:
    """Sitzpositionen (x, y) innerhalb EINER Einstellung, nach x sortiert.

    Gleiches Verfahren wie bisher, aber auf einen Abschnitt beschränkt, in dem die Kamera steht.
    """
    punkte = [
        (x + bw / 2.0, y + bh / 2.0)
        for a in einstellung.abtastungen
        for (x, y, bw, bh) in a.boxen
    ]
    if not punkte:
        return []
    xs = sorted(p[0] for p in punkte)
    k = min(n_max, len(set(round(x, -1) for x in xs)))
    if k <= 1:
        return [(sum(p[0] for p in punkte) / len(punkte), sum(p[1] for p in punkte) / len(punkte))]

    mitten = [xs[0] + (xs[-1] - xs[0]) * i / (k - 1) for i in range(k)]
    for _ in range(25):
        gruppen: list[list[tuple[float, float]]] = [[] for _ in range(k)]
        for p in punkte:
            j = min(range(k), key=lambda i: abs(p[0] - mitten[i]))
            gruppen[j].append(p)
        neu = [sum(g[i][0] for i in range(len(g))) / len(g) if g else mitten[j] for j, g in enumerate(gruppen)]
        if all(abs(a - b) < 0.5 for a, b in zip(neu, mitten)):
            mitten = neu
            break
        mitten = neu
    out = []
    for g in gruppen:
        if g:
            out.append((sum(p[0] for p in g) / len(g), sum(p[1] for p in g) / len(g)))
    return sorted(out)


# -- Wer spricht -----------------------------------------------------------------------------------
def sprecher_box(abtastungen: list[Abtastung], vorsprung: float = SPRECHER_VORSPRUNG) -> int | None:
    """Index der Box, deren Mund sich am deutlichsten bewegt, oder None.

    None bedeutet ausdrücklich „nicht entscheidbar", nicht „die erste". Ein geratener Sprecher ist
    schlimmer als gar keiner: Der Ausschnitt springt dann auf eine Person, die schweigt.
    """
    werte: dict[int, list[float]] = {}
    for a in abtastungen:
        for i, wert in enumerate(a.mundbewegung):
            werte.setdefault(i, []).append(float(wert))
    if len(werte) < 2:
        return 0 if werte else None

    # Median, nicht Mittelwert: Ein einzelner Ausschlag (Niesen, Lachen, ein Ruckler im Bild) zieht
    # den Mittelwert so weit hoch, dass eine schweigende Person gewinnen kann. Beim Median hat ein
    # Ausreisser keine Wirkung, und Sprechen ist ohnehin ein Dauerzustand, kein Einzelereignis.
    def median(xs: list[float]) -> float:
        g = sorted(xs)
        n = len(g)
        return g[n // 2] if n % 2 else (g[n // 2 - 1] + g[n // 2]) / 2.0

    mittel = {i: median(v) for i, v in werte.items()}
    sortiert = sorted(mittel.items(), key=lambda kv: kv[1], reverse=True)
    (bester, hoch), (_, zweit) = sortiert[0], sortiert[1]
    if hoch <= 0.0:
        return None
    if zweit <= 0.0:
        return bester
    return bester if hoch / zweit >= vorsprung else None


# -- Drittelregel, waagerecht ----------------------------------------------------------------------
def blickraum_anker(gesicht_cx: float, quelle_breite: float, ab: float = BLICKRAUM_AB) -> float:
    """Wo im Ausschnitt soll das Gesicht sitzen? 0,33 links, 0,5 mittig, 0,67 rechts.

    Wer links der Bildmitte sitzt, wendet sich in aller Regel nach rechts, zum Gegenüber. Dann
    gehört er auf das linke Drittel, damit rechts Blickraum bleibt. Umgekehrt genauso. Nahe der
    Mitte bleibt es bei der Mitte, dort gibt es keine Richtung.

    Ohne Blickrichtungserkennung ist die Sitzposition der beste verfügbare Anhaltspunkt. Das ist
    eine Annahme, keine Messung, und sie ist bei einem Sprecher, der sich wegdreht, falsch.
    """
    if quelle_breite <= 0:
        return 0.5
    versatz = (gesicht_cx - quelle_breite / 2.0) / quelle_breite
    if versatz < -ab:
        return DRITTEL
    if versatz > ab:
        return 1.0 - DRITTEL
    return 0.5


__all__ = [
    "Abtastung",
    "BLICKRAUM_AB",
    "Einstellung",
    "MIN_EINSTELLUNG_S",
    "SCHNITT_SCHWELLE",
    "SPRECHER_VORSPRUNG",
    "blickraum_anker",
    "in_einstellungen_teilen",
    "positionen",
    "schnitte_finden",
    "sprecher_box",
]
