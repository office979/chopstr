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

# Wie oft muss eine Position ueberhaupt messbar sein, damit sie als Sprecher in Frage kommt, im
# Verhaeltnis zur bestbelegten Position. Wer nur in jedem siebten Bild auftaucht, ist keine
# verlaessliche Grundlage: An BP CW gewann sonst eine Erkennung mit 5 Messungen gegen den echten
# Sprecher mit 32, allein weil ihr Median hoeher lag.
MINDEST_PRAESENZ = 0.4

# Wie viele Sitzpositionen hoechstens. Die alte Grenze von drei stammt aus der Welt mit nur
# „talking_head" und „two_speakers". An BP CW sitzen sieben Personen an einem Tisch; mit drei
# Positionen fielen vier davon unter den Tisch und der Sprecher war womoeglich nicht dabei.
MAX_POSITIONEN = 8

# Waagerechte Drittelregel: Wie weit muss jemand aus der Bildmitte sitzen, damit ein Blickraum
# angelegt wird. In Anteilen der Quellbreite.
BLICKRAUM_AB = 0.08
DRITTEL = 1.0 / 3.0

# Eine Haeufung mit weniger Rueckhalt als das gilt als Fehlerkennung, nicht als Person.
MINDEST_ANTEIL = 0.12

# Mundbewegung, die nicht verglichen werden konnte (erstes Bild, direkt nach einem Schnitt, oder die
# Box ist gesprungen). Ausdruecklich keine Aussage, nicht etwa „keine Bewegung".
NICHT_MESSBAR = -1.0


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
def positionen(einstellung: Einstellung, n_max: int = MAX_POSITIONEN, mindest_anteil: float = MINDEST_ANTEIL) -> list[tuple[float, float]]:
    """Sitzpositionen (x, y) innerhalb EINER Einstellung, nach x sortiert.

    Getrennt wird an echten Lücken, nicht mit einer vorgegebenen Clusterzahl. Der bisherige Weg
    setzte k auf die Zahl unterschiedlicher gerundeter x-Werte, was bei stetigen Werten fast immer
    das Höchstmass ergab; k-Means zersägte dann EINE Häufung in drei Teile und lieferte Positionen,
    an denen niemand sitzt. Gemessen an einem echten Video: eine Person ergab die Positionen 1126,
    2147 und 3234.

    Der Mindestabstand kalibriert sich selbst an der Gesichtsbreite: Zwei Erkennungen, die näher
    beieinander liegen als ein halbes Gesicht, sind dieselbe Person. Häufungen mit zu wenig
    Rückhalt fliegen raus, das sind in aller Regel Fehlerkennungen (Poster, Spiegelungen).
    """
    punkte = [
        (x + bw / 2.0, y + bh / 2.0, bw)
        for a in einstellung.abtastungen
        for (x, y, bw, bh) in a.boxen
    ]
    if not punkte:
        return []

    breiten = sorted(p[2] for p in punkte)
    mittlere_breite = breiten[len(breiten) // 2]
    mindest_abstand = max(1.0, mittlere_breite * 0.5)

    punkte.sort(key=lambda p: p[0])
    gruppen: list[list[tuple[float, float, float]]] = [[punkte[0]]]
    for p in punkte[1:]:
        if p[0] - gruppen[-1][-1][0] > mindest_abstand:
            gruppen.append([p])
        else:
            gruppen[-1].append(p)

    schwelle = max(1, int(len(punkte) * mindest_anteil))
    stark = [g for g in gruppen if len(g) >= schwelle]
    if not stark:
        stark = [max(gruppen, key=len)]
    stark.sort(key=len, reverse=True)
    stark = stark[:n_max]

    out = [(sum(q[0] for q in g) / len(g), sum(q[1] for q in g) / len(g)) for g in stark]
    return sorted(out)


# -- Wer spricht -----------------------------------------------------------------------------------
def sprecher_position(
    abtastungen: list[Abtastung],
    positionen_xy: list[tuple[float, float]],
    vorsprung: float = SPRECHER_VORSPRUNG,
) -> int | None:
    """Index der Sitzposition, an der gesprochen wird, oder None.

    Zugeordnet wird ueber die Lage im Bild, NICHT ueber den Listenindex der Erkennung. Der Detektor
    liefert die Gesichter je Bild in wechselnder Reihenfolge; an einem echten Video gemessen:

        t=76.0  x=[1304, 2595]
        t=76.2  x=[2596, 1305]   <- gekippt
        t=76.4  x=[1305, 2593]

    Wer ueber den Index summiert, vermischt die Mundbewegung zweier Menschen und bekommt fuer beide
    denselben Mittelwert. Genau daran ist die erste Fassung gescheitert, ohne dass ein Test es
    zeigen konnte: in erdachten Daten steht die Reihenfolge fest.

    None heisst ausdruecklich „nicht entscheidbar", nicht „die erste". Ein geratener Sprecher ist
    schlimmer als gar keiner, weil der Ausschnitt dann auf jemanden springt, der schweigt.
    """
    if not positionen_xy:
        return None
    if len(positionen_xy) == 1:
        return 0

    werte: dict[int, list[float]] = {}
    for a in abtastungen:
        for (x, _y, bw, _bh), bewegung in zip(a.boxen, a.mundbewegung):
            if float(bewegung) < 0.0:
                continue  # nicht vergleichbar, siehe NICHT_MESSBAR
            cx = x + bw / 2.0
            j = min(range(len(positionen_xy)), key=lambda i: abs(positionen_xy[i][0] - cx))
            werte.setdefault(j, []).append(float(bewegung))
    if len(werte) < 2:
        return next(iter(werte), None)

    # Median, nicht Mittelwert: Ein einzelner Ausschlag (Niesen, Lachen, ein Ruckler im Bild) zieht
    # den Mittelwert so weit hoch, dass eine schweigende Person gewinnen kann. Beim Median hat ein
    # Ausreisser keine Wirkung, und Sprechen ist ohnehin ein Dauerzustand, kein Einzelereignis.
    def median(xs: list[float]) -> float:
        g = sorted(xs)
        n = len(g)
        return g[n // 2] if n % 2 else (g[n // 2 - 1] + g[n // 2]) / 2.0

    hoechste_belegung = max(len(v) for v in werte.values())
    brauchbar = {i: v for i, v in werte.items() if len(v) >= hoechste_belegung * MINDEST_PRAESENZ}
    if len(brauchbar) < 2:
        return next(iter(brauchbar), None)

    mittel = {i: median(v) for i, v in brauchbar.items()}
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
    "MINDEST_ANTEIL",
    "MAX_POSITIONEN",
    "MINDEST_PRAESENZ",
    "NICHT_MESSBAR",
    "MIN_EINSTELLUNG_S",
    "SCHNITT_SCHWELLE",
    "SPRECHER_VORSPRUNG",
    "blickraum_anker",
    "in_einstellungen_teilen",
    "positionen",
    "schnitte_finden",
    "sprecher_position",
]
