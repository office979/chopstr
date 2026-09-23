"""Story-Engine (Phase 2): LLM schlägt Momente vor, Rubrik bewertet mit Gates und Belegzitaten.

Zweistufig, damit es bei 90-Min-Podcasts bezahlbar bleibt:
  Stufe A (pro Kapitel): ``propose`` mit ``propose_moments_v1``
  Stufe B (pro Vorschlag): ``score`` mit ``score_clip_v2``; bei offenem Kontext erweitert
                           ``score_with_repair`` die Grenzen und bewertet neu (max. 2 Runden).

Was einen guten Clip ausmacht, steht nicht hier und nicht im Prompt, sondern in der redaktionellen
Grundlage (``packages/editorial/clip_policy_v<N>.yaml``, geladen über ``editorial.load``). Von dort
kommen die sieben Kriterien, ihre Anker, die Skala, die Gewichte und die Gesamtpunktzahl. Der Prompt
bekommt sie zur Laufzeit in den Platzhalter ``{policy}`` gefüllt. Das Frontmatter des Prompts darf
die Gewichte als Kopie mitführen, aber bei Abweichung gewinnt die Grundlage, und die Abweichung wird
geloggt (``weight_drift``).

Kein Provider-Client auf Modulebene: alle Aufrufe laufen über ``providers_llm.LLM`` (Residency-Guard)
und ``prompts.load`` (versionierte Prompts).
"""

from __future__ import annotations

import logging
from typing import Any

from .. import editorial, prompts
from ..providers_llm import LLM
from .segment import Sentence, numbered

log = logging.getLogger("chopstr.story")

STRUCTURES = ["payoff_first", "tension_first", "hook_build_payoff", "decision_story", "how_to_list", "loop"]

PROPOSE_SCHEMA = {
    "type": "object",
    "properties": {
        "moments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "first_sent": {"type": "integer"},
                    "last_sent": {"type": "integer"},
                    "structure": {"type": "string", "enum": STRUCTURES},
                    "why": {"type": "string"},
                },
                "required": ["first_sent", "last_sent", "structure", "why"],
            },
        }
    },
    "required": ["moments"],
}

# Bestandsschema der Fassung ``score_clip_v1``: fünf Kriterien auf einer Skala von 0 bis 10. Es wird
# nicht mehr an das Modell geschickt, bleibt aber die verbindliche Beschreibung dessen, was jedes
# Ergebnis von ``score`` weiterhin enthält (Bestandsdaten, Web-App, ``story_engine.SCORE_KEYS``).
RUBRIC_SCHEMA = {
    "type": "object",
    "properties": {
        "unresolved_references": {"type": "array", "items": {"type": "string"}},
        "needs_earlier_context": {"type": "boolean"},
        "ends_before_answer": {"type": "boolean"},
        "hook": {"type": "integer", "minimum": 0, "maximum": 10},
        "hook_evidence": {"type": "string"},
        "payoff": {"type": "integer", "minimum": 0, "maximum": 10},
        "payoff_evidence": {"type": "string"},
        "specificity": {"type": "integer", "minimum": 0, "maximum": 10},
        "specificity_evidence": {"type": "string"},
        "tension": {"type": "integer", "minimum": 0, "maximum": 10},
        "tension_evidence": {"type": "string"},
        "audience_fit": {"type": "integer", "minimum": 0, "maximum": 10},
        "audience_fit_evidence": {"type": "string"},
        "is_humor": {"type": "boolean"},
        "sensitive_topic": {"type": "boolean"},
        "suggested_title_card": {"type": "string"},
        "why": {"type": "string"},
    },
    "required": [
        "unresolved_references", "needs_earlier_context", "ends_before_answer", "hook", "hook_evidence",
        "payoff", "payoff_evidence", "specificity", "specificity_evidence", "tension", "audience_fit",
        "is_humor", "suggested_title_card", "why",
    ],  # fmt: skip
}

# Gewichte der Fassung v1, als sie noch im Prompt-Frontmatter standen. Nur noch Referenz für den
# Vergleich mit Bestandsdaten; die gültigen Gewichte kommen aus der Grundlage.
DEFAULT_WEIGHTS = {"hook": 0.30, "payoff": 0.25, "specificity": 0.20, "tension": 0.15, "audience_fit": 0.10}

LEGACY_KEYS = ("hook", "payoff", "specificity", "tension", "audience_fit")

# Zuordnung der sieben Kriterien der Grundlage auf die alten fünf Rubrik-Schlüssel.
#
# Warum überhaupt: ``candidates.rubric`` in der Datenbank und die Web-App kennen die alten fünf
# Schlüssel auf der Skala 0 bis 10. Bestehende Zeilen lassen sich nicht nachbewerten, und eine
# Oberfläche, die plötzlich leere Felder zeigt, ist schlimmer als eine grobe Umrechnung. Deshalb
# trägt jedes Ergebnis beide Rubriken nebeneinander.
#
#   hook         -> hook          gleiche Frage, gleicher Name
#   aufloesung   -> payoff        „endet auf einem Hochpunkt" ist die alte „Auflösung im Clip"
#   spezifitaet  -> specificity   Zahlen, Namen, Bilder
#   offene_frage -> tension       das alte „tension" war die Neugierlücke, nur unschärfer gefasst
#   zielgruppe   -> audience_fit  Bewusstseinsstufe des Zuschauers
#
# Ohne alte Entsprechung bleiben ``standalone`` und ``emotion``. Beide sind in der alten Rubrik
# schlicht nicht vorgekommen (``standalone`` war nur eine Ja/Nein-Sperre, ``emotion`` fehlte ganz).
# Sie gehen deshalb in ``total`` und in ``rubric_points`` ein, aber in keinen alten Schlüssel; nichts
# anderes wäre ehrlich, als ihnen ein fremdes Feld zuzuweisen.
POLICY_TO_LEGACY = {
    "hook": "hook",
    "aufloesung": "payoff",
    "spezifitaet": "specificity",
    "offene_frage": "tension",
    "zielgruppe": "audience_fit",
}
LEGACY_TO_POLICY = {v: k for k, v in POLICY_TO_LEGACY.items()}
LEGACY_SCALE_MAX = 10


def system_prompt() -> str:
    return prompts.load("system_editor").render()


def rubric_schema(pol: editorial.Policy | None = None) -> dict:
    """Antwortschema zur Grundlage: sieben Kriterien auf ihrer Skala, je mit Belegzitat.

    ``required`` enthält bewusst nur Gates und Flags, nicht die Punkte. Grund: neben dem Sprachmodell
    bedient auch der Heuristik-Provider ``local-heuristic`` dieses Tool, und der antwortet in einer
    eigenen Form (alte fünf flach, die sieben unter ``rubrik``). Ein hartes ``required`` auf den
    sieben flachen Schlüsseln würde ihn abwürgen, ohne dass dadurch eine Bewertung besser würde.
    Dass am Ende beide Rubriken vollständig dastehen, stellt ``_harmonise`` sicher; kommt überhaupt
    keine Punktzahl, scheitert es dort laut.
    """
    pol = pol or editorial.load()
    props: dict[str, Any] = {
        "unresolved_references": {"type": "array", "items": {"type": "string"}},
        "needs_earlier_context": {"type": "boolean"},
        "ends_before_answer": {"type": "boolean"},
    }
    for k in pol.kriterien:
        props[k.schluessel] = {"type": "integer", "minimum": 0, "maximum": pol.skala_max, "description": k.frage}
        props[f"{k.schluessel}_evidence"] = {"type": "string", "description": "wörtliches Zitat aus dem Kandidaten"}
    props |= {
        "is_humor": {"type": "boolean"},
        "sensitive_topic": {"type": "boolean"},
        "suggested_title_card": {"type": "string"},
        "why": {"type": "string"},
    }
    return {
        "type": "object",
        "properties": props,
        "required": [
            "unresolved_references", "needs_earlier_context", "ends_before_answer",
            "is_humor", "suggested_title_card", "why",
        ],  # fmt: skip
    }


def policy_weights(pol: editorial.Policy | None = None) -> dict[str, float]:
    """Die Gewichte der Grundlage, unverändert. Einzige Quelle, alles andere leitet sich davon ab."""
    return dict((pol or editorial.load()).gewichte)


def legacy_weights(pol: editorial.Policy | None = None) -> dict[str, float]:
    """Die Gewichte der Grundlage, projiziert auf die alten fünf Schlüssel.

    ``standalone`` und ``emotion`` haben keine alte Entsprechung und fallen weg; die verbleibenden
    fünf werden auf Summe 1 normiert. Das muss sein: ``story_engine.weighted_total`` rechnet über
    genau diese fünf Schlüssel, und ein Gewichtsvektor, der nur 0,65 ergibt, würde alle Gesamtwerte
    stauchen und sie damit unvergleichbar zu den Zeilen machen, die schon in der Datenbank stehen.
    Die Rangfolge untereinander bleibt die der Grundlage.
    """
    pol = pol or editorial.load()
    roh = {legacy: float(pol.gewichte.get(pk, 0.0)) for pk, legacy in POLICY_TO_LEGACY.items()}
    summe = sum(roh.values()) or 1.0
    return {k: round(v / summe, 4) for k, v in roh.items()}


def weight_drift(p: prompts.Prompt, pol: editorial.Policy | None = None) -> dict[str, tuple[float, float]]:
    """Weicht das Gewichts-Frontmatter des Prompts von der Grundlage ab?

    Liefert ``{schluessel: (frontmatter, grundlage)}`` für jede Abweichung. Leer heisst einig. Die
    Grundlage gewinnt in jedem Fall, aber eine stille Abweichung wäre genau die doppelte Pflege,
    die hier abgeschafft werden sollte.
    """
    pol = pol or editorial.load()
    fm = p.meta.get("weights") or {}
    if not fm:
        return {}
    # Frontmatter in den Schlüsseln der Grundlage (v2) gegen die Grundlage, altes Frontmatter (v1)
    # gegen die projizierten Gewichte. Anders wären die beiden Schlüsselwelten nicht vergleichbar.
    erwartet = policy_weights(pol) if set(fm) <= set(pol.gewichte) else legacy_weights(pol)
    return {
        str(k): (float(v), float(erwartet.get(str(k), 0.0)))
        for k, v in fm.items()
        if abs(float(v) - float(erwartet.get(str(k), 0.0))) > 0.005
    }


def weights(p: prompts.Prompt | None = None) -> dict[str, float]:
    """Gewichte für die Bewertung, aus der Grundlage, in den alten fünf Schlüsseln.

    Die fünf Schlüssel sind Vorgabe von aussen: ``story_engine.SCORE_KEYS``, ``learned_weights`` in
    ``brand_profiles`` und das Decision-Log rechnen damit. Die Werte kommen trotzdem nur noch aus
    ``policy.gewichte`` (siehe ``legacy_weights``). Wer die sieben unverfälscht braucht, nimmt
    ``policy_weights``.
    """
    pol = editorial.load()
    p = p or prompts.load("score_clip")
    drift = weight_drift(p, pol)
    if drift:
        log.warning(
            "Gewichte in %s weichen von der Grundlage %s ab, die Grundlage gewinnt: %s",
            p.prompt_version,
            editorial.policy_version(pol.version),
            ", ".join(f"{k}: {fm:.2f} statt {soll:.2f}" for k, (fm, soll) in sorted(drift.items())),
        )
    return legacy_weights(pol)


def propose(chapter: list[Sentence], brief: dict[str, Any], llm: LLM) -> list[dict]:
    p = prompts.load("propose_moments")
    user = p.render(
        audience=brief.get("audience"),
        wanted=brief.get("wanted"),
        exclude=brief.get("exclude"),
        platform=brief.get("platform", "linkedin"),
        chapter_numbered=numbered(chapter),
    )
    out = llm.structured(system_prompt(), user, PROPOSE_SCHEMA, p.tool or "propose_moments", p.prompt_version, job_type="llm_propose")
    valid_idx = {s.idx for s in chapter}
    moments = []
    for m in out.get("moments", []):
        if m.get("first_sent") in valid_idx and m.get("last_sent") in valid_idx and m["first_sent"] <= m["last_sent"]:
            m["prompt_version"] = p.prompt_version
            moments.append(m)
    return moments


def _evidence_keys(pol: editorial.Policy) -> list[str]:
    """Belegfelder beider Rubriken, ohne Doppelung (``hook`` heisst in beiden gleich)."""
    keys = [f"{k}_evidence" for k in LEGACY_KEYS]
    keys += [f"{k.schluessel}_evidence" for k in pol.kriterien if f"{k.schluessel}_evidence" not in keys]
    return keys


def _evidence_grounded(r: dict, text: str, pol: editorial.Policy | None = None) -> list[str]:
    """Belegzitate müssen wörtlich im Kandidaten vorkommen (Halluzinationsschutz)."""
    issues = []
    low = text.lower()
    for key in _evidence_keys(pol or editorial.load()):
        ev = str(r.get(key, "") or "").strip()
        if ev and ev.lower() not in low:
            issues.append(key)
    return issues


def _zahl(wert: Any, obergrenze: float) -> float | None:
    """Zahl im erlaubten Bereich, sonst ``None``. Bruchteile bleiben erhalten."""
    try:
        z = float(wert)
    except (TypeError, ValueError):
        return None
    return round(max(0.0, min(float(obergrenze), z)), 2)


def _clamp(wert: Any, obergrenze: int) -> int:
    z = _zahl(wert, obergrenze)
    return 0 if z is None else int(round(z))


def _harmonise(r: dict, pol: editorial.Policy) -> tuple[dict[str, float], list[str]]:
    """Beide Rubriken nebeneinander stellen und die Punkte der Grundlage zurückgeben.

    Drei Arten von Antwort treffen ein:
      * Sprachmodell mit ``score_clip_v2``: die sieben Kriterien der Grundlage flach im Objekt.
      * Heuristik-Provider ``local-heuristic``: die sieben unter ``rubrik`` UND die alten fünf
        daneben, weil er beide Rubriken bedient.
      * Bestandsantwort zu ``score_clip_v1``: nur die alten fünf.
    Was fehlt, wird aus der jeweils anderen Rubrik umgerechnet.

    Eine gelieferte alte Punktzahl wird dabei NICHT über die grobe Skala der Grundlage
    zurückgerechnet, sonst würde aus einer 7 eine 5.

    ``hook`` heisst in beiden Rubriken gleich, deshalb festgelegt:
      * die alten fünf Schlüssel stehen im Ergebnis immer auf 0 bis 10, auch ``hook``,
      * die übrigen Schlüssel der Grundlage stehen auf ihrer eigenen Skala (0 bis ``skala_max``),
      * alle sieben auf der Skala der Grundlage stehen in ``rubric_points``.
    Flach geliefertes ``hook`` zählt nur dann zur Grundlage, wenn die Antwort sonst keine alte
    Rubrik mitbringt; sobald ``rubrik`` dabei ist, gilt flaches ``hook`` als alter Wert.

    Rückgabe: die Punkte der sieben Kriterien und die Liste der Schlüssel, die geraten werden
    mussten, weil die Antwort dazu nichts hergab.
    """
    schluessel = [k.schluessel for k in pol.kriterien]
    nur_neu = [k for k in schluessel if k not in LEGACY_KEYS]  # alles ausser ``hook``

    verschachtelt = r.get("rubrik")
    verschachtelt = dict(verschachtelt) if isinstance(verschachtelt, dict) else {}
    if not any(k in verschachtelt for k in schluessel):
        verschachtelt = {}
    flach_neu = not verschachtelt and any(k in r for k in nur_neu)
    if not verschachtelt and not flach_neu and not any(k in r for k in LEGACY_KEYS):
        raise ValueError(
            "Bewertung enthält weder die Kriterien der Grundlage noch die alten fünf: " + ", ".join(sorted(r))
        )

    def neu_wert(pk: str) -> float | None:
        if verschachtelt:
            return _zahl(verschachtelt.get(pk), pol.skala_max) if pk in verschachtelt else None
        return _zahl(r.get(pk), pol.skala_max) if flach_neu and pk in r else None

    def alt_wert(legacy: str) -> float | None:
        if legacy == "hook" and flach_neu:
            return None  # gehört in diesem Fall zur Grundlage, nicht zur alten Rubrik
        return _zahl(r.get(legacy), LEGACY_SCALE_MAX) if legacy in r else None

    punkte: dict[str, float] = {}
    geraten: list[str] = []
    for pk in schluessel:
        legacy = POLICY_TO_LEGACY.get(pk)
        neu = neu_wert(pk)
        alt = alt_wert(legacy) if legacy else None
        if neu is not None:
            punkte[pk] = neu
        elif alt is not None:
            punkte[pk] = round(alt / LEGACY_SCALE_MAX * pol.skala_max, 2)
        elif pk == "standalone":
            # Die alte Rubrik hat Verständlichkeit ohne Vorwissen als Sperre geführt, nicht als
            # Punktzahl. Genau das sagen die Gates, also kommt der Wert von dort.
            punkte[pk] = 0.0 if (r.get("needs_earlier_context") or r.get("unresolved_references")) else pol.skala_max
            geraten.append(pk)
        else:
            # Kein Signal in der Antwort (``emotion`` in der alten Rubrik). Mitte statt Bestnote:
            # geschenkt wird nichts, bestraft wird auch nichts, und es steht in ``rubric_guessed``.
            punkte[pk] = pol.skala_max / 2
            geraten.append(pk)

    # Belege: fehlt einer Rubrik das Zitat, erbt sie es von ihrem Gegenstück.
    for pk, legacy in POLICY_TO_LEGACY.items():
        neu_ev, alt_ev = f"{pk}_evidence", f"{legacy}_evidence"
        if neu_ev in r and alt_ev not in r:
            r[alt_ev] = r[neu_ev]
        elif alt_ev in r and neu_ev not in r:
            r[neu_ev] = r[alt_ev]

    for pk, legacy in POLICY_TO_LEGACY.items():
        alt = alt_wert(legacy)
        r[legacy] = _clamp(alt if alt is not None else punkte[pk] / pol.skala_max * LEGACY_SCALE_MAX, LEGACY_SCALE_MAX)
    for pk in nur_neu:
        r[pk] = punkte[pk]
    return punkte, geraten


def score(span_sents: list[Sentence], brief: dict[str, Any], llm: LLM) -> dict:
    p = prompts.load("score_clip")
    pol = editorial.load()
    text = " ".join(s.text for s in span_sents)
    user = p.render(
        audience=brief.get("audience"),
        platform=brief.get("platform", "linkedin"),
        candidate_numbered=numbered(span_sents),
        policy=pol.als_prompt_text(),
    )
    r = llm.structured(system_prompt(), user, rubric_schema(pol), p.tool or "score_clip", p.prompt_version, job_type="llm_score")
    punkte, geraten = _harmonise(r, pol)
    r["gate_passed"] = not (r["needs_earlier_context"] or r["ends_before_answer"] or r["unresolved_references"])
    r["rubric_points"] = punkte  # alle sieben auf der Skala der Grundlage
    r["rubric_guessed"] = geraten
    r["total"] = pol.gesamtwert(punkte)  # Skala der Grundlage (0 bis punkte_gesamt), nicht 0 bis 10
    r["needs_human"] = bool(r.get("is_humor")) or bool(r.get("sensitive_topic"))
    r["ungrounded_evidence"] = _evidence_grounded(r, text, pol)
    r["prompt_version"] = p.prompt_version
    r["policy_version"] = editorial.policy_version(pol.version)
    r["model_id"] = llm.model()
    return r


def score_with_repair(sents: list[Sentence], first: int, last: int, brief: dict[str, Any], llm: LLM, max_rounds: int = 2) -> dict:
    """Erweitert die Grenzen, solange Kontext fehlt (erst nach vorne, dann nach hinten)."""
    r: dict = {}
    for _ in range(max_rounds + 1):
        r = score(sents[first : last + 1], brief, llm)
        r.update(first_sent=first, last_sent=last, start=sents[first].start, end=sents[last].end)
        if r["gate_passed"]:
            return r
        moved = False
        if (r["needs_earlier_context"] or r["unresolved_references"]) and first > 0:
            first, moved = first - 1, True
        if r["ends_before_answer"] and last < len(sents) - 1:
            last, moved = last + 1, True
        if not moved:
            break
    r["repair_failed"] = True  # UI zeigt Titelkarten-Vorschlag statt Clip zu verwerfen
    return r


__all__ = [
    "DEFAULT_WEIGHTS",
    "LEGACY_KEYS",
    "LEGACY_TO_POLICY",
    "POLICY_TO_LEGACY",
    "PROPOSE_SCHEMA",
    "RUBRIC_SCHEMA",
    "STRUCTURES",
    "legacy_weights",
    "policy_weights",
    "propose",
    "rubric_schema",
    "score",
    "score_with_repair",
    "system_prompt",
    "weight_drift",
    "weights",
]
