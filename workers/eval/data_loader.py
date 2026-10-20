"""Loader mit Validierung für den Referenzdatensatz in ``eval/data`` (Datenvertrag in ``eval/data/README.md``).

Jede Funktion liest eine Datei, prüft sie und gibt ein bereinigtes ``dict`` zurück. Fehler kommen als
``DataError`` mit Datei, Stelle und Problem, damit die Redaktion die Datei selbst korrigieren kann.

Dateien je Quelle (``<quelle>`` ist die ``id`` oder der ``dateiname`` aus ``split.json``):

    split.json                        Teil je Quelle: entwicklung | kalibrierung | abschluss
    spannen/<quelle>.json             menschlich gewählte Spannen (Gold und Silber über ``gold_silver``)
    redakteure/<quelle>.json          Top-10 je Redakteur mit Rang
    transkript_referenz/<quelle>.json Wörter mit Sprecher und Zeit (oder <quelle>.rttm, nur Segmente)
    audioanker/<quelle>.json          Wortanfang und Wortende gegen das Audio, mit Kategorie
    schnittpunkte/<quelle>.json       Schnittpunkte mit Urteil je Hörer und Urteil je Clip
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PARTS = ("entwicklung", "kalibrierung", "abschluss")
FORMATS = ("debatte", "podcast", "interview", "keynote", "webinar", "erklaerformat", "monolog", "fixture")
LANGUAGE_VARIANTS = ("DE", "AT", "CH", "gemischt")
PLATFORMS = ("tiktok", "reels", "shorts", "linkedin", "youtube", "andere")
ANCHOR_CATEGORIES = ("name", "betrag", "prozent", "verneinung", "einschraenkung", "sonstiges")
CUT_VERDICTS = ("natuerlich", "abgehackt", "zu_lang")
CLIP_VERDICTS = ("brauchbar", "unbrauchbar")
TOP_N = 10
GOLD_IOU = 0.5
GOLD_MIN_PERSONS = 2


class DataError(ValueError):
    """Ungültige Datei im Referenzdatensatz; die Meldung nennt Datei, Stelle und Problem."""


def _read_json(path: str | Path) -> Any:
    p = Path(path)
    if not p.is_file():
        raise DataError(f"{p}: Datei fehlt.")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DataError(f"{p}: kein gültiges JSON ({exc.msg}, Zeile {exc.lineno}).") from exc


def _fail(path: Path | str, where: str, problem: str) -> DataError:
    return DataError(f"{path}: {where}: {problem}")


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _span(path: Path | str, where: str, item: Any, start_key: str = "start_s", end_key: str = "end_s") -> tuple[float, float]:
    if not isinstance(item, dict):
        raise _fail(path, where, "Eintrag ist kein Objekt.")
    start, end = item.get(start_key), item.get(end_key)
    if not _number(start) or not _number(end):
        raise _fail(path, where, f"{start_key} und {end_key} müssen Zahlen in Sekunden sein.")
    if start < 0 or end <= start:
        raise _fail(path, where, f"{start_key} {start} und {end_key} {end}: Ende muss nach dem Anfang liegen, Anfang ab 0.")
    return float(start), float(end)


def _text(path: Path | str, where: str, item: dict, key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _fail(path, where, f"{key} fehlt oder ist leer.")
    return value.strip()


def _choice(path: Path | str, where: str, item: dict, key: str, allowed: tuple[str, ...]) -> str:
    value = item.get(key)
    if value not in allowed:
        raise _fail(path, where, f"{key} {value!r} ist nicht erlaubt; erlaubt sind {', '.join(allowed)}.")
    return str(value)


def _list(path: Path | str, doc: Any, key: str) -> list:
    if not isinstance(doc, dict) or not isinstance(doc.get(key), list):
        raise _fail(path, key, "Liste fehlt.")
    return doc[key]


# -- split.json -------------------------------------------------------------------------------------


def source_key(entry: dict) -> str:
    """Schlüssel einer Quelle: ``id``, sonst ``dateiname``."""
    return str(entry.get("id") or entry.get("dateiname"))


def validate_split(doc: Any, path: str | Path = "split.json") -> dict[str, Any]:
    """Prüft Teil, Format, Sprachvariante und Dauer je Quelle; Ausschnitte derselben ``aufnahme`` müssen im
    selben Teil liegen."""
    sources = _list(path, doc, "quellen")
    seen: set[str] = set()
    recordings: dict[str, tuple[str, str]] = {}
    out = []
    for i, item in enumerate(sources):
        where = f"quellen[{i}]"
        if not isinstance(item, dict):
            raise _fail(path, where, "Eintrag ist kein Objekt.")
        if not (item.get("id") or item.get("dateiname")):
            raise _fail(path, where, "id oder dateiname fehlt.")
        key = source_key(item)
        where = f"quellen[{i}] ({key})"
        if key in seen:
            raise _fail(path, where, "Quelle steht doppelt im Split.")
        seen.add(key)
        part = _choice(path, where, item, "teil", PARTS)
        _choice(path, where, item, "format", FORMATS)
        _choice(path, where, item, "sprachvariante", LANGUAGE_VARIANTS)
        if not _number(item.get("dauer_s")) or item["dauer_s"] <= 0:
            raise _fail(path, where, "dauer_s muss eine positive Zahl in Sekunden sein.")
        recording = str(item.get("aufnahme") or key)
        if recording in recordings and recordings[recording][0] != part:
            other_part, other_key = recordings[recording]
            raise _fail(path, where, f"Aufnahme {recording!r} liegt auch in Teil {other_part!r} ({other_key}); "
                                     "Ausschnitte derselben Aufnahme gehören in denselben Teil.")  # fmt: skip
        recordings.setdefault(recording, (part, key))
        out.append({**item, "aufnahme": recording})
    return {**doc, "quellen": out}


def load_split(path: str | Path) -> dict[str, Any]:
    return validate_split(_read_json(path), path)


def sources_in(split: dict[str, Any], part: str) -> list[dict[str, Any]]:
    if part not in PARTS:
        raise DataError(f"Teil {part!r} gibt es nicht; erlaubt sind {', '.join(PARTS)}.")
    return [s for s in split["quellen"] if s["teil"] == part]


def check_part_access(part: str, confirmed: bool) -> None:
    """Der Abschlussteil bleibt während der Entwicklung unangetastet: Auswertung nur mit ausdrücklicher
    Bestätigung, nachdem Bewertungsregeln und Schwellen festgeschrieben sind."""
    if part == "abschluss" and not confirmed:
        raise DataError("Teil abschluss ist gesperrt: erst Bewertungsregeln und Schwellen festschreiben, "
                        "dann mit --abschluss-bestaetigt auswerten.")  # fmt: skip


# -- Spannen und Gold/Silber ------------------------------------------------------------------------


def validate_spans(doc: Any, path: str | Path = "spannen.json") -> dict[str, Any]:
    items = _list(path, doc, "spannen")
    out = []
    for i, item in enumerate(items):
        where = f"spannen[{i}]"
        start, end = _span(path, where, item)
        person = _text(path, where, item, "person")
        platform = _choice(path, where, item, "platform", PLATFORMS)
        views = item.get("views")
        if views is not None and (not isinstance(views, int) or isinstance(views, bool) or views < 0):
            raise _fail(path, where, f"views {views!r} muss eine ganze Zahl ab 0 sein oder fehlen.")
        out.append({"person": person, "start_s": start, "end_s": end, "platform": platform, "views": views})
    return {**doc, "spannen": out}


def load_spans(path: str | Path) -> dict[str, Any]:
    return validate_spans(_read_json(path), path)


def span_iou(a: dict, b: dict) -> float:
    inter = max(0.0, min(a["end_s"], b["end_s"]) - max(a["start_s"], b["start_s"]))
    union = max(a["end_s"], b["end_s"]) - min(a["start_s"], b["start_s"])
    return inter / union if union > 0 else 0.0


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def gold_silver(spans: list[dict], iou: float = GOLD_IOU, min_persons: int = GOLD_MIN_PERSONS) -> list[dict[str, Any]]:
    """Referenzmomente aus menschlichen Spannen: Spannen verschiedener Personen mit IoU >= ``iou`` bilden einen
    Moment. Gold heißt von mindestens ``min_persons`` Personen gewählt, Silber einmal. Gold ist ein
    Übereinstimmungssignal, keine Korrektheitsgarantie. Der Moment reicht vom Median der Anfänge bis zum
    Median der Enden."""
    parent = list(range(len(spans)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(spans):
        for j in range(i + 1, len(spans)):
            b = spans[j]
            if a["person"] != b["person"] and span_iou(a, b) >= iou:
                parent[find(i)] = find(j)
    groups: dict[int, list[dict]] = {}
    for i, s in enumerate(spans):
        groups.setdefault(find(i), []).append(s)
    moments = []
    for members in groups.values():
        persons = sorted({m["person"] for m in members})
        moments.append({
            "start_s": round(_median([m["start_s"] for m in members]), 3),
            "end_s": round(_median([m["end_s"] for m in members]), 3),
            "stufe": "gold" if len(persons) >= min_persons else "silber",
            "personen": persons,
            "spannen": len(members),
        })  # fmt: skip
    return sorted(moments, key=lambda m: (m["start_s"], m["end_s"]))


# -- Redakteure --------------------------------------------------------------------------------------


def validate_editors(doc: Any, path: str | Path = "redakteure.json") -> dict[str, Any]:
    editors = _list(path, doc, "redakteure")
    seen: set[str] = set()
    out = []
    for i, ed in enumerate(editors):
        where = f"redakteure[{i}]"
        if not isinstance(ed, dict):
            raise _fail(path, where, "Eintrag ist kein Objekt.")
        person = _text(path, where, ed, "person")
        if person in seen:
            raise _fail(path, where, f"Redakteur {person!r} steht doppelt.")
        seen.add(person)
        top = ed.get("top10")
        if not isinstance(top, list) or not top:
            raise _fail(path, where, "top10 fehlt oder ist leer.")
        if len(top) > TOP_N:
            raise _fail(path, where, f"top10 hat {len(top)} Einträge, höchstens {TOP_N}.")
        ranks: set[int] = set()
        items = []
        for j, item in enumerate(top):
            w = f"{where}.top10[{j}]"
            start, end = _span(path, w, item)
            rank = item.get("rang")
            if not isinstance(rank, int) or isinstance(rank, bool) or not 1 <= rank <= TOP_N:
                raise _fail(path, w, f"rang {rank!r} muss eine ganze Zahl von 1 bis {TOP_N} sein.")
            if rank in ranks:
                raise _fail(path, w, f"rang {rank} ist doppelt vergeben.")
            ranks.add(rank)
            items.append({"rang": rank, "start_s": start, "end_s": end})
        out.append({"person": person, "top10": sorted(items, key=lambda x: x["rang"])})
    return {**doc, "redakteure": out}


def load_editors(path: str | Path) -> dict[str, Any]:
    return validate_editors(_read_json(path), path)


# -- Transkript-Referenz -----------------------------------------------------------------------------


def parse_rttm(text: str, path: str | Path = "referenz.rttm") -> list[dict[str, Any]]:
    """RTTM-Zeilen ``SPEAKER <datei> <kanal> <start> <dauer> <NA> <NA> <sprecher> <NA> <NA>`` als Segmente."""
    segs = []
    for n, line in enumerate(text.splitlines(), start=1):
        parts = line.split()
        if not parts or parts[0].startswith("#"):
            continue
        if parts[0] != "SPEAKER" or len(parts) < 8:
            raise _fail(path, f"Zeile {n}", "erwartet SPEAKER <datei> <kanal> <start> <dauer> <NA> <NA> <sprecher>.")
        try:
            start, dur = float(parts[3]), float(parts[4])
        except ValueError as exc:
            raise _fail(path, f"Zeile {n}", "Start und Dauer müssen Zahlen sein.") from exc
        if start < 0 or dur <= 0:
            raise _fail(path, f"Zeile {n}", "Start ab 0 und Dauer größer 0.")
        segs.append({"sprecher": parts[7], "start": start, "end": round(start + dur, 6)})
    return segs


def validate_transcript_reference(doc: Any, path: str | Path = "transkript_referenz.json") -> dict[str, Any]:
    words = _list(path, doc, "woerter")
    out_words = []
    for i, w in enumerate(words):
        where = f"woerter[{i}]"
        start, end = _span(path, where, w, "start", "end")
        out_words.append({"wort": _text(path, where, w, "wort"), "start": start, "end": end, "sprecher": _text(path, where, w, "sprecher")})
    segs = []
    for i, s in enumerate(doc.get("segmente") or []):
        where = f"segmente[{i}]"
        start, end = _span(path, where, s, "start", "end")
        segs.append({"sprecher": _text(path, where, s, "sprecher"), "start": start, "end": end})
    variant = doc.get("sprachvariante", "DE")
    if variant not in LANGUAGE_VARIANTS:
        raise _fail(path, "sprachvariante", f"{variant!r} ist nicht erlaubt; erlaubt sind {', '.join(LANGUAGE_VARIANTS)}.")
    return {**doc, "sprachvariante": variant, "woerter": out_words, "segmente": segs}


def load_transcript_reference(path: str | Path) -> dict[str, Any]:
    """JSON mit Wörtern (Sprecher, Zeit) und optional Segmenten, oder RTTM (nur Segmente, keine Wörter)."""
    p = Path(path)
    if p.suffix == ".rttm":
        if not p.is_file():
            raise DataError(f"{p}: Datei fehlt.")
        return {"woerter": [], "segmente": parse_rttm(p.read_text(encoding="utf-8"), p), "sprachvariante": None}
    return validate_transcript_reference(_read_json(p), p)


# -- Audioanker ---------------------------------------------------------------------------------------


def validate_anchors(doc: Any, path: str | Path = "audioanker.json") -> dict[str, Any]:
    items = _list(path, doc, "anker")
    out = []
    for i, a in enumerate(items):
        where = f"anker[{i}]"
        start, end = _span(path, where, a, "anker_start", "anker_ende")
        out.append({"wort": _text(path, where, a, "wort"), "anker_start": start, "anker_ende": end,
                    "kategorie": _choice(path, where, a, "kategorie", ANCHOR_CATEGORIES)})  # fmt: skip
    return {**doc, "anker": out}


def load_anchors(path: str | Path) -> dict[str, Any]:
    return validate_anchors(_read_json(path), path)


# -- Schnittpunkte ------------------------------------------------------------------------------------


def validate_cut_points(doc: Any, path: str | Path = "schnittpunkte.json") -> dict[str, Any]:
    points = _list(path, doc, "schnittpunkte")
    out_points = []
    for i, p in enumerate(points):
        where = f"schnittpunkte[{i}]"
        if not isinstance(p, dict):
            raise _fail(path, where, "Eintrag ist kein Objekt.")
        if not _number(p.get("zeit_s")) or p["zeit_s"] < 0:
            raise _fail(path, where, "zeit_s muss eine Zahl ab 0 sein.")
        out_points.append({"clip_id": _text(path, where, p, "clip_id"), "zeit_s": float(p["zeit_s"]),
                           "urteil": _choice(path, where, p, "urteil", CUT_VERDICTS), "hoerer": _text(path, where, p, "hoerer")})  # fmt: skip
    clips = []
    for i, c in enumerate(doc.get("clip_urteile") or []):
        where = f"clip_urteile[{i}]"
        if not isinstance(c, dict):
            raise _fail(path, where, "Eintrag ist kein Objekt.")
        clips.append({"clip_id": _text(path, where, c, "clip_id"), "hoerer": _text(path, where, c, "hoerer"),
                      "urteil": _choice(path, where, c, "urteil", CLIP_VERDICTS)})  # fmt: skip
    return {**doc, "schnittpunkte": out_points, "clip_urteile": clips}


def load_cut_points(path: str | Path) -> dict[str, Any]:
    return validate_cut_points(_read_json(path), path)


# -- Alles zu einer Quelle -----------------------------------------------------------------------------

LOADERS = {
    "spannen": load_spans,
    "redakteure": load_editors,
    "audioanker": load_anchors,
    "schnittpunkte": load_cut_points,
}


def load_source_data(data_dir: str | Path, source: str) -> dict[str, Any]:
    """Alle vorhandenen Dateien einer Quelle; fehlende Arten stehen unter ``fehlt``."""
    base = Path(data_dir)
    out: dict[str, Any] = {"quelle": source, "fehlt": []}
    for kind, loader in LOADERS.items():
        path = base / kind / f"{source}.json"
        if path.is_file():
            out[kind] = loader(path)
        else:
            out["fehlt"].append(kind)
    ref_json, ref_rttm = base / "transkript_referenz" / f"{source}.json", base / "transkript_referenz" / f"{source}.rttm"
    if ref_json.is_file():
        out["transkript_referenz"] = load_transcript_reference(ref_json)
    elif ref_rttm.is_file():
        out["transkript_referenz"] = load_transcript_reference(ref_rttm)
    else:
        out["fehlt"].append("transkript_referenz")
    return out


def validate_folder(data_dir: str | Path) -> dict[str, Any]:
    """Prüft ``split.json`` und jede Datei in den Unterordnern; meldet Dateien zu Quellen ohne Split-Eintrag."""
    base = Path(data_dir)
    split = load_split(base / "split.json")
    known = {source_key(s) for s in split["quellen"]}
    checked, unknown = 0, []
    for kind in (*LOADERS, "transkript_referenz"):
        folder = base / kind
        if not folder.is_dir():
            continue
        for file in sorted(folder.iterdir()):
            if file.suffix not in (".json", ".rttm"):
                continue
            if file.stem not in known:
                unknown.append(f"{kind}/{file.name}")
            if kind == "transkript_referenz":
                load_transcript_reference(file)
            else:
                LOADERS[kind](file)
            checked += 1
    return {"quellen": len(split["quellen"]), "dateien_geprueft": checked, "ohne_split_eintrag": unknown,
            "je_teil": {p: len(sources_in(split, p)) for p in PARTS}}  # fmt: skip


def main(argv: list[str] | None = None) -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Prüft den Referenzdatensatz in eval/data.")
    ap.add_argument("ordner", nargs="?", default=str(Path(__file__).parent / "data"))
    args = ap.parse_args(argv)
    try:
        res = validate_folder(args.ordner)
    except DataError as exc:
        raise SystemExit(f"Fehler: {exc}") from exc
    print(f"Quellen im Split: {res['quellen']} ({', '.join(f'{k} {v}' for k, v in res['je_teil'].items())})")
    print(f"Dateien geprüft: {res['dateien_geprueft']}")
    for name in res["ohne_split_eintrag"]:
        print(f"Warnung: {name} gehört zu keiner Quelle aus split.json")


if __name__ == "__main__":
    main()
