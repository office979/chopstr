"""Aus fertigen Beispielclips lernen, was einen guten Clip ausmacht.

    .venv/bin/python -m eval.learn_from_examples --positiv "/pfad/Positive Beispiele" \
        --negativ "/pfad/Negative Beispiele" --out eval/clips/beispiele.json

Die Redaktion hat gute und schlechte Clips geliefert, aber keine Zeitmarken im Quellvideo. Die
Clips tragen ihren Text jedoch selbst. Dieses Skript transkribiert sie und misst an jedem Clip
dieselben Merkmale, die ``eval/clip_eval.py`` an den Vorschlaegen der Pipeline misst. Aus dem
Vergleich der beiden Gruppen ergibt sich, worin sie sich unterscheiden.

Bewusst nur Beschreibung, keine Bewertung: das Skript sagt nicht, was richtig ist, es zaehlt nur
aus. Welche Unterschiede bedeutsam sind, entscheidet der Mensch, der die Tabelle liest.

Transkription laeuft lokal ueber denselben Weg wie die Pipeline (faster-whisper, CPU). Ergebnisse
werden je Datei zwischengespeichert, ein zweiter Lauf ist deshalb schnell.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from chopstr_worker import ingest
from chopstr_worker.pipeline import dach_nlp, transcribe
from eval import clip_eval

VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v"}


def schluessel(video: Path) -> str:
    """Eindeutiger Name für den Zwischenspeicher.

    Der Dateiname allein reicht nicht: Beide Beispielordner enthalten Dateien mit exakt denselben
    Namen („Download (2).mp4"). Mit dem Dateinamen als Schlüssel bekäme der negative Clip das
    Transkript des positiven und der Vergleich wäre wertlos, ohne dass man es merkt. Der Ordnername
    kommt deshalb mit hinein.
    """
    return f"{video.parent.name}__{video.stem}".replace(" ", "_").replace("/", "_")


def audio_of(video: Path, work: Path) -> Path:
    """16-kHz-Mono-WAV wie im Ingest, damit die Transkription dieselbe Grundlage hat."""
    out = work / f"{schluessel(video)}.wav"
    if not out.is_file():
        ingest.extract_audio(str(video), str(out))
    return out


def transcribe_clip(video: Path, work: Path) -> dict[str, Any]:
    cache = work / f"{schluessel(video)}.json"
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    wav = audio_of(video, work)
    res = transcribe.transcribe(str(wav), variant="de")
    words = [dict(w) for w in res.words]
    daten = {"datei": video.name, "woerter": words, "text": " ".join(str(w.get("text", "")) for w in words)}
    cache.write_text(json.dumps(daten, ensure_ascii=False), encoding="utf-8")
    return daten


def measure(daten: dict[str, Any], dauer_s: float) -> dict[str, Any]:
    """Dieselben Merkmale wie in clip_eval, plus ein paar, die nur am fertigen Clip messbar sind."""
    words = daten["woerter"]
    if not words:
        return {"datei": daten["datei"], "dauer_s": round(dauer_s, 1), "woerter": 0, "hinweis": "keine Sprache erkannt"}

    cand = {"start_s": float(words[0].get("start", 0.0)), "end_s": float(words[-1].get("end", dauer_s))}
    grenzen = clip_eval.check_boundaries(cand, words)

    sprech_s = max(1e-6, cand["end_s"] - cand["start_s"])
    saetze = dach_nlp.sentence_boundaries(words)
    # Vorlauf bis zum ersten Wort und Nachlauf nach dem letzten: zeigt, wie eng geschnitten wird.
    vorlauf = cand["start_s"]
    nachlauf = max(0.0, dauer_s - cand["end_s"])

    return {
        "datei": daten["datei"],
        "dauer_s": round(dauer_s, 1),
        "woerter": len(words),
        "woerter_pro_minute": round(len(words) / (sprech_s / 60.0), 1),
        "saetze": len(saetze),
        "vorlauf_s": round(vorlauf, 2),
        "nachlauf_s": round(nachlauf, 2),
        "satzanfang": grenzen["satzanfang"],
        "satzende": grenzen["satzende"],
        "beginnt_mit_rueckverweis": grenzen["beginnt_mit_rueckverweis"],
        "verneinung_am_rand": grenzen["verneinung_am_rand"],
        "erstes_wort": grenzen.get("erstes_wort"),
        "letztes_wort": grenzen.get("letztes_wort"),
        "erste_woerter": " ".join(str(w.get("text", "")) for w in words[:12]),
        "letzte_woerter": " ".join(str(w.get("text", "")) for w in words[-12:]),
    }


def anteil(werte: list[Any]) -> float | None:
    echte = [w for w in werte if w is not None]
    return round(sum(1 for w in echte if w) / len(echte), 3) if echte else None


def gruppe_zusammenfassen(zeilen: list[dict]) -> dict[str, Any]:
    brauchbar = [z for z in zeilen if z.get("woerter")]
    if not brauchbar:
        return {"clips": len(zeilen), "auswertbar": 0}
    dauern = sorted(z["dauer_s"] for z in brauchbar)
    saetze = sorted(z["saetze"] for z in brauchbar)
    wpm = sorted(z["woerter_pro_minute"] for z in brauchbar)
    return {
        "clips": len(zeilen),
        "auswertbar": len(brauchbar),
        "dauer_median_s": statistics.median(dauern),
        "dauer_min_s": dauern[0],
        "dauer_max_s": dauern[-1],
        "saetze_median": statistics.median(saetze),
        "woerter_pro_minute_median": statistics.median(wpm),
        "vorlauf_median_s": round(statistics.median([z["vorlauf_s"] for z in brauchbar]), 2),
        "nachlauf_median_s": round(statistics.median([z["nachlauf_s"] for z in brauchbar]), 2),
        "satzanfang_anteil": anteil([z["satzanfang"] for z in brauchbar]),
        "satzende_anteil": anteil([z["satzende"] for z in brauchbar]),
        "rueckverweis_anteil": anteil([z["beginnt_mit_rueckverweis"] for z in brauchbar]),
        "verneinung_am_rand_anteil": anteil([z["verneinung_am_rand"] for z in brauchbar]),
    }


def sammeln(ordner: Path, work: Path, grenze: int | None) -> list[dict]:
    dateien = sorted(p for p in ordner.iterdir() if p.suffix.lower() in VIDEO_SUFFIXES)
    if grenze:
        dateien = dateien[:grenze]
    out = []
    for i, p in enumerate(dateien, start=1):
        print(f"  [{i}/{len(dateien)}] {p.name}", flush=True)
        try:
            dauer = ingest.probe(str(p)).duration_s or 0.0
            daten = transcribe_clip(p, work)
            out.append(measure(daten, float(dauer)))
        except Exception as exc:  # eine kaputte Datei darf den Lauf nicht beenden
            print(f"      uebersprungen: {exc.__class__.__name__}: {exc}", flush=True)
            out.append({"datei": p.name, "woerter": 0, "hinweis": f"Fehler: {exc.__class__.__name__}"})
    return out


def zeile(z: dict) -> str:
    if not z.get("woerter"):
        return f"{z['datei'][:34]:<34}  {'-':>6}  {z.get('hinweis', '')}"
    return (
        f"{z['datei'][:34]:<34}  {z['dauer_s']:>6.1f}  {z['saetze']:>4}  {z['woerter_pro_minute']:>5.0f}  "
        f"{clip_eval.ja(z['satzanfang']):>4}  {clip_eval.ja(z['satzende']):>4}  "
        f"{clip_eval.ja(z['beginnt_mit_rueckverweis']):>4}  {z['erste_woerter'][:46]}"
    )


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Merkmale guter und schlechter Beispielclips auszaehlen.")
    ap.add_argument("--positiv", required=True, help="Ordner mit guten Beispielclips")
    ap.add_argument("--negativ", required=True, help="Ordner mit schlechten Beispielclips")
    ap.add_argument("--arbeit", default="/tmp/chopstr-beispiele", help="Zwischenspeicher fuer Audio und Transkripte")
    ap.add_argument("--grenze", type=int, default=None, help="Nur die ersten N Dateien je Ordner")
    ap.add_argument("--out", default=None, help="Ergebnis als JSON ablegen")
    args = ap.parse_args(argv)

    work = Path(args.arbeit)
    work.mkdir(parents=True, exist_ok=True)

    print("Positive Beispiele:")
    positiv = sammeln(Path(args.positiv), work, args.grenze)
    print("Negative Beispiele:")
    negativ = sammeln(Path(args.negativ), work, args.grenze)

    kopf = f"{'Datei':<34}  {'Dauer':>6}  {'Sätze':>4}  {'W/min':>5}  {'SA':>4}  {'SE':>4}  {'RV':>4}  Anfang"
    for titel, zeilen in (("POSITIV", positiv), ("NEGATIV", negativ)):
        print()
        print(titel)
        print(kopf)
        print("-" * len(kopf))
        for z in zeilen:
            print(zeile(z))

    p, n = gruppe_zusammenfassen(positiv), gruppe_zusammenfassen(negativ)
    print()
    print(f"{'Merkmal':<32}  {'positiv':>10}  {'negativ':>10}")
    print("-" * 56)
    for schluessel in (
        "clips", "dauer_median_s", "dauer_min_s", "dauer_max_s", "saetze_median",
        "woerter_pro_minute_median", "vorlauf_median_s", "nachlauf_median_s",
        "satzanfang_anteil", "satzende_anteil", "rueckverweis_anteil", "verneinung_am_rand_anteil",
    ):  # fmt: skip
        pv, nv = p.get(schluessel), n.get(schluessel)
        print(f"{schluessel:<32}  {str(pv):>10}  {str(nv):>10}")

    if args.out:
        Path(args.out).write_text(
            json.dumps({"positiv": {"clips": positiv, "summe": p}, "negativ": {"clips": negativ, "summe": n}}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print()
        print(f"JSON geschrieben: {args.out}")


if __name__ == "__main__":
    main(sys.argv[1:])
