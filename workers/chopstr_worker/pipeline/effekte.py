"""Effekte auf der Zeitachse des Clips: Zoom hinein, Zoom heraus.

WOZU. Ein Zoom betont. Bisher kannte der Renderer nur einen langsamen Push-in über eine ganze
Einstellung (``motion.zoom_to``) - eine Grundbewegung, die immer läuft und nichts hervorhebt. Was
fehlte, war die Stelle: „hier, auf dieses Wort, für anderthalb Sekunden".

DIE BEWEGUNG IST EIN ZUSTANDSWECHSEL, KEIN AUSSCHLAG. Ein Block ist die FAHRT: über seine Länge
fährt das Bild weich von der bisherigen Nähe auf die neue. Danach bleibt es dort - auch wenn der
Block längst vorbei ist. Wer wieder herauswill, setzt einen „heraus" dahinter.

Das ist der Unterschied zu einem Ausschlag, der hin und gleich wieder her geht: der sah aus wie
Wackeln, mitten im Satz. Ein Schnittprogramm arbeitet mit Zuständen, und die Fahrt dazwischen ist
das, was man in der Zeitleiste länger oder kürzer zieht.

Die Wirkungen addieren sich: zwei „hinein" hintereinander gehen doppelt so nah. Begrenzt wird das
auf ``MIN_FAKTOR`` bis ``MAX_FAKTOR`` - darüber hinaus gibt es keine Bildpunkte mehr, und darunter
wäre das Bild eine Briefmarke.

„Heraus" ist das Spiegelbild: das Bild wird kleiner, rundherum steht Schwarz.

WARUM ES EINEN RAND BRAUCHT. Kleiner zu werden heisst, mehr zu zeigen als da ist. ``zoompan`` kann
nur hineingehen (``z >= 1``). Deshalb wird das Bild vor dem Zoom auf eine grössere schwarze Fläche
gelegt (``RESERVE``), und der Ruhezustand ist dann nicht ``z = 1``, sondern ``z = RESERVE``. Von
dort aus geht es in beide Richtungen.

DIE ZEITRECHNUNG. ``ab_s`` ist die Sekunde IM FERTIGEN CLIP, wie bei den Zeitmarken. Wer den
Schnitt ändert, verschiebt damit die Effekte - richtig so, sie hängen an dem, was gesagt wird.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

ARTEN = ("zoom_in", "zoom_out")

# Wie nah der Zoom geht. Zehn Prozent sind bei einem hochkanten Clip deutlich sichtbar und noch
# nicht ruckartig; darüber wird aus Betonung Effekthascherei.
STAERKE = 0.10

MIN_DAUER_S = 0.4
MAX_DAUER_S = 6.0
STANDARD_DAUER_S = 1.0

# Wieviel schwarze Flaeche rund um das Bild vorgehalten wird, damit „heraus" ueberhaupt moeglich
# ist. 1,25 erlaubt eine Verkleinerung auf 80 Prozent - mehr braucht niemand, und jeder Prozentpunkt
# kostet Aufloesung, weil das Bild vorher hochskaliert werden muss.
RESERVE = 1.25

# Wie weit der Zoom insgesamt gehen darf. Nach oben begrenzt die Aufloesung: vor dem Zoom wird auf
# das Doppelte skaliert, darueber hinaus wird das Bild weich. Nach unten begrenzt die Reserve, auf
# der das Bild liegt (1/RESERVE = 0,8).
MAX_FAKTOR = 1.6
MIN_FAKTOR = 0.8

# Zwei Betonungen dicht hintereinander heben sich auf: das Bild wackelt, und betont ist nichts
# mehr. Mindestens so viele Sekunden zwischen zwei automatisch gesetzten Effekten.
MIN_ABSTAND_S = 4.0

# Die ersten Sekunden gehören dem Einstieg. Ein Zoom auf das erste Wort wirkt wie ein Fehler.
VORLAUF_S = 1.0


@dataclass
class Effekt:
    art: str
    ab_s: float
    dauer_s: float

    def als_dict(self) -> dict[str, Any]:
        return asdict(self)


def _zahl(v: Any, ersatz: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ersatz
    return f if f == f and abs(f) != float("inf") else ersatz


def lesen(roh: Any, clip_dauer_s: float) -> list[Effekt]:
    """Aus dem, was in der Datenbank steht, eine geprüfte Liste machen.

    Grosszügig beim Lesen, streng beim Ergebnis: unbekannte Arten fliegen raus, Zeiten werden in
    den Clip hineingeschoben, zu kurze und zu lange Dauern begrenzt, und Überschneidungen
    aufgelöst. Ein Effekt, der über das Ende hinausragt, wird gekürzt statt verworfen - der Nutzer
    hat ihn gesetzt, nur der Schnitt ist seitdem kürzer geworden."""
    if not isinstance(roh, list):
        return []
    aus: list[Effekt] = []
    for e in roh:
        if not isinstance(e, dict):
            continue
        art = str(e.get("art") or "")
        if art not in ARTEN:
            continue
        ab = max(0.0, _zahl(e.get("ab_s"), 0.0))
        if ab >= clip_dauer_s:
            continue
        dauer = _zahl(e.get("dauer_s"), STANDARD_DAUER_S)
        dauer = min(max(dauer, MIN_DAUER_S), MAX_DAUER_S, clip_dauer_s - ab)
        if dauer < MIN_DAUER_S:
            continue
        aus.append(Effekt(art, round(ab, 3), round(dauer, 3)))
    aus.sort(key=lambda e: e.ab_s)
    return _entzerren(aus)


def _entzerren(effekte: list[Effekt]) -> list[Effekt]:
    """Überschneidungen auflösen: der frühere gewinnt, der spätere rückt nach.

    Zwei Zooms übereinander addieren sich im Bild. Das sieht nicht nach zwei Betonungen aus,
    sondern nach einem Fehler."""
    aus: list[Effekt] = []
    for e in effekte:
        if aus and e.ab_s < aus[-1].ab_s + aus[-1].dauer_s:
            neu_ab = aus[-1].ab_s + aus[-1].dauer_s
            rest = e.ab_s + e.dauer_s - neu_ab
            if rest < MIN_DAUER_S:
                continue
            e = Effekt(e.art, round(neu_ab, 3), round(rest, 3))
        aus.append(e)
    return aus


def faktor(effekte: list[Effekt], t: float) -> float:
    """Der Zoomfaktor zum Zeitpunkt ``t`` (Sekunden im Clip). 1,0 heisst: unberührt.

    Dieselbe Rechnung wie der ffmpeg-Ausdruck weiter unten und wie die Vorschau in der Oberfläche.
    Drei Umsetzungen derselben Kurve sind eine zu viel - deshalb ist diese hier die Wahrheit, und
    die Tests halten die anderen daran fest."""
    z = 1.0
    for e in effekte:
        if t <= e.ab_s:
            continue
        z += _vorzeichen(e.art) * STAERKE * _form(t - e.ab_s, e.dauer_s)
    return min(MAX_FAKTOR, max(MIN_FAKTOR, z))


def _form(t_im_effekt: float, dauer_s: float) -> float:
    """Wie weit die Fahrt fortgeschritten ist: 0 am Anfang des Blocks, 1 an seinem Ende und danach.

    Smoothstep: die Fahrt setzt ohne Knick an und kommt ohne Knick an. Ein linearer Verlauf setzt
    sichtbar an und bricht sichtbar ab, und genau das nimmt man als Ruckeln wahr."""
    if dauer_s <= 0 or t_im_effekt >= dauer_s:
        return 1.0
    if t_im_effekt <= 0:
        return 0.0
    x = t_im_effekt / dauer_s
    return x * x * (3.0 - 2.0 * x)


def _vorzeichen(art: str) -> float:
    return -1.0 if art == "zoom_out" else 1.0


def ffmpeg_ausdruck(effekte: list[Effekt], fps: float) -> str:
    """Derselbe Verlauf als ``z``-Ausdruck für ``zoompan``.

    Der Ruhezustand ist ``RESERVE`` und nicht 1: das Bild liegt auf einer groesseren schwarzen
    Flaeche, und erst dadurch kann „heraus" ueberhaupt kleiner werden. Der zurueckgegebene Ausdruck
    ist also ``RESERVE * faktor``.

    ``on`` ist die Nummer des Ausgabeframes, geteilt durch die Bildrate also die Sekunde im Clip.
    Die Summanden stehen hintereinander; ausserhalb seiner Zeit liefert jeder 0."""
    if not effekte:
        return f"{RESERVE:.4f}"
    teile = ["1"]
    for e in effekte:
        seit = f"((on/{fps:g})-{e.ab_s:.3f})"
        x = f"min(1,max(0,{seit}/{e.dauer_s:.3f}))"
        form = f"({x}*{x}*(3-2*({x})))"
        # Kein „between": die Wirkung bleibt, auch wenn der Block laengst vorbei ist.
        teile.append(f"{_vorzeichen(e.art) * STAERKE:.4f}*{form}")
    roh = "+".join(teile)
    return f"{RESERVE:.4f}*min({MAX_FAKTOR:.3f},max({MIN_FAKTOR:.3f},{roh}))"


def automatisch(woerter: list[dict], clip_dauer_s: float) -> list[Effekt]:
    """Effekte setzen, wo betont wird.

    WORAUF. Auf Zahlen und auf Wörter, mit denen jemand eine Aussage ankündigt („entscheidend",
    „wichtig", „das Ergebnis"). Beides steht im Text, beides ist ohne Sprachmodell erkennbar, und
    beides ist der Moment, in dem ein Zuschauer aufhört zu scrollen.

    WORAUF NICHT. Nicht auf die erste Sekunde (das wirkt wie ein Fehler), nicht zweimal dicht
    hintereinander (dann wackelt das Bild), und nicht mehr als drei Mal - eine Betonung, die
    ständig kommt, ist keine."""
    anker: list[float] = []
    for w in woerter:
        t = _zahl(w.get("start"), -1.0)
        if t < VORLAUF_S or t > clip_dauer_s - MIN_DAUER_S:
            continue
        text = str(w.get("text") or "")
        if _betont(text):
            anker.append(t)

    aus: list[Effekt] = []
    for t in anker:
        if len(aus) >= 3:
            break
        if aus and t < aus[-1].ab_s + max(aus[-1].dauer_s, MIN_ABSTAND_S):
            continue
        dauer = min(STANDARD_DAUER_S, clip_dauer_s - t)
        if dauer < MIN_DAUER_S:
            continue
        # Kurz VOR dem Wort ansetzen, damit die Bewegung auf dem Wort ihren Höhepunkt hat und
        # nicht erst danach.
        ab = max(0.0, t - 0.15)
        aus.append(Effekt("zoom_in", round(ab, 3), round(dauer, 3)))
    return _entzerren(aus)


ZAHL = re.compile(r"\d")
# Wörter, mit denen jemand ankündigt, dass jetzt etwas kommt. Bewusst kurz gehalten: eine lange
# Liste trifft irgendwann jeden Satz, und dann betont sie nichts mehr.
ANKUENDIGUNG = {
    "entscheidend",
    "wichtig",
    "wichtigste",
    "ergebnis",
    "genau",
    "punkt",
    "fehler",
    "achtung",
    "merk",
    "merkt",
    "niemals",
    "immer",
    "nie",
}


def _betont(text: str) -> bool:
    roh = text.strip().strip(".,;:!?\"'„“»«()").lower()
    if not roh:
        return False
    if ZAHL.search(roh):
        return True
    return roh in ANKUENDIGUNG


def als_liste(effekte: list[Effekt]) -> list[dict[str, Any]]:
    return [e.als_dict() for e in effekte]
