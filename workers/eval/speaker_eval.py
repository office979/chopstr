"""Sprecherzuordnung gegen eine manuelle Referenz: je Wort, cpWER und DER (ohne jiwer, ohne pyannote.metrics).

    .venv/bin/python -m eval.speaker_eval --referenz eval/data/transkript_referenz/<quelle>.json \
        --hypothese transkript.json [--json sprecher.json]

Referenz: ``transkript_referenz/<quelle>.json`` (Wörter mit Sprecher und Zeit, optional Segmente), eine RTTM-Datei
(nur Segmente, dann nur DER) oder ``sprecherwechsel.json`` aus ``eval/runs/testmaterial`` (Turns als Segmente,
Sätze als Wörter mit gleichmäßig verteilten Zeiten). Hypothese: Transkript-JSON (Wortliste oder ``{"words":
[...]}`` mit ``text``, ``start``, ``end``, ``speaker``) oder RTTM.

1. Je Wort: Referenz- und Hypothesenwörter werden über den Text aligniert (Levenshtein aus ``wer_eval``), die
   Sprecherlabels über die beste Eins-zu-eins-Zuordnung verbunden. Jedes Referenzwort ist genau eines von:
   korrekt, falsch (anderer Sprecher), nicht zugeordnet (Hypothese ohne Sprecher), nicht erkannt (kein
   Hypothesenwort). Getrennt für alle Wörter und für Wörter in Überlappung (zwei oder mehr Referenzsprecher
   gleichzeitig aktiv).
2. cpWER: je Sprecher die Wörter zeitlich verkettet, die Zuordnung der Sprecher mit den wenigsten Fehlern
   gewählt; nicht zugeordnete Referenzsprecher zählen als Auslassung, nicht zugeordnete Hypothesensprecher als
   Einfügung.
3. DER ohne Collar mit Überlappung: verpasste Sprache, Fehlalarm und Verwechslung getrennt, geteilt durch die
   gesamte Referenz-Sprechzeit (je Sprecher gezählt).
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from functools import cache
from pathlib import Path
from typing import Any

from eval import data_loader, wer_eval

UNKNOWN_SPEAKERS = {"", "UNKNOWN", "?", None}
EXACT_MAPPING_MAX = 12
SEGMENT_MERGE_GAP_S = 1.0


def _word(w: dict) -> tuple[str, float | None, float | None, str | None]:
    text = str(w.get("wort", w.get("text", w.get("word", ""))))
    spk = w.get("sprecher", w.get("speaker"))
    start, end = w.get("start"), w.get("end")
    return text, (None if start is None else float(start)), (None if end is None else float(end)), (None if spk in UNKNOWN_SPEAKERS else str(spk))


def best_mapping(weights: dict[tuple[str, str], float], hyps: list[str], refs: list[str]) -> dict[str, str]:
    """Eins-zu-eins-Zuordnung Hypothese zu Referenz mit größter Summe der Gewichte (exakt bis zwölf
    Referenzsprechern, darüber gierig)."""
    hyps, refs = sorted(hyps), sorted(refs)
    if len(refs) > EXACT_MAPPING_MAX:
        pairs = sorted(((w, h, r) for (h, r), w in weights.items() if w > 0), reverse=True)
        used_h, used_r, out = set(), set(), {}
        for _w, h, r in pairs:
            if h not in used_h and r not in used_r:
                used_h.add(h)
                used_r.add(r)
                out[h] = r
        return out

    @cache
    def best(i: int, mask: int) -> tuple[float, tuple[tuple[str, str], ...]]:
        if i == len(hyps):
            return 0.0, ()
        top = best(i + 1, mask)
        for j, r in enumerate(refs):
            w = weights.get((hyps[i], r), 0.0)
            if w > 0 and not mask & (1 << j):
                val, rest = best(i + 1, mask | (1 << j))
                if val + w > top[0]:
                    top = (val + w, ((hyps[i], r), *rest))
        return top

    return dict(best(0, 0)[1])


def _tokens(words: list[dict], ch: bool = False) -> tuple[list[str], list[int]]:
    toks, owner = [], []
    for i, w in enumerate(words):
        for t in wer_eval.normalize(_word(w)[0], ch):
            toks.append(t)
            owner.append(i)
    return toks, owner


def align_words(ref_words: list[dict], hyp_words: list[dict], ch: bool = False) -> dict[int, int]:
    """Referenzwort-Index zu Hypothesenwort-Index über die Levenshtein-Alignierung der Tokens (erster Treffer
    je Referenzwort; Ersetzungen zählen als Treffer, weil es um den Sprecher geht, nicht um das Wort)."""
    rt, rown = _tokens(ref_words, ch)
    ht, hown = _tokens(hyp_words, ch)
    al = wer_eval.align(rt, ht)
    i = j = 0
    out: dict[int, int] = {}
    for op, _r, _h in al.ops:
        if op in ("ok", "sub"):
            out.setdefault(rown[i], hown[j])
            i, j = i + 1, j + 1
        elif op == "del":
            i += 1
        else:
            j += 1
    return out


def segments_from_words(words: list[dict], max_gap: float = SEGMENT_MERGE_GAP_S) -> list[dict[str, Any]]:
    """Aufeinanderfolgende Wörter desselben Sprechers mit Lücke bis ``max_gap`` zu Segmenten; Wörter ohne
    Sprecher oder Zeit fallen weg."""
    segs: list[dict[str, Any]] = []
    for w in words:
        _t, start, end, spk = _word(w)
        if spk is None or start is None or end is None:
            continue
        if segs and segs[-1]["sprecher"] == spk and start - segs[-1]["end"] <= max_gap:
            segs[-1]["end"] = max(segs[-1]["end"], end)
        else:
            segs.append({"sprecher": spk, "start": start, "end": end})
    return segs


def _intervals(*seg_lists: list[dict]) -> list[tuple[float, float, list[set[str]]]]:
    """Elementare Intervalle mit den aktiven Sprechern je Liste."""
    bounds = sorted({t for segs in seg_lists for s in segs for t in (s["start"], s["end"])})
    out = []
    for a, b in zip(bounds, bounds[1:]):
        if b <= a:
            continue
        mid = (a + b) / 2
        out.append((a, b, [{s["sprecher"] for s in segs if s["start"] <= mid < s["end"]} for segs in seg_lists]))
    return out


def overlap_regions(segments: list[dict]) -> list[tuple[float, float]]:
    """Zeitbereiche, in denen mindestens zwei Referenzsprecher gleichzeitig aktiv sind."""
    regions: list[tuple[float, float]] = []
    for a, b, (active,) in _intervals(segments):
        if len(active) >= 2:
            if regions and abs(regions[-1][1] - a) < 1e-9:
                regions[-1] = (regions[-1][0], b)
            else:
                regions.append((a, b))
    return regions


def _counts(labels: list[str]) -> dict[str, Any]:
    c = Counter(labels)
    n = len(labels)
    out: dict[str, Any] = {"woerter": n}
    for key in ("korrekt", "falsch", "nicht_zugeordnet", "nicht_erkannt"):
        out[key] = c.get(key, 0)
        out[f"{key}_anteil"] = c.get(key, 0) / n if n else None
    return out


def speaker_attribution(ref_words: list[dict], hyp_words: list[dict], ref_segments: list[dict] | None = None, ch: bool = False) -> dict[str, Any]:
    """Je Referenzwort: korrekt, falsch, nicht zugeordnet oder nicht erkannt; gesamt und in Überlappung."""
    if not ref_words:
        cause = "Referenz ohne Wörter"
        return {"gesamt": None, "overlap": None, "zuordnung": {}, "ursache": cause, "overlap_ursache": cause}
    pairs = align_words(ref_words, hyp_words, ch)
    weights: dict[tuple[str, str], float] = defaultdict(float)
    for i, j in pairs.items():
        r, h = _word(ref_words[i])[3], _word(hyp_words[j])[3]
        if r is not None and h is not None:
            weights[(h, r)] += 1.0
    mapping = best_mapping(dict(weights), list({h for h, _ in weights}), list({r for _, r in weights}))
    labels = []
    for i, w in enumerate(ref_words):
        ref_spk = _word(w)[3]
        if i not in pairs:
            labels.append("nicht_erkannt")
            continue
        hyp_spk = _word(hyp_words[pairs[i]])[3]
        if hyp_spk is None:
            labels.append("nicht_zugeordnet")
        else:
            labels.append("korrekt" if mapping.get(hyp_spk) == ref_spk else "falsch")
    regions = overlap_regions(ref_segments if ref_segments is not None else segments_from_words(ref_words))
    in_overlap = []
    for w, label in zip(ref_words, labels):
        _t, start, end, _s = _word(w)
        if start is not None and end is not None and any(start < b and end > a for a, b in regions):
            in_overlap.append(label)
    return {
        "gesamt": _counts(labels),
        "overlap": _counts(in_overlap) if in_overlap else None,
        "zuordnung": mapping,
        "ursache": None,
        "overlap_ursache": None if in_overlap else ("keine Überlappung in der Referenz" if not regions else "keine Referenzwörter in Überlappung"),
    }


def cpwer(ref_words: list[dict], hyp_words: list[dict], ch: bool = False) -> dict[str, Any]:
    """Concatenated minimum-permutation WER über die Sprecherzuordnung."""

    def by_speaker(words: list[dict]) -> dict[str, list[str]]:
        groups: dict[str, list[tuple[float, int, str]]] = defaultdict(list)
        for i, w in enumerate(words):
            text, start, _e, spk = _word(w)
            groups[spk or "?"].append((start if start is not None else float(i), i, text))
        return {s: [t for _st, _i, text in sorted(items) for t in wer_eval.normalize(text, ch)] for s, items in groups.items()}

    refs, hyps = by_speaker(ref_words), by_speaker(hyp_words)
    n_ref = sum(len(v) for v in refs.values())
    if not n_ref:
        return {"cpwer": None, "fehler": None, "n_ref": 0, "zuordnung": {}, "ursache": "Referenz ohne Wörter"}
    cost = {(h, r): wer_eval.align(refs[r], hyps[h]).errors for h in hyps for r in refs}
    saving = {(h, r): len(refs[r]) + len(hyps[h]) - c for (h, r), c in cost.items()}
    mapping = best_mapping({k: float(v) for k, v in saving.items()}, list(hyps), list(refs))
    errors = n_ref + sum(len(v) for v in hyps.values()) - sum(saving[(h, r)] for h, r in mapping.items())
    return {"cpwer": errors / n_ref, "fehler": errors, "n_ref": n_ref, "zuordnung": mapping, "ursache": None}


def der(ref_segments: list[dict], hyp_segments: list[dict]) -> dict[str, Any]:
    """Diarization Error Rate ohne Collar, mit Überlappung, beste Eins-zu-eins-Zuordnung der Sprecher."""
    intervals = _intervals(ref_segments, hyp_segments)
    total = sum((b - a) * len(r) for a, b, (r, _h) in intervals)
    if total <= 0:
        return {"der": None, "missed_s": None, "false_alarm_s": None, "confusion_s": None, "referenz_s": 0.0, "zuordnung": {},
                "ursache": "Referenz ohne Sprechzeit"}  # fmt: skip
    weights: dict[tuple[str, str], float] = defaultdict(float)
    for a, b, (r, h) in intervals:
        for hs in h:
            for rs in r:
                weights[(hs, rs)] += b - a
    mapping = best_mapping(dict(weights), list({s["sprecher"] for s in hyp_segments}), list({s["sprecher"] for s in ref_segments}))
    missed = fa = conf = 0.0
    for a, b, (r, h) in intervals:
        d = b - a
        correct = len(r & {mapping[x] for x in h if x in mapping})
        missed += max(0, len(r) - len(h)) * d
        fa += max(0, len(h) - len(r)) * d
        conf += (min(len(r), len(h)) - correct) * d
    return {
        "der": (missed + fa + conf) / total,
        "missed_s": round(missed, 4), "false_alarm_s": round(fa, 4), "confusion_s": round(conf, 4), "referenz_s": round(total, 4),
        "missed_anteil": missed / total, "false_alarm_anteil": fa / total, "confusion_anteil": conf / total,
        "zuordnung": mapping, "ursache": None,
    }  # fmt: skip


def reference_from_speaker_changes(doc: dict[str, Any]) -> dict[str, Any]:
    """``sprecherwechsel.json`` aus dem Testmaterial: Turns als Segmente, Sätze als Wörter. Die Wortzeiten sind
    gleichmäßig nach Zeichenzahl über den Satz verteilt (``zeit: interpoliert``); für die Zuordnung je Wort
    und für cpWER reicht das, für Zeitmessungen nicht."""
    words = []
    for sent in doc.get("saetze") or []:
        toks = str(sent["text"]).split()
        total = sum(len(t) for t in toks) or 1
        t, span = float(sent["start"]), float(sent["end"]) - float(sent["start"])
        for tok in toks:
            d = span * len(tok) / total
            words.append({"wort": tok, "start": round(t, 3), "end": round(t + d, 3), "sprecher": sent["sprecher"], "zeit": "interpoliert"})
            t += d
    segs = [{"sprecher": s["sprecher"], "start": float(s["start"]), "end": float(s["end"])} for s in doc.get("turns") or []]
    return {"woerter": words, "segmente": segs}


def load_reference(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if p.suffix == ".json":
        doc = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and "turns" in doc and "saetze" in doc:
            return reference_from_speaker_changes(doc)
    return data_loader.load_transcript_reference(p)


def load_hypothesis(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if p.suffix == ".rttm":
        return {"woerter": [], "segmente": data_loader.parse_rttm(p.read_text(encoding="utf-8"), p)}
    doc = json.loads(p.read_text(encoding="utf-8"))
    words = doc if isinstance(doc, list) else doc.get("words") or doc.get("woerter") or []
    return {"woerter": words, "segmente": segments_from_words(words)}


def evaluate(ref: dict[str, Any], hyp: dict[str, Any], ch: bool = False) -> dict[str, Any]:
    ref_words, hyp_words = ref.get("woerter") or [], hyp.get("woerter") or []
    ref_segs = ref.get("segmente") or segments_from_words(ref_words)
    hyp_segs = hyp.get("segmente") or segments_from_words(hyp_words)
    if ref_words and not hyp_words:
        attribution: dict[str, Any] = {"gesamt": None, "overlap": None, "zuordnung": {}, "ursache": "Hypothese ohne Wörter", "overlap_ursache": "Hypothese ohne Wörter"}
        cp: dict[str, Any] = {"cpwer": None, "ursache": "Hypothese ohne Wörter"}
    else:
        attribution = speaker_attribution(ref_words, hyp_words, ref_segs, ch)
        cp = cpwer(ref_words, hyp_words, ch)
    d = der(ref_segs, hyp_segs) if hyp_segs else {"der": None, "ursache": "Hypothese ohne Sprechersegmente"}
    res = {"zuordnung_je_wort": attribution, "cpwer": cp, "der": d}
    res["metriken"] = metrics(res)
    return res


def metrics(res: dict[str, Any]) -> dict[str, dict[str, Any]]:
    a = res["zuordnung_je_wort"]

    def share(block: dict | None, cause: str | None) -> dict[str, Any]:
        if block is None:
            return {"wert": None, "stichprobe": None, "ursache": cause or "keine Daten"}
        return {"wert": block["korrekt_anteil"], "stichprobe": block["woerter"], "ursache": None}

    cp, d = res["cpwer"], res["der"]
    return {
        "sprecher_korrekt_overlap": share(a["overlap"], a.get("overlap_ursache")),
        "sprecher_korrekt_gesamt": share(a["gesamt"], a.get("ursache")),
        "cpwer": {"wert": cp.get("cpwer"), "stichprobe": cp.get("n_ref"), "ursache": cp.get("ursache")},
        "der": {"wert": d.get("der"), "stichprobe": d.get("referenz_s"), "ursache": d.get("ursache")},
    }


def _pct(value: float | None, cause: str | None) -> str:
    return f"nicht messbar: {cause}" if value is None else f"{value * 100:.1f} %".replace(".", ",")


def format_report(res: dict[str, Any]) -> str:
    a = res["zuordnung_je_wort"]
    lines = []
    for title, block, cause in (("alle Wörter", a["gesamt"], a.get("ursache")), ("in Überlappung", a["overlap"], a.get("overlap_ursache"))):
        if block is None:
            lines.append(f"Sprecher je Wort, {title}: nicht messbar: {cause}")
        else:
            lines.append(f"Sprecher je Wort, {title} ({block['woerter']} Wörter): korrekt {_pct(block['korrekt_anteil'], None)}, "
                         f"falsch {block['falsch']}, nicht zugeordnet {block['nicht_zugeordnet']}, nicht erkannt {block['nicht_erkannt']}")  # fmt: skip
    lines.append(f"cpWER: {_pct(res['cpwer'].get('cpwer'), res['cpwer'].get('ursache'))}")
    d = res["der"]
    if d.get("der") is None:
        lines.append(f"DER: nicht messbar: {d.get('ursache')}")
    else:
        lines.append(f"DER (ohne Collar, mit Überlappung): {_pct(d['der'], None)}; verpasst {_pct(d['missed_anteil'], None)}, "
                     f"Fehlalarm {_pct(d['false_alarm_anteil'], None)}, Verwechslung {_pct(d['confusion_anteil'], None)}")  # fmt: skip
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Sprecherzuordnung je Wort, cpWER und DER gegen eine Referenz.")
    ap.add_argument("--referenz", required=True, help="transkript_referenz JSON, RTTM oder sprecherwechsel.json")
    ap.add_argument("--hypothese", required=True, help="Transkript-JSON mit speaker je Wort oder RTTM")
    ap.add_argument("--ch", action="store_true", help="ß und ss gleichsetzen")
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args(argv)
    try:
        res = evaluate(load_reference(args.referenz), load_hypothesis(args.hypothese), args.ch)
    except data_loader.DataError as exc:
        raise SystemExit(f"Fehler: {exc}") from exc
    print(format_report(res))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
