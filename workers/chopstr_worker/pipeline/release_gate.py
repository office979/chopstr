"""Freigaberelevante Behauptungen: wann ein Kandidat nicht automatisch angenommen wird.

Das Flag ``claim`` aus ``story_graph.claims_in`` bleibt, wie es ist (Grounding, ``risk_flags``,
Snapshot v1). Als Kriterium für die automatische Freigabe ist es zu breit: jede Ziffer, jedes
„weil“ und „dadurch“, jedes „alle“ und „jede“ zählt dort, und weil ohne Wortgrenzen gesucht wird,
trifft „Allerdings“ auf „alle“, „jederzeit“ auf „jede“ und „Positionierung“ auf „nie“. An den
Fällen des Testsatzes ``editorial_v1`` und an der Demo trug fast jeder Kandidat das Flag; die
Freigabepflicht hätte damit praktisch jeden Clip zurückgehalten (``docs/ENTSCHEIDUNGEN.md`` P27).

Hier zählt nur, was ein Mensch vor der Veröffentlichung prüfen muss (``docs/ENTSCHEIDUNGEN.md``
P27), und immer als ganzes Wort:

* eine Zahl mit Einheit, Prozent, Währung oder Vervielfachung („40.000 Euro“, „12 Franken“,
  „40 Prozentpunkte“, „fünfundzwanzig Stunden“, „500 Mitarbeiter“, „zehnmal“). Zahlwörter werden
  über einen Ausdruck erkannt, auch zusammengesetzte („fünfzehn“, „vierzigtausend“), das bloße
  Artikelwort „ein“ nicht;
* Vergleich und Vervielfachung ohne Zahl: „doppelt“, „verdoppelt“, „verdreifacht“, „halb so“,
  „Hälfte“, „Drittel“, „Viertel“, „Fünftel“, dazu „Nummer eins“;
* Beleg- und Absolutwörter: „garantiert“, „bewiesen“, „belegt“, „erwiesen“, „wissenschaftlich“;
* Allaussagen: „immer“, „nie“, „niemals“, „jeder“, „alle“ (alle Formen) zusammen mit einer
  Verallgemeinerung im selben Satz. Stark verallgemeinernd sind „man“, „gilt“, „überall“,
  „grundsätzlich“, „bei allen“, „für alle“ und ähnliche; schwächer sind Gruppenobjekte („Kunden“,
  „Firmen“, „Unternehmen“, „Menschen“) und Wirkungsverben („funktioniert“, „klappt“, „wirkt“,
  „hilft“), die nur zählen, wenn der Satz nicht ausdrücklich vom eigenen Fall spricht („bei uns“).

„weil“ und „dadurch“ zählen nicht: eine Begründung ist keine Tatsachenbehauptung, die man am
Material prüfen müsste. Eine Jahreszahl allein („2024“) zählt ebenfalls nicht.
"""

from __future__ import annotations

import re
from typing import Any

# Zeilenpräfix im Kandidatentext (``rubric.text``): „[3] (SPEAKER_00) “. Die Ziffern darin sind
# keine Aussage.
_LINE_PREFIX = re.compile(r"^\s*\[\d+\]\s*(?:\([^)]*\)\s*)?", re.MULTILINE)
# Satzende nach . ! ?, aber nicht nach Abkürzungen, die in Zahlenangaben vorkommen („3 Mio. Euro“, „z. B.“).
_SENTENCE_SPLIT = re.compile(
    r"(?<!\bMio\.)(?<!\bMrd\.)(?<!\bca\.)(?<!\bbzw\.)(?<!\bz\.)(?<!\bB\.)(?<=[.!?])\s+|\n+"
)

# Zahlwörter als Ausdruck statt Liste: ein Wort, das nur aus Zahlbausteinen besteht („fünfzehn“,
# „fünfundzwanzig“, „vierzigtausend“, „einhundert“). „ein“ allein ist meist Artikel und zählt nicht.
_NUMBER_PART = (
    r"(?:eins|ein|zwei|drei|vier|fünf|sechs|sech|sieben|sieb|acht|neun|zehn|elf|zwölf|"
    r"zwanzig|dreißig|vierzig|fünfzig|sechzig|siebzig|achtzig|neunzig|hundert|tausend|und)"
)
_NUMBER_WORD = rf"(?!(?:ein|und)(?!\w))(?!und){_NUMBER_PART}+"
_NUMBER = rf"(?:\d+(?:[.,]\d+)*|{_NUMBER_WORD})"
_UNITS = (
    r"(?:prozent|prozentpunkte|prozentpunkten|euro|franken|chf|dollar|"
    r"million|millionen|mio\.|milliarde|milliarden|mrd\.|mal|"
    r"jahr|jahre|jahren|jahres|monat|monate|monaten|monats|woche|wochen|tag|tage|tagen|stunde|stunden|"
    r"kunden|kundinnen|mitarbeiter|mitarbeitern|mitarbeitende|mitarbeitenden|nutzer|nutzern)"
)

_QUANTIFIED = (
    # Zahl, dann Einheit als eigenes Wort: „40.000 Euro“, „fünfzehn Prozent“, „5 Mio.“
    re.compile(rf"(?<![\w.,]){_NUMBER}\s+{_UNITS}(?!\w)", re.IGNORECASE),
    # Zeichen direkt an der Zahl: „40 %“, „40%“, „500 €“, „20 $“
    re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)*\s*[%€$]", re.IGNORECASE),
    # Währung vor der Zahl: „€ 500“, „$500“, „CHF 50“
    re.compile(r"(?:[€$]|(?<!\w)chf)\s*\d", re.IGNORECASE),
    # Vervielfachung als ein Wort: „zehnmal“, „3-mal“, „3mal“
    re.compile(rf"(?<![\w.,]){_NUMBER}-?mal(?!\w)", re.IGNORECASE),
    # Vergleich und Vervielfachung ohne Zahl, Bruchwörter, Rangplatz
    re.compile(
        r"(?<!\w)(?:doppelt|doppelte|doppelten|doppelter|doppeltes|"
        r"ver(?:doppel|dreifach|vierfach|zehnfach|vielfach)\w*|"
        r"hälfte|drittel|dritteln|viertel|vierteln|fünftel|fünfteln|"
        r"halb\s+so|nummer\s+(?:eins|1))(?!\w)",
        re.IGNORECASE,
    ),
)
_ABSOLUTE = re.compile(r"(?<!\w)(?:garantiert|bewiesen|belegt|erwiesen|wissenschaftlich\w*)(?!\w)", re.IGNORECASE)
_UNIVERSAL = re.compile(
    r"(?<!\w)(?:immer|nie|niemals|jeder|jede|jedes|jeden|jedem|alle|allen|aller|alles)(?!\w)", re.IGNORECASE
)
# Verallgemeinerung, die immer zählt.
_GENERALIZATION = re.compile(
    r"(?<!\w)(?:man|gilt|gelten|galt|überall|grundsätzlich|generell|pauschal|ausnahmslos|egal|"
    r"bei\s+allen|für\s+alle|für\s+jede[nrs]?)(?!\w)",
    re.IGNORECASE,
)
# Gruppenobjekte und Wirkungsverben: verallgemeinern nur, wenn der Satz nicht vom eigenen Fall spricht.
_GENERALIZATION_WEAK = re.compile(
    r"(?<!\w)(?:kunden|kundinnen|firmen|unternehmen|menschen|betriebe|leute|"
    r"funktioniert|funktionieren|klappt|klappen|wirkt|wirken|hilft|helfen)(?!\w)",
    re.IGNORECASE,
)
_OWN_CASE = re.compile(r"(?<!\w)(?:bei\s+uns|bei\s+mir|in\s+unsere[mrn]?|unsere[mrns]?|unser)(?!\w)", re.IGNORECASE)


def _sentences(text: str) -> list[str]:
    plain = _LINE_PREFIX.sub("", text or "")
    return [s.strip() for s in _SENTENCE_SPLIT.split(plain) if s and s.strip()]


def _is_release_relevant(sentence: str) -> bool:
    if any(p.search(sentence) for p in _QUANTIFIED):
        return True
    if _ABSOLUTE.search(sentence):
        return True
    if not _UNIVERSAL.search(sentence):
        return False
    if _GENERALIZATION.search(sentence):
        return True
    return bool(_GENERALIZATION_WEAK.search(sentence) and not _OWN_CASE.search(sentence))


def release_relevant_claims(text: str) -> list[str]:
    """Die Sätze im Text, die eine freigaberelevante Behauptung enthalten, in Textreihenfolge.

    Leere Liste heißt: nichts, was die automatische Freigabe aufhalten muss."""
    out: list[str] = []
    for sentence in _sentences(text):
        if _is_release_relevant(sentence) and sentence not in out:
            out.append(sentence)
    return out


# -- Drei Ergebnisklassen (Lane P3, Master-Prompt Regel 14, Review 5) -------------------------------------------
# ``rubric.review_state`` ist der Vertrag für Web und Export: ``passed`` (keine Befunde), ``uncertain`` (Hinweise
# aus Regeln oder Modellen ohne Bestätigung, Flags humor, sensitive_topic, claim) und ``blocked`` (bestätigter
# Fehler nach gescheiterter oder unmöglicher Reparatur). Regelbasierte Hinweise (``rule``), modellbasierte
# Bewertung (``model``) und bestätigte Fehler (``confirmed``) bleiben getrennt (Review 3); ein Regelhinweis allein
# wird nie ``blocked``. Ein blockierter Kandidat wird nie automatisch angenommen (``analyze.auto_accept_blockers``).
REVIEW_SWITCH = "review.review_state"
REVIEW_STATES = ("passed", "uncertain", "blocked")
REVIEW_ORIGINS = ("rule", "model", "confirmed")
REPAIR_KINDS = ("title_card", "gate_heal", "start_heal", "context_extension")
REPAIR_RESULTS = ("passed", "failed", "not_attempted")
# Flags aus ``risk_flags``, die eine menschliche Prüfung verlangen (Regel 11, P27).
REVIEW_FLAGS = ("humor", "sensitive_topic", "debate_contradiction")
_DASHES = re.compile(r"\s*[–—]\s*")


def review_settings(policy: Any) -> bool:
    """Ergebnisklassen an? Nur Fassung 2 mit Schalter ``implementation.review.review_state`` und Regel
    ``review.review_state`` (beide true); ein Wert, der kein Wahrheitswert ist, scheitert laut."""
    from .. import editorial

    if policy is None or getattr(policy, "version", 1) < 2:
        return False
    if editorial._switch_value(policy.roh.get("implementation") or {}, REVIEW_SWITCH) is not True:
        return False
    raw = (policy.roh.get("review") or {}).get("review_state")
    if raw is None:
        return False
    if not isinstance(raw, bool):
        raise editorial.PolicyError(f"clip_policy_v{policy.version}: review.review_state ist true oder false.")
    return raw


def _sentence(text: str) -> str:
    """Ein deutscher Satz ohne Gedankenstriche, mit Punkt am Ende."""
    out = _DASHES.sub(", ", " ".join(str(text or "").split())).strip()
    if not out:
        return ""
    return out if out.endswith((".", "!", "?")) else out + "."


def _word_span(words: list[dict] | None, ids: Any) -> dict[str, float] | None:
    ids = [int(i) for i in (ids or []) if isinstance(i, int) and not isinstance(i, bool)]
    if not words or not ids or not all(0 <= i < len(words) for i in ids):
        return None
    return {"start_s": round(float(words[min(ids)]["start"]), 3), "end_s": round(float(words[max(ids)]["end"]), 3)}


def _sentence_span(sents: list[Any] | None, refs: Any) -> dict[str, float] | None:
    refs = [int(r) for r in (refs or []) if isinstance(r, int) and not isinstance(r, bool)]
    if not sents or not refs or not all(0 <= r < len(sents) for r in refs):
        return None
    return {"start_s": round(float(sents[min(refs)].start), 3), "end_s": round(float(sents[max(refs)].end), 3)}


def _repair_state(rubric: dict[str, Any], confirmed: bool) -> dict[str, Any]:
    """Was die Pipeline schon repariert hat (nur gelesen): Titelkarte, Gate-Heilung, Anfang, Kontextzugabe."""
    card = rubric.get("title_card_attempt")
    gate_heal = rubric.get("gate_heal") or {}
    start = rubric.get("start_heal") or {}
    kind: str | None = None
    failed = confirmed
    if isinstance(card, dict):
        kind = "title_card"
        failed = failed or not bool((card.get("recheck") or {}).get("passed"))
    elif any(isinstance(v, dict) and (v.get("healed") or v.get("saetze") or v.get("discarded")) for v in gate_heal.values()):
        kind = "gate_heal"
    elif isinstance(start, dict) and start.get("defects"):
        kind = "start_heal"
        failed = failed or not start.get("healed")
    elif rubric.get("kontext_zugabe"):
        kind = "context_extension"
    if kind is None:
        return {"attempted": False, "kind": None, "result": "not_attempted"}
    return {"attempted": True, "kind": kind, "result": "failed" if failed else "passed"}


def derive_review_state(
    rubric: dict[str, Any],
    risk_flags: Any = (),
    gates: dict[str, Any] | None = None,
    story_graph_flags: Any = (),
    words: list[dict] | None = None,
    sents: list[Any] | None = None,
) -> dict[str, Any]:
    """Ergebnisklasse eines Kandidaten aus dem, was die Pipeline schon geprüft hat (deterministisch).

    Rückgabe ``{"state", "reasons": [{"code", "text", "source_span", "origin"}], "repair"}``. ``blocked`` heißt:
    mindestens ein bestätigter Fehler (Kritiker bestätigt Schwere ``fidelity``, Gegenleser bestätigt, Gate
    verworfen unter Regel ``gates.discard_hard``) ist nach der Reparatur geblieben. ``uncertain`` heißt: es gibt
    Gründe, aber keinen bestätigten Fehler. ``passed``: keine Gründe. Ein nicht gefundener Befund ist kein
    Beleg, dass es keinen gibt (Regel 12); ``passed`` heißt nur, dass diese Prüfungen nichts fanden."""
    reasons: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(code: str, text: str, span: dict | None, origin: str) -> None:
        key = (code, str(span))
        if key in seen or not _sentence(text):
            return
        seen.add(key)
        reasons.append({"code": code, "text": _sentence(text), "source_span": span, "origin": origin})

    flags = [str(f) for f in (risk_flags or [])]
    heuristic = "heuristic_only" in flags
    decision = rubric.get("quality_gate_decision") or {}
    rejected_gate = str(decision.get("reason") or "")[5:] if decision.get("decision") == "rejected" else ""
    for key, res in (rubric.get("quality_gate_results") or {}).items():
        if not isinstance(res, dict):
            continue
        span = _word_span(words, res.get("evidence_word_ids"))
        if key == rejected_gate:
            add(f"gate_rejected:{key}", f"Bestätigt durch Gate {key} (Regel discard_hard): {res.get('detail')}", span, "confirmed")
        elif res.get("passed") is False:
            add(f"gate:{key}", f"Regelhinweis {key}: {res.get('detail')}", span, "rule")
        elif res.get("flagged"):
            add(f"gate_flag:{key}", f"Regelhinweis {key}: {res.get('detail')}", span, "rule")
    for key, g in (gates or {}).items():
        if isinstance(g, dict) and g.get("passed") is False:
            add(f"tor:{key}", f"Regelhinweis {key}: {g.get('detail') or 'Tor nicht bestanden'}", None, "rule")
    critic_run = rubric.get("critic") or {}
    critic_heur = bool(critic_run.get("heuristic"))
    for f in rubric.get("critic_findings") or []:
        if not isinstance(f, dict) or f.get("severity") == "minor":
            continue
        span = _sentence_span(sents, f.get("sentence_refs"))
        if critic_run.get("confirmed") is True and f.get("severity") == "fidelity" and not critic_heur:
            add(f"critic_confirmed:{f.get('kind')}", f"Vom Kritiker bestätigt: {f.get('explanation')}", span, "confirmed")
        else:
            add(f"critic:{f.get('kind')}", f"Hinweis des Kritikers: {f.get('explanation')}", span, "rule" if critic_heur else "model")
    cr = rubric.get("counter_reader") or {}
    for f in ((cr.get("deterministic") or {}).get("findings")) or []:
        if isinstance(f, dict) and f.get("verdict") == "differs":
            add(f"counter_reader:{f.get('dimension')}", f"Gegenleser nach Regeln: {f.get('detail')}", f.get("source_span"), "rule")
    model = cr.get("model") or {}
    for f in model.get("findings") or []:
        origin = "confirmed" if cr.get("confirmed") and f.get("severity") == "high" else "model"
        add(f"counter_reader_model:{f.get('dimension')}", f"Gegenleser mit Modell: {f.get('explanation') or f.get('dimension')}", None, origin)
    for f in cr.get("additional_findings") or []:
        add(f"counter_reader_second:{f.get('dimension')}", f"Nur das zweite Modell meldet: {f.get('explanation') or f.get('dimension')}", None, "model")
    for h in ((rubric.get("context_hits") or {}).get("hits")) or []:
        if h.get("reaction") in ("later_correction", "review", "flag"):
            what = {"self_correction": "Der Sprecher korrigiert oder relativiert die Aussage später",
                    "contradiction_by_other": "Ein anderer Sprecher widerspricht der Aussage"}.get(h.get("context_class"), "Kontextbezug")  # fmt: skip
            add(f"context:{h.get('context_class')}", f"{what}: „{h.get('text')}“", {"start_s": h.get("start_s"), "end_s": h.get("end_s")}, "rule")
    for fl in story_graph_flags or []:
        if not isinstance(fl, dict) or fl.get("confirmed") is False:
            continue
        span = _sentence_span(sents, [fl.get("sentence_idx")])
        if fl.get("confirmed") is True:
            add("story_graph", f"Das Modell bestätigt eine spätere Relativierung: „{fl.get('text')}“", span, "rule" if heuristic else "model")
        else:
            add("story_graph_unconfirmed", f"Mögliche spätere Relativierung, ungeprüft: „{fl.get('text')}“", span, "rule")
    for flag in REVIEW_FLAGS:
        if flag in flags:
            text = {"humor": "Humor erkannt, die Wirkung beurteilt ein Mensch",
                    "sensitive_topic": "Sensibles Thema (Gesundheit, Recht oder Finanzen), ein Mensch prüft",
                    "debate_contradiction": "In der Debatte widerspricht ein anderer Sprecher, ein Mensch prüft die Einordnung"}[flag]  # fmt: skip
            add(f"flag:{flag}", text, None, "rule" if heuristic or flag == "debate_contradiction" else "model")
    claims = release_relevant_claims(str(rubric.get("text") or ""))
    if claims:
        add("flag:claim", f"Freigaberelevante Behauptung: „{claims[0]}“", None, "rule")
    card = rubric.get("repair_applied")
    if isinstance(card, dict) and card.get("kind") == "title_card":
        add("repair:title_card", "Die Bedingung steht nur auf einer Titelkarte, der Ton allein klingt uneingeschränkt; ein Mensch prüft das Ergebnis",
            card.get("source_span"), "rule")  # fmt: skip
    confirmed = any(r["origin"] == "confirmed" for r in reasons)
    repair = _repair_state(rubric, confirmed)
    state = "blocked" if confirmed else ("uncertain" if reasons else "passed")
    return {"state": state, "reasons": reasons, "repair": repair}


def _adjacent(sents: list[Any], idx: int, speaker: Any) -> dict[str, Any] | None:
    if not 0 <= idx < len(sents) or sents[idx].speaker != speaker:
        return None
    s = sents[idx]
    return {"text": s.text, "start_s": round(s.start, 3), "end_s": round(s.end, 3), "sentence_idx": s.idx}


def title_card_attempt(words: list[dict], sents: list[Any], first: int, last: int, rubric: dict[str, Any], policy: Any) -> dict[str, Any] | None:
    """Regel 2, zweite Wahl: eine Bedingung oder Einschränkung steht im Satz direkt vor dem Clip (gleicher
    Sprecher, Bezug zum Clip), und die Heilung nach vorn hat ihn nicht in den Clip geholt. Dann wird der Satz
    als Titelkarte vorgeschlagen, nur wörtlich aus der Quelle (Zitatprüfung) und mit höchstens
    ``context.title_card.max_words`` Wörtern. Danach werden Gates und Gegenleser auf Clip plus Karte erneut
    geprüft (Review 3). Zurück ``None`` (kein Anlass) oder der Versuch mit ``recheck``."""
    from . import critic, editorial_gates, fidelity

    cfg = fidelity.title_card_settings(policy)
    if cfg is None or first <= 0:
        return None
    prev = _adjacent(sents, first - 1, sents[first].speaker)
    if prev is None:
        return None
    found = fidelity.context_findings(sents[first].text, sents[last].text, prev, None).get("condition")
    if found is None:
        return None
    text = prev["text"].strip()
    span = {"start_s": prev["start_s"], "end_s": prev["end_s"]}
    attempt: dict[str, Any] = {"kind": "title_card", "text": text, "source_span": span, "sentence_idx": prev["sentence_idx"],
                               "trigger": found["detail"], "front_heal": rubric.get("start_heal") or (rubric.get("gate_heal") or {}).get("front")}  # fmt: skip
    source = critic._norm(" ".join(s.text for s in sents))
    if not critic._contains(source, critic._norm(text)):
        attempt["recheck"] = {"passed": False, "detail": "Kartentext steht nicht wörtlich in der Quelle"}
        return attempt
    if len(text.split()) > cfg["max_words"]:
        attempt["recheck"] = {"passed": False, "detail": f"Quellsatz hat {len(text.split())} Wörter, erlaubt sind {cfg['max_words']}"}
        return attempt
    before = editorial_gates.run_gates(words, sents, first, last, policy)
    after = editorial_gates.run_gates(words, sents, first - 1, last, policy)
    new = [k for k in after["failed"] if k not in before["failed"]]
    clip_with_card = [{"text": s.text, "start_s": s.start, "end_s": s.end} for s in sents[first - 1 : last + 1]]
    cr_after = fidelity.counter_read(clip_with_card, _adjacent(sents, first - 2, sents[first].speaker), None)
    still = [f["dimension"] for f in cr_after["findings"] if f["verdict"] == "differs" and f["source"] == "context_before" and f["dimension"] == "condition"]
    attempt["recheck"] = {
        "passed": not new and not still,
        "gates_failed_before": list(before["failed"]),
        "gates_failed_after": list(after["failed"]),
        "new_gate_failures": new,
        "counter_reader_after": cr_after["differs"],
        "detail": "Gates und Gegenleser auf Clip plus Karte ohne neuen Befund" if not new and not still else "Prüfung auf Clip plus Karte meldet neue Befunde",
    }  # fmt: skip
    return attempt


def annotate_review(candidate: Any, words: list[dict], sents: list[Any], policy: Any) -> None:
    """Lane P3, nur Fassung 2, additiv in der Rubrik eines ``CandidateResult``: ``context_hits`` (Claim-Index),
    ``counter_reader`` (regelbasiert, ergänzt den Modellteil aus ``critic.critique``), ``title_card_attempt`` und
    ``repair_applied`` (Titelkarte, nur nach bestandener Wiederholungsprüfung) und ``review_state``. Ein
    Widerspruch durch einen anderen Sprecher setzt das Flag ``debate_contradiction`` in ``risk_flags``; die
    Story-Graph-Treffer bekommen ihre Klasse (``context_class``). Wiederholt aufrufbar."""
    from . import critic, fidelity, story_graph

    if policy is None or getattr(policy, "version", 1) < 2:
        return
    rubric = candidate.rubric
    first, last = int(candidate.first_sent), int(candidate.last_sent)
    if not (0 <= first <= last < len(sents)):
        return
    report = story_graph.context_report(sents, first, last, policy)
    if report is not None:
        rubric["context_hits"] = report
        classes = {h["sentence_idx"]: h["context_class"] for h in report["hits"]}
        for fl in candidate.story_graph_flags or []:
            if isinstance(fl, dict) and fl.get("sentence_idx") in classes:
                fl["context_class"] = classes[fl["sentence_idx"]]
        if report["flags"] and "debate_contradiction" not in candidate.risk_flags:
            candidate.risk_flags = [*candidate.risk_flags, "debate_contradiction"]
    if fidelity.counter_reader_settings(policy) is not None:
        span = sents[first : last + 1]
        a, b = span[0].word_range[0], span[-1].word_range[1]
        clip_text = " ".join(s.text for s in span)
        hook, hook_source = critic.text_hook(clip_text, words[a : b + 1])
        det = fidelity.counter_read(
            [{"text": s.text, "start_s": round(s.start, 3), "end_s": round(s.end, 3)} for s in span],
            _adjacent(sents, first - 1, span[0].speaker), _adjacent(sents, last + 1, span[-1].speaker), hook,
        )  # fmt: skip
        model_part = {k: v for k, v in (rubric.get("counter_reader") or {}).items() if k not in ("deterministic", "status", "hook", "hook_source")}
        rubric["counter_reader"] = {
            "status": "checked", "hook": hook, "hook_source": hook_source,
            "deterministic": det, **{"model": None, "second": None, "additional_findings": [], "rejected_by_second_only": False, "confirmed": False},
            **model_part,
        }  # fmt: skip
    attempt = title_card_attempt(words, sents, first, last, rubric, policy)
    rubric.pop("repair_applied", None)
    if attempt is not None:
        rubric["title_card_attempt"] = attempt
        if attempt["recheck"]["passed"]:
            rubric["repair_applied"] = {k: attempt[k] for k in ("kind", "text", "source_span", "sentence_idx", "recheck")}
    else:
        rubric.pop("title_card_attempt", None)
    if review_settings(policy):
        rubric["review_state"] = derive_review_state(
            rubric, candidate.risk_flags, candidate.gates, candidate.story_graph_flags, words, sents
        )


__all__ = [
    "REVIEW_ORIGINS",
    "REVIEW_STATES",
    "REVIEW_SWITCH",
    "annotate_review",
    "derive_review_state",
    "release_relevant_claims",
    "review_settings",
    "title_card_attempt",
]
