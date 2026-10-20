"""Baseline und Vergleich je Metrik mit Einheit, Richtung, Toleranz und Stichprobe (Launch-Auftrag 6.3).

    .venv/bin/python -m eval.baseline --messen-testmaterial eval/runs/testmaterial --out messung_testmaterial.json
    .venv/bin/python -m eval.baseline --messen-ausbeute berichte/*.json --out messung_ausbeute.json
    .venv/bin/python -m eval.baseline --erstellen messung_a.json messung_b.json --provider ... --policy ... --hardware ...
    .venv/bin/python -m eval.baseline --vergleich neu_a.json neu_b.json --aenderung kurzname [--datum 2026-10-21]

Eine Messung ist jede JSON-Datei mit ``"metriken": {name: {"wert", "stichprobe", "ursache"}}``; so schreiben es
``eval_harness --daten``, ``speaker_eval``, ``alignment_eval``, ``repro_eval``, ``cost_eval``, ``sinnfehler``,
``wer_eval`` und ``blind_compare --auswerten`` (Wettbewerbsmodus) in ihr ``--json``. Jede Metrik muss in
``METRICS`` stehen, damit Einheit, Richtung und Toleranz feststehen.

``--erstellen`` schreibt ``eval/results/baseline.json``: je Metrik Wert oder ``None`` mit Ursache, dazu Einheit,
Richtung, Toleranz, Stichprobe, Provider, Policy-Fassung und Hardware-Notiz. ``--vergleich`` schreibt
``eval/results/<datum>-<aenderung>.md`` mit Metrik, Baseline, neu, Differenz, Toleranz und Urteil (ok,
verschlechtert, nicht messbar). Eine Verschlechterung über die Toleranz ergibt Exit-Code 1 (blockiert den
Merge); nicht messbar blockiert nicht, steht aber mit Ursache im Bericht.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

RESULTS_DIR = Path(__file__).parent / "results"
BASELINE_FILE = RESULTS_DIR / "baseline.json"
VERDICTS = ("ok", "verschlechtert", "nicht messbar")
HIGHER, LOWER, INFO = "hoeher", "niedriger", "information"

# Toleranzen sind erste Festlegungen aus Phase 0 (docs/decisions/060-messsystem.md); sie gelten in der Einheit
# der Metrik als absolute Differenz. Richtung: welche Änderung besser ist.
METRICS: dict[str, dict[str, Any]] = {
    "abdeckung_pool": {"einheit": "Anteil", "richtung": HIGHER, "toleranz": 0.05, "beschreibung": "Referenzmomente im Kandidatenpool (IoU >= 0,5)"},
    "abdeckung_nach_gates": {"einheit": "Anteil", "richtung": HIGHER, "toleranz": 0.05, "beschreibung": "Referenzmomente nach den Gates"},
    "abdeckung_top_k": {"einheit": "Anteil", "richtung": HIGHER, "toleranz": 0.05, "beschreibung": "Referenzmomente unter den angebotenen Kandidaten"},
    "recall_at_20": {"einheit": "Anteil", "richtung": HIGHER, "toleranz": 0.05, "beschreibung": "Referenzmomente unter den ersten 20 angebotenen"},
    "precision_at_5": {"einheit": "Anteil", "richtung": HIGHER, "toleranz": 0.05, "beschreibung": "Precision@5 gegen Redakteurs-Top-10, gemittelt"},
    "precision_at_10": {"einheit": "Anteil", "richtung": HIGHER, "toleranz": 0.05, "beschreibung": "Precision@10 gegen Redakteurs-Top-10, gemittelt"},
    "grenzfehler_start_s": {"einheit": "s", "richtung": LOWER, "toleranz": 0.3, "beschreibung": "mittlerer Startfehler getroffener Kandidaten"},
    "grenzfehler_ende_s": {"einheit": "s", "richtung": LOWER, "toleranz": 0.5, "beschreibung": "mittlerer Endfehler getroffener Kandidaten"},
    "grenzfehler_gewichtet_s": {"einheit": "s", "richtung": LOWER, "toleranz": 0.3, "beschreibung": "(2 x Start + Ende) / 3"},
    "neue_momente": {"einheit": "Anzahl", "richtung": INFO, "toleranz": None, "beschreibung": "angeboten, in keiner Referenz; Prüfauftrag, kein Fehler"},
    "wer_de": {"einheit": "Anteil", "richtung": LOWER, "toleranz": 0.005, "beschreibung": "WER Hochdeutsch gegen eigenes Referenzmaterial"},
    "wer_at": {"einheit": "Anteil", "richtung": LOWER, "toleranz": 0.01, "beschreibung": "WER österreichisches Deutsch"},
    "wer_ch": {"einheit": "Anteil", "richtung": LOWER, "toleranz": 0.02, "beschreibung": "WER Schweizerdeutsch zu Hochdeutsch (Beta)"},
    "wer_de_synthetisch": {"einheit": "Anteil", "richtung": LOWER, "toleranz": 0.005, "beschreibung": "WER auf dem synthetischen Testmaterial (Sprachsynthese), nur Regressionssignal"},
    "sprecher_korrekt_overlap": {"einheit": "Anteil", "richtung": HIGHER, "toleranz": 0.02, "beschreibung": "Wörter in Überlappung mit korrektem Sprecher"},
    "sprecher_korrekt_gesamt": {"einheit": "Anteil", "richtung": HIGHER, "toleranz": 0.02, "beschreibung": "alle Wörter mit korrektem Sprecher"},
    "cpwer": {"einheit": "Anteil", "richtung": LOWER, "toleranz": 0.01, "beschreibung": "concatenated minimum-permutation WER"},
    "der": {"einheit": "Anteil", "richtung": LOWER, "toleranz": 0.01, "beschreibung": "DER ohne Collar mit Überlappung"},
    "versatz_anfang_median_ms": {"einheit": "ms", "richtung": LOWER, "toleranz": 10, "beschreibung": "Wortanfang gegen Audioanker, Median"},
    "versatz_anfang_p95_ms": {"einheit": "ms", "richtung": LOWER, "toleranz": 20, "beschreibung": "Wortanfang gegen Audioanker, 95. Perzentil"},
    "versatz_ende_median_ms": {"einheit": "ms", "richtung": LOWER, "toleranz": 10, "beschreibung": "Wortende gegen Audioanker, Median"},
    "versatz_ende_p95_ms": {"einheit": "ms", "richtung": LOWER, "toleranz": 20, "beschreibung": "Wortende gegen Audioanker, 95. Perzentil"},
    "alignment_fehlend_anteil": {"einheit": "Anteil", "richtung": LOWER, "toleranz": 0.01, "beschreibung": "Anker ohne zugeordnetes Wort"},
    "versatz_anfang_median_synthetisch_ms": {"einheit": "ms", "richtung": LOWER, "toleranz": 20, "beschreibung": "Wortanfang gegen Satzgrenzen der Montage (Testmaterial), nur Regressionssignal"},
    "versatz_ende_median_synthetisch_ms": {"einheit": "ms", "richtung": LOWER, "toleranz": 20, "beschreibung": "Wortende gegen Satzgrenzen der Montage (Testmaterial), nur Regressionssignal"},
    "jaccard_top5_mittel": {"einheit": "Anteil", "richtung": HIGHER, "toleranz": 0.05, "beschreibung": "Jaccard der Top-5 über frische Läufe, paarweise gemittelt"},
    "rang1_gleich_anteil": {"einheit": "Anteil", "richtung": HIGHER, "toleranz": 0.0, "beschreibung": "Läufe mit gleichem Rang 1 wie der Bezugslauf"},
    "repro_bestanden_anteil": {"einheit": "Anteil", "richtung": HIGHER, "toleranz": 0.0, "beschreibung": "Läufe mit Jaccard >= 0,8 und gleichem Rang 1"},
    "jaccard_top5_mittel_gespeichert": {"einheit": "Anteil", "richtung": HIGHER, "toleranz": 0.0, "beschreibung": "gespeicherte Wiederholung, muss 1 sein"},
    "rang1_gleich_anteil_gespeichert": {"einheit": "Anteil", "richtung": HIGHER, "toleranz": 0.0, "beschreibung": "gespeicherte Wiederholung, Rang 1"},
    "repro_bestanden_anteil_gespeichert": {"einheit": "Anteil", "richtung": HIGHER, "toleranz": 0.0, "beschreibung": "gespeicherte Wiederholung identisch"},
    "eur_je_quellstunde": {"einheit": "EUR", "richtung": LOWER, "toleranz": 0.10, "beschreibung": "geschätzte Kosten je Quellstunde"},
    "rechenzeit_s_je_quellstunde": {"einheit": "s", "richtung": LOWER, "toleranz": 60, "beschreibung": "CPU plus GPU Sekunden je Quellstunde"},
    "wartezeit_s_je_quellstunde": {"einheit": "s", "richtung": LOWER, "toleranz": 60, "beschreibung": "Wanduhr Upload bis Kandidatenliste je Quellstunde"},
    "sinnfehler_obere_grenze": {"einheit": "Anteil", "richtung": LOWER, "toleranz": 0.0, "beschreibung": "obere 95-%-Grenze kritischer Sinnfehler (Clopper-Pearson)"},
    "sinnfehler_beobachtet": {"einheit": "Anteil", "richtung": LOWER, "toleranz": 0.0, "beschreibung": "beobachteter Anteil Clips mit bestätigtem kritischem Sinnfehler"},
    "schnitt_natuerlich_anteil": {"einheit": "Anteil", "richtung": HIGHER, "toleranz": 0.02, "beschreibung": "Schnittpunkt-Urteile natürlich"},
    "clips_unbrauchbar_anteil": {"einheit": "Anteil", "richtung": LOWER, "toleranz": 0.02, "beschreibung": "Clips mit abgehacktem Schnitt oder Urteil unbrauchbar"},
    "angeboten_je_quellstunde": {"einheit": "je Quellstunde", "richtung": INFO, "toleranz": None, "beschreibung": "angebotene Kandidaten je Quellstunde (report.yield)"},
    "verwendbare_je_quellstunde": {"einheit": "je Quellstunde", "richtung": HIGHER, "toleranz": 0.5, "beschreibung": "angebotene mit review_state passed je Quellstunde"},
    "verschiedene_je_quellstunde": {"einheit": "je Quellstunde", "richtung": HIGHER, "toleranz": 0.5, "beschreibung": "untereinander verschiedene angebotene je Quellstunde (report.yield.distinct)"},
    "verwerfungsquote_gesamt": {"einheit": "Anteil", "richtung": INFO, "toleranz": None, "beschreibung": "verworfene Vorschläge im Pool (funnel_counts, sonst discarded)"},
    "blind_gewinnrate": {"einheit": "Anteil", "richtung": HIGHER, "toleranz": 0.05, "beschreibung": "chopstr gewinnt unter den entschiedenen Urteilen"},
    "beide_unbrauchbar_anteil": {"einheit": "Anteil", "richtung": LOWER, "toleranz": 0.05, "beschreibung": "Urteile beide unbrauchbar"},
}  # fmt: skip
# Verwerfungsquote je Grund: Name ``verwerfungsquote_<grund>``, Gründe kommen aus dem Bericht und sind nicht vorab bekannt.
REASON_PREFIX = "verwerfungsquote_"
REASON_SPEC = {"einheit": "Anteil", "richtung": INFO, "toleranz": None, "beschreibung": "Anteil der Pool-Vorschläge, die mit diesem Grund verworfen wurden"}


def spec_for(name: str) -> dict[str, Any] | None:
    if name in METRICS:
        return METRICS[name]
    if name.startswith(REASON_PREFIX) and len(name) > len(REASON_PREFIX):
        return REASON_SPEC
    return None


def merge_measurements(docs: list[tuple[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """Metriken aus mehreren Messungen; jede Metrik darf nur aus einer Datei kommen."""
    out: dict[str, dict[str, Any]] = {}
    for name, doc in docs:
        metrics = doc.get("metriken") if isinstance(doc, dict) else None
        if not isinstance(metrics, dict):
            raise SystemExit(f"{name}: Feld metriken fehlt; das Werkzeug mit --json aufrufen.")
        for key, entry in metrics.items():
            if spec_for(key) is None:
                raise SystemExit(f"{name}: Metrik {key!r} ist nicht registriert (METRICS in eval/baseline.py).")
            if key in out:
                raise SystemExit(f"{name}: Metrik {key!r} steht auch in {out[key]['herkunft']}.")
            value = entry.get("wert")
            cause = entry.get("ursache")
            if value is None and not cause:
                cause = "keine Ursache angegeben"
            out[key] = {"wert": value, "stichprobe": entry.get("stichprobe"), "ursache": None if value is not None else cause, "herkunft": name,
                        **({"hinweis": entry["hinweis"]} if entry.get("hinweis") else {})}  # fmt: skip
    return out


def make_baseline(docs: list[tuple[str, dict[str, Any]]], provider: str | None, policy: str | None, hardware: str | None, date: str) -> dict[str, Any]:
    measured = merge_measurements(docs)
    metrics = {}
    for key in [*METRICS, *sorted(k for k in measured if k not in METRICS)]:
        m = measured.get(key) or {"wert": None, "stichprobe": None, "ursache": "nicht gemessen: keine Messung mit dieser Metrik", "herkunft": None}
        metrics[key] = {**spec_for(key), **m}
    meta = {k: v for name, doc in docs for k, v in doc.items() if k in ("provider", "policy", "hardware") and v}
    return {
        "fassung": "baseline_v1", "erstellt_am": date,
        "provider": provider or meta.get("provider"), "policy": policy or meta.get("policy"), "hardware": hardware or meta.get("hardware"),
        "hinweis": "Werte None heißen nicht messbar, die Ursache steht daneben. Toleranz ist die erlaubte absolute Verschlechterung in der Einheit der Metrik.",
        "metriken": metrics,
    }  # fmt: skip


def judge(spec: dict[str, Any], base: float | None, new: float | None) -> str:
    if base is None or new is None:
        return "nicht messbar"
    if spec["richtung"] == INFO:
        return "ok"
    tol = float(spec.get("toleranz") or 0.0)
    if spec["richtung"] == HIGHER:
        return "verschlechtert" if new < base - tol - 1e-12 else "ok"
    return "verschlechtert" if new > base + tol + 1e-12 else "ok"


def compare(baseline: dict[str, Any], docs: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    new = merge_measurements(docs)
    rows = []
    extra = sorted({k for k in (*baseline["metriken"], *new) if k not in METRICS and spec_for(k) is not None})
    for key in [*METRICS, *extra]:
        b = baseline["metriken"].get(key) or {**spec_for(key), "wert": None, "ursache": "nicht in der Baseline"}
        spec = {**spec_for(key), **{k: b[k] for k in ("richtung", "toleranz", "einheit") if k in b}}
        n = new.get(key) or {"wert": None, "ursache": "nicht gemessen", "stichprobe": None}
        verdict = judge(spec, b.get("wert"), n.get("wert"))
        causes = []
        if b.get("wert") is None:
            causes.append(f"Baseline: {b.get('ursache')}")
        if n.get("wert") is None:
            causes.append(f"neu: {n.get('ursache')}")
        rows.append({
            "metrik": key, "einheit": spec["einheit"], "richtung": spec["richtung"], "toleranz": spec.get("toleranz"),
            "baseline": b.get("wert"), "neu": n.get("wert"), "differenz": None if verdict == "nicht messbar" else n["wert"] - b["wert"],
            "stichprobe_baseline": b.get("stichprobe"), "stichprobe_neu": n.get("stichprobe"), "urteil": verdict, "ursache": "; ".join(causes) or None,
        })  # fmt: skip
    return rows


def _fmt(value: float | None, unit: str) -> str:
    if value is None:
        return "nicht messbar"
    if unit == "Anteil":
        return f"{value * 100:.1f} %".replace(".", ",")
    if unit == "Anzahl":
        return str(int(value))
    return f"{value:.2f} {unit}".replace(".", ",")


# -- Ausbeute aus DetectReports (report.yield, funnel_counts, discarded) --------------------------------


def _reason_key(reason: str) -> str:
    return REASON_PREFIX + (re.sub(r"[^a-z0-9]+", "_", str(reason).lower()).strip("_") or "ohne_grund")


def _review_state_name(value: object) -> str | None:
    """``state`` aus ``rubric.review_state`` (Objekt) oder der String selbst; None, wenn es fehlt."""
    if isinstance(value, dict):
        state = value.get("state")
        return str(state) if state else None
    return str(value) if isinstance(value, str) and value else None


def yield_of_report(report: dict[str, Any]) -> dict[str, Any]:
    """Ausbeute einer Quelle: angeboten, verwendbar (``rubric.review_state == "passed"``), verschieden, Quellstunden
    und Verwerfungen je Grund. Was im Bericht fehlt, ist ``None`` mit Ursache."""
    y = report.get("yield")
    out: dict[str, Any] = {"stunden": None, "angeboten": None, "verschieden": None, "verwendbar": None, "ursache": None, "verwendbar_ursache": None}
    if not isinstance(y, dict):
        out["ursache"] = out["verwendbar_ursache"] = "yield fehlt im Bericht"
    elif not y.get("source_hours"):
        out["ursache"] = out["verwendbar_ursache"] = "yield.source_hours fehlt oder ist 0"
    else:
        out.update(stunden=float(y["source_hours"]), angeboten=int(y.get("offered") or 0), verschieden=y.get("distinct"))
        cands = report.get("candidates") or []
        # review_state ist ein Objekt {"state", "reasons", "repair"} (Lane P3, CANDIDATES.md); ein nackter
        # String wird zur Sicherheit ebenfalls gelesen.
        states = [_review_state_name((c.get("rubric") or {}).get("review_state")) for c in cands]
        if out["angeboten"] == 0:
            out["verwendbar"] = 0
        elif cands and all(st is not None for st in states):
            out["verwendbar"] = sum(1 for st in states if st == "passed")
        else:
            out["verwendbar_ursache"] = "review_state fehlt im Bericht (Schalter review.review_state aus)"
    counts = report.get("funnel_counts")
    if isinstance(counts, dict) and isinstance(counts.get("pool_reasons"), dict) and counts.get("pool") is not None:
        out["gruende"], out["nenner"], out["gruende_herkunft"] = dict(counts["pool_reasons"]), int(counts["pool"]), "funnel_counts"
    elif isinstance(report.get("discarded"), list):
        reasons: dict[str, int] = {}
        for d in report["discarded"]:
            r = str(d.get("reason") or "ohne_grund")
            if r in ("budget_exhausted", "clip_candidate_error"):
                continue  # Laufereignisse, kein einzelner Vorschlag
            reasons[r] = reasons.get(r, 0) + 1
        out["gruende"], out["nenner"], out["gruende_herkunft"] = reasons, sum(reasons.values()) + len(report.get("candidates") or []), "discarded"
    else:
        out["gruende"], out["nenner"], out["gruende_herkunft"] = None, None, None
    return out


def measure_yield(reports: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    """Ausbeute über Quellen: Summen geteilt durch die Summe der Quellstunden; Verwerfungsquote je Grund über die
    Summe der Pool-Vorschläge."""
    rows = {name: yield_of_report(r) for name, r in reports}
    with_yield = {n: r for n, r in rows.items() if r["stunden"]}
    hours = sum(r["stunden"] for r in with_yield.values())
    no_yield = "; ".join(f"{n}: {r['ursache']}" for n, r in rows.items() if not r["stunden"]) or "keine Berichte"

    def per_hour(field: str, cause_field: str) -> dict[str, Any]:
        missing = [f"{n}: {r[cause_field] or 'Wert fehlt'}" for n, r in with_yield.items() if r[field] is None]
        if not with_yield:
            return {"wert": None, "stichprobe": None, "ursache": no_yield}
        if missing:
            return {"wert": None, "stichprobe": None, "ursache": "; ".join(missing)}
        return {"wert": sum(r[field] for r in with_yield.values()) / hours, "stichprobe": len(with_yield), "ursache": None}

    metrics = {
        "angeboten_je_quellstunde": per_hour("angeboten", "ursache"),
        "verwendbare_je_quellstunde": per_hour("verwendbar", "verwendbar_ursache"),
        "verschiedene_je_quellstunde": per_hour("verschieden", "ursache"),
    }
    counted = [r for r in rows.values() if r["gruende"] is not None]
    den = sum(r["nenner"] for r in counted)
    if counted and den:
        reasons: dict[str, int] = {}
        for r in counted:
            for k, v in r["gruende"].items():
                reasons[k] = reasons.get(k, 0) + v
        metrics["verwerfungsquote_gesamt"] = {"wert": sum(reasons.values()) / den, "stichprobe": den, "ursache": None}
        for k, v in sorted(reasons.items()):
            metrics[_reason_key(k)] = {"wert": v / den, "stichprobe": den, "ursache": None}
    else:
        cause = "funnel_counts und discarded fehlen im Bericht" if not counted else "keine Vorschläge im Pool"
        metrics["verwerfungsquote_gesamt"] = {"wert": None, "stichprobe": None, "ursache": cause if reports else "keine Berichte"}
    return {"quelle": f"ausbeute: {', '.join(rows) or 'keine Berichte'}", "je_quelle": rows, "quell_stunden": hours or None, "metriken": metrics}


def _fmt_diff(value: float | None, unit: str) -> str:
    if value is None:
        return "nicht messbar"
    sign = "+" if value > 0 else ""
    if unit == "Anteil":
        return f"{sign}{value * 100:.1f} Punkte".replace(".", ",")
    return f"{sign}{value:.2f} {unit}".replace(".", ",")


def report_markdown(rows: list[dict[str, Any]], baseline: dict[str, Any], change: str, date: str, sources: list[str]) -> str:
    worse = [r for r in rows if r["urteil"] == "verschlechtert"]
    unmeasured = [r for r in rows if r["urteil"] == "nicht messbar"]
    lines = [
        f"# Vergleich gegen die Baseline: {change}", "",
        f"Datum: {date}. Baseline vom {baseline.get('erstellt_am')}, Provider {baseline.get('provider') or 'nicht angegeben'}, "
        f"Policy {baseline.get('policy') or 'nicht angegeben'}, Hardware {baseline.get('hardware') or 'nicht angegeben'}.",
        f"Messungen: {', '.join(sources)}.", "",
        f"**Ergebnis: {'verschlechtert, blockiert den Merge' if worse else 'keine Verschlechterung über der Toleranz'}** "
        f"({len(worse)} verschlechtert, {len(unmeasured)} nicht messbar, {len(rows) - len(worse) - len(unmeasured)} ok).", "",
        "| Metrik | Baseline | neu | Differenz | Toleranz | Urteil |", "|---|---|---|---|---|---|",
    ]  # fmt: skip
    for r in rows:
        tol = "keine (nur Information)" if r["richtung"] == INFO else _fmt_diff(r["toleranz"], r["einheit"]).lstrip("+")
        verdict = r["urteil"] if r["urteil"] != "nicht messbar" else f"nicht messbar: {r['ursache']}"
        lines.append(f"| {r['metrik']} | {_fmt(r['baseline'], r['einheit'])} | {_fmt(r['neu'], r['einheit'])} | {_fmt_diff(r['differenz'], r['einheit'])} | {tol} | {verdict} |")
    lines += ["", "Richtung je Metrik und Beschreibung stehen in eval/baseline.py (METRICS). Nicht messbar heißt nie bestanden und nie null."]
    return "\n".join(lines) + "\n"


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")).strip("-")
    if not s:
        raise SystemExit("--aenderung braucht einen Namen aus Buchstaben oder Ziffern.")
    return s


def write_comparison(baseline_path: Path, docs: list[tuple[str, dict[str, Any]]], change: str, date: str, out_dir: Path) -> tuple[Path, list[dict[str, Any]]]:
    if not baseline_path.is_file():
        raise SystemExit(f"{baseline_path} fehlt; erst --erstellen.")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    rows = compare(baseline, docs)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{date}-{slug(change)}.md"
    path.write_text(report_markdown(rows, baseline, change, date, [n for n, _ in docs]), encoding="utf-8")
    return path, rows


# -- Messung aus dem synthetischen Testmaterial ---------------------------------------------------------


def measure_testmaterial(folder: str | Path) -> dict[str, Any]:
    """WER und Wortzeiten des synthetischen Testmaterials (``eval/runs/testmaterial``): je Gespräch
    ``<name>/sprecherwechsel.json`` gegen ``transkripte/<name>.json``. Die Sprecher im Transkript stammen aus der
    Montage, nicht aus einer Diarisierung; Sprechermetriken sind darauf nicht messbar."""
    from eval import alignment_eval, wer_eval

    base = Path(folder)
    errors = n_ref = 0
    rows: list[dict] = []
    names = []
    for gt in sorted(base.glob("*/sprecherwechsel.json")):
        name = gt.parent.name
        tr = base / "transkripte" / f"{name}.json"
        if not tr.is_file():
            continue
        doc = json.loads(gt.read_text(encoding="utf-8"))
        words = json.loads(tr.read_text(encoding="utf-8"))
        words = words["words"] if isinstance(words, dict) else words
        r = wer_eval.evaluate_pair(" ".join(s["text"] for s in doc["saetze"]), " ".join(w["text"] for w in words), "DE", [])
        errors += r["sub"] + r["del"] + r["ins"]
        n_ref += r["n_ref"]
        rows += alignment_eval.match_anchors(alignment_eval.anchors_from_speaker_changes(doc), words)
        names.append(name)
    summary = alignment_eval.summarize(rows)
    none = "kein Gespräch mit sprecherwechsel.json und Transkript gefunden"
    synth = "Sprachsynthese (macOS say), kein echtes Material"
    diar = "Sprecher im Transkript stammen aus der Montage (synthetisch), keine echte Diarisierung"
    return {
        "quelle": f"testmaterial: {', '.join(names) or 'leer'}",
        "hinweis": f"{synth}. Anker sind Satzgrenzen der Montage, keine manuell kontrollierten Audioanker.",
        "metriken": {
            "wer_de_synthetisch": {"wert": errors / n_ref if n_ref else None, "stichprobe": n_ref, "ursache": None if n_ref else none, "hinweis": synth},
            "versatz_anfang_median_synthetisch_ms": {"wert": summary["anfang"]["median_ms"], "stichprobe": summary["anfang"]["n"], "ursache": summary["anfang"]["ursache"],
                                                     "hinweis": f"Median mit Vorzeichen {summary['anfang']['median_mit_vorzeichen_ms']} ms (negativ: Wortanfang im Transkript vor der Montagegrenze)"},
            "versatz_ende_median_synthetisch_ms": {"wert": summary["ende"]["median_ms"], "stichprobe": summary["ende"]["n"], "ursache": summary["ende"]["ursache"],
                                                   "hinweis": f"Median mit Vorzeichen {summary['ende']['median_mit_vorzeichen_ms']} ms"},
            "sprecher_korrekt_overlap": {"wert": None, "stichprobe": None, "ursache": f"{diar}; außerdem ohne Überlappung"},
            "sprecher_korrekt_gesamt": {"wert": None, "stichprobe": None, "ursache": diar},
            "cpwer": {"wert": None, "stichprobe": None, "ursache": diar},
            "der": {"wert": None, "stichprobe": None, "ursache": diar},
        },
    }  # fmt: skip


def _docs(paths: list[str]) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for p in paths:
        path = Path(p)
        if not path.is_file():
            raise SystemExit(f"{p} fehlt.")
        out.append((path.name, json.loads(path.read_text(encoding="utf-8"))))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Baseline erstellen und neue Läufe dagegen vergleichen.")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--erstellen", nargs="+", metavar="MESSUNG", help="Messungen (JSON mit metriken) zur Baseline zusammenführen")
    mode.add_argument("--vergleich", nargs="+", metavar="MESSUNG", help="Messungen eines neuen Laufs gegen die Baseline halten")
    mode.add_argument("--messen-testmaterial", metavar="ORDNER", help="WER und Wortzeiten des synthetischen Testmaterials messen")
    mode.add_argument("--messen-ausbeute", nargs="+", metavar="BERICHT", help="Ausbeute und Verwerfungsquoten aus DetectReport-JSONs")
    ap.add_argument("--baseline", default=str(BASELINE_FILE))
    ap.add_argument("--out", help="Ziel für --erstellen (Standard eval/results/baseline.json) oder --messen-testmaterial")
    ap.add_argument("--aenderung", help="Kurzname der Änderung für --vergleich")
    ap.add_argument("--datum", default=dt.date.today().isoformat())
    ap.add_argument("--ziel", default=str(RESULTS_DIR), help="Ordner für den Vergleichsbericht")
    ap.add_argument("--provider")
    ap.add_argument("--policy")
    ap.add_argument("--hardware")
    args = ap.parse_args(argv)
    if args.messen_testmaterial:
        if not args.out:
            raise SystemExit("--messen-testmaterial braucht --out.")
        doc = measure_testmaterial(args.messen_testmaterial)
        Path(args.out).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Messung geschrieben: {args.out}")
        return 0
    if args.messen_ausbeute:
        if not args.out:
            raise SystemExit("--messen-ausbeute braucht --out.")
        doc = measure_yield(_docs(args.messen_ausbeute))
        Path(args.out).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Messung geschrieben: {args.out}")
        return 0
    if args.erstellen:
        doc = make_baseline(_docs(args.erstellen), args.provider, args.policy, args.hardware, args.datum)
        target = Path(args.out or args.baseline)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        measured = sum(1 for m in doc["metriken"].values() if m["wert"] is not None)
        print(f"Baseline geschrieben: {target} ({measured} von {len(doc['metriken'])} Metriken gemessen, Rest nicht messbar mit Ursache)")
        return 0
    if not args.aenderung:
        raise SystemExit("--vergleich braucht --aenderung.")
    path, rows = write_comparison(Path(args.baseline), _docs(args.vergleich), args.aenderung, args.datum, Path(args.ziel))
    worse = [r["metrik"] for r in rows if r["urteil"] == "verschlechtert"]
    print(f"Bericht geschrieben: {path}")
    if worse:
        print("Verschlechtert über der Toleranz: " + ", ".join(worse))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
