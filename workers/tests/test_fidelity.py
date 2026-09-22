from __future__ import annotations

from chopstr_worker.pipeline import fidelity


def _words(tokens, gap=0.1):
    out, t = [], 0.0
    for tok in tokens:
        out.append({"text": tok, "start": round(t, 3), "end": round(t + 0.3, 3)})
        t += 0.3 + gap
    return out


def test_negation_removed_is_high_severity():
    words = _words(["Das", "ist", "nicht", "gut"])
    warns = fidelity.check_cut(words, [(0, 1), (3, 3)])
    assert any(w["type"] == "negation_removed" and w["severity"] == "high" for w in warns)


def test_qualifier_removed():
    words = _words(["Das", "gilt", "nur", "bei", "uns"])
    warns = fidelity.check_cut(words, [(0, 1)])
    types = {w["type"] for w in warns}
    assert "qualifier_removed" in types


def test_ends_before_contrast():
    words = _words(["Das", "war", "gut.", "Aber", "nur", "kurz."])
    warns = fidelity.check_cut(words, [(0, 2)])
    assert any(w["type"] == "ends_before_contrast" for w in warns)


def test_joined_statements():
    words = _words(["a", "b"]) + [{"text": "c", "start": 60.0, "end": 60.3}, {"text": "d", "start": 60.4, "end": 60.7}]
    warns = fidelity.check_cut(words, [(0, 1), (2, 3)])
    assert any(w["type"] == "joined_statements" for w in warns)


def test_clean_cut_has_no_warnings():
    words = _words(["Wir", "haben", "äh", "gewonnen."])
    assert fidelity.check_cut(words, [(0, 1), (3, 3)]) == []


def test_hook_claim_check():
    issues = fidelity.hook_claim_check("50.000 Euro garantiert verloren", "Wir haben 40.000 Euro verloren")
    assert any("50.000" in i for i in issues)
    assert any("garantiert" in i for i in issues)
    assert fidelity.hook_claim_check("40.000 Euro verloren", "Wir haben 40.000 Euro verloren") == []
