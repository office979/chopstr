"""Transkriptkorrektur als Vorschlag (A1, Schritte 5 und 6): Heuristik, Prüfer, Speicherung, Schalter.

Alles offline: der Heuristik-Provider schlägt nur Verwechslungen und Lexikon-Treffer vor, die Datenbank ist
eine Fake-Verbindung. Wortzeiten dürfen sich nie ändern."""

from __future__ import annotations

import logging

from chopstr_worker import config, editorial, providers_llm
from chopstr_worker.pipeline import lexicon as lex
from chopstr_worker.pipeline import transcript_fix as tf
from chopstr_worker.providers_llm import LLM
from chopstr_worker.residency import Tenant


def _words(*texts: str, **flags) -> list[dict]:
    out = []
    t = 0.0
    for i, text in enumerate(texts):
        w = {"text": text, "start": round(t, 2), "end": round(t + 0.4, 2), "prob": 0.5, "speaker": "S1", "sentence_idx": 0}
        w.update(flags.get(str(i), {}))
        out.append(w)
        t += 0.5
    return out


LEXICON = lex.Lexicon(terms=["Rimowa-Koffer", "Kleinecke", "PLACEMedia", "Jause"], protected=["Jause"], confusions={"remover-koffer": "Rimowa-Koffer"})


def _heuristic() -> LLM:
    return LLM(Tenant(id="ws"), provider=providers_llm.HEURISTIC_PROVIDER, s=config.settings())


class _Cursor:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class FakeConn:
    def __init__(self, brand=None, corrections=()):
        self.brand, self.corrections = brand, list(corrections)
        self.inserts: list[tuple[str, dict]] = []

    def execute(self, sql, params=()):
        if sql == lex.SQL_BRAND:
            return _Cursor([self.brand] if self.brand else [])
        if sql == lex.SQL_CORRECTIONS:
            return _Cursor(self.corrections)
        if sql.startswith("insert into "):
            table = sql.split()[2]
            cols = [c.strip() for c in sql.split("(", 1)[1].split(")", 1)[0].split(",")]
            vals = [getattr(v, "obj", v) for v in params]
            self.inserts.append((table, dict(zip(cols, vals))))
            return _Cursor()
        raise AssertionError(sql)


# -- Heuristik ---------------------------------------------------------------------------------
def test_heuristic_uses_confusions_and_lexicon_only():
    words = _words("Der", "Remover-Koffer,", "von", "Kleineke", "kostet", "viel", "Jausn")
    edits = tf.heuristic_edits(words, LEXICON)
    assert [(e["word_index"], e["new_text"], e["origin"]) for e in edits] == [(1, "Rimowa-Koffer,", "confusion"), (3, "Kleinecke", "lexicon")]
    assert edits[0]["confidence"] == tf.CONFIDENCE_CONFUSION and edits[1]["confidence"] == tf.CONFIDENCE_FUZZY[1]
    assert edits[1]["kind"] == "name"


def test_heuristic_leaves_correct_protected_and_short_words():
    words = _words("Kleinecke", "Jause", "Jausi", "und", "viel")
    assert tf.heuristic_edits(words, LEXICON) == []  # „Jausi“ läge nahe an „Jause“, aber geschützte Begriffe sind kein Ziel


def test_heuristic_skips_common_words_and_confident_lowercase_words():
    """Review R1-09: „wieder“ → „Wieser“, „meinte“ → „Meindl“, „Leiter“ → „Leitner“ waren Fehlvorschläge."""
    lx = lex.Lexicon(terms=["Wieser", "Meindl", "Leitner", "Kitzbühel"])
    sure = {str(i): {"prob": 0.95} for i in range(6)}
    words = _words("wieder", "meinte", "Leiter", "Wieder", "meindel", "Meindel", **sure)
    edits = tf.heuristic_edits(words, lx)
    # nur der großgeschriebene Fehlhörer, der kein Grundwort ist
    assert [(e["word_index"], e["new_text"]) for e in edits] == [(5, "Meindl")]
    # kleingeschrieben, aber unsicher erkannt: darf ein Name sein
    unsure = _words("meindel", **{"0": {"prob": 0.3}})
    assert [e["new_text"] for e in tf.heuristic_edits(unsure, lx)] == ["Meindl"]


def test_heuristic_uses_distance_two_only_for_long_terms():
    lx = lex.Lexicon(terms=["Leitner", "Kitzbühel"])
    # „Leutnar“ ist 2 von „Leitner“ (7 Zeichen) entfernt: zu kurz für Abstand 2
    assert tf.heuristic_edits(_words("Leutnar"), lx) == []
    # „Kitzbüchl“ ist 2 von „Kitzbühel“ (9 Zeichen) entfernt: lang genug
    edits = tf.heuristic_edits(_words("Kitzbüchl"), lx)
    assert [(e["new_text"], e["confidence"]) for e in edits] == [("Kitzbühel", tf.CONFIDENCE_FUZZY[2])]


def test_confusions_need_a_whole_word_and_a_name_like_token():
    lx = lex.Lexicon(terms=["Rimowa"], confusions={"remover": "Rimowa"})
    sure = {str(i): {"prob": 0.95} for i in range(3)}
    assert [e["new_text"] for e in tf.heuristic_edits(_words("Remover", **sure), lx)] == ["Rimowa"]
    # kleingeschrieben und sicher erkannt: kein Name, keine Ersetzung
    assert tf.heuristic_edits(_words("remover", **sure), lx) == []
    # Teil einer Bindestrich-Verbindung über zwei Tokens: keine Wortgrenze
    assert tf.heuristic_edits(_words("Remover-", "Set", **sure), lx) == []


def test_heuristic_provider_answers_transcript_fix_offline():
    words = _words("Der", "Remover-Koffer", "<script>")
    out = _heuristic().structured(tf.SYSTEM, tf.build_user(words, LEXICON), tf.SCHEMA, tf.TOOL_NAME, tf.PROMPT_VERSION, job_type="transcript_fix")
    assert [e["new_text"] for e in out["edits"]] == ["Rimowa-Koffer"]
    assert "<script>" not in tf.build_user(words, LEXICON)  # Transkript als Daten, Klammern maskiert


def test_suggest_with_heuristic_and_without_prompt_for_real_models(caplog):
    words = _words("Der", "Remover-Koffer")
    assert [e["new_text"] for e in tf.suggest(_heuristic(), words, LEXICON)] == ["Rimowa-Koffer"]

    class RealModel:
        is_heuristic = False

        def structured(self, *a, **k):  # pragma: no cover - darf nicht aufgerufen werden
            raise AssertionError("ohne Prompt transcript_fix_v1 kein Aufruf an ein echtes Modell")

    with caplog.at_level(logging.WARNING, logger="chopstr.pipeline.transcript_fix"):
        assert tf.suggest(RealModel(), words, LEXICON) == []
    assert "transcript_fix_v1" in caplog.text


# -- Prüfer --------------------------------------------------------------------------------------
def test_validator_enforces_hard_rules():
    words = _words("nicht", "Remover-Koffer", "Haus", "vierzig", **{"0": {"negation": True}})
    edits = [
        {"word_index": 0, "new_text": "nichts", "kind": "sonstiges", "reason": "", "confidence": 0.9},  # Verneinung
        {"word_index": 9, "new_text": "x", "kind": "sonstiges", "reason": "", "confidence": 0.9},  # außerhalb
        {"word_index": 1, "new_text": "Rimowa-Koffer", "kind": "name", "reason": "r", "confidence": 0.95},  # Lexikon-Ziel
        {"word_index": 1, "new_text": "Rimowa-Koffer", "kind": "name", "reason": "r", "confidence": 0.95},  # doppelt
        {"word_index": 2, "new_text": "Gartenzaun", "kind": "fachwort", "reason": "", "confidence": 0.9},  # zu weit weg
        {"word_index": 2, "new_text": "zwei Wörter", "kind": "fachwort", "reason": "", "confidence": 0.9},  # kein 1:1
        {"word_index": 3, "new_text": "vierzehn", "kind": "zahl", "reason": "", "confidence": 0.8},  # Zahl nur Hinweis
    ]
    out = tf.validate_edits(words, edits, LEXICON)
    assert [(e["word_index"], e["new_text"]) for e in out] == [(1, "Rimowa-Koffer"), (3, "vierzehn")]
    assert out[1]["confidence"] < 0.5 and out[0]["old_text"] == "Remover-Koffer"
    assert tf.validate_edits(words, edits, LEXICON, candidates={3}) == [out[1]]


# -- Speicherung -----------------------------------------------------------------------------------
def test_persist_writes_open_suggestions_without_auto_fix():
    conn = FakeConn()
    words = _words("Der", "Remover-Koffer", "von", "Kleineke")
    edits = tf.validate_edits(words, tf.heuristic_edits(words, LEXICON), LEXICON)
    res = tf.persist(conn, "ws", "src", "tv-1", 1, words, edits, LEXICON, auto_fix=False)
    assert res == {"suggestions": 2, "applied": 0, "new_version": None}
    rows = [r for t, r in conn.inserts if t == "transcript_suggestions"]
    assert [(r["word_index"], r["status"], r["origin"]) for r in rows] == [(1, "offen", "confusion"), (3, "offen", "lexicon")]
    assert all(r["transcript_version_id"] == "tv-1" and r["workspace_id"] == "ws" for r in rows)
    assert not [t for t, _ in conn.inserts if t == "transcript_versions"]


def test_auto_fix_applies_only_safe_lexicon_hits_and_keeps_times():
    conn = FakeConn()
    words = _words("Der", "Remover-Koffer", "von", "Kleineke")
    edits = tf.validate_edits(words, tf.heuristic_edits(words, LEXICON), LEXICON)
    res = tf.persist(conn, "ws", "src", "tv-1", 3, words, edits, LEXICON, auto_fix=True, stats={"word_count": 4})
    assert res == {"suggestions": 2, "applied": 1, "new_version": 4}
    status = {r["word_index"]: r["status"] for t, r in conn.inserts if t == "transcript_suggestions"}
    assert status == {1: "angenommen", 3: "offen"}  # Kleineke: nur 0,75 sicher, bleibt Vorschlag
    version = next(r for t, r in conn.inserts if t == "transcript_versions")
    assert version["origin"] == "llm_correction" and version["version"] == 4 and version["source_id"] == "src"
    assert [w["text"] for w in version["words"]] == ["Der", "Rimowa-Koffer", "von", "Kleineke"]
    assert [(w["start"], w["end"]) for w in version["words"]] == [(w["start"], w["end"]) for w in words]
    assert version["stats"]["llm_correction"] == {"applied": 1, "from_version": 3} and version["stats"]["word_count"] == 4
    assert words[1]["text"] == "Remover-Koffer"  # Eingabe bleibt unverändert


# -- Schalter und Einstieg -------------------------------------------------------------------------
class _Policy:
    def __init__(self, fix: bool, auto: bool = False):
        self.transcript_llm_fix, self.transcript_auto_fix = fix, auto


SRC = {"id": "src", "workspace_id": "ws", "brand_profile_id": "bp", "brand_vocab": ["PLACEMedia"], "protected_terms": []}


def test_run_after_transcription_is_off_by_default():
    editorial.clear_cache()
    pol = editorial.load(2)
    assert pol.transcript_llm_fix is False and pol.transcript_auto_fix is False
    conn = FakeConn()
    assert tf.run_after_transcription(conn, SRC, "tv", 1, _words("Remover-Koffer"), _heuristic(), policy=pol) is None
    assert conn.inserts == []


def test_run_after_transcription_learns_from_the_brand_profile():
    conn = FakeConn(brand=(["Rimowa-Koffer"], []), corrections=[("Remover-Koffer", "Rimowa-Koffer", True)])
    res = tf.run_after_transcription(conn, SRC, "tv", 1, _words("Der", "Remover-Koffer"), _heuristic(), policy=_Policy(True, True))
    assert res == {"suggestions": 1, "applied": 1, "new_version": 2}
    assert [r["new_text"] for t, r in conn.inserts if t == "transcript_suggestions"] == ["Rimowa-Koffer"]


def test_run_after_transcription_never_raises():
    class Broken(FakeConn):
        def execute(self, sql, params=()):
            raise RuntimeError("Tabelle transcript_suggestions fehlt")

    res = tf.run_after_transcription(Broken(), SRC, "tv", 1, _words("Remover-Koffer"), _heuristic(), policy=_Policy(True))
    assert res["error"].startswith("RuntimeError") and res["suggestions"] == 0
