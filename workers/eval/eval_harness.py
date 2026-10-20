"""Eval-Harness: Wie nah kommt die Maschine an die Redakteur:innen?

Zwei Wege:

1. Alt (Gold je Episode, unverändert lesbar):
   Gold-Datei (JSON pro Episode):
     {"episode": "ep01.mp4", "dialect": "AT", "clips": [{"start": 812.4, "end": 861.0, "rating": 3}]}
     rating: 3 = würde sofort posten, 2 = mit Nacharbeit, 1 = Notlösung
   Vorhersage-Datei: {"episode": "ep01.mp4", "clips": [{"start":..., "end":..., "total":...}]}
   Aufruf: python -m eval.eval_harness gold/ preds/ --k 10 [--json out.json]

2. Neu (Referenzdatensatz ``eval/data`` und DetectReport-JSON je Quelle, Launch-Auftrag 6.2):
   Aufruf: python -m eval.eval_harness --daten eval/data --berichte berichte/ --teil entwicklung [--json out.json]
   ``berichte/<quelle>.json`` ist der DetectReport (``story_engine.DetectReport.to_json``).

Metriken (IoU >= 0,5 ist ein Treffer):
- Abdeckung der Referenzmomente an drei Stellen: Kandidatenpool, nach Gates, angebotene Kandidaten.
- Recall@20 gegen die Referenzmomente (Gold und Silber, Gold getrennt).
- Precision@5 und @10 gegen die Top-10 je Redakteur, je Redakteur und gemittelt.
- Grenzfehler getrennt nach Start und Ende in Sekunden; der Gesamtwert gewichtet den Start doppelt.
- Neu entdeckte Momente (angeboten, in keiner Referenz) werden gesondert gezählt, nicht als Fehler.
Leere Eingaben ergeben ``None`` mit Ursache, nie 0.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from eval import data_loader

IOU_MATCH = 0.5
RECALL_K = 20
PRECISION_KS = (5, 10)
BOUNDARY_K = 10
START_WEIGHT = 2
STAGES = ("pool", "after_gates", "offered")
STAGE_LABELS = {"pool": "Kandidatenpool", "after_gates": "nach Gates", "offered": "angeboten"}
HARNESS_METRICS = (
    "abdeckung_pool", "abdeckung_nach_gates", "abdeckung_top_k", "recall_at_20", "precision_at_5", "precision_at_10",
    "grenzfehler_start_s", "grenzfehler_ende_s", "grenzfehler_gewichtet_s", "neue_momente",
)  # fmt: skip


def iou(a: dict, b: dict) -> float:
    inter = max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    union = max(a["end"], b["end"]) - min(a["start"], b["start"])
    return inter / union if union > 0 else 0.0


def evaluate(gold: dict, pred: dict, k: int) -> dict:
    top = sorted(pred["clips"], key=lambda c: c.get("total", 0), reverse=True)[:k]
    good_gold = [g for g in gold["clips"] if g.get("rating", 1) >= 2]
    hits, boundary, starts, ends = 0, [], [], []
    for p in top:
        best = max(good_gold, key=lambda g: iou(p, g), default=None)
        if best and iou(p, best) >= IOU_MATCH:
            hits += 1
            starts.append(abs(p["start"] - best["start"]))
            ends.append(abs(p["end"] - best["end"]))
            boundary.append((starts[-1] + ends[-1]) / 2)
    found = sum(1 for g in good_gold if any(iou(p, g) >= IOU_MATCH for p in top))
    return {
        "precision_at_k": hits / len(top) if top else None,
        "recall": found / len(good_gold) if good_gold else None,
        # Alt: Mittel aus Start- und Endfehler; getrennt stehen sie in boundary_start_s und boundary_end_s.
        "boundary_err_s": sum(boundary) / len(boundary) if boundary else None,
        **_boundary_summary(starts, ends),
        "n_pred": len(top),
        "n_gold": len(good_gold),
    }


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _boundary_summary(starts: list[float], ends: list[float]) -> dict[str, float | None]:
    s, e = _mean(starts), _mean(ends)
    weighted = None if s is None or e is None else (START_WEIGHT * s + e) / (START_WEIGHT + 1)
    return {"boundary_start_s": s, "boundary_end_s": e, "boundary_weighted_s": weighted}


def aggregate(rows: list[dict]) -> dict:
    out: dict[str, Any] = {"n": len(rows)}
    for key in ("precision_at_k", "recall", "boundary_err_s", "boundary_start_s", "boundary_end_s", "boundary_weighted_s"):
        out[key] = _mean([r[key] for r in rows if r.get(key) is not None])
    return out


def run(gold_dir: str, pred_dir: str, k: int) -> dict[str, dict]:
    by_dialect: dict[str, list[dict]] = defaultdict(list)
    for gf in sorted(Path(gold_dir).glob("*.json")):
        gold = json.loads(gf.read_text(encoding="utf-8"))
        pf = Path(pred_dir) / gf.name
        if not pf.exists():
            continue
        res = evaluate(gold, json.loads(pf.read_text(encoding="utf-8")), k)
        by_dialect[gold.get("dialect", "?")].append(res)
    return {d: aggregate(rows) for d, rows in sorted(by_dialect.items())}


def _cell(value: float | None, fmt: str) -> str:
    return "n. m." if value is None else format(value, fmt)


def format_table(summary: dict[str, dict], k: int) -> str:
    lines = [f"{'Dialekt':8} {'n':>4} {'P@' + str(k):>7} {'Recall':>7} {'Start':>7} {'Ende':>7}"]
    for d, agg in summary.items():
        start = _cell(agg.get("boundary_start_s"), ".1f")
        end = _cell(agg.get("boundary_end_s"), ".1f")
        lines.append(f"{d:8} {agg['n']:>4} {_cell(agg['precision_at_k'], '.2f'):>7} {_cell(agg['recall'], '.2f'):>7} {start:>7} {end:>7}")
    lines.append("n. m. heißt nicht messbar (leere Eingabe), nicht null. Start und Ende in Sekunden.")
    return "\n".join(lines)


# -- Neu: Referenzmomente, Funnel, Redakteure ------------------------------------------------------


def _span(d: dict) -> dict[str, float]:
    start = d.get("start_s", d.get("start"))
    end = d.get("end_s", d.get("end"))
    return {"start_s": float(start), "end_s": float(end)}


def _ranked(items: list[dict]) -> list[dict]:
    """Rangfolge: ``rank`` aufsteigend, sonst ``total`` absteigend, sonst wie geliefert."""
    if items and all("rank" in x for x in items):
        return sorted(items, key=lambda x: x["rank"])
    if items and all(x.get("total") is not None for x in items):
        return sorted(items, key=lambda x: x["total"], reverse=True)
    return list(items)


def funnel_stages(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Spannen je Stelle aus einem DetectReport-JSON, mit Ursache, wenn eine Stelle fehlt.

    ``report["funnel"] = {"pool": [...], "after_gates": [...], "offered": [...]}`` (je ``start_s``, ``end_s``).
    Ohne ``funnel``: Pool aus ``search.chapters[*].proposals`` (falls mit Zeiten vorhanden), angeboten aus
    ``candidates`` nach ``total``; nach Gates ist dann nicht ableitbar."""
    funnel = report.get("funnel")
    out: dict[str, dict[str, Any]] = {}
    if isinstance(funnel, dict):
        for stage in STAGES:
            items = funnel.get(stage)
            if isinstance(items, list):
                out[stage] = {"spannen": [_span(x) for x in _ranked(items)], "ursache": None, "herkunft": f"funnel.{stage}"}
            else:
                out[stage] = {"spannen": None, "ursache": f"funnel.{stage} fehlt im Bericht", "herkunft": None}
        return out
    chapters = (report.get("search") or {}).get("chapters") or []
    proposals = [p for ch in chapters if isinstance(ch, dict) for p in (ch.get("proposals") or [])]
    timed = [p for p in proposals if isinstance(p, dict) and p.get("start_s") is not None and p.get("end_s") is not None]
    if timed:
        out["pool"] = {"spannen": [_span(p) for p in timed], "ursache": None, "herkunft": "search.chapters.proposals"}
    else:
        cause = "funnel fehlt und search.chapters enthält keine Vorschläge mit Zeiten" if chapters else "funnel fehlt und der Bericht hat keine Suchkapitel"
        out["pool"] = {"spannen": None, "ursache": cause, "herkunft": None}
    out["after_gates"] = {"spannen": None, "ursache": "funnel fehlt; nach Gates ist aus dem Bericht nicht ableitbar", "herkunft": None}
    cands = report.get("candidates")
    if isinstance(cands, list):
        out["offered"] = {"spannen": [_span(c) for c in _ranked(cands)], "ursache": None, "herkunft": "candidates"}
    else:
        out["offered"] = {"spannen": None, "ursache": "candidates fehlt im Bericht", "herkunft": None}
    return out


def _best(span: dict, refs: list[dict]) -> tuple[dict | None, float]:
    best, best_iou = None, 0.0
    for r in refs:
        v = data_loader.span_iou(span, r)
        if v > best_iou:
            best, best_iou = r, v
    return best, best_iou


def coverage(refs: list[dict] | None, spans: list[dict] | None, threshold: float = IOU_MATCH) -> dict[str, Any]:
    """Anteil der Referenzmomente, die von mindestens einer Spanne mit IoU >= ``threshold`` getroffen werden."""
    if refs is None:
        return {"abgedeckt": None, "gesamt": None, "wert": None, "ursache": "keine Referenzmomente"}
    if not refs:
        return {"abgedeckt": None, "gesamt": 0, "wert": None, "ursache": "keine Referenzmomente"}
    if spans is None:
        return {"abgedeckt": None, "gesamt": len(refs), "wert": None, "ursache": "keine Spannen an dieser Stelle"}
    hit = sum(1 for r in refs if any(data_loader.span_iou(r, s) >= threshold for s in spans))
    return {"abgedeckt": hit, "gesamt": len(refs), "wert": hit / len(refs), "ursache": None}


def coverage_funnel(moments: list[dict] | None, stages: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out = {}
    for stage in STAGES:
        spans = stages[stage]["spannen"]
        gold = None if moments is None else [m for m in moments if m.get("stufe") == "gold"]
        res_all, res_gold = coverage(moments, spans), coverage(gold, spans)
        if spans is None:
            res_all["ursache"] = res_gold["ursache"] = stages[stage]["ursache"]
        out[stage] = {"alle": res_all, "gold": res_gold}
    return out


def recall_at(offered: list[dict] | None, refs: list[dict] | None, k: int = RECALL_K) -> dict[str, Any]:
    """Anteil der Referenzmomente unter den ersten k angebotenen; nichts angeboten ergibt gemessen 0."""
    return coverage(refs, None if offered is None else offered[:k])


def precision_at(offered: list[dict] | None, refs: list[dict] | None, k: int) -> dict[str, Any]:
    """Treffer unter den ersten k angebotenen geteilt durch deren Zahl (weniger als k sind zulässig)."""
    if offered is None:
        return {"treffer": None, "n": None, "wert": None, "ursache": "keine angebotenen Kandidaten im Bericht"}
    if refs is None:
        return {"treffer": None, "n": None, "wert": None, "ursache": "keine Referenz"}
    top = offered[:k]
    if not top:
        return {"treffer": None, "n": 0, "wert": None, "ursache": "nichts angeboten"}
    hits = sum(1 for p in top if _best(p, refs)[1] >= IOU_MATCH)
    return {"treffer": hits, "n": len(top), "wert": hits / len(top), "ursache": None}


def precision_per_editor(offered: list[dict] | None, editors: list[dict] | None, ks: tuple[int, ...] = PRECISION_KS) -> dict[str, Any]:
    """Precision@k gegen die Top-10 jedes Redakteurs und gemittelt über die Redakteure."""
    if not editors:
        cause = "keine Redakteurs-Top-10"
        return {"je_redakteur": {}, "gemittelt": {f"p@{k}": {"wert": None, "ursache": cause} for k in ks}}
    per = {ed["person"]: {f"p@{k}": precision_at(offered, ed["top10"], k) for k in ks} for ed in editors}
    mean = {}
    for k in ks:
        vals = [v[f"p@{k}"]["wert"] for v in per.values() if v[f"p@{k}"]["wert"] is not None]
        causes = {v[f"p@{k}"]["ursache"] for v in per.values() if v[f"p@{k}"]["ursache"]}
        mean[f"p@{k}"] = {"wert": _mean(vals), "redakteure": len(vals), "ursache": None if vals else "; ".join(sorted(causes))}
    return {"je_redakteur": per, "gemittelt": mean}


def boundary_errors(offered: list[dict] | None, refs: list[dict] | None, k: int = BOUNDARY_K) -> dict[str, Any]:
    """Absoluter Start- und Endfehler in Sekunden je getroffenem Kandidaten unter den ersten k; der Gesamtwert
    gewichtet den Start doppelt: (2 * Start + Ende) / 3."""
    starts, ends = [], []
    for p in (offered or [])[:k]:
        best, v = _best(p, refs or [])
        if best is not None and v >= IOU_MATCH:
            starts.append(abs(p["start_s"] - best["start_s"]))
            ends.append(abs(p["end_s"] - best["end_s"]))
    s = _boundary_summary(starts, ends)
    cause = None
    if not starts:
        cause = "keine Referenz" if refs is None else ("keine angebotenen Kandidaten" if not offered else "kein Treffer mit IoU >= 0,5")
    return {"start_s": s["boundary_start_s"], "ende_s": s["boundary_end_s"], "gewichtet_s": s["boundary_weighted_s"],
            "start_summe": sum(starts), "ende_summe": sum(ends), "n": len(starts), "ursache": cause}  # fmt: skip


def new_moments(offered: list[dict] | None, moments: list[dict] | None, editors: list[dict] | None, k: int = BOUNDARY_K) -> dict[str, Any]:
    """Angebotene Kandidaten unter den ersten k, die keine Referenz trifft (weder Spannen noch Top-10). Sie sind
    kein Fehler, sondern ein Prüfauftrag für die Redaktion."""
    if offered is None:
        return {"anzahl": None, "spannen": [], "ursache": "keine angebotenen Kandidaten im Bericht"}
    if moments is None and not editors:
        return {"anzahl": None, "spannen": [], "ursache": "keine Referenz"}
    refs = list(moments or []) + [x for ed in editors or [] for x in ed["top10"]]
    new = [p for p in offered[:k] if _best(p, refs)[1] < IOU_MATCH]
    return {"anzahl": len(new), "spannen": new, "ursache": None}


def evaluate_source(report: dict[str, Any], moments: list[dict] | None, editors: list[dict] | None = None) -> dict[str, Any]:
    stages = funnel_stages(report)
    offered = stages["offered"]["spannen"]
    return {
        "funnel_herkunft": {s: stages[s]["herkunft"] for s in STAGES},
        "abdeckung": coverage_funnel(moments, stages),
        "recall_at_20": {"alle": recall_at(offered, moments), "gold": recall_at(offered, None if moments is None else [m for m in moments if m["stufe"] == "gold"])},
        "precision": precision_per_editor(offered, editors),
        "grenzfehler": boundary_errors(offered, moments),
        "neue_momente": new_moments(offered, moments, editors),
        "angeboten": None if offered is None else len(offered),
        "referenzmomente": None if moments is None else {"gold": sum(1 for m in moments if m["stufe"] == "gold"), "silber": sum(1 for m in moments if m["stufe"] == "silber")},
    }  # fmt: skip


def _sum_ratio(items: list[dict], num: str, den: str) -> dict[str, Any]:
    usable = [x for x in items if x.get(num) is not None and x.get(den)]
    if not usable:
        causes = sorted({str(x.get("ursache")) for x in items if x.get("ursache")})
        return {num: None, den: None, "wert": None, "ursache": "; ".join(causes) or "keine Daten"}
    a, b = sum(x[num] for x in usable), sum(x[den] for x in usable)
    return {num: a, den: b, "wert": a / b, "ursache": None}


def aggregate_sources(rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Über Quellen summiert (Treffer und Nenner werden addiert, nicht Quoten gemittelt)."""
    vals = list(rows.values())
    cov = {stage: {lvl: _sum_ratio([r["abdeckung"][stage][lvl] for r in vals], "abgedeckt", "gesamt") for lvl in ("alle", "gold")} for stage in STAGES}
    recall = {lvl: _sum_ratio([r["recall_at_20"][lvl] for r in vals], "abgedeckt", "gesamt") for lvl in ("alle", "gold")}
    prec = {}
    for k in PRECISION_KS:
        cells = [ed[f"p@{k}"] for r in vals for ed in r["precision"]["je_redakteur"].values()]
        prec[f"p@{k}"] = _sum_ratio(cells, "treffer", "n") if cells else {"wert": None, "ursache": "keine Redakteurs-Top-10"}
    bnd = [r["grenzfehler"] for r in vals if r["grenzfehler"]["n"]]
    n = sum(b["n"] for b in bnd)
    start = sum(b["start_summe"] for b in bnd) / n if n else None
    end = sum(b["ende_summe"] for b in bnd) / n if n else None
    new = [r["neue_momente"]["anzahl"] for r in vals if r["neue_momente"]["anzahl"] is not None]
    return {
        "quellen": len(vals),
        "abdeckung": cov,
        "recall_at_20": recall,
        "precision": prec,
        "grenzfehler": {"start_s": start, "ende_s": end, "gewichtet_s": None if start is None else (START_WEIGHT * start + end) / (START_WEIGHT + 1), "n": n,
                        "ursache": None if n else "kein Treffer mit IoU >= 0,5 in einer Quelle"},
        "neue_momente": {"anzahl": sum(new) if new else None, "ursache": None if new else "keine Referenz"},
    }  # fmt: skip


def _metric(value: float | None, sample: int | None, cause: str | None) -> dict[str, Any]:
    return {"wert": value, "stichprobe": sample, "ursache": None if value is not None else (cause or "keine Daten")}


def metrics(agg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Kennzahlen im gemeinsamen Format für ``eval.baseline``."""
    out = {}
    for stage, name in (("pool", "abdeckung_pool"), ("after_gates", "abdeckung_nach_gates"), ("offered", "abdeckung_top_k")):
        c = agg["abdeckung"][stage]["alle"]
        out[name] = _metric(c["wert"], c["gesamt"], c["ursache"])
    r = agg["recall_at_20"]["alle"]
    out["recall_at_20"] = _metric(r["wert"], r["gesamt"], r["ursache"])
    for k in PRECISION_KS:
        p = agg["precision"][f"p@{k}"]
        out[f"precision_at_{k}"] = _metric(p["wert"], p.get("n"), p["ursache"])
    g = agg["grenzfehler"]
    for key, name in (("start_s", "grenzfehler_start_s"), ("ende_s", "grenzfehler_ende_s"), ("gewichtet_s", "grenzfehler_gewichtet_s")):
        out[name] = _metric(g[key], g["n"], g["ursache"])
    out["neue_momente"] = _metric(agg["neue_momente"]["anzahl"], None, agg["neue_momente"]["ursache"])
    return out


def run_data(data_dir: str | Path, reports_dir: str | Path, part: str = "entwicklung", confirmed: bool = False) -> dict[str, Any]:
    """Wertet alle Quellen eines Teils aus ``split.json`` aus; Quellen ohne Bericht stehen unter ``ohne_bericht``."""
    data_loader.check_part_access(part, confirmed)
    split = data_loader.load_split(Path(data_dir) / "split.json")
    rows, missing = {}, {}
    cuts: dict[str, list[dict]] = {"schnittpunkte": [], "clip_urteile": []}
    for src in data_loader.sources_in(split, part):
        key = data_loader.source_key(src)
        data = data_loader.load_source_data(data_dir, key)
        if "schnittpunkte" in data:
            for kind in cuts:
                cuts[kind] += [{**x, "clip_id": f"{key}/{x['clip_id']}"} for x in data["schnittpunkte"][kind]]
        report_path = Path(reports_dir) / f"{key}.json"
        if not report_path.is_file():
            missing[key] = f"Bericht {report_path.name} fehlt"
            continue
        report = json.loads(report_path.read_text(encoding="utf-8"))
        moments = data_loader.gold_silver(data["spannen"]["spannen"]) if "spannen" in data else None
        editors = data["redakteure"]["redakteure"] if "redakteure" in data else None
        rows[key] = evaluate_source(report, moments, editors)
    agg = aggregate_sources(rows) if rows else None
    cut = cut_quality(cuts)
    no_report = f"keine Quelle im Teil {part} mit DetectReport-Bericht in {Path(reports_dir).name}"
    out_metrics = metrics(agg) if agg else {name: _metric(None, None, no_report) for name in HARNESS_METRICS}
    out_metrics.update(cut["metriken"])
    return {"teil": part, "je_quelle": rows, "ohne_bericht": missing, "gesamt": agg, "schnitt": cut, "metriken": out_metrics}


def cut_quality(doc: dict[str, Any]) -> dict[str, Any]:
    """Schnitt-Natürlichkeit aus ``schnittpunkte/<quelle>.json``: Anteil der Urteile „natuerlich“ je Hörer und
    gesamt; ein Clip ist unbrauchbar, sobald ein Hörer einen Punkt „abgehackt“ nennt oder den Clip
    „unbrauchbar“."""
    points = doc.get("schnittpunkte") or []
    per_listener: dict[str, list[str]] = defaultdict(list)
    for p in points:
        per_listener[p["hoerer"]].append(p["urteil"])
    natural = sum(1 for p in points if p["urteil"] == "natuerlich")
    clips = sorted({p["clip_id"] for p in points} | {c["clip_id"] for c in doc.get("clip_urteile") or []})
    unusable = {p["clip_id"] for p in points if p["urteil"] == "abgehackt"}
    unusable |= {c["clip_id"] for c in doc.get("clip_urteile") or [] if c["urteil"] == "unbrauchbar"}
    res = {
        "urteile": len(points),
        "natuerlich_anteil": natural / len(points) if points else None,
        "je_hoerer": {h: sum(1 for v in vs if v == "natuerlich") / len(vs) for h, vs in sorted(per_listener.items())},
        "clips": len(clips),
        "clips_unbrauchbar": sorted(unusable),
        "clips_unbrauchbar_anteil": len(unusable) / len(clips) if clips else None,
        "ursache": None if points else "keine Schnittpunkt-Urteile",
    }
    res["metriken"] = {
        "schnitt_natuerlich_anteil": _metric(res["natuerlich_anteil"], len(points), "keine Schnittpunkt-Urteile"),
        "clips_unbrauchbar_anteil": _metric(res["clips_unbrauchbar_anteil"], len(clips), "keine Clips mit Schnitt- oder Clip-Urteil"),
    }
    return res


def _pct(value: float | None, cause: str | None = None) -> str:
    if value is None:
        return f"nicht messbar: {cause or 'keine Daten'}"
    return f"{value * 100:.1f} %".replace(".", ",")


def format_data_report(res: dict[str, Any]) -> str:
    lines = [f"Teil: {res['teil']}, Quellen mit Bericht: {len(res['je_quelle'])}"]
    for key, cause in sorted(res["ohne_bericht"].items()):
        lines.append(f"  {key}: nicht messbar: {cause}")
    cut = res["schnitt"]
    lines.append(f"Schnittpunkte natürlich       {_pct(cut['natuerlich_anteil'], cut['ursache'])}")
    lines.append(f"Clips unbrauchbar (Schnitt)   {_pct(cut['clips_unbrauchbar_anteil'], cut['ursache'])}")
    agg = res["gesamt"]
    if not agg:
        lines.append("Keine Quelle mit Bericht: Abdeckung, Recall, Precision und Grenzfehler nicht messbar.")
        return "\n".join(lines)
    for stage in STAGES:
        c = agg["abdeckung"][stage]["alle"]
        lines.append(f"Abdeckung {STAGE_LABELS[stage]:15} {_pct(c['wert'], c['ursache'])}")
    r = agg["recall_at_20"]["alle"]
    lines.append(f"Recall@20                 {_pct(r['wert'], r['ursache'])}")
    for k in PRECISION_KS:
        p = agg["precision"][f"p@{k}"]
        lines.append(f"Precision@{k:<2} (Redakteure) {_pct(p['wert'], p['ursache'])}")
    g = agg["grenzfehler"]
    if g["n"]:
        lines.append(f"Grenzfehler Start {g['start_s']:.2f} s, Ende {g['ende_s']:.2f} s, gewichtet {g['gewichtet_s']:.2f} s (n = {g['n']})".replace(".", ","))
    else:
        lines.append(f"Grenzfehler: nicht messbar: {g['ursache']}")
    nm = agg["neue_momente"]
    lines.append(f"Neu entdeckte Momente (kein Fehler, Prüfauftrag): {nm['anzahl'] if nm['anzahl'] is not None else 'nicht messbar: ' + nm['ursache']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Clip-Auswahl gegen Referenzen messen.")
    ap.add_argument("gold_dir", nargs="?", help="alt: Ordner mit Gold-Dateien")
    ap.add_argument("pred_dir", nargs="?", help="alt: Ordner mit Vorhersagen")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--daten", help="neu: Referenzdatensatz, z. B. eval/data")
    ap.add_argument("--berichte", help="neu: Ordner mit DetectReport-JSON je Quelle (<quelle>.json)")
    ap.add_argument("--teil", default="entwicklung", choices=data_loader.PARTS)
    ap.add_argument("--abschluss-bestaetigt", action="store_true", help="Abschlussteil auswerten (nur nach Festschreiben der Regeln)")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args(argv)
    if args.daten:
        if not args.berichte:
            raise SystemExit("--daten braucht --berichte.")
        try:
            result: Any = run_data(args.daten, args.berichte, args.teil, args.abschluss_bestaetigt)
        except data_loader.DataError as exc:
            raise SystemExit(f"Fehler: {exc}") from exc
        print(format_data_report(result))
    else:
        if not args.gold_dir or not args.pred_dir:
            raise SystemExit("Entweder gold_dir und pred_dir (alt) oder --daten und --berichte (neu) angeben.")
        result = run(args.gold_dir, args.pred_dir, args.k)
        print(format_table(result, args.k))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
