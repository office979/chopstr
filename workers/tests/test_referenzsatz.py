"""Der Referenzsatz haelt fest, womit gemessen wurde.

Ohne ihn sagt eine geaenderte Zahl nichts: die Pipeline kann besser geworden sein, oder es lagen
drei Dateien mehr im Ordner."""

from __future__ import annotations

import json

from eval import referenzsatz as rs


def _ordner(tmp_path):
    pos = tmp_path / "positiv"
    neg = tmp_path / "negativ"
    pos.mkdir()
    neg.mkdir()
    (pos / "a.mp4").write_bytes(b"eins")
    (neg / "b.mp4").write_bytes(b"zwei")
    (neg / "notiz.txt").write_text("kein Video")
    return pos, neg


def test_erfasst_nur_videos_und_haelt_pruefsummen_fest(tmp_path):
    pos, neg = _ordner(tmp_path)
    out = tmp_path / "satz.json"
    rs.main(["erfassen", "--positiv", str(pos), "--negativ", str(neg), "--out", str(out)])
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["anzahl"] == {"positiv": 1, "negativ": 1}
    assert [e["datei"] for e in d["dateien"]] == ["a.mp4", "b.mp4"]
    assert all(len(e["sha256"]) == 64 for e in d["dateien"])


def test_ein_kleiner_satz_wird_als_nicht_belastbar_gekennzeichnet(tmp_path):
    # Vier gute und zwoelf schlechte Beispiele tragen keine Aussage darueber, was einen guten Clip
    # ausmacht. Das muss im Manifest stehen und nicht im Kopf dessen, der es gelesen hat.
    pos, neg = _ordner(tmp_path)
    out = tmp_path / "satz.json"
    rs.main(["erfassen", "--positiv", str(pos), "--negativ", str(neg), "--out", str(out)])
    assert json.loads(out.read_text(encoding="utf-8"))["belastbar"] is False


def test_merkt_wenn_eine_datei_fehlt_oder_sich_geaendert_hat(tmp_path):
    pos, neg = _ordner(tmp_path)
    out = tmp_path / "satz.json"
    rs.main(["erfassen", "--positiv", str(pos), "--negativ", str(neg), "--out", str(out)])
    assert rs.pruefen(out, {"positiv": pos, "negativ": neg}) == ([], [])

    (pos / "a.mp4").write_bytes(b"anders")
    (neg / "b.mp4").unlink()
    fehlt, anders = rs.pruefen(out, {"positiv": pos, "negativ": neg})
    assert fehlt == ["negativ/b.mp4"]
    assert anders == ["positiv/a.mp4"]


def test_uebernimmt_nur_zahlen_aus_der_messung_keinen_text(tmp_path):
    # Die Einzelmessungen enthalten Ausschnitte aus Kundenaufnahmen. Die gehoeren nicht ins Repo.
    pos, neg = _ordner(tmp_path)
    messung = tmp_path / "messung.json"
    messung.write_text(
        json.dumps(
            {
                "positiv": {
                    "summe": {"clips": 1, "dauer_median_s": 43.5},
                    "clips": [{"datei": "a.mp4", "erste_woerter": "Ich bin für eine komplette"}],
                },
                "negativ": {"summe": {"clips": 1}, "clips": []},
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "satz.json"
    rs.main(
        ["erfassen", "--positiv", str(pos), "--negativ", str(neg), "--messung", str(messung), "--out", str(out)]
    )
    text = out.read_text(encoding="utf-8")
    assert "dauer_median_s" in text
    assert "komplette" not in text
