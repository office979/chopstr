"""Kosten und Laufzeit je Quellstunde aus einem job_costs-Export (ohne Datenbank)."""

from __future__ import annotations

import json

import pytest

from eval import cost_eval as ce


def row(sid, job, eur, cpu=0.0, gpu=0.0, minutes=0.0):
    return {"source_id": sid, "job_type": job, "estimated_eur": eur, "cpu_seconds": cpu, "gpu_seconds": gpu, "source_minutes": minutes}


EXPORT = {
    "job_costs": [row("s1", "ingest", 0.0, cpu=10, minutes=30), row("s1", "asr", "0.50", gpu=600), row("s1", "llm_propose", 0.25),
                  row("s2", "asr", 1.0, cpu=100), row(None, "render", 0.3)],
    "sources": [{"id": "s1", "duration_s": 1800.0}],
    "laufzeiten": [{"source_id": "s1", "wartezeit_s": 450.0, "cache": "kalt", "hardware": "M2, CPU", "gerenderte_clips": 0}],
}  # fmt: skip


def test_evaluate_per_source_and_total():
    res = ce.evaluate(EXPORT)
    s1, s2 = res["je_quelle"]["s1"], res["je_quelle"]["s2"]
    assert s1["quell_stunden"] == 0.5 and s1["dauer_herkunft"] == "sources.duration_s"
    assert s1["eur_je_quellstunde"] == pytest.approx(1.5) and s1["rechenzeit_s_je_quellstunde"] == pytest.approx(1220.0)
    assert s1["wartezeit_s_je_quellstunde"] == pytest.approx(900.0) and s1["cache"] == "kalt"
    assert s1["je_job_typ"]["asr"] == {"eur": 0.5, "rechenzeit_s": 600.0}
    assert s2["eur_je_quellstunde"] is None and "Quelldauer unbekannt" in s2["ursache"]
    g = res["gesamt"]
    assert g["quellen"] == 2 and g["quellen_mit_dauer"] == 1 and g["zeilen_ohne_quelle"] == 1
    m = res["metriken"]
    assert m["eur_je_quellstunde"]["wert"] == pytest.approx(1.5) and m["wartezeit_s_je_quellstunde"]["wert"] == pytest.approx(900.0)
    assert "Platzhalter" in ce.format_report(res)


def test_source_hours_from_ingest_minutes():
    assert ce.source_hours("x", {}, [row("x", "ingest", 0, minutes=90)]) == (1.5, "job_costs.source_minutes (ingest)")
    assert ce.source_hours("x", {}, [row("x", "asr", 0, minutes=90)]) == (None, None)


def test_empty_and_list_exports():
    empty = ce.evaluate([])
    assert empty["metriken"]["eur_je_quellstunde"] == {"wert": None, "stichprobe": 0, "ursache": "keine job_costs-Zeilen mit Quelle"}
    no_wait = ce.evaluate([row("s", "ingest", 1.0, minutes=60)])
    assert no_wait["metriken"]["eur_je_quellstunde"]["wert"] == 1.0
    assert no_wait["metriken"]["wartezeit_s_je_quellstunde"]["ursache"] == "keine Wartezeiten im Export (laufzeiten fehlt)"
    with pytest.raises(SystemExit, match="Export"):
        ce.normalize_export({"x": 1})


def test_load_from_db_with_fake_connection():
    class Cursor:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    class Conn:
        def __init__(self):
            self.queries = []

        def execute(self, sql, params):
            self.queries.append((sql, params))
            if "job_costs" in sql:
                return Cursor([("s1", "asr", "selfhost-eu", "m", 0.0, 0.0, 60.0, 0.2)])
            return Cursor([("s1", 3600.0)])

    conn = Conn()
    export = ce.load_from_db(conn, ["s1"])
    assert export["job_costs"][0]["estimated_eur"] == 0.2 and export["sources"] == [{"id": "s1", "duration_s": 3600.0}]
    assert conn.queries[0][1] == (["s1"],)
    assert ce.evaluate(export)["gesamt"]["eur_je_quellstunde"] == pytest.approx(0.2)


def test_cli(tmp_path, capsys):
    path = tmp_path / "k.json"
    path.write_text(json.dumps(EXPORT), encoding="utf-8")
    out = tmp_path / "o.json"
    ce.main(["--export", str(path), "--json", str(out)])
    assert "1,50 EUR je Quellstunde" in capsys.readouterr().out
    assert json.loads(out.read_text(encoding="utf-8"))["metriken"]["rechenzeit_s_je_quellstunde"]["wert"] == pytest.approx(1220.0)
    with pytest.raises(SystemExit, match="mindestens eine --quelle"):
        ce.main(["--database-url", "postgresql://nicht-benutzt"])
