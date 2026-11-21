"""Lernendes Kontolexikon (A1): Wörterbuch, geschützte Begriffe, gelernte Verwechslungen. Ohne Datenbank."""

from __future__ import annotations

from chopstr_worker.pipeline import lexicon as lex


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class FakeConn:
    """Kennt genau die zwei Abfragen von ``build_lexicon``."""

    def __init__(self, brand=None, corrections=()):
        self.brand = brand
        self.corrections = list(corrections)
        self.queries: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.queries.append((sql, tuple(params)))
        if sql == lex.SQL_BRAND:
            return _Cursor([self.brand] if self.brand else [])
        if sql == lex.SQL_CORRECTIONS:
            return _Cursor(self.corrections)
        raise AssertionError(sql)


def test_confusion_needs_two_corrections_or_vocab_flag():
    rows = [("Remover-Koffer", "Rimowa-Koffer", False), ("Remover-Koffer", "Rimowa-Koffer", False), ("Kleineke", "Kleinecke", True), ("einmal", "Einmal", False), ("Testa", "Tesla", False)]
    conf = lex.build_confusions(rows)
    assert conf == {"remover-koffer": "Rimowa-Koffer", "kleineke": "Kleinecke"}


def test_confusion_skips_contradictions_phrases_and_protected_terms():
    rows = [
        ("Marie", "Mary", False), ("Marie", "Mary", False), ("Marie", "Maria", False), ("Marie", "Maria", False),
        ("zwei Wörter", "Zweiwort", True),
        ("Jause", "Brotzeit", True),
    ]  # fmt: skip
    assert lex.build_confusions(rows, protected=["Jause"]) == {}


def test_build_lexicon_merges_vocab_protected_and_learned_terms():
    conn = FakeConn(brand=(["PLACEMedia", "Rimowa"], ["Jause"]), corrections=[("Kleineke", "Kleinecke.", True), ("Remover", "Rimowa", False)])
    lx = lex.build_lexicon(conn, "bp-1", extra_vocab=["rimowa"])
    # einmalig je Schreibweise, Reihenfolge stabil, gelernte Begriffe ohne Satzzeichen am Ende
    assert lx.terms == ["rimowa", "PLACEMedia", "Kleinecke", "Jause"]
    assert lx.protected == ["Jause"]
    assert lx.confusions == {"kleineke": "Kleinecke"}
    assert lx.has_term("RIMOWA") and lx.is_protected("jause,") and not lx.is_protected("Rimowa")
    assert conn.queries[1][1] == ("bp-1",)


def test_build_lexicon_without_brand_profile_uses_only_given_terms():
    conn = FakeConn()
    lx = lex.build_lexicon(conn, None, extra_vocab=["Rimowa"], extra_protected=["Marille"])
    assert lx.terms == ["Rimowa", "Marille"] and lx.confusions == {} and conn.queries == []


def test_apply_confusions_keeps_times_and_punctuation():
    words = [
        {"text": "Der", "start": 0.0, "end": 0.2, "prob": 0.9},
        {"text": "Remover-Koffer,", "start": 0.2, "end": 0.9, "prob": 0.4, "speaker": "S1"},
        {"text": "REMOVER-KOFFER", "start": 1.0, "end": 1.5},
        {"text": "Koffer", "start": 1.5, "end": 1.9},
    ]
    out = lex.apply_confusions(words, {"remover-koffer": "Rimowa-Koffer"})
    assert [w["text"] for w in out] == ["Der", "Rimowa-Koffer,", "Rimowa-Koffer", "Koffer"]
    assert out[1] == {"text": "Rimowa-Koffer,", "start": 0.2, "end": 0.9, "prob": 0.4, "speaker": "S1"}
    assert lex.apply_confusions(words, {}) is words
