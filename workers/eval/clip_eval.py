"""Messlatte für die Clip-Auswahl: findet die Pipeline gute Stellen, und schneidet sie sauber?

    .venv/bin/python -m eval.clip_eval --titel "Jakob Test"
    .venv/bin/python -m eval.clip_eval --quelle <uuid> --referenzen eval/clips --json messung.json

Zwei Fragen, getrennt gemessen:

(a) TREFFER. Nur mit Referenzstellen aus ``eval/clips`` (Format siehe README dort). Ein Vorschlag
    zählt als Treffer, wenn er mindestens die Hälfte der markierten Stelle abdeckt. Daraus folgen
    Trefferquote und Precision@k.

(b) GRENZEN. Ohne Referenz messbar, deshalb sofort nutzbar. Je Vorschlag: Beginnt er auf einem
    Satzanfang? Endet er auf einem Satzende? Fängt er mit einem Rückverweis an („und", „aber",
    „das", „deswegen", „wie gesagt")? Wird eine Verneinung am Rand abgeschnitten? Wie lang ist er?

Die Daten kommen aus der Datenbank, das Video muss also durch die Analyse gelaufen sein. Gemessen
wird der Zustand vor jeder Nachbearbeitung, damit Läufe vergleichbar bleiben.

Die Ausgabe geht als Tabelle in die Konsole und auf Wunsch als JSON in eine Datei. Das JSON ist das
eigentliche Ergebnis: nur damit lassen sich zwei Läufe gegeneinander halten.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from chopstr_worker import db
from chopstr_worker.pipeline import dach_nlp

# Wörter, die auf etwas vorher Gesagtes verweisen. Beginnt ein Clip damit, fehlt dem Zuschauer der
# Bezug.
#
# Zwei Gruppen, weil sie unterschiedlich sicher sind:
#
# EINDEUTIG sind Konjunktionen und Adverbien, die ohne Vorlauf nicht funktionieren. „Deswegen haben
# wir das gemacht" verlangt ein Davor, egal in welchem Satz es steht.
#
# MEHRDEUTIG sind Wörter, die als Artikel völlig harmlos und als Demonstrativpronomen ein
# Rückverweis sind. „Der Empfänger prüft zuerst" ist ein sauberer Anfang, „Das ist genau der Punkt"
# nicht. Beide beginnen mit demselben Wortstamm. Der Unterschied steht nur in der Wortart, deshalb
# entscheidet hier spaCy: PDS und PDAT sind Demonstrativpronomen, ART ist ein Artikel. Ohne spaCy
# werden diese Fälle NICHT gemeldet, lieber ein übersehener Treffer als ein falscher Alarm, der die
# Messung unbrauchbar macht.
BACKREF_CLEAR = dach_nlp.OPEN_LOOP_END | {
    "dadurch", "darum", "daher", "dann", "damit", "davon", "dafür", "dagegen",
    "außerdem", "zudem", "genau", "naja",
}  # fmt: skip
BACKREF_AMBIGUOUS = {"das", "dies", "dieses", "diese", "dieser", "diesem", "dem", "den", "der", "die"}
BACKREF_POS_TAGS = {"PDS", "PDAT"}  # substituierend („das ist") und attribuierend („dieser Punkt")
BACKREF_PHRASES = {"wie gesagt", "wie eben", "wie vorhin", "wie erwähnt", "das heißt", "und zwar"}

# So viele Wörter am Rand gelten als „am Rand". Eine Verneinung, die hier steht, verliert leicht
# ihren Bezug, wenn davor oder danach geschnitten wird.
EDGE_WORDS = 3

SQL_SOURCE_BY_ID = "select id, title, duration_s from sources where id = %s and status <> 'deleted'"
SQL_SOURCE_BY_TITLE = (
    "select id, title, duration_s from sources where title ilike %s and status <> 'deleted' "
    "order by created_at desc limit 1"
)
SQL_WORDS = "select words from transcript_versions where source_id = %s order by version desc limit 1"
SQL_CANDIDATES = (
    "select id, start_s, end_s, total, gate_passed, why from candidates "
    "where source_id = %s order by coalesce(total, 0) desc, start_s asc"
)


# -- Laden ---------------------------------------------------------------------------------------
def load_source(conn, source_id: str | None, titel: str | None) -> dict[str, Any]:
    if source_id:
        row = db.fetch_one(conn, SQL_SOURCE_BY_ID, (source_id,))
        if row is None:
            raise SystemExit(f"Quelle {source_id} nicht gefunden.")
    else:
        row = db.fetch_one(conn, SQL_SOURCE_BY_TITLE, (f"%{titel}%",))
        if row is None:
            raise SystemExit(f"Keine Quelle gefunden, deren Titel „{titel}“ enthält.")
    return {"id": str(row[0]), "title": row[1], "duration_s": float(row[2]) if row[2] is not None else None}


def load_words(conn, source_id: str) -> list[dict]:
    row = db.fetch_one(conn, SQL_WORDS, (source_id,))
    if row is None:
        raise SystemExit("Zu dieser Quelle gibt es kein Transkript. Ist die Analyse durchgelaufen?")
    words = row[0]
    if isinstance(words, str):
        words = json.loads(words)
    return list(words or [])


def load_candidates(conn, source_id: str) -> list[dict]:
    rows = db.fetch_all(conn, SQL_CANDIDATES, (source_id,))
    return [
        {
            "id": str(r[0]),
            "start_s": float(r[1]),
            "end_s": float(r[2]),
            "total": float(r[3]) if r[3] is not None else None,
            "gate_passed": bool(r[4]),
            "why": r[5],
        }
        for r in rows
    ]


def load_references(ordner: str | None) -> list[dict]:
    if not ordner:
        return []
    pfad = Path(ordner)
    if not pfad.is_dir():
        raise SystemExit(f"Referenzordner {ordner} gibt es nicht.")
    stellen: list[dict] = []
    for datei in sorted(pfad.glob("*.json")):
        daten = json.loads(datei.read_text(encoding="utf-8"))
        for s in daten.get("stellen", []):
            stellen.append(
                {
                    "datei": datei.name,
                    "video": daten.get("video"),
                    "start_s": float(s["start_s"]),
                    "end_s": float(s["end_s"]),
                    "grund": s.get("grund", ""),
                }
            )
    return stellen


# -- Teil b: Grenzen -----------------------------------------------------------------------------
def word_index_at(words: list[dict], t: float, kante: str) -> int | None:
    """Index des Wortes, das an Sekunde ``t`` beginnt (kante="start") bzw. endet (kante="ende").

    Gesucht wird das nächstgelegene Wort, weil die Kandidatengrenzen einen Puffer enthalten können.
    """
    if not words:
        return None
    feld = "start" if kante == "start" else "end"
    bester, beste_diff = None, None
    for i, w in enumerate(words):
        wert = w.get(feld)
        if wert is None:
            continue
        diff = abs(float(wert) - t)
        if beste_diff is None or diff < beste_diff:
            bester, beste_diff = i, diff
    return bester


def first_token(text: str) -> str:
    return dach_nlp.core_token(str(text or ""))


def starts_with_backref(words: list[dict], i_start: int, i_ende: int) -> bool | None:
    """Beginnt der Clip mit einem Rückverweis?

    None bedeutet: nicht entscheidbar, weil das Wort mehrdeutig ist und spaCy fehlt. Das ist ehrlicher
    als ein geratenes Nein und fällt in der Auswertung als „?" auf.
    """
    erstes = first_token(words[i_start].get("text"))
    zwei = " ".join(first_token(w.get("text")) for w in words[i_start : i_start + 2])
    if erstes in BACKREF_CLEAR or zwei in BACKREF_PHRASES:
        return True
    if erstes not in BACKREF_AMBIGUOUS:
        return False

    pipe = dach_nlp.nlp()
    if pipe is None:
        return None
    # Der ganze Satzanfang, damit spaCy den Kontext hat: ein einzelnes „Das" ist nicht auflösbar.
    ende = min(i_start + 8, i_ende + 1)
    satz = " ".join(str(w.get("text", "")) for w in words[i_start:ende]).strip()
    if not satz:
        return None
    doc = pipe(satz)
    if not len(doc):
        return None
    return doc[0].tag_ in BACKREF_POS_TAGS


def check_boundaries(cand: dict, words: list[dict]) -> dict[str, Any]:
    """Grenzqualität eines Vorschlags. Alle Werte sind für sich verständlich, ohne Referenzstellen."""
    i_start = word_index_at(words, cand["start_s"], "start")
    i_ende = word_index_at(words, cand["end_s"], "ende")
    laenge = round(cand["end_s"] - cand["start_s"], 2)

    if i_start is None or i_ende is None or i_start > i_ende:
        return {
            "laenge_s": laenge,
            "satzanfang": False,
            "satzende": False,
            "beginnt_mit_rueckverweis": None,
            "verneinung_am_rand": None,
            "hinweis": "Grenzen liegen außerhalb des Transkripts",
        }

    # Satzanfang: das Wort davor beendet einen Satz, oder der Clip beginnt am Anfang der Aufnahme.
    satzanfang = i_start == 0 or dach_nlp.is_sentence_end(words, i_start - 1)
    # Satzende: das letzte Wort des Clips beendet einen Satz.
    satzende = dach_nlp.is_sentence_end(words, i_ende)

    rueckverweis = starts_with_backref(words, i_start, i_ende)

    # Verneinung am Rand: steht in den ersten oder letzten Wörtern eine Verneinung, kann ihr Bezug
    # außerhalb des Clips liegen. Das ist der Fall, der aus „kein Problem" ein „Problem" macht.
    rand = list(range(i_start, min(i_start + EDGE_WORDS, i_ende + 1)))
    rand += list(range(max(i_ende - EDGE_WORDS + 1, i_start), i_ende + 1))
    verneinung_am_rand = any(first_token(words[i].get("text")) in dach_nlp.NEGATIONS for i in set(rand))

    return {
        "laenge_s": laenge,
        "satzanfang": bool(satzanfang),
        "satzende": bool(satzende),
        # Nicht nach bool zwingen: None heisst „nicht entscheidbar" und muss das bleiben, sonst
        # sieht ein unklarer Fall wie ein sauberer aus.
        "beginnt_mit_rueckverweis": rueckverweis,
        "verneinung_am_rand": bool(verneinung_am_rand),
        "erstes_wort": words[i_start].get("text"),
        "letztes_wort": words[i_ende].get("text"),
    }


def sauber(b: dict[str, Any]) -> bool:
    """Ein Vorschlag gilt als sauber geschnitten, wenn alle vier Grenzprüfungen stimmen."""
    return bool(b.get("satzanfang")) and bool(b.get("satzende")) and not b.get("beginnt_mit_rueckverweis") and not b.get("verneinung_am_rand")


# -- Teil a: Treffer -----------------------------------------------------------------------------
def abdeckung(vorschlag: dict, stelle: dict) -> float:
    """Anteil der Referenzstelle, den der Vorschlag abdeckt (0 bis 1)."""
    a = max(vorschlag["start_s"], stelle["start_s"])
    b = min(vorschlag["end_s"], stelle["end_s"])
    schnitt = max(0.0, b - a)
    dauer = max(1e-6, stelle["end_s"] - stelle["start_s"])
    return schnitt / dauer


def iou(vorschlag: dict, stelle: dict) -> float:
    a = max(vorschlag["start_s"], stelle["start_s"])
    b = min(vorschlag["end_s"], stelle["end_s"])
    schnitt = max(0.0, b - a)
    vereinigung = (vorschlag["end_s"] - vorschlag["start_s"]) + (stelle["end_s"] - stelle["start_s"]) - schnitt
    return schnitt / vereinigung if vereinigung > 0 else 0.0


def match_references(kandidaten: list[dict], stellen: list[dict], schwelle: float, k: int) -> dict[str, Any]:
    """Jede Referenzstelle bekommt höchstens einen Vorschlag, jeder Vorschlag höchstens eine Stelle."""
    paare = []
    for si, s in enumerate(stellen):
        for ki, kand in enumerate(kandidaten):
            deckung = abdeckung(kand, s)
            if deckung >= schwelle:
                paare.append((deckung, si, ki, iou(kand, s)))
    paare.sort(reverse=True)

    stelle_vergeben: set[int] = set()
    kandidat_vergeben: dict[int, int] = {}
    treffer = []
    for deckung, si, ki, ov in paare:
        if si in stelle_vergeben or ki in kandidat_vergeben:
            continue
        stelle_vergeben.add(si)
        kandidat_vergeben[ki] = si
        treffer.append({"stelle": si, "kandidat": ki, "abdeckung": round(deckung, 3), "iou": round(ov, 3)})

    topk = [i for i in range(min(k, len(kandidaten)))]
    treffer_in_topk = sum(1 for i in topk if i in kandidat_vergeben)
    return {
        "stellen_gesamt": len(stellen),
        "gefunden": len(treffer),
        "trefferquote": round(len(treffer) / len(stellen), 3) if stellen else None,
        f"precision_at_{k}": round(treffer_in_topk / len(topk), 3) if topk else None,
        "treffer": treffer,
        "verpasst": [
            {"start_s": s["start_s"], "end_s": s["end_s"], "grund": s["grund"]}
            for si, s in enumerate(stellen)
            if si not in stelle_vergeben
        ],
    }


# -- Ausgabe -------------------------------------------------------------------------------------
def ja(wert: Any) -> str:
    if wert is None:
        return "?"
    return "ja" if wert else "nein"


def tabelle(zeilen: list[dict]) -> str:
    kopf = f"{'#':>2}  {'von':>8}  {'bis':>8}  {'Länge':>6}  {'Bew':>4}  {'Satzanfang':>10}  {'Satzende':>8}  {'Rückverweis':>11}  {'Verneinung':>10}  Sauber"
    linien = [kopf, "-" * len(kopf)]
    for i, z in enumerate(zeilen, start=1):
        b = z["grenzen"]
        bew = f"{z['total']:.1f}" if z.get("total") is not None else "  -"
        linien.append(
            f"{i:>2}  {z['start_s']:>8.1f}  {z['end_s']:>8.1f}  {b['laenge_s']:>6.1f}  {bew:>4}  "
            f"{ja(b['satzanfang']):>10}  {ja(b['satzende']):>8}  {ja(b['beginnt_mit_rueckverweis']):>11}  "
            f"{ja(b['verneinung_am_rand']):>10}  {'ja' if sauber(b) else 'nein'}"
        )
    return "\n".join(linien)


def zusammenfassung(zeilen: list[dict]) -> dict[str, Any]:
    n = len(zeilen)
    if n == 0:
        return {"vorschlaege": 0}
    g = [z["grenzen"] for z in zeilen]
    laengen = sorted(x["laenge_s"] for x in g)
    return {
        "vorschlaege": n,
        "satzanfang_anteil": round(sum(1 for x in g if x["satzanfang"]) / n, 3),
        "satzende_anteil": round(sum(1 for x in g if x["satzende"]) / n, 3),
        "rueckverweis_anteil": round(sum(1 for x in g if x["beginnt_mit_rueckverweis"] is True) / n, 3),
        # Mehrdeutige Anfänge ohne spaCy. Grösser als null heisst: die Zahl darüber ist zu niedrig.
        "rueckverweis_unklar": sum(1 for x in g if x["beginnt_mit_rueckverweis"] is None),
        "verneinung_am_rand_anteil": round(sum(1 for x in g if x["verneinung_am_rand"] is True) / n, 3),
        "sauber_anteil": round(sum(1 for x in g if sauber(x)) / n, 3),
        "laenge_median_s": laengen[n // 2],
        "laenge_min_s": laengen[0],
        "laenge_max_s": laengen[-1],
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Misst Trefferquote und Schnittgrenzen der Clip-Auswahl.")
    gruppe = ap.add_mutually_exclusive_group(required=True)
    gruppe.add_argument("--quelle", help="UUID der Quelle")
    gruppe.add_argument("--titel", help="Teil des Titels, jüngste passende Quelle wird genommen")
    ap.add_argument("--referenzen", default=None, help="Ordner mit Referenzstellen, z. B. eval/clips")
    ap.add_argument("--k", type=int, default=10, help="Precision@k, Standard 10")
    ap.add_argument("--schwelle", type=float, default=0.5, help="Mindestabdeckung für einen Treffer, Standard 0,5")
    ap.add_argument("--json", dest="json_out", default=None, help="Ergebnis zusätzlich als JSON ablegen")
    args = ap.parse_args(argv)

    if not os.environ.get("DATABASE_URL"):
        raise SystemExit("DATABASE_URL fehlt. Vorher: source scripts/local_env.sh")

    conn = db.connect()
    try:
        quelle = load_source(conn, args.quelle, args.titel)
        words = load_words(conn, quelle["id"])
        kandidaten = load_candidates(conn, quelle["id"])
    finally:
        conn.close()

    if not kandidaten:
        raise SystemExit("Zu dieser Quelle gibt es keine Vorschläge. Ist die Analyse durchgelaufen?")

    zeilen = []
    for kand in kandidaten:
        zeilen.append({**kand, "grenzen": check_boundaries(kand, words)})

    stellen = load_references(args.referenzen)
    ergebnis: dict[str, Any] = {
        "quelle": {"id": quelle["id"], "titel": quelle["title"], "dauer_s": quelle["duration_s"]},
        "woerter": len(words),
        "grenzen": zusammenfassung(zeilen),
        "vorschlaege": zeilen,
    }
    if stellen:
        ergebnis["treffer"] = match_references(kandidaten, stellen, args.schwelle, args.k)

    print(f"Quelle: {quelle['title']}  ({quelle['id']})")
    dauer = f"{quelle['duration_s']:.0f} s" if quelle["duration_s"] else "unbekannt"
    print(f"Dauer: {dauer}, Transkript: {len(words)} Wörter, Vorschläge: {len(kandidaten)}")
    print()
    print(tabelle(zeilen))
    print()

    z = ergebnis["grenzen"]
    print("Grenzen über alle Vorschläge:")
    print(f"  beginnt auf Satzanfang   {z['satzanfang_anteil'] * 100:5.1f} %")
    print(f"  endet auf Satzende       {z['satzende_anteil'] * 100:5.1f} %")
    unklar = f"   {z['rueckverweis_unklar']} unklar ohne spaCy" if z["rueckverweis_unklar"] else ""
    print(f"  beginnt mit Rückverweis  {z['rueckverweis_anteil'] * 100:5.1f} %   (niedriger ist besser){unklar}")
    print(f"  Verneinung am Rand       {z['verneinung_am_rand_anteil'] * 100:5.1f} %   (niedriger ist besser)")
    print(f"  komplett sauber          {z['sauber_anteil'] * 100:5.1f} %")
    print(f"  Länge: Median {z['laenge_median_s']:.1f} s, von {z['laenge_min_s']:.1f} bis {z['laenge_max_s']:.1f} s")

    if stellen:
        t = ergebnis["treffer"]
        print()
        print(f"Treffer gegen {t['stellen_gesamt']} Referenzstellen:")
        print(f"  gefunden        {t['gefunden']} von {t['stellen_gesamt']}  ({(t['trefferquote'] or 0) * 100:.1f} %)")
        print(f"  Precision@{args.k}    {(t[f'precision_at_{args.k}'] or 0) * 100:.1f} %")
        if t["verpasst"]:
            print("  verpasst:")
            for v in t["verpasst"]:
                print(f"    {v['start_s']:.1f} bis {v['end_s']:.1f}  {v['grund']}")
    else:
        print()
        print("Keine Referenzstellen geladen. Gemessen wurden nur die Schnittgrenzen.")
        print("Referenzstellen anlegen: siehe eval/clips/README.md")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(ergebnis, ensure_ascii=False, indent=2), encoding="utf-8")
        print()
        print(f"JSON geschrieben: {args.json_out}")


if __name__ == "__main__":
    main(sys.argv[1:])
