"""WER-Auswertung für deutsche ASR, getrennt nach Dialekt (DE/AT/CH), plus Eigennamen-Fehlerrate.

Normalisierung (deutsch):
- Kleinschreibung, Satzzeichen entfernen, Whitespace zusammenfassen
- ß/ss optional gleichsetzen (``--ch`` bzw. Dialekt CH), Zahlen bleiben als Token unverändert

Eigennamen-Fehlerrate: Anteil der Lexikon-Token (Markenwörterbuch, Namen) in der Referenz, die in der
Alignierung nicht exakt getroffen wurden.

Eingabe: Ordner mit Referenzen (``<name>.json`` mit {"dialect","text","names"} oder ``<name>.txt``)
und Hypothesen (``<name>.json`` mit {"words":[{"text":...}]} oder {"text": "..."}).
Aufruf: python -m eval.wer_eval gold/ hyp/ [--lexicon names.txt] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")


def normalize(text: str, ch: bool = False) -> list[str]:
    """Kleinschreibung, Satzzeichen raus; ``ch=True`` setzt ß und ss gleich."""
    t = text.lower().replace("’", "").replace("'", "")
    t = _PUNCT.sub(" ", t)
    if ch:
        t = t.replace("ß", "ss")
    return [tok for tok in _WS.split(t.strip()) if tok]


@dataclass
class Alignment:
    sub: int = 0
    dele: int = 0
    ins: int = 0
    n_ref: int = 0
    ops: list[tuple[str, str | None, str | None]] = field(default_factory=list)  # (op, ref, hyp)

    @property
    def errors(self) -> int:
        return self.sub + self.dele + self.ins

    @property
    def wer(self) -> float:
        return self.errors / self.n_ref if self.n_ref else (0.0 if not self.ins else 1.0)


def align(ref: list[str], hyp: list[str]) -> Alignment:
    """Levenshtein auf Wortebene mit Rückverfolgung (eigene Implementierung, keine Abhängigkeit)."""
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        d[i][0] = i
    for j in range(1, m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
    out = Alignment(n_ref=n)
    i, j = n, m
    ops: list[tuple[str, str | None, str | None]] = []
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (0 if ref[i - 1] == hyp[j - 1] else 1):
            if ref[i - 1] == hyp[j - 1]:
                ops.append(("ok", ref[i - 1], hyp[j - 1]))
            else:
                ops.append(("sub", ref[i - 1], hyp[j - 1]))
                out.sub += 1
            i, j = i - 1, j - 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            ops.append(("del", ref[i - 1], None))
            out.dele += 1
            i -= 1
        else:
            ops.append(("ins", None, hyp[j - 1]))
            out.ins += 1
            j -= 1
    out.ops = list(reversed(ops))
    return out


def name_error_rate(al: Alignment, lexicon: set[str]) -> tuple[float, int, int]:
    """(Rate, Fehler, Gesamt) über Referenz-Token, die im Lexikon stehen."""
    total = errors = 0
    for op, r, _h in al.ops:
        if r is not None and r in lexicon:
            total += 1
            if op != "ok":
                errors += 1
    return (errors / total if total else 0.0), errors, total


def load_reference(path: Path) -> dict:
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return {"text": data.get("text", ""), "dialect": data.get("dialect", "DE"), "names": data.get("names", [])}
    text = path.read_text(encoding="utf-8")
    m = re.search(r"[._-](DE|AT|CH)$", path.stem)
    return {"text": text, "dialect": m.group(1) if m else "DE", "names": []}


def load_hypothesis(path: Path) -> str:
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if "words" in data:
            return " ".join(str(w.get("text", "")) for w in data["words"])
        return str(data.get("text", ""))
    return path.read_text(encoding="utf-8")


def find_hypothesis(hyp_dir: Path, stem: str) -> Path | None:
    for cand in (hyp_dir / f"{stem}.json", hyp_dir / f"{stem}.hyp.json", hyp_dir / f"{stem}.txt"):
        if cand.exists():
            return cand
    return None


def evaluate_pair(ref_text: str, hyp_text: str, dialect: str, names: list[str], ch: bool | None = None) -> dict:
    ch = (dialect == "CH") if ch is None else ch
    ref, hyp = normalize(ref_text, ch), normalize(hyp_text, ch)
    al = align(ref, hyp)
    lex = {tok for n in names for tok in normalize(n, ch)}
    ner, n_err, n_tot = name_error_rate(al, lex)
    return {
        "dialect": dialect,
        "wer": round(al.wer, 4),
        "sub": al.sub,
        "del": al.dele,
        "ins": al.ins,
        "n_ref": al.n_ref,
        "name_error_rate": round(ner, 4),
        "name_errors": n_err,
        "name_total": n_tot,
    }


def run(gold_dir: str, hyp_dir: str, lexicon: list[str] | None = None, ch: bool | None = None) -> dict:
    gold_p, hyp_p = Path(gold_dir), Path(hyp_dir)
    per_file: dict[str, dict] = {}
    for rf in sorted(list(gold_p.glob("*.json")) + list(gold_p.glob("*.txt"))):
        stem = rf.stem.removesuffix(".ref")
        hf = find_hypothesis(hyp_p, stem)
        if hf is None:
            continue
        ref = load_reference(rf)
        names = list(ref["names"]) + list(lexicon or [])
        per_file[stem] = evaluate_pair(ref["text"], load_hypothesis(hf), ref["dialect"], names, ch)
    by_dialect: dict[str, list[dict]] = defaultdict(list)
    for r in per_file.values():
        by_dialect[r["dialect"]].append(r)
    summary = {}
    for d, rows in sorted(by_dialect.items()):
        n_ref = sum(r["n_ref"] for r in rows)
        errs = sum(r["sub"] + r["del"] + r["ins"] for r in rows)
        n_names = sum(r["name_total"] for r in rows)
        name_errs = sum(r["name_errors"] for r in rows)
        summary[d] = {
            "files": len(rows),
            "n_ref": n_ref,
            "wer": round(errs / n_ref, 4) if n_ref else 0.0,
            "name_error_rate": round(name_errs / n_names, 4) if n_names else 0.0,
            "name_total": n_names,
        }
    return {"per_file": per_file, "summary": summary}


def format_table(summary: dict) -> str:
    lines = [f"{'Dialekt':8} {'Dateien':>7} {'Wörter':>8} {'WER':>7} {'Namen-FR':>9} {'Namen':>6}"]
    for d, s in summary.items():
        lines.append(f"{d:8} {s['files']:>7} {s['n_ref']:>8} {s['wer'] * 100:>6.1f}% {s['name_error_rate'] * 100:>8.1f}% {s['name_total']:>6}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("gold_dir")
    ap.add_argument("hyp_dir")
    ap.add_argument("--lexicon", help="Textdatei mit Eigennamen (eine pro Zeile)")
    ap.add_argument("--ch", action="store_true", help="ß und ss gleichsetzen (alle Dialekte)")
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args(argv)
    lexicon = None
    if args.lexicon:
        lexicon = [ln.strip() for ln in Path(args.lexicon).read_text(encoding="utf-8").splitlines() if ln.strip()]
    result = run(args.gold_dir, args.hyp_dir, lexicon, True if args.ch else None)
    print(format_table(result["summary"]))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
