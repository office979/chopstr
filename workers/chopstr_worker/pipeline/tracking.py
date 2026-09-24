"""Wer ist im Bild, wo sitzt er, und wann wechselt die Kamera.

Reine Entscheidungslogik, ohne Videozugriff und damit vollständig ohne Datei testbar. Das Lesen der
Frames bleibt in ``reframe.py``; hierher kommen nur Zahlen.

Drei Aufgaben:

1. KAMERAWECHSEL. Bis hierher wurden alle Gesichter eines Clips in eine Punktwolke geworfen und die
   Zeit verworfen. Das setzt eine feste Kamera voraus. Schneidet die Quelle zwischen Totale
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

# Ab wann ein Bildwechsel als Kameraschnitt gilt. ``bildwechsel`` ist der Bhattacharyya-Abstand der
# Farbverteilung zum vorigen Abtastpunkt, 0 bis 1.
#
# An BP CW gemessen, 60 Sekunden mit sechs Schnitten: ruhige Stellen liegen bei 0,04 (95. Perzentil
# 0,05), die Schnitte bei 0,24 bis 0,32. Die Untergrenze liegt dazwischen.
#
# Ein fester Wert allein trägt nicht: eine dunkle Handkamera rauscht deutlich stärker als ein
# ausgeleuchtetes Studio. Deshalb zusätzlich ein Vielfaches des Medians der Aufnahme selbst. Der
# Median ist unempfindlich dagegen, dass ein paar Abtastpunkte Schnitte sind, denn Schnitte sind
# immer die Minderheit.
SCHNITT_SCHWELLE = 0.15
SCHNITT_FAKTOR = 3.0

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

# Wie fein innerhalb EINER Einstellung nach dem Sprecher gesucht wird. Feiner reagiert schneller auf
# einen Sprecherwechsel, kostet aber Ruhe im Bild; die Mindestdauer darunter faengt das wieder ab.
FENSTER_S = 1.2

# Kuerzer darf kein Ausschnitt stehen. Ein Bild, das haeufiger springt, ist nicht mehr zu lesen.
MIN_ZIEL_S = 1.2

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


@dataclass
class Ziel:
    """Was in einem Zeitabschnitt im Ausschnitt stehen soll.

    ``cx``/``cy`` ist die Bildstelle, auf die der Ausschnitt gelegt wird; ``None`` heisst, dass kein
    Gesicht messbar war und mittig geschnitten wird. ``anker`` sagt, WO im Ausschnitt diese Stelle
    sitzt (Drittelregel). ``grund`` haelt fest, warum es dieses Ziel wurde, damit im Nachhinein
    nachvollziehbar bleibt, ob die Wahl gemessen oder geraten war.
    """

    start_s: float
    ende_s: float
    cx: float | None = None
    cy: float | None = None
    anker: float = 0.5
    grund: str = "kein_gesicht"

    @property
    def dauer_s(self) -> float:
        return self.ende_s - self.start_s


# -- Kamerawechsel ---------------------------------------------------------------------------------
def schnitt_schwelle(abtastungen: list[Abtastung], untergrenze: float = SCHNITT_SCHWELLE, faktor: float = SCHNITT_FAKTOR) -> float:
    """Ab welchem Bildwechsel in DIESER Aufnahme ein Schnitt angenommen wird.

    Die Untergrenze verhindert, dass in einer sehr ruhigen Aufnahme jedes Flackern zum Schnitt wird;
    das Vielfache des Medians verhindert, dass in einer unruhigen Aufnahme jede zweite Bewegung als
    Schnitt zählt.
    """
    werte = sorted(a.bildwechsel for a in abtastungen if a.bildwechsel is not None)
    if not werte:
        return untergrenze
    n = len(werte)
    median = werte[n // 2] if n % 2 else (werte[n // 2 - 1] + werte[n // 2]) / 2.0
    return max(untergrenze, median * faktor)


def schnitte_finden(abtastungen: list[Abtastung], schwelle: float | None = None) -> list[int]:
    """Indizes der Abtastpunkte, an denen eine neue Einstellung beginnt (ohne den ersten)."""
    if schwelle is None:
        schwelle = schnitt_schwelle(abtastungen)
    return [i for i, a in enumerate(abtastungen) if i > 0 and a.bildwechsel is not None and a.bildwechsel >= schwelle]


def in_einstellungen_teilen(
    abtastungen: list[Abtastung],
    schwelle: float | None = None,
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



# -- Was wann im Bild stehen soll ------------------------------------------------------------------
def _haeufigste_position(einstellung: Einstellung, positionen_xy: list[tuple[float, float]]) -> int:
    """Index der Position, die in dieser Einstellung am oeftesten erkannt wurde."""
    zaehler = [0] * len(positionen_xy)
    for a in einstellung.abtastungen:
        for x, _y, bw, _bh in a.boxen:
            cx = x + bw / 2.0
            zaehler[min(range(len(positionen_xy)), key=lambda i: abs(positionen_xy[i][0] - cx))] += 1
    return max(range(len(zaehler)), key=lambda i: zaehler[i])


def _fenster(einstellung: Einstellung, positionen_xy: list[tuple[float, float]], fenster_s: float) -> list[list]:
    """Die Einstellung in gleich lange Fenster zerlegen und je Fenster fragen, wer spricht.

    Ergebnis je Fenster: ``[start_s, ende_s, index_oder_None]``.
    """
    aus: list[list] = []
    t = einstellung.start_s
    while t < einstellung.ende_s:
        t1 = min(t + fenster_s, einstellung.ende_s)
        im_fenster = [a for a in einstellung.abtastungen if t <= a.t < t1]
        aus.append([t, t1, sprecher_position(im_fenster, positionen_xy) if im_fenster else None])
        t = t1
    if not aus:
        aus.append([einstellung.start_s, einstellung.ende_s, sprecher_position(einstellung.abtastungen, positionen_xy)])
    # Ein angeschnittenes letztes Fenster hat zu wenig Messungen fuer eine eigene Entscheidung.
    if len(aus) > 1 and (aus[-1][1] - aus[-1][0]) < fenster_s * 0.5:
        aus[-2][1] = aus[-1][1]
        aus.pop()
    return aus


def _luecken_fuellen(fenster: list[list]) -> bool:
    """Fenster ohne Entscheidung uebernehmen die Entscheidung davor, sonst die danach.

    Gibt zurueck, ob ueberhaupt eine Entscheidung vorlag. Wer schweigt, verschwindet sonst aus dem
    Bild, obwohl er gleich weiterspricht: eine kurze Pause ist kein Sprecherwechsel.
    """
    letzte = None
    for f in fenster:
        if f[2] is None:
            f[2] = letzte
        else:
            letzte = f[2]
    naechste = None
    for f in reversed(fenster):
        if f[2] is None:
            f[2] = naechste
        else:
            naechste = f[2]
    return any(f[2] is not None for f in fenster)


def _gleiche_nachbarn(laeufe: list[list]) -> list[list]:
    """Aufeinanderfolgende Abschnitte mit derselben Person zu einem zusammenziehen."""
    aus: list[list] = []
    for start, ende, idx in laeufe:
        if aus and aus[-1][2] == idx:
            aus[-1][1] = ende
        else:
            aus.append([start, ende, idx])
    return aus


def _zu_laeufen(fenster: list[list], min_ziel_s: float) -> list[list]:
    """Gleiche Nachbarn zusammenfassen und zu kurze Laeufe aufloesen.

    Nach jedem Aufloesen wird erneut zusammengefasst. Ohne das bleiben zwei benachbarte Abschnitte
    mit derselben Person stehen, nur weil zwischen ihnen einmal ein kurzer Zwischenruf lag: derselbe
    Ausschnitt, zweimal geplant, und im Render eine Schnittmarke, hinter der sich nichts aendert.
    """
    laeufe = _gleiche_nachbarn(fenster)
    geaendert = True
    while geaendert and len(laeufe) > 1:
        geaendert = False
        for i, lauf in enumerate(laeufe):
            if lauf[1] - lauf[0] >= min_ziel_s:
                continue
            # Zu kurz: die Zeit faellt an den Nachbarn davor, am Anfang an den danach.
            if i > 0:
                laeufe[i - 1][1] = lauf[1]
            else:
                laeufe[i + 1][0] = lauf[0]
            laeufe.pop(i)
            laeufe = _gleiche_nachbarn(laeufe)
            geaendert = True
            break
    return laeufe


def ziele(
    einstellungen: list[Einstellung],
    quelle_breite: float,
    folgen: bool = True,
    fenster_s: float = FENSTER_S,
    min_ziel_s: float = MIN_ZIEL_S,
) -> list[Ziel]:
    """Aus den gemessenen Einstellungen wird, wer wann im Hochformat zu sehen ist.

    Je Einstellung getrennt, denn ueber einen Kameraschnitt hinweg bedeutet dieselbe Bildstelle
    einen anderen Menschen. Innerhalb einer Einstellung mit mehreren Personen wird fensterweise
    gefragt, wessen Mund sich bewegt, und das Ergebnis auf ruhige Laeufe geglaettet.

    ``folgen=False`` bleibt je Einstellung bei der am oeftesten erkannten Person. Das ist die
    Strategie ``talking_head``: Kameraschnitte werden weiterhin beachtet, aber innerhalb einer
    Einstellung springt der Ausschnitt nicht.

    Laesst sich in einer Totale niemand als Sprecher bestimmen, wird die Mitte der Gruppe gezeigt
    statt auf gut Glueck eine Person. Ein geratener Sprecher ist der schlechtere Fehler: dann steht
    jemand gross im Bild, der gerade schweigt.
    """
    aus: list[Ziel] = []
    for e in einstellungen:
        pos = positionen(e)
        if not pos:
            aus.append(Ziel(e.start_s, e.ende_s, None, None, 0.5, "kein_gesicht"))
            continue
        if len(pos) == 1 or not folgen:
            i = 0 if len(pos) == 1 else _haeufigste_position(e, pos)
            cx, cy = pos[i]
            grund = "einzige_person" if len(pos) == 1 else "haeufigste_person"
            aus.append(Ziel(e.start_s, e.ende_s, cx, cy, blickraum_anker(cx, quelle_breite), grund))
            continue

        fenster = _fenster(e, pos, fenster_s)
        if not _luecken_fuellen(fenster):
            cx = sum(p[0] for p in pos) / len(pos)
            cy = sum(p[1] for p in pos) / len(pos)
            aus.append(Ziel(e.start_s, e.ende_s, cx, cy, 0.5, "gruppe_unentschieden"))
            continue
        for start, ende, idx in _zu_laeufen(fenster, min_ziel_s):
            cx, cy = pos[idx]
            aus.append(Ziel(start, ende, cx, cy, blickraum_anker(cx, quelle_breite), "sprecher"))
    return aus


__all__ = [
    "Abtastung",
    "FENSTER_S",
    "MIN_ZIEL_S",
    "Ziel",
    "BLICKRAUM_AB",
    "Einstellung",
    "MINDEST_ANTEIL",
    "MAX_POSITIONEN",
    "MINDEST_PRAESENZ",
    "NICHT_MESSBAR",
    "MIN_EINSTELLUNG_S",
    "SCHNITT_FAKTOR",
    "SCHNITT_SCHWELLE",
    "SPRECHER_VORSPRUNG",
    "blickraum_anker",
    "in_einstellungen_teilen",
    "positionen",
    "schnitt_schwelle",
    "schnitte_finden",
    "sprecher_position",
    "ziele",
]
