"""Transkription mit Wort-Zeitstempeln und Sprecherzuordnung (DACH-optimiert).

- Hochdeutsch (DE/AT): Modell aus ``ASR_MODEL_DE`` (CTranslate2 für faster-whisper)
- Schweizerdeutsch: Modell aus ``ASR_MODEL_CH`` (Beta, Flag ``beta=True`` im Ergebnis)
- Fallback ``gladia-eu``: nur wenn ``GLADIA_BASE_URL`` gesetzt ist und der Residency-Guard den Host erlaubt
- Lange Dateien werden in Fenster (Default 600 s) mit Überlappung (20 s) transkribiert und an der
  Grenze über Wortzeiten zusammengeführt (``merge_windows``, deterministisch, ohne Modell testbar).
- Marken-Wörterbuch: als hotwords + Nachkorrektur (``apply_brand_vocab``)
- Zahlen-Normalisierung (``normalize_numbers``) läuft ERST nach dem Alignment (Sprecher pro Wort),
  damit die Wortzeiten unverändert bleiben.
- Diarisierung: pyannote (lazy), exclusive_speaker_diarization; Sprecher pro Wort per MEHRHEIT
  über die Wortdauer (``assign_speakers``, reine Funktion).

Lane P1 (Phase 1, Master-Prompt Regel 13, Review 4A und 4B):
- Datenvertrag: jedes Ergebnis trägt ``route`` = {variant, model_id, verbatim, time_source, beta,
  detected_language, detected_variant, routing_reason, hints}. ``text`` ist die gesprochene Form (Whisper
  wortgetreu, ``verbatim = true``); ``text_norm`` (``dach_nlp.annotate``) ist nur Untertitelform und wird nie
  für Schnittgrenzen gelesen (Leser: ``captions_de``, ``render``, ``render_plan``, Web ``transcript/dialect.ts``).
  Wortzeiten stammen aus Whisper (``time_source = asr_word_timestamps``), nicht aus einem Alignment.
- Routing nach erkannter Sprache (``ASR_AUTO_ROUTE=1``, Standard aus): Stichprobe (erste 60 s und Mitte) mit
  ``detect_language`` und Lexikon-Markern auf einem Vorab-Transkript (``detect_variant``, ``choose_route``).
- Hotwords: Marken-Wörterbuch, geschützte Begriffe und für erkanntes AT ``AUSTRIACISMS`` (``build_hotwords``).
  Im Decoder nur mit ``asr.hotwords.decode`` (Fassung 2, Standard aus): Hotwords stehen in faster-whisper
  als Prompt vor jedem 30-s-Abschnitt und haben am Testmaterial ganze Sätze verschluckt (Notiz 010).
  Ohne Decoder-Hotwords wirkt das Wörterbuch nur als Nachkorrektur (``apply_brand_vocab``).
- Überlappung: pyannote liefert zusätzlich die nicht exklusive Annotation (``overlap_turns``); Mehrspur
  ohne pyannote über Spurenergie (``energy_diarization``, Quelle ``multitrack_energy``).

faster-whisper, pyannote und torch werden nur innerhalb von Funktionen importiert.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .. import config, residency
from . import dach_nlp

log = logging.getLogger("chopstr.asr")

VARIANTS = ("de", "de-CH")
LOW_CONF_THRESHOLD = 0.5
_DEFAULT_DIARIZER = "pyannote/speaker-diarization-community-1"  # TODO: per DIARIZER_MODEL bestätigen
DIARIZER_NONE = "none"  # Fallback ohne pyannote: ein Sprecher für die ganze Datei
FALLBACK_SPEAKER = "SPEAKER_00"
DIARIZER_MULTITRACK = "multitrack_energy"  # Lane P1: Sprecher aus getrennten Mikrofonspuren, ohne pyannote
# Klasse C (docs/BEDIENKONZEPT.md, Abschnitt 7): Serverzustand, an dem der Nutzer nichts ändern kann.
# Der Text sagt deshalb, was das für ihn bedeutet, nicht welche Umgebungsvariable fehlt. Der genaue
# Grund steht weiterhin im Serverlog.
HINT_DIARIZATION_SKIPPED = "Alle Wörter einem Sprecher zugeordnet, die Sprechertrennung ist hier nicht eingerichtet"
HINT_PYANNOTE_MISSING = "Alle Wörter einem Sprecher zugeordnet, die Sprechertrennung ist hier nicht eingerichtet"
HINT_GENERIC_WHISPER = "Standard-Whisper statt deutschem Fine-Tune"

# -- Lane P1: Datenvertrag, Routing, Hotwords, Überlappung ------------------------------------------------------
TIME_SOURCE_ASR = "asr_word_timestamps"
DETECTED_VARIANTS = ("de", "de-AT", "de-CH", "unklar")
# Hinweise in ``route.hints`` und den Statistiken (Schlüssel, keine Sätze; die Oberfläche übersetzt).
HINT_CH_NO_MODEL = "ch_detected_no_model"
HINT_NON_GERMAN = "non_german_detected"
HINT_NO_DETECTION_MODEL = "no_de_model_for_detection"
# Stichprobe für die Spracherkennung: erste 60 s und 30 s um die Mitte (Auftrag Lane P1).
SAMPLE_HEAD_S = 60.0
SAMPLE_MID_S = 30.0
# Standardwerte, solange die aktive Fassung die Abschnitte ``asr`` und ``speakers`` nicht hat (Fassung 1).
# Gleiche Werte wie in clip_policy_v2.yaml; Herkunft dort in ``origins``.
ASR_DEFAULTS: dict[str, Any] = {"routing_enabled": True, "min_confidence": 0.6, "max_terms": 40, "decode": False, "ch_beta": True}
SPEAKER_DEFAULTS: dict[str, Any] = {"overlap_min_ratio": 0.3, "energy_window_s": 0.1, "overlap_db": 10.0, "silence_dbfs": -45.0}
# faster-whisper 1.2.1 (``WhisperModel.get_prompt``) kürzt Hotwords still auf 223 Token; etwa 3 Zeichen je Token.
HOTWORDS_MAX_CHARS = 600
# Österreichische Varianten (Austriazismen) als Hotwords für erkanntes de-AT. Auswahl aus dem
# Variantenwörterbuch des Deutschen (Ammon, Bickel, Lenz u. a., 2. Auflage 2016, Kennzeichnung A) und dem
# Österreichischen Wörterbuch (ÖWB, 44. Auflage 2022); Alltags-, Verwaltungs- und Wirtschaftswortschatz, der in
# Interviews und Podcasts vorkommt. Nicht je Eintrag gegen die Druckausgabe geprüft; Abnahme über die
# Untertitel-WER auf AT-Material (Master-Prompt Abschnitt 6), die heute mangels Material nicht messbar ist.
AUSTRIACISMS = (
    "Jänner", "Feber", "heuer", "Paradeiser", "Erdäpfel", "Karfiol", "Kren", "Marille", "Topfen", "Obers",
    "Schlagobers", "Semmel", "Kipferl", "Palatschinke", "Powidl", "Ribisel", "Fisolen", "Kukuruz", "Melanzani",
    "Schwammerl", "Eierschwammerl", "Vogerlsalat", "Germ", "Faschiertes", "Beiried", "Lungenbraten", "Fleischhauer",
    "Selchfleisch", "Stelze", "Hendl", "Grammeln", "Kracherl", "Häferl", "Agrasel", "Nachtmahl", "Jause",
    "jausnen", "Sackerl", "Packerl", "Stiege", "Kasten", "Polster", "Spital", "Matura", "Maturant", "Schularbeit",
    "Inskription", "Sponsion", "Trafik", "Trafikant", "Greißler", "Bankomat", "Bankomatkarte", "Erlagschein",
    "Krampus", "Gelse", "Zuckerl", "Fauteuil", "Mistkübel", "Rauchfangkehrer", "Schlapfen", "Patschen",
    "hackeln", "Gspritzter", "Heuriger", "Beisl", "Kassa", "Schmäh", "leiwand", "Bim", "Pickerl", "Magistrat",
    "Landeshauptmann", "Bezirkshauptmannschaft", "Kollektivvertrag", "Abfertigung", "Karenz", "Gebarung",
    "Ordination", "Primar", "Exekution", "Firmenbuch", "Akonto",
)  # fmt: skip


class TranscribeError(RuntimeError):
    pass


@dataclass
class Word:
    text: str
    start: float
    end: float
    prob: float
    speaker: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TranscriptResult:
    words: list[dict]
    model_id: str
    variant: str
    provider: str = "selfhost-eu"
    beta: bool = False
    windows: int = 1
    duration_s: float = 0.0
    compute_seconds: float = 0.0
    stats: dict[str, Any] = field(default_factory=dict)
    # Datenvertrag (Regel 13): Route, Wortgetreue, Zeitquelle, Erkennung (``choose_route``).
    route: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------------------------
# Reine Funktionen (ohne Modell testbar)
# ---------------------------------------------------------------------------------------------
def plan_windows(duration_s: float, window_s: float = 600.0, overlap_s: float = 20.0) -> list[tuple[float, float]]:
    """Fensterplan [(start, end), ...]. Letztes Fenster endet bei ``duration_s``."""
    if duration_s <= 0:
        return [(0.0, 0.0)]
    if window_s <= overlap_s:
        raise ValueError("window_s muss größer als overlap_s sein")
    if duration_s <= window_s:
        return [(0.0, float(duration_s))]
    out, start = [], 0.0
    while True:
        end = min(start + window_s, duration_s)
        out.append((round(start, 3), round(end, 3)))
        if end >= duration_s:
            break
        start = end - overlap_s
    return out


def _mid(w: dict) -> float:
    return (float(w["start"]) + float(w["end"])) / 2.0


def _best_cut(words_a: list[dict], lo: float, hi: float) -> float:
    """Schnittpunkt im Überlappungsbereich [lo, hi]: Mitte der längsten Pause, sonst Mitte des Bereichs."""
    best_gap, best_t = -1.0, (lo + hi) / 2.0
    inside = [w for w in words_a if lo <= _mid(w) <= hi]
    for a, b in zip(inside, inside[1:]):
        gap = float(b["start"]) - float(a["end"])
        if gap > best_gap:
            best_gap, best_t = gap, (float(a["end"]) + float(b["start"])) / 2.0
    return best_t


def merge_windows(results: list[tuple[float, float, list[dict]]]) -> list[dict]:
    """Führt Fensterergebnisse ``[(win_start, win_end, words_absolute), ...]`` zusammen.

    Im Überlappungsbereich zweier Fenster wird an der längsten Pause des ersten Fensters geschnitten:
    Wörter des ersten Fensters mit Mitte vor dem Schnitt bleiben, Wörter des zweiten Fensters mit Mitte
    danach kommen dazu. Zeitlich stark überlappende Dubletten an der Naht werden verworfen.
    Deterministisch, keine Modellabhängigkeit.
    """
    if not results:
        return []
    results = sorted(results, key=lambda r: r[0])
    merged: list[dict] = list(results[0][2])
    prev_end = results[0][1]
    for win_start, win_end, words in results[1:]:
        if win_start >= prev_end:
            merged.extend(words)
            prev_end = win_end
            continue
        cut = _best_cut(merged, win_start, prev_end)
        merged = [w for w in merged if _mid(w) < cut]
        incoming = [w for w in words if _mid(w) >= cut]
        if merged and incoming:
            last = merged[-1]
            while incoming and _overlap_ratio(last, incoming[0]) > 0.5:
                incoming.pop(0)
        merged.extend(incoming)
        prev_end = win_end
    return merged


def _overlap_ratio(a: dict, b: dict) -> float:
    inter = max(0.0, min(float(a["end"]), float(b["end"])) - max(float(a["start"]), float(b["start"])))
    shorter = max(1e-6, min(float(a["end"]) - float(a["start"]), float(b["end"]) - float(b["start"])))
    return inter / shorter


def _edit_distance_le1(a: str, b: str) -> bool:
    """True, wenn sich a und b um höchstens eine Einfügung, Löschung oder Ersetzung unterscheiden."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(1 for x, y in zip(a, b) if x != y) <= 1
    if len(a) > len(b):
        a, b = b, a
    i = j = 0
    skipped = False
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            i += 1
            j += 1
        elif skipped:
            return False
        else:
            skipped = True
            j += 1
    return True


FUZZY_MIN_LEN = 6


def apply_brand_vocab(words: list[dict], vocab: list[str]) -> list[dict]:
    """Nachkorrektur auf Markenschreibweise: exakt (case-insensitiv, ohne Sonderzeichen) oder konservativ
    fuzzy (ein Tippfehler, gleicher Wortanfang, nur für Vokabeln ab 6 Zeichen)."""
    lookup = {re.sub(r"\W", "", v.lower()): v for v in vocab if v and v.strip()}
    if not lookup:
        return words
    fuzzy = [(k, v) for k, v in lookup.items() if len(k) >= FUZZY_MIN_LEN]
    for w in words:
        raw = str(w["text"])
        key = re.sub(r"\W", "", raw.lower())
        if not key:
            continue
        hit = lookup.get(key)
        if hit is None and len(key) >= FUZZY_MIN_LEN:
            for k, v in fuzzy:
                if k[:3] == key[:3] and _edit_distance_le1(k, key):
                    hit = v
                    break
        if hit is not None:
            trailing = re.findall(r"[.,!?;:]+$", raw)
            w["text"] = hit + (trailing[0] if trailing else "")
    return words


def normalize_numbers(words: list[dict]) -> list[dict]:
    """Dezimalkomma und Prozentzeichen; NUR nach dem Alignment aufrufen (ändert keine Zeiten)."""
    for w in words:
        w["text"] = dach_nlp.de_number(str(w["text"]))
    return words


def assign_speakers(
    words: list[dict],
    turns: list[tuple[float, float, str]],
    overlap_turns: list[tuple[float, float, str]] | None = None,
    min_ratio: float = SPEAKER_DEFAULTS["overlap_min_ratio"],
) -> list[dict]:
    """Sprecher pro Wort per Mehrheit über die Wortdauer. ``turns``: [(start, end, speaker), ...].

    Ein Wort bekommt den Sprecher, dessen Turns die größte Überlappung mit [start, end] haben.
    Ohne Überlappung: nächstgelegener Turn. Ohne Turns: ``speaker`` bleibt None.

    ``overlap_turns`` (Lane P1): die nicht exklusive Sprecherstruktur (pyannote ``speaker_diarization`` oder
    Spurenergie). Decken darin mindestens zwei Sprecher je mindestens ``min_ratio`` der Wortdauer ab
    (``speakers.overlap.min_ratio_for_flag``), bekommt das Wort ``overlap: true`` und ``speakers`` (nach Anteil,
    der Mehrheitssprecher aus ``turns`` bleibt in ``speaker``). Ohne ``overlap_turns`` wie vor Lane P1."""
    if not turns:
        return words
    turns = sorted(turns, key=lambda t: (t[0], t[1]))
    j = 0
    for w in words:
        ws, we = float(w["start"]), float(w["end"])
        if we <= ws:
            we = ws + 1e-3
        while j < len(turns) - 1 and turns[j][1] < ws:
            j += 1
        share: dict[str, float] = {}
        k = j
        while k < len(turns) and turns[k][0] < we:
            ts, te, spk = turns[k]
            inter = max(0.0, min(we, te) - max(ws, ts))
            if inter > 0:
                share[spk] = share.get(spk, 0.0) + inter
            k += 1
        if share:
            w["speaker"] = max(share.items(), key=lambda kv: (kv[1], kv[0]))[0]
        else:
            w["speaker"] = _nearest(turns, (ws + we) / 2)
    if overlap_turns is not None:
        _mark_overlap(words, overlap_turns, min_ratio)
    return words


def _mark_overlap(words: list[dict], overlap_turns: list[tuple[float, float, str]], min_ratio: float) -> None:
    ordered = sorted(overlap_turns, key=lambda t: (t[0], t[1]))
    for w in words:
        ws, we = float(w["start"]), float(w["end"])
        dur = max(we - ws, 1e-3)
        cover: dict[str, float] = {}
        for ts, te, spk in ordered:
            if ts >= we:
                break
            inter = max(0.0, min(we, te) - max(ws, ts))
            if inter > 0:
                cover[spk] = cover.get(spk, 0.0) + inter
        active = sorted((s for s, c in cover.items() if c / dur >= min_ratio), key=lambda s: (-cover[s], s))
        w["overlap"] = len(active) >= 2
        if w["overlap"]:
            w["speakers"] = active
        else:
            w.pop("speakers", None)


def overlap_ratio(words: list[dict]) -> float | None:
    """Anteil der Wörter mit ``overlap: true``; ``None``, wenn kein Wort eine Überlappungsangabe trägt."""
    marked = [w for w in words if "overlap" in w]
    if not marked:
        return None
    return round(sum(1 for w in marked if w["overlap"]) / len(words), 4)


def _nearest(turns: list[tuple[float, float, str]], t: float) -> str:
    return min(turns, key=lambda x: min(abs(x[0] - t), abs(x[1] - t)))[2]


def confidence_stats(words: list[dict], threshold: float = LOW_CONF_THRESHOLD) -> dict[str, Any]:
    n = len(words)
    if n == 0:
        return {"word_count": 0, "mean_prob": 0.0, "low_conf_ratio": 0.0, "low_conf_count": 0, "speakers": []}
    probs = [float(w.get("prob", 1.0)) for w in words]
    low = sum(1 for p in probs if p < threshold)
    speakers = sorted({w["speaker"] for w in words if w.get("speaker")})
    return {
        "word_count": n,
        "mean_prob": round(sum(probs) / n, 4),
        "low_conf_ratio": round(low / n, 4),
        "low_conf_count": low,
        "speakers": speakers,
    }


def to_json(words: list[Word]) -> list[dict]:
    return [w.to_dict() for w in words]


# ---------------------------------------------------------------------------------------------
# Lane P1: Policy-Werte, Hotwords, Routing, Spurenergie (reine Funktionen)
# ---------------------------------------------------------------------------------------------
def _policy_section(policy: Any, name: str) -> dict | None:
    if policy is None:
        from .. import editorial

        policy = editorial.load()
    if getattr(policy, "version", 1) < 2:
        return None
    raw = policy.roh.get(name)
    return raw if isinstance(raw, dict) else None


def _num(value: Any, path: str, lo: float, hi: float) -> float:
    from ..editorial import PolicyError

    if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= float(value) <= hi:
        raise PolicyError(f"{path} liegt nicht zwischen {lo} und {hi}: {value!r}")
    return float(value)


def _flag(value: Any, path: str) -> bool:
    from ..editorial import PolicyError

    if not isinstance(value, bool):
        raise PolicyError(f"{path} ist true oder false, nicht {value!r}")
    return value


def asr_settings(policy: Any = None) -> dict[str, Any]:
    """ASR-Regeln der aktiven Fassung: ``asr.routing.enabled``, ``asr.routing.min_confidence``,
    ``asr.hotwords.max_terms``, ``asr.hotwords.decode``, ``asr.ch_route.beta``. Fassung 1 hat keinen Abschnitt
    ``asr``; dann gelten ``ASR_DEFAULTS``. Ein unbrauchbarer Wert scheitert laut (``PolicyError``)."""
    raw = _policy_section(policy, "asr")
    if raw is None:
        return dict(ASR_DEFAULTS)
    try:
        routing, hotwords, ch_route = raw["routing"], raw["hotwords"], raw["ch_route"]
        max_terms = hotwords["max_terms"]
        if isinstance(max_terms, bool) or not isinstance(max_terms, int) or not 0 <= max_terms <= 200:
            from ..editorial import PolicyError

            raise PolicyError(f"asr.hotwords.max_terms ist eine ganze Zahl von 0 bis 200, nicht {max_terms!r}")
        return {
            "routing_enabled": _flag(routing["enabled"], "asr.routing.enabled"),
            "min_confidence": _num(routing["min_confidence"], "asr.routing.min_confidence", 0.0, 1.0),
            "max_terms": max_terms,
            "decode": _flag(hotwords["decode"], "asr.hotwords.decode"),
            "ch_beta": _flag(ch_route["beta"], "asr.ch_route.beta"),
        }
    except (KeyError, TypeError):
        from ..editorial import PolicyError

        raise PolicyError("asr braucht routing.enabled, routing.min_confidence, hotwords.max_terms, hotwords.decode, ch_route.beta") from None


def speaker_settings(policy: Any = None) -> dict[str, Any]:
    """Sprecher-Regeln der aktiven Fassung: ``speakers.overlap.min_ratio_for_flag``,
    ``speakers.multitrack.energy_window_s``, ``speakers.multitrack.overlap_db``, ``speakers.multitrack.silence_dbfs``.
    Fassung 1 hat keinen Abschnitt ``speakers``; dann gelten ``SPEAKER_DEFAULTS``."""
    raw = _policy_section(policy, "speakers")
    if raw is None:
        return dict(SPEAKER_DEFAULTS)
    try:
        overlap, multitrack = raw["overlap"], raw["multitrack"]
        return {
            "overlap_min_ratio": _num(overlap["min_ratio_for_flag"], "speakers.overlap.min_ratio_for_flag", 0.01, 1.0),
            "energy_window_s": _num(multitrack["energy_window_s"], "speakers.multitrack.energy_window_s", 0.01, 2.0),
            "overlap_db": _num(multitrack["overlap_db"], "speakers.multitrack.overlap_db", 0.0, 60.0),
            "silence_dbfs": _num(multitrack["silence_dbfs"], "speakers.multitrack.silence_dbfs", -120.0, 0.0),
        }
    except (KeyError, TypeError):
        from ..editorial import PolicyError

        raise PolicyError("speakers braucht overlap.min_ratio_for_flag und multitrack.energy_window_s, overlap_db, silence_dbfs") from None


def build_hotwords(
    brand_vocab: list[str] | None,
    protected_terms: list[str] | None = None,
    extra: tuple[str, ...] | list[str] = (),
    max_terms: int = ASR_DEFAULTS["max_terms"],
    max_chars: int = HOTWORDS_MAX_CHARS,
) -> str | None:
    """Hotword-Zeile für faster-whisper: Marken-Wörterbuch, dann geschützte Begriffe, dann ``extra``
    (Austriazismen), ohne Dubletten (Groß- und Kleinschreibung egal, erste Schreibweise gewinnt), höchstens
    ``max_terms`` Begriffe und ``max_chars`` Zeichen (faster-whisper kürzt sonst still auf 223 Token).
    Die Reihenfolge ist die Priorität: was zuerst kommt, wird nie gekürzt. ``None`` ohne Begriff."""
    out: list[str] = []
    seen: set[str] = set()
    length = 0
    for term in [*(brand_vocab or []), *(protected_terms or []), *extra]:
        t = " ".join(str(term or "").split())
        key = t.casefold()
        if not t or key in seen:
            continue
        if len(out) >= max_terms or length + len(t) + (1 if out else 0) > max_chars:
            break
        seen.add(key)
        out.append(t)
        length += len(t) + (1 if len(out) > 1 else 0)
    return " ".join(out) or None


def sample_spans(duration_s: float) -> list[tuple[float, float]]:
    """Stichprobe für die Spracherkennung: erste ``SAMPLE_HEAD_S`` und ``SAMPLE_MID_S`` um die Mitte."""
    if duration_s <= 0:
        return []
    head = (0.0, round(min(SAMPLE_HEAD_S, duration_s), 3))
    if duration_s <= SAMPLE_HEAD_S + SAMPLE_MID_S:
        return [head]
    mid = duration_s / 2.0
    return [head, (round(mid - SAMPLE_MID_S / 2, 3), round(mid + SAMPLE_MID_S / 2, 3))]


def classify_variant(lang_probs: dict[str, float], sample_words: list[dict], min_confidence: float) -> dict[str, Any]:
    """Sprache und Variante aus Spracherkennung und Lexikon-Markern (``dach_nlp.detect_dialect``).

    ``detected_variant`` ist ``de``, ``de-AT``, ``de-CH`` oder ``unklar``: ``unklar``, wenn Deutsch nicht
    die erkannte Sprache ist oder ihre Wahrscheinlichkeit unter ``min_confidence`` liegt, und wenn Marker
    einer Variante gefunden werden, deren Sicherheit unter ``min_confidence`` bleibt. Ohne Marker heißt
    ``de`` nur: kein Hinweis auf AT oder CH (ein Lexikon findet nur, was drinsteht)."""
    language = max(lang_probs, key=lambda k: (lang_probs[k], k)) if lang_probs else "unknown"
    de_prob = round(float(lang_probs.get("de", 0.0)), 4)
    dialect = dach_nlp.detect_dialect(sample_words)
    variant, confidence = "unklar", de_prob
    if language == "de" and de_prob >= min_confidence:
        if dialect["variant"] == "de":
            variant = "de"
        else:
            confidence = round(min(de_prob, float(dialect["confidence"])), 4)
            variant = dialect["variant"] if confidence >= min_confidence else "unklar"
    return {
        "detected_language": language,
        "language_probability": round(float(lang_probs.get(language, 0.0)), 4),
        "detected_variant": variant,
        "confidence": confidence,
        "markers": dialect["markers"],
        "sample_words": len(sample_words),
    }


def choose_route(
    profile_variant: str,
    detection: dict[str, Any] | None,
    s: config.Settings,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Route der Transkription (Datenvertrag Regel 13). Ohne ``detection`` gilt das Markenprofil (``profile``).

    Mit Erkennung: ``de-CH`` mit ``ASR_MODEL_CH`` ergibt die CH-Route (Beta, nicht wortgetreu), ohne CH-Modell
    das DE-Modell mit Hinweis ``ch_detected_no_model``; ``de-AT`` das DE-Modell mit Austriazismen; ``de`` das
    DE-Modell, auch gegen ein Profil ``de-CH``; ``unklar`` lässt das Profil stehen. Eine andere Sprache
    bricht nichts ab, sie steht als Hinweis ``non_german_detected`` in der Route."""
    cfg = cfg or ASR_DEFAULTS
    hints: list[str] = []
    variant, reason, austriacisms = profile_variant, "profile", False
    if detection is not None:
        detected = detection["detected_variant"]
        if detected == "de-CH":
            if s.asr_model_ch:
                variant, reason = "de-CH", "detected_ch"
            else:
                variant, reason = "de", HINT_CH_NO_MODEL
                hints.append(HINT_CH_NO_MODEL)
        elif detected == "de-AT":
            variant, reason, austriacisms = "de", "detected_at", True
        elif detected == "de":
            variant, reason = "de", "detected_de"
        else:
            reason = "unsure_profile_kept"
            if detection["detected_language"] != "de" and detection["language_probability"] >= cfg["min_confidence"]:
                hints.append(HINT_NON_GERMAN)
        hints.extend(h for h in detection.get("hints", []) if h not in hints)
    ch = variant == "de-CH"
    return {
        "variant": variant,
        "model_id": s.asr_model_for(variant),
        # CH-Modelle wie Flix übertragen laut Modellkarte in Standarddeutsch (Review 4A); ohne eigene Messung
        # gilt jede CH-Route als nicht wortgetreu, Whisper-DE als wortgetreu.
        "verbatim": not ch,
        "time_source": TIME_SOURCE_ASR,
        "beta": bool(ch and cfg["ch_beta"]),
        "detected_language": detection["detected_language"] if detection else None,
        "detected_variant": detection["detected_variant"] if detection else None,
        "detection_confidence": detection["confidence"] if detection else None,
        "routing_reason": reason,
        "austriacisms": austriacisms,
        "hints": hints,
    }


def default_route(variant: str, model_id: str, beta: bool, provider: str = "selfhost-eu") -> dict[str, Any]:
    """Route für ein Ergebnis ohne gespeicherte Route (ASR-JSON vor Lane P1, Gladia): Profil, keine Erkennung."""
    return {
        "variant": variant,
        "model_id": model_id,
        "verbatim": variant != "de-CH",
        "time_source": TIME_SOURCE_ASR,
        "beta": bool(beta),
        "detected_language": None,
        "detected_variant": None,
        "detection_confidence": None,
        "routing_reason": "profile" if provider != "gladia-eu" else "fallback_gladia",
        "austriacisms": False,
        "hints": [],
    }


def energy_diarization(
    tracks: list[Any],
    sr: int,
    window_s: float = SPEAKER_DEFAULTS["energy_window_s"],
    overlap_db: float = SPEAKER_DEFAULTS["overlap_db"],
    silence_dbfs: float = SPEAKER_DEFAULTS["silence_dbfs"],
) -> dict[str, Any]:
    """Sprecherzuordnung aus getrennten Mikrofonspuren, ohne Modell und deterministisch.

    Je Fenster von ``window_s`` gewinnt die Spur mit der höchsten RMS (``turns``, exklusiv). Aktiv sind alle
    Spuren über ``silence_dbfs``, die höchstens ``overlap_db`` unter der lautesten liegen (``overlap_turns``);
    zwei aktive Spuren sind Überlappung, eine leisere Spur weiter unten ist Übersprechen. Fenster, in denen
    keine Spur über ``silence_dbfs`` liegt, bleiben ohne Sprecher. Spur ``i`` heißt ``SPEAKER_{i:02d}``.
    Die Spuren müssen dieselbe Zeitbasis haben (gleicher Container, ``ingest.audio_streams``)."""
    import numpy as np

    if not tracks:
        return {"turns": [], "overlap_turns": [], "speakers": [], "model_id": DIARIZER_MULTITRACK, "overlap_windows": 0, "windows": 0}
    hop = max(1, int(round(window_s * sr)))
    n = min(len(t) for t in tracks)
    count = n // hop
    labels = [f"SPEAKER_{i:02d}" for i in range(len(tracks))]
    levels = np.full((len(tracks), count), -200.0)
    for i, t in enumerate(tracks):
        x = np.asarray(t[: count * hop], dtype=np.float64).reshape(count, hop) if count else np.zeros((0, hop))
        rms = np.sqrt((x**2).mean(axis=1)) if count else np.zeros(0)
        levels[i] = 20.0 * np.log10(np.maximum(rms, 1e-10))
    excl: list[list[Any]] = []
    multi: dict[int, list[list[Any]]] = {i: [] for i in range(len(tracks))}
    overlap_windows = 0

    def extend(seq: list[list[Any]], a: float, b: float, label: str) -> None:
        if seq and seq[-1][2] == label and abs(seq[-1][1] - a) < 1e-9:
            seq[-1][1] = b
        else:
            seq.append([a, b, label])

    for k in range(count):
        col = levels[:, k]
        top = int(np.argmax(col))
        if col[top] < silence_dbfs:
            continue
        a, b = round(k * hop / sr, 3), round((k + 1) * hop / sr, 3)
        extend(excl, a, b, labels[top])
        active = [i for i in range(len(tracks)) if col[i] >= silence_dbfs and col[i] >= col[top] - overlap_db]
        if len(active) >= 2:
            overlap_windows += 1
        for i in active:
            extend(multi[i], a, b, labels[i])
    overlap_turns = sorted((t for seq in multi.values() for t in seq), key=lambda t: (t[0], t[1], t[2]))
    return {
        "turns": excl,
        "overlap_turns": overlap_turns,
        "speakers": sorted({t[2] for t in excl}),
        "model_id": DIARIZER_MULTITRACK,
        "overlap_windows": overlap_windows,
        "windows": count,
    }


# ---------------------------------------------------------------------------------------------
# Modellgestützte Funktionen (lazy imports)
# ---------------------------------------------------------------------------------------------
def _device(s: config.Settings) -> tuple[str, str]:
    device, compute = s.asr_device or "auto", s.asr_compute or "int8"
    if device == "auto":
        try:
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"
    if device == "cpu" and compute in {"int8_float16", "float16"}:
        compute = "int8"
    return device, compute


_MODEL_CACHE: dict[tuple[str, str, str], Any] = {}


def load_model(model_id: str, s: config.Settings | None = None):
    """faster-whisper-Modell (gecacht pro Prozess)."""
    s = s or config.settings()
    device, compute = _device(s)
    key = (model_id, device, compute)
    if key not in _MODEL_CACHE:
        from faster_whisper import WhisperModel

        _MODEL_CACHE[key] = WhisperModel(model_id, device=device, compute_type=compute)
    return _MODEL_CACHE[key]


def _read_wav(audio_path: str):
    import wave

    import numpy as np

    with wave.open(audio_path, "rb") as wf:
        sr = wf.getframerate()
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            raise TranscribeError("Audio muss 16-bit Mono PCM sein (siehe ingest.extract_audio)")
        x = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    return sr, x


def transcribe_window(model, audio, sr: int, start: float, end: float, hotwords: str | None) -> list[dict]:
    """Ein Fenster transkribieren; Wortzeiten absolut (um ``start`` verschoben)."""
    a, b = int(start * sr), int(end * sr)
    chunk = audio[a:b]
    if len(chunk) == 0:
        return []
    segments, _info = model.transcribe(
        chunk,
        language="de",
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
        hotwords=hotwords or None,
        condition_on_previous_text=False,
    )
    out: list[dict] = []
    for seg in segments:
        for w in seg.words or []:
            text = str(w.word).strip()
            if not text:
                continue
            out.append(
                Word(text, round(float(w.start) + start, 3), round(float(w.end) + start, 3), float(w.probability)).to_dict()
            )
    return out


def detect_variant(model, audio, sr: int, duration_s: float, min_confidence: float) -> dict[str, Any]:
    """Spracherkennung auf der Stichprobe (``sample_spans``): ``model.detect_language`` je Abschnitt, gewichtet
    nach Dauer, und ein schnelles Vorab-Transkript derselben Abschnitte (ohne Hotwords) für die Lexikon-Marker.
    Ergebnis wie ``classify_variant`` plus ``samples``."""
    spans = sample_spans(duration_s)
    acc: dict[str, float] = {}
    total = 0.0
    words: list[dict] = []
    for a, b in spans:
        chunk = audio[int(a * sr) : int(b * sr)]
        if len(chunk) == 0:
            continue
        _lang, _prob, all_probs = model.detect_language(chunk)
        for lang, prob in all_probs:
            acc[lang] = acc.get(lang, 0.0) + float(prob) * (b - a)
        total += b - a
        words.extend(transcribe_window(model, audio, sr, a, b, None))
    probs = {k: v / total for k, v in acc.items()} if total else {}
    out = classify_variant(probs, words, min_confidence)
    out["samples"] = [[a, b] for a, b in spans]
    return out


def transcribe(
    audio_path: str,
    variant: str = "de",
    brand_vocab: list[str] | None = None,
    s: config.Settings | None = None,
    fallback: str | None = None,
    duration_s: float | None = None,
    protected_terms: list[str] | None = None,
    auto_route: bool | None = None,
) -> TranscriptResult:
    """Routing: ``de`` | ``de-CH`` (Beta) | ``fallback="gladia-eu"``.

    ``auto_route`` (Standard ``ASR_AUTO_ROUTE``) prüft vor der Transkription die tatsächliche Sprache
    (``detect_variant``, ``choose_route``); das Profil ``variant`` bleibt Vorgabe, bis die Erkennung sicher
    ist (``asr.routing.min_confidence``). Hotwords gehen nur mit ``asr.hotwords.decode`` in den Decoder
    (Notiz 010); das Marken-Wörterbuch wirkt immer als Nachkorrektur."""
    s = s or config.settings()
    brand_vocab = [v for v in (brand_vocab or []) if v]
    if variant not in VARIANTS:
        raise TranscribeError(f"Unbekannte ASR-Variante {variant!r} (erlaubt: {', '.join(VARIANTS)})")
    if fallback == "gladia-eu":
        return _transcribe_gladia(audio_path, brand_vocab, s)
    if fallback:
        raise TranscribeError(f"Unbekannter ASR-Fallback {fallback!r}")

    auto = s.asr_auto_route if auto_route is None else bool(auto_route)
    cfg = asr_settings() if auto else dict(ASR_DEFAULTS)
    t0 = time.monotonic()
    detection = None
    audio = sr = None
    if auto and cfg["routing_enabled"]:
        if s.asr_model_de:
            sr, audio = _read_wav(audio_path)
            total = duration_s if duration_s is not None else len(audio) / float(sr)
            detection = detect_variant(load_model(s.asr_model_de, s), audio, sr, total, cfg["min_confidence"])
        else:
            detection = {"detected_language": None, "language_probability": 0.0, "detected_variant": "unklar",
                         "confidence": 0.0, "markers": [], "sample_words": 0, "hints": [HINT_NO_DETECTION_MODEL]}  # fmt: skip
    route = choose_route(variant, detection, s, cfg)
    if detection is not None:
        route["detection"] = {k: v for k, v in detection.items() if k != "hints"}
    model_id = route["model_id"]
    if not model_id:
        env = "ASR_MODEL_CH" if route["variant"] == "de-CH" else "ASR_MODEL_DE"
        raise TranscribeError(f"Kein ASR-Modell für Variante {route['variant']} konfiguriert ({env} setzen)")

    model = load_model(model_id, s)
    if audio is None:
        sr, audio = _read_wav(audio_path)
    total = duration_s if duration_s is not None else len(audio) / float(sr)
    windows = plan_windows(total, s.asr_window_s, s.asr_overlap_s)
    extra = AUSTRIACISMS if route["austriacisms"] else ()
    terms = build_hotwords(brand_vocab, protected_terms if auto else None, extra, cfg["max_terms"])
    hotwords = terms if cfg["decode"] else None
    route["hotwords"] = {"terms": len(terms.split()) if terms else 0, "decode": bool(cfg["decode"] and terms)}
    results = []
    for ws, we in windows:
        results.append((ws, we, transcribe_window(model, audio, sr, ws, we, hotwords)))
        log.info("asr window %.0f..%.0f done (%d words)", ws, we, len(results[-1][2]))
    words = merge_windows(results)
    words = apply_brand_vocab(words, brand_vocab)
    stats = confidence_stats(words)
    if route["hints"]:
        stats["route_hints"] = list(route["hints"])
    return TranscriptResult(
        words=words,
        model_id=model_id,
        variant=route["variant"],
        provider="selfhost-eu",
        beta=route["beta"],
        windows=len(windows),
        duration_s=round(total, 3),
        compute_seconds=round(time.monotonic() - t0, 3),
        stats=stats,
        route=route,
    )


def _transcribe_gladia(audio_path: str, brand_vocab: list[str], s: config.Settings) -> TranscriptResult:
    """Fallback über Gladia (EU-Endpoint). Nur mit GLADIA_BASE_URL und erlaubtem Host.

    TODO: Antwortformat gegen die aktuelle Gladia-API prüfen (Upload, pre-recorded, Polling)."""
    if not s.gladia_base_url:
        raise TranscribeError(
            "Fallback gladia-eu ist nicht freigeschaltet: GLADIA_BASE_URL fehlt. "
            "Fallback muss pro Workspace freigegeben und der Host per Residency-Allowlist erlaubt sein."
        )
    residency.assert_eu_host(s.gladia_base_url, s)
    if not s.gladia_api_key:
        raise TranscribeError("GLADIA_API_KEY fehlt")
    base = s.gladia_base_url.rstrip("/")
    headers = {"x-gladia-key": s.gladia_api_key}
    t0 = time.monotonic()
    with residency.guarded_client(s, timeout=600) as client:
        with open(audio_path, "rb") as f:
            up = client.post(f"{base}/v2/upload", headers=headers, files={"audio": ("audio.wav", f, "audio/wav")})
        up.raise_for_status()
        audio_url = up.json().get("audio_url")
        body = {
            "audio_url": audio_url,
            "language": "de",
            "diarization": False,
            "custom_vocabulary": brand_vocab or None,
        }
        job = client.post(f"{base}/v2/pre-recorded", headers=headers, json=body)
        job.raise_for_status()
        result_url = job.json().get("result_url")
        if not result_url:
            raise TranscribeError("Gladia: keine result_url erhalten")
        residency.assert_eu_host(result_url, s)
        data = None
        for _ in range(720):
            r = client.get(result_url, headers=headers)
            r.raise_for_status()
            data = r.json()
            if data.get("status") in {"done", "error"}:
                break
            time.sleep(5)
    if not data or data.get("status") != "done":
        raise TranscribeError("Gladia: Transkription nicht abgeschlossen")
    words: list[dict] = []
    for utt in data.get("result", {}).get("transcription", {}).get("utterances", []):
        for w in utt.get("words", []):
            words.append(Word(str(w.get("word", "")).strip(), float(w["start"]), float(w["end"]), float(w.get("confidence", 1.0))).to_dict())
    words = apply_brand_vocab(words, brand_vocab)
    return TranscriptResult(
        words=words,
        model_id="gladia",
        variant="de",
        provider="gladia-eu",
        beta=False,
        windows=1,
        duration_s=float(words[-1]["end"]) if words else 0.0,
        compute_seconds=round(time.monotonic() - t0, 3),
        stats=confidence_stats(words),
        route=default_route("de", "gladia", False, provider="gladia-eu"),
    )


def model_hint(model_id: str) -> str | None:
    """Hinweis für das Event, wenn die konfigurierte Modell-ID kein deutscher Fine-Tune ist (Name ohne „german“)."""
    return None if "german" in (model_id or "").lower() else HINT_GENERIC_WHISPER


def wav_duration_s(audio_path: str) -> float:
    import wave

    with wave.open(audio_path, "rb") as wf:
        return round(wf.getnframes() / float(wf.getframerate() or 16000), 3)


_DIARIZER_CACHE: dict[str, Any] = {}


def diarization_availability(s: config.Settings | None = None) -> tuple[bool, str | None]:
    """(verfügbar, Hinweis). Ohne ``HF_TOKEN`` oder ohne installiertes ``pyannote.audio`` läuft der Fallback."""
    import importlib.util

    s = s or config.settings()
    if not s.hf_token:
        return False, HINT_DIARIZATION_SKIPPED
    if importlib.util.find_spec("pyannote") is None or importlib.util.find_spec("pyannote.audio") is None:
        return False, HINT_PYANNOTE_MISSING
    return True, None


def diarizer_id(s: config.Settings | None = None) -> str:
    """Modell-ID für Storage-Keys: konfiguriertes Modell oder ``none`` im Fallback (neuer Key, sobald pyannote da ist)."""
    s = s or config.settings()
    available, _ = diarization_availability(s)
    return (s.diarizer_model or _DEFAULT_DIARIZER) if available else DIARIZER_NONE


def fallback_diarization(duration_s: float, reason: str) -> dict[str, Any]:
    """Ein Sprecher ``SPEAKER_00`` über die ganze Datei; ``skipped = True`` und ``hint`` für das Event."""
    return {
        "turns": [[0.0, round(float(duration_s), 3), FALLBACK_SPEAKER]] if duration_s > 0 else [],
        "model_id": DIARIZER_NONE,
        "speakers": [FALLBACK_SPEAKER],
        "compute_seconds": 0.0,
        "skipped": True,
        "hint": reason,
    }


def load_diarizer(s: config.Settings | None = None):
    s = s or config.settings()
    model_id = s.diarizer_model or _DEFAULT_DIARIZER
    if model_id not in _DIARIZER_CACHE:
        import torch
        from pyannote.audio import Pipeline

        if not s.hf_token:
            raise TranscribeError("HF_TOKEN fehlt (Nutzungsbedingungen des pyannote-Modells akzeptieren)")
        pipe = Pipeline.from_pretrained(model_id, token=s.hf_token)
        if pipe is None:
            raise TranscribeError(f"Diarisierungsmodell {model_id} konnte nicht geladen werden")
        if torch.cuda.is_available():
            pipe.to(torch.device("cuda"))
        _DIARIZER_CACHE[model_id] = pipe
    return _DIARIZER_CACHE[model_id]


def diarize(
    audio_path: str,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
    s: config.Settings | None = None,
) -> dict[str, Any]:
    """Liefert ``{"turns": [[start, end, speaker], ...], "model_id": ..., "compute_seconds": ...}``.

    DSGVO: anonyme Labels (SPEAKER_00 ...), keine projektübergreifende Stimm-Wiedererkennung.
    Ohne ``HF_TOKEN`` oder ohne ``pyannote.audio``: kein Fehler, sondern ``fallback_diarization``
    (ein Sprecher, ``skipped = True``, ``hint`` mit dem Grund)."""
    s = s or config.settings()
    available, reason = diarization_availability(s)
    if not available:
        log.info("diarization skipped reason=%s", reason)
        return fallback_diarization(wav_duration_s(audio_path), reason or HINT_DIARIZATION_SKIPPED)
    t0 = time.monotonic()
    pipe = load_diarizer(s)
    kwargs = {}
    if min_speakers:
        kwargs["min_speakers"] = int(min_speakers)
    if max_speakers:
        kwargs["max_speakers"] = int(max_speakers)
    out = pipe(audio_path, **kwargs)
    annotation = getattr(out, "exclusive_speaker_diarization", None)
    if annotation is None:  # ältere pyannote-Versionen liefern die Annotation direkt
        annotation = getattr(out, "speaker_diarization", out)
    # Review 4B: die reguläre Annotation kann Überlappung darstellen, die exklusive nicht. Beide bleiben:
    # ``turns`` (exklusiv) für Anzeige und Mehrheit je Wort, ``overlap_turns`` für ``overlap`` je Wort.
    regular = getattr(out, "speaker_diarization", out)
    turns = _annotation_turns(annotation)
    return {
        "turns": turns,
        "overlap_turns": _annotation_turns(regular),
        "model_id": s.diarizer_model or _DEFAULT_DIARIZER,
        "speakers": sorted({t[2] for t in turns}),
        "compute_seconds": round(time.monotonic() - t0, 3),
    }


def _annotation_turns(annotation) -> list[list[Any]]:
    turns = [[round(float(seg.start), 3), round(float(seg.end), 3), str(spk)] for seg, _track, spk in annotation.itertracks(yield_label=True)]
    turns.sort(key=lambda t: (t[0], t[1], t[2]))
    return turns


def multitrack_diarization(track_paths: list[str], cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """``energy_diarization`` über 16-kHz-Mono-WAVs je Spur (``ingest.extract_track``); Dokument wie ``diarize``
    plus ``source = multitrack_energy``, ``tracks`` und ``overlap_turns``. Ohne pyannote lauffähig."""
    cfg = cfg or SPEAKER_DEFAULTS
    t0 = time.monotonic()
    loaded = [_read_wav(p) for p in track_paths]
    rates = {sr for sr, _x in loaded}
    if len(rates) != 1:
        raise TranscribeError(f"Mehrspur mit verschiedenen Abtastraten {sorted(rates)}; erwartet eine gemeinsame Zeitbasis")
    sr = rates.pop()
    res = energy_diarization([x for _sr, x in loaded], sr, cfg["energy_window_s"], cfg["overlap_db"], cfg["silence_dbfs"])
    res["tracks"] = len(track_paths)
    res["compute_seconds"] = round(time.monotonic() - t0, 3)
    res["skipped"] = False
    return res


__all__ = [
    "AUSTRIACISMS",
    "DIARIZER_MULTITRACK",
    "DIARIZER_NONE",
    "DETECTED_VARIANTS",
    "HINT_CH_NO_MODEL",
    "HINT_NON_GERMAN",
    "TIME_SOURCE_ASR",
    "asr_settings",
    "build_hotwords",
    "choose_route",
    "classify_variant",
    "default_route",
    "detect_variant",
    "energy_diarization",
    "multitrack_diarization",
    "overlap_ratio",
    "sample_spans",
    "speaker_settings",
    "FALLBACK_SPEAKER",
    "HINT_DIARIZATION_SKIPPED",
    "HINT_GENERIC_WHISPER",
    "HINT_PYANNOTE_MISSING",
    "LOW_CONF_THRESHOLD",
    "VARIANTS",
    "TranscribeError",
    "TranscriptResult",
    "Word",
    "apply_brand_vocab",
    "assign_speakers",
    "confidence_stats",
    "diarization_availability",
    "diarize",
    "diarizer_id",
    "fallback_diarization",
    "load_diarizer",
    "load_model",
    "merge_windows",
    "model_hint",
    "normalize_numbers",
    "plan_windows",
    "to_json",
    "transcribe",
    "transcribe_window",
    "wav_duration_s",
]
