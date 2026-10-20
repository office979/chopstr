"""Story-Graph light (Phase 2): findet Stellen NACH einem Clip, die dessen Aussage einschränken.

Ein Clip kann formal sauber geschnitten und trotzdem irreführend sein, wenn 20 Sekunden später
„Das heißt aber nicht, dass ..." kommt.

Stufe 1 (billig, deterministisch): Kontrastmarker plus lexikalische Überlappung im Folgefenster.
Stufe 2 (nur bei Treffer): LLM-Urteil über ``story_graph_confirm_v1`` (``confirm`` unten).
Ohne spaCy werden statt Lemmata einfache Wortstämme verglichen.
"""

from __future__ import annotations

import re
from typing import Any

from .. import prompts
from . import dach_nlp
from .segment import Sentence

CONTRAST_MARKERS = (
    "das heißt aber nicht", "das heißt nicht", "das bedeutet nicht", "wobei man sagen muss",
    "allerdings", "aber natürlich", "außer", "nur wenn", "es sei denn", "fairerweise",
    "um das einzuordnen", "nicht falsch verstehen", "das gilt nicht", "in unserem fall",
    "bei uns war das", "das ist aber die ausnahme", "das gilt nur", "mit einer einschränkung",
)  # fmt: skip
# Korrekturmarker (AP4, nur Regel v2): der Sprecher nimmt eine eigene Aussage zurück. Wortliste ohne Messung
# (Herkunft H, origins.gates.later_correction.wordlist).
CORRECTION_MARKERS = (
    "ich korrigiere mich", "ich muss mich korrigieren", "muss ich korrigieren", "das stimmt so nicht",
    "stimmt gar nicht", "das stimmt nöd", "das war falsch", "ich hab mich vertan", "ich habe mich vertan",
    "nein, falsch", "nein, quatsch", "korrektur", "ich meinte", "ich meine natürlich", "um das richtigzustellen",
)  # fmt: skip
# Unter Regel v2 zusätzlich als Einschränkung (keine Korrektur): „genauer gesagt“ präzisiert; „ausser“ ist die
# Schreibung ohne ß (Schweiz).
CONTRAST_MARKERS_V2 = (*CONTRAST_MARKERS, "ausser", "genauer gesagt")
LOOKAHEAD_S = 60.0
MIN_OVERLAP = 0.15

CONFIRM_SCHEMA = {
    "type": "object",
    "properties": {
        "misleading_without": {"type": "boolean"},
        "reason": {"type": "string"},
        "repair": {"type": "string", "enum": ["extend", "overlay", "none"]},
    },
    "required": ["misleading_without", "reason"],
}

_SUFFIXES = ("ungen", "heiten", "keiten", "lich", "isch", "ung", "heit", "keit", "en", "er", "es", "em", "e", "n", "s")


def _stem(tok: str) -> str:
    for suf in _SUFFIXES:
        if tok.endswith(suf) and len(tok) - len(suf) >= 4:
            return tok[: -len(suf)]
    return tok


def _lemmas(text: str) -> set[str]:
    pipe = dach_nlp.nlp()
    if pipe is not None:
        doc = pipe(text)
        return {t.lemma_.lower() for t in doc if t.pos_ in ("NOUN", "PROPN", "VERB", "ADJ") and len(t) > 3}
    return {_stem(t) for t in re.findall(r"[a-zäöüß]+", text.lower()) if len(t) > 3}


def lexical_overlap(clip_text: str, later_text: str) -> float:
    """Anteil der Inhaltswörter von ``later_text``, die auch in ``clip_text`` stehen (wie im Story-Graph)."""
    lem = _lemmas(later_text)
    return len(_lemmas(clip_text) & lem) / max(len(lem), 1)


def _marker_tokens(marker: str) -> tuple[str, ...]:
    return tuple(t for t in (dach_nlp.core_token(x) for x in marker.split()) if t)


def find_marker(text: str, markers: tuple[str, ...]) -> str | None:
    """Erster Marker aus ``markers``, der als ganze Wortfolge in ``text`` steht („außer“ trifft nicht
    „außerdem“, Satzzeichen zählen nicht)."""
    toks = [t for t in (dach_nlp.core_token(x) for x in text.split()) if t]
    for m in markers:
        mt = _marker_tokens(m)
        if mt and any(tuple(toks[k : k + len(mt)]) == mt for k in range(len(toks) - len(mt) + 1)):
            return m
    return None


def _find_later_qualifications_v2(sents: list[Sentence], clip_first: int, clip_last: int, policy: Any = None) -> list[dict]:
    """Regel v2: Marker an Wortgrenzen, zusätzlich Korrekturmarker. Bei einer Korrektur zählt für den Bezug
    auch der Satz danach, weil die Korrektur oft erst dort sagt, was sie richtigstellt.

    Mit dem Claim-Index (Lane P3, ``context.claim_index``) kommen Eigenkorrekturen und Widersprüche aus dem
    ganzen Transkript dazu, ohne 60-s-Grenze (``_claim_index_hits``)."""
    hits = _marker_hits_v2(sents, clip_first, clip_last)
    return hits + _claim_index_hits(sents, clip_first, clip_last, {int(h["sentence_idx"]) for h in hits}, policy)


def _marker_hits_v2(sents: list[Sentence], clip_first: int, clip_last: int) -> list[dict]:
    clip_text = " ".join(s.text for s in sents[clip_first : clip_last + 1])
    end_t = sents[clip_last].end
    hits = []
    later = sents[clip_last + 1 :]
    for n, s in enumerate(later):
        if s.start - end_t > LOOKAHEAD_S:
            break
        marker = find_marker(s.text, CORRECTION_MARKERS)
        kind = "correction"
        if marker is None:
            marker, kind = find_marker(s.text, CONTRAST_MARKERS_V2), "contrast"
        if not marker:
            continue
        text = s.text
        if kind == "correction" and n + 1 < len(later):
            text = f"{s.text} {later[n + 1].text}"
        overlap = lexical_overlap(clip_text, text)
        if overlap >= MIN_OVERLAP:
            hits.append(
                {
                    "sentence_idx": s.idx,
                    "seconds_after": round(s.start - end_t, 1),
                    "marker": marker,
                    "text": s.text,
                    "overlap": round(overlap, 2),
                    "suggestion": f"Clip bis Satz {s.idx} verlängern oder Einschränkung als Text einblenden",
                    "kind": kind,
                }
            )
    return hits


def find_later_qualifications(
    sents: list[Sentence], clip_first: int, clip_last: int, rule: str = "v1", policy: Any = None
) -> list[dict]:
    """Spätere Einschränkungen nach dem Clip. ``rule="v1"`` ist das Verhalten vor AP4 (Teilstring-Abgleich),
    ``rule="v2"`` gleicht an Wortgrenzen ab und kennt Korrekturmarker (``kind``: contrast oder correction).
    Unter ``v2`` mit eingeschaltetem Claim-Index (``policy`` oder die aktive Fassung) zusätzlich Treffer aus dem
    ganzen Transkript mit ``context_class``."""
    if rule == "v2":
        return _find_later_qualifications_v2(sents, clip_first, clip_last, policy)
    clip_text = " ".join(s.text for s in sents[clip_first : clip_last + 1])
    clip_lem = _lemmas(clip_text)
    end_t = sents[clip_last].end
    hits = []
    for s in sents[clip_last + 1 :]:
        if s.start - end_t > LOOKAHEAD_S:
            break
        low = s.text.lower()
        marker = next((m for m in CONTRAST_MARKERS if m in low), None)
        if not marker:
            continue
        lem = _lemmas(s.text)
        overlap = len(clip_lem & lem) / max(len(lem), 1)
        if overlap >= MIN_OVERLAP:
            hits.append(
                {
                    "sentence_idx": s.idx,
                    "seconds_after": round(s.start - end_t, 1),
                    "marker": marker,
                    "text": s.text,
                    "overlap": round(overlap, 2),
                    "suggestion": f"Clip bis Satz {s.idx} verlängern oder Einschränkung als Text einblenden",
                }
            )
    return hits


# -- Claim-Index über das ganze Video (Lane P3, Launch-Auftrag Phase 3) ----------------------------------------
# Deterministisch, ohne Embeddings und ohne neue Abhängigkeit: jeder Satz mit Zahl, Verneinung, Bedingung,
# Einschränkung, Zeitbezug oder Zuschreibung kommt in den Index. Je Kandidat werden im ganzen Transkript Sätze
# mit denselben Lemmata, Zahlen oder Namen gesucht (Lemma-Jaccard gegen den ähnlichsten Clipsatz) und mit
# Sprecherbezug eingeordnet. Die Wortlisten sind Übertragungshypothesen ohne Messung (Herkunft H in
# ``origins.context.claim_index.*``). Ein nicht gefundener Bezug beweist nicht, dass keiner existiert
# (Master-Prompt Regel 12); ``CLAIM_INDEX_NOTE`` steht deshalb in jedem Bericht.
CLAIM_INDEX_SWITCH = "context.claim_index"
CLAIM_INDEX_DEFAULTS = {"max_hits": 5, "min_overlap": 0.2}
CLAIM_INDEX_NOTE = "Ein nicht gefundener Kontextbezug ist kein Beleg, dass keiner existiert; durchsucht wurde nur der Wortlaut des Transkripts."
CONTEXT_CLASSES = ("self_correction", "addition", "contradiction_by_other", "unrelated")
CLAIM_NEGATIONS = frozenset({
    "nicht", "kein", "keine", "keinen", "keinem", "keiner", "keines", "keins", "nie", "niemals", "nichts",
    "niemand", "ned", "nöd", "nid", "nit", "net",
})  # fmt: skip
CLAIM_CONDITIONS = ("nur wenn", "es sei denn", "vorausgesetzt", "wenn", "falls", "sofern", "außer", "ausser")
CLAIM_RESTRICTIONS = (
    "nur", "bei uns", "bei mir", "in unserem fall", "in meinem fall", "meistens", "manchmal", "teilweise",
    "in der regel", "nicht immer",
)  # fmt: skip
CLAIM_TIME = (
    "damals", "früher", "heute", "inzwischen", "mittlerweile", "seit", "letztes jahr", "letzte woche",
    "letzten monat", "dieses jahr", "nächstes jahr", "vor kurzem",
)  # fmt: skip
CLAIM_ATTRIBUTION = (
    "laut", "zufolge", "sagt", "sagte", "sagen", "meint", "meinte", "behauptet", "behauptete", "angeblich",
    "schreibt", "schrieb",
)  # fmt: skip
NAME_CUES = frozenset({"laut", "herr", "frau", "dr", "prof", "kollege", "kollegin"})
DISAGREEMENT_MARKERS = (
    "stimmt nicht", "stimmt so nicht", "sehe ich anders", "seh ich anders", "widerspreche", "widerspruch",
    "quatsch", "unsinn", "falsch", "im gegenteil", "das glaube ich nicht", "da muss ich widersprechen",
)  # fmt: skip
REPETITION_JACCARD = 0.6
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d\d(?!\d)")
_LEMMA_CACHE: dict[tuple[str, bool], frozenset[str]] = {}
_LEMMA_CACHE_MAX = 20000


def claim_index_settings(policy: Any) -> dict[str, Any] | None:
    """Einstellungen des Claim-Index oder ``None`` (Fassung 1, Schalter ``implementation.context.claim_index``
    aus oder Regel ``context.claim_index.enabled`` aus). Wirksam nur mit beiden; ``max_hits`` (Top-M Treffer)
    und ``min_overlap`` (Lemma-Jaccard ab dem ein Treffer als verwandt gilt) aus der Policy. Ein Wert, der
    keiner ist, scheitert laut."""
    from .. import editorial

    if policy is None or getattr(policy, "version", 1) < 2:
        return None
    roh = policy.roh
    if editorial._switch_value(roh.get("implementation") or {}, CLAIM_INDEX_SWITCH) is not True:
        return None
    raw = ((roh.get("context") or {}).get("claim_index")) or {}
    if raw.get("enabled") is not True:
        return None
    try:
        max_hits = int(raw.get("max_hits", CLAIM_INDEX_DEFAULTS["max_hits"]))
        min_overlap = float(raw.get("min_overlap", CLAIM_INDEX_DEFAULTS["min_overlap"]))
    except (TypeError, ValueError):
        raise editorial.PolicyError(f"clip_policy_v{policy.version}: context.claim_index braucht max_hits und min_overlap als Zahl.") from None
    if max_hits < 1 or not 0.0 < min_overlap <= 1.0:
        raise editorial.PolicyError(f"clip_policy_v{policy.version}: context.claim_index.max_hits ab 1, min_overlap über 0 bis 1.")
    return {"max_hits": max_hits, "min_overlap": min_overlap}


def _active_policy_or_none() -> Any:
    from .. import editorial

    try:
        return editorial.load()
    except editorial.PolicyError:
        return None


def _cached_lemmas(text: str) -> frozenset[str]:
    key = (text, dach_nlp.nlp() is not None)
    hit = _LEMMA_CACHE.get(key)
    if hit is None:
        if len(_LEMMA_CACHE) >= _LEMMA_CACHE_MAX:
            _LEMMA_CACHE.clear()
        hit = _LEMMA_CACHE[key] = frozenset(_lemmas(text))
    return hit


def _core_tokens(text: str) -> list[str]:
    return [t for t in (dach_nlp.core_token(x) for x in text.split()) if t]


def _has_phrase(toks: list[str], phrases: tuple[str, ...]) -> str | None:
    for p in phrases:
        pt = _marker_tokens(p)
        if pt and any(tuple(toks[k : k + len(pt)]) == pt for k in range(len(toks) - len(pt) + 1)):
            return p
    return None


def _names(text: str) -> set[str]:
    """Namen nur nach einem Hinweis („laut“, „Herr“, „Frau“, „Dr.“) oder vor „sagt“/„meint“: im Deutschen sind
    alle Nomen großgeschrieben, ein großer Anfangsbuchstabe allein ist kein Name."""
    raw = text.split()
    toks = [dach_nlp.core_token(x) for x in raw]
    out: set[str] = set()
    for k, tok in enumerate(toks):
        nxt = raw[k + 1] if k + 1 < len(raw) else ""
        if tok in NAME_CUES and nxt[:1].isupper() and dach_nlp.core_token(nxt) not in NAME_CUES:
            out.add(dach_nlp.core_token(nxt))
        if tok in ("sagt", "sagte", "meint", "meinte") and k > 0 and raw[k - 1][:1].isupper() and k - 1 > 0:
            out.add(toks[k - 1])
    return {n for n in out if n}


def claim_features(text: str) -> dict[str, Any]:
    """Merkmale eines Satzes für den Index: Arten (``number``, ``negation``, ``condition``, ``restriction``,
    ``time``, ``attribution``), Zahlen als (Wert, Einheit) und Namen."""
    from . import fidelity

    toks = _core_tokens(text)
    numbers = sorted({(m.value, m.unit) for m in fidelity.number_mentions(text)}, key=lambda x: (x[0], str(x[1])))
    kinds = []
    if numbers:
        kinds.append("number")
    if any(t in CLAIM_NEGATIONS for t in toks):
        kinds.append("negation")
    if _has_phrase(toks, CLAIM_CONDITIONS):
        kinds.append("condition")
    if _has_phrase(toks, CLAIM_RESTRICTIONS):
        kinds.append("restriction")
    if _has_phrase(toks, CLAIM_TIME) or _YEAR.search(text):
        kinds.append("time")
    names = _names(text)
    if _has_phrase(toks, CLAIM_ATTRIBUTION) or names:
        kinds.append("attribution")
    return {"kinds": kinds, "numbers": numbers, "names": sorted(names), "negated": "negation" in kinds}


def build_claim_index(sents: list[Sentence]) -> list[dict[str, Any]]:
    """Alle Sätze mit mindestens einer Art aus ``claim_features``, in Transkriptreihenfolge."""
    out = []
    for s in sents:
        feats = claim_features(s.text)
        if feats["kinds"]:
            out.append({"sentence_idx": s.idx, "speaker": s.speaker, "start_s": round(s.start, 3), "end_s": round(s.end, 3), **feats})
    return out


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _number_relation(a: list, b: list) -> tuple[bool, bool]:
    """(gleiche Zahl, abweichende Zahl): abweichend heißt dieselbe Einheit, aber kein gemeinsamer Wert."""
    shared = {x for x in a} & {x for x in b}
    units_a, units_b = {u for _v, u in a}, {u for _v, u in b}
    common_units = units_a & units_b
    differs = bool(common_units) and not any(u in common_units for _v, u in shared)
    return bool(shared), differs


def _classify(s: Sentence, c: Sentence, feats_s: dict, feats_c: dict, jaccard: float, shared_names: bool,
              sents: list[Sentence], last: int, min_overlap: float) -> tuple[str, str, str | None]:  # fmt: skip
    """(Klasse, Grund, Marker) eines Treffers ``s`` gegen den ähnlichsten Clipsatz ``c``."""
    same_num, num_differs = _number_relation(feats_s["numbers"], feats_c["numbers"])
    related = jaccard >= min_overlap or (shared_names and jaccard > 0)
    if not related:
        return "unrelated", ("same_number_only" if same_num else "low_overlap"), None
    neg_flip = feats_s["negated"] != feats_c["negated"]
    after = s.idx > last
    same_speaker = s.speaker == c.speaker
    if same_speaker:
        marker = find_marker(s.text, CORRECTION_MARKERS)
        prev = sents[s.idx - 1] if s.idx - 1 > last else None
        if marker is None and prev is not None and prev.speaker == s.speaker:
            marker = find_marker(prev.text, CORRECTION_MARKERS)
        if after and marker:
            return "self_correction", "marker", marker
        if after and num_differs:
            return "self_correction", "number", None
        if after and neg_flip:
            return "self_correction", "negation", None
        contrast = find_marker(s.text, CONTRAST_MARKERS_V2)
        if after and contrast:
            return "self_correction", "qualification", contrast
        if jaccard >= REPETITION_JACCARD and not num_differs and not neg_flip:
            return "addition", "repetition", None
        return "addition", "addition", None
    disagree = find_marker(s.text, DISAGREEMENT_MARKERS) or find_marker(s.text, CONTRAST_MARKERS_V2)
    if disagree:
        return "contradiction_by_other", "marker", disagree
    if num_differs:
        return "contradiction_by_other", "number", None
    if neg_flip:
        return "contradiction_by_other", "negation", None
    return "unrelated", "other_speaker_agrees", None


REACTIONS = {
    ("self_correction", "marker"): "later_correction",
    ("self_correction", "number"): "later_correction",
    ("self_correction", "negation"): "later_correction",
    ("self_correction", "qualification"): "review",
    ("addition", "addition"): "hint",
    ("addition", "repetition"): "hint",
    ("contradiction_by_other", "marker"): "flag",
    ("contradiction_by_other", "number"): "flag",
    ("contradiction_by_other", "negation"): "flag",
}


def context_hits(
    sents: list[Sentence], first: int, last: int, max_hits: int = 5, min_overlap: float = 0.2, policy: Any = None
) -> list[dict[str, Any]]:
    """Treffer aus dem Claim-Index für den Kandidaten ``first`` bis ``last`` über das ganze Transkript.

    Ein Satz außerhalb des Clips ist Kandidat, wenn er im Index steht und mit einem Clipsatz Lemmata
    (Jaccard), eine Zahl (Wert und Einheit) oder einen Namen teilt. Rangfolge nach Ähnlichkeit, dann Nähe;
    höchstens ``max_hits``. Je Treffer ``context_class`` (``CONTEXT_CLASSES``), ``class_reason``, die
    Schnittreaktion ``reaction`` (``later_correction``, ``review``, ``hint``, ``flag``, ``none``) und bei einer
    Eigenkorrektur in Reichweite der Policy ``heal_to_sentence_idx``."""
    from .editorial_gates import _back_heal

    clip = sents[first : last + 1]
    clip_feats = [(c, _cached_lemmas(c.text), claim_features(c.text)) for c in clip]
    end_t, start_t = sents[last].end, sents[first].start
    found = []
    for entry in build_claim_index(sents):
        idx = entry["sentence_idx"]
        if first <= idx <= last:
            continue
        s = sents[idx]
        lem = _cached_lemmas(s.text)
        best = None
        for c, clem, cfeat in clip_feats:
            j = _jaccard(lem, clem)
            same_num, _diff = _number_relation(entry["numbers"], cfeat["numbers"])
            names = bool(set(entry["names"]) & set(cfeat["names"]))
            score = j + (0.2 if same_num else 0.0) + (0.2 if names else 0.0)
            if (j >= min_overlap or same_num or names) and (best is None or score > best[0]):
                best = (score, c, cfeat, j, names)
        if best is None:
            continue
        score, c, cfeat, j, names = best
        cls, reason, marker = _classify(s, c, entry, cfeat, j, names, sents, last, min_overlap)
        reaction = REACTIONS.get((cls, reason), "none")
        hit = {
            "sentence_idx": idx,
            "clip_sentence_idx": c.idx,
            "speaker": s.speaker,
            "clip_speaker": c.speaker,
            "text": s.text,
            "start_s": round(s.start, 3),
            "end_s": round(s.end, 3),
            "seconds_from_clip": round(s.start - end_t, 1) if idx > last else round(s.end - start_t, 1),
            "kinds": entry["kinds"],
            "jaccard": round(j, 3),
            "score": round(score, 3),
            "context_class": cls,
            "class_reason": reason,
            "marker": marker,
            "reaction": reaction,
        }
        if reaction == "later_correction":
            target = idx + 1 if reason == "marker" and find_marker(s.text, CORRECTION_MARKERS) and idx + 1 < len(sents) else idx
            hit["heal_to_sentence_idx"] = target if _back_heal(sents, last, target, policy) else None
        found.append(hit)
    found.sort(key=lambda h: (-h["score"], abs(h["sentence_idx"] - last)))
    return found[:max_hits]


def context_report(sents: list[Sentence], first: int, last: int, policy: Any) -> dict[str, Any] | None:
    """``rubric.context_hits`` für einen Kandidaten oder ``None`` ohne Claim-Index. ``flags`` enthält
    ``debate_contradiction`` mit Belegstelle, wenn ein anderer Sprecher widerspricht (kein Verwerfen)."""
    cfg = claim_index_settings(policy)
    if cfg is None:
        return None
    hits = context_hits(sents, first, last, cfg["max_hits"], cfg["min_overlap"], policy)
    flags = [
        {"flag": "debate_contradiction", "sentence_idx": h["sentence_idx"], "speaker": h["speaker"],
         "source_span": {"start_s": h["start_s"], "end_s": h["end_s"]}, "quote": h["text"]}
        for h in hits if h["context_class"] == "contradiction_by_other"
    ]  # fmt: skip
    return {
        "method": "lemma_jaccard",
        "max_hits": cfg["max_hits"],
        "min_overlap": cfg["min_overlap"],
        "index_size": len(build_claim_index(sents)),
        "hits": hits,
        "flags": flags,
        "note": CLAIM_INDEX_NOTE,
    }


def _claim_index_hits(sents: list[Sentence], first: int, last: int, known: set[int], policy: Any) -> list[dict]:
    """Treffer für ``find_later_qualifications`` (Regel v2): Eigenkorrekturen und Widersprüche nach dem Clip
    aus dem Claim-Index, auch außerhalb des 60-s-Fensters, ohne die schon gefundenen Sätze. ``kind`` ist
    ``correction`` für eine Eigenkorrektur mit Korrekturmarker, anderer Zahl oder Verneinung (das Gate
    ``later_correction`` liest sie), sonst ``contrast``."""
    policy = policy if policy is not None else _active_policy_or_none()
    cfg = claim_index_settings(policy)
    if cfg is None:
        return []
    clip_text = " ".join(s.text for s in sents[first : last + 1])
    end_t = sents[last].end
    out = []
    for h in context_hits(sents, first, last, cfg["max_hits"], cfg["min_overlap"], policy):
        idx = h["sentence_idx"]
        if idx <= last or idx in known or h["context_class"] not in ("self_correction", "contradiction_by_other"):
            continue
        correction = h["reaction"] == "later_correction"
        out.append({
            "sentence_idx": idx,
            "seconds_after": round(sents[idx].start - end_t, 1),
            "marker": h["marker"] or {"number": "abweichende Zahl", "negation": "umgekehrte Verneinung"}.get(h["class_reason"], ""),
            "text": h["text"],
            "overlap": round(lexical_overlap(clip_text, h["text"]), 2),
            "suggestion": f"Clip bis Satz {idx} verlängern oder Einschränkung als Text einblenden",
            "kind": "correction" if correction else "contrast",
            "context_class": h["context_class"],
            "heal_to_sentence_idx": h.get("heal_to_sentence_idx"),
        })  # fmt: skip
    return out


def build_confirm_prompt(clip_text: str, later_text: str, seconds_after: float) -> tuple[str, prompts.Prompt]:
    p = prompts.load_pinned("story_graph_confirm")
    return p.render(clip_text=clip_text, later_text=later_text, seconds_after=round(seconds_after)), p


def confirm(llm, clip_text: str, later_text: str, seconds_after: float) -> dict[str, Any]:
    """Stufe 2: LLM bestätigt oder verwirft den Treffer."""
    from .story_score import system_prompt

    user, p = build_confirm_prompt(clip_text, later_text, seconds_after)
    out = llm.structured(system_prompt(), user, CONFIRM_SCHEMA, p.tool or "confirm_qualification", p.prompt_version, job_type="llm_score")
    out["prompt_version"] = p.prompt_version
    return out


def claims_in(text: str) -> list[str]:
    """Grobe Claim-Extraktion für Grounding: Sätze mit Zahlen, Superlativen oder Kausalbehauptungen."""
    out = []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if re.search(r"\d|immer|nie|jede[rsn]?|alle|garantiert|bewiesen|weil|dadurch", sent.lower()):
            out.append(sent.strip())
    return out


__all__ = [
    "CLAIM_INDEX_NOTE",
    "CLAIM_INDEX_SWITCH",
    "CONFIRM_SCHEMA",
    "CONTEXT_CLASSES",
    "CONTRAST_MARKERS",
    "CONTRAST_MARKERS_V2",
    "CORRECTION_MARKERS",
    "build_claim_index",
    "build_confirm_prompt",
    "claim_features",
    "claim_index_settings",
    "claims_in",
    "confirm",
    "context_hits",
    "context_report",
    "find_later_qualifications",
    "find_marker",
    "lexical_overlap",
]
