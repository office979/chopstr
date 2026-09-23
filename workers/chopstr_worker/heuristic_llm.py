"""Heuristik-Provider ``local-heuristic``: bedient die Tool-Schemata der Story-Engine und der Copy ohne Netz.

Das ist KEIN Ersatz für ein Sprachmodell. Der Provider existiert, damit Entwicklung, Tests und Demos
ohne LLM-Zugang durch die ganze Kette laufen (Kandidaten entstehen, die UI hat Daten). Produktion
braucht einen echten EU-Provider (``bedrock-eu``, ``mistral-eu``, ``selfhost-eu``). Ergebnisse tragen
``model_id = "heuristic-v1"`` und ``risk_flags`` enthält ``heuristic_only``.

WOHER DIE REGELN KOMMEN: aus ``packages/editorial/clip_policy_v1.yaml`` über ``editorial.load()``.
Hier stehen keine redaktionellen Zahlen mehr. Längenfenster, Rubrik, Moment-Typen, Einstiegsregeln,
Ausstiegsregeln und der Ausschluss werden aus der Grundlage gelesen. Was hier bleibt, sind reine
Textmerkmale: Wortlisten, Satzzeichen, Zahlen, Sprecherwechsel. Sie sind die Näherung, mit der die
Heuristik die redaktionellen Fragen beantwortet, so gut das ohne Sprachmodell geht.

Der Provider liest nur den gerenderten Prompt (Zeilen ``[idx] (Sprecher) Text``). Zeiten kennt er
nicht; Längen werden aus der Wortzahl geschätzt (``WORDS_PER_SECOND``). Die harten Längen-Grenzen
prüft die Story-Engine anschließend mit den echten Wortzeiten.

MODUS SORTIEREN: ``bewertung.modus`` steht auf ``sortieren``. Kein Moment wird hier unterdrückt,
auch reines Organisationsgespräch nicht. Es bekommt nur eine sehr niedrige Bewertung.

Alles hier ist deterministisch: gleicher Prompt, gleiche Antwort.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import editorial
from .pipeline import dach_nlp
from .pipeline.signals import DISCOURSE_MARKERS
from .pipeline.story_graph import CONTRAST_MARKERS

MODEL_ID = "heuristic-v1"
WORDS_PER_SECOND = 2.5  # ruhiges Sprechtempo Deutsch, etwa 150 Wörter pro Minute
PROPOSE_MAX_MOMENTS = 3
EVIDENCE_WORDS = 8
HOOK_MAX_WORDS = 15  # „stoppt in drei Sekunden“ heisst in Textmerkmalen: kurzer erster Satz
NEUTRAL = 0.5  # Mittelwert für das, was die Heuristik ehrlicherweise nicht misst

_LINE = re.compile(r"^\[(\d+)\]\s+\(([^)]*)\)\s*(.*)$")
_NUMBER = re.compile(r"\d[\d.,]*")

CONTEXT_STARTS = (
    "und ", "aber ", "also ", "deshalb ", "deswegen ", "weil ", "dann ", "denn ", "sondern ", "trotzdem ",
    "wie gesagt", "das heißt ", "außerdem ", "dazu ", "darum ", "danach ", "davor ",
)  # fmt: skip
REFERENCE_PHRASES = (
    "wie gesagt", "wie vorhin", "wie erwähnt", "das von vorhin", "diese grafik", "dieses bild",
    "wie ihr seht", "wie sie sehen", "hier oben", "hier unten", "die folie",
)  # fmt: skip
SENSITIVE_TERMS = (
    "diagnose", "therapie", "medikament", "krankheit", "symptom", "heilung", "rendite", "aktie", "aktien",
    "investieren", "investment", "kredit", "steuern sparen", "anwalt", "klage", "gericht", "haftung",
)  # fmt: skip
CONTRAST_WORDS = re.compile(r"\b(aber|allerdings|jedoch|wobei|trotzdem)\b")

# -- Rubrik ----------------------------------------------------------------------------------------
# Die sieben Schlüssel stehen in der Grundlage (rubrik.kriterien). Diese Zuordnung übersetzt die
# alten fünf Schlüssel, an denen Bestandsdaten, RUBRIC_SCHEMA und die Web-App hängen, auf die neuen.
ALT_AUS_NEU = {
    "hook": "hook",
    "payoff": "aufloesung",
    "specificity": "spezifitaet",
    "tension": "offene_frage",
    "audience_fit": "zielgruppe",
}
ALT_SKALA_MAX = 10  # Skala der alten fünf Schlüssel (RUBRIC_SCHEMA: integer 0 bis 10)

# Welches Kriterium hebt ein Moment-Typ? Aus dem Feld ``hebel`` der Grundlage abgeleitet:
# contrarian „Kontrast, Erwartungsbruch“, zahl „Spezifität, Beweis“, ministory „Spannungsbogen“,
# gestaendnis „Verletzlichkeit“, merksatz „Nutzen, Speicherwert“, konflikt „Emotion“.
# ``konflikt`` steht nur der Vollständigkeit halber da: er trägt ``braucht_audio: true`` und kommt
# aus ``policy.typen_im_text()`` nie zurück.
TYP_WIRKT_AUF = {
    "contrarian": ("offene_frage", "emotion"),
    "zahl": ("spezifitaet",),
    "ministory": ("offene_frage",),
    "gestaendnis": ("emotion",),
    "merksatz": ("aufloesung",),
    "konflikt": ("emotion",),
}
TYP_BONUS_PRO_PUNKT = 0.12  # ein Bonus von 2,0 hebt den Anteil des Kriteriums um 0,24

# Ein Moment, der reine Logistik ist, soll ganz unten landen, aber sichtbar bleiben (modus: sortieren).
ORGANISATORISCH_FAKTOR = 0.15

# -- Emotion ---------------------------------------------------------------------------------------
# Näherung, siehe Docstring von ``_emotion``. Kleingeschrieben, Teilstring-Abgleich, damit Beugungen
# mitgehen („teuerste“ trifft auch „teuersten“).
EMOTION_WERTUNG = (
    "furchtbar", "schrecklich", "unglaublich", "unfassbar", "wahnsinn", "großartig", "grossartig",
    "fantastisch", "schlimm", "brutal", "krass", "absurd", "peinlich", "stolz", "wütend", "wut",
    "angst", "traurig", "glücklich", "hass", "liebe", "katastrophe", "desaster", "fehler", "verloren",
    "gescheitert", "geschockt", "begeistert", "enttäuscht", "verzweifelt", "empörend", "lächerlich",
    "wunderbar", "teuerste", "schlimmste", "größte", "grösste", "beste", "schlechteste", "härteste",
)  # fmt: skip
EMOTION_VERSTAERKER = (
    "sehr", "total", "völlig", "komplett", "extrem", "massiv", "absolut", "richtig ", "echt ",
    "wirklich", "viel zu", "so was von",
)  # fmt: skip
EMOTION_NACHDRUCK = (
    "nie wieder", "niemals", "gar nicht", "überhaupt nicht", "auf keinen fall", "kein einziges mal",
    "nicht ein einziges", "keineswegs",
)  # fmt: skip


def parse_numbered(text: str) -> list[dict]:
    """Zeilen ``[idx] (Sprecher) Text`` aus dem gerenderten Prompt."""
    out = []
    for line in text.splitlines():
        m = _LINE.match(line.strip())
        if m:
            out.append({"idx": int(m.group(1)), "speaker": m.group(2), "text": m.group(3).strip()})
    return out


def estimate_seconds(sents: list[dict]) -> float:
    n = sum(len(s["text"].split()) for s in sents)
    return n / WORDS_PER_SECOND


def _evidence(sent: dict) -> str:
    """Wörtlicher Satzanfang (maximal ``EVIDENCE_WORDS`` Wörter), damit der Beleg im Clip vorkommt."""
    return " ".join(sent["text"].split()[:EVIDENCE_WORDS])


def _markers_in(low: str) -> list[str]:
    return [m for m in DISCOURSE_MARKERS if m in low]


def policy() -> editorial.Policy:
    """Die redaktionelle Grundlage. Fehlt sie, scheitert das laut (``editorial.PolicyError``)."""
    return editorial.load()


def _typ_boni(p: editorial.Policy) -> dict[str, float]:
    return {t.schluessel: t.bonus for t in p.moment_typen}


def _anchor_score(sent: dict, p: editorial.Policy | None = None) -> float:
    """Wie sehr taugt dieser Satz als Anker? Eigene Marker plus die Moment-Typen der Grundlage."""
    p = p or policy()
    low = sent["text"].lower()
    score = 0.0
    score += 2.0 * min(len(_markers_in(low)), 2)
    if _NUMBER.search(sent["text"]):
        score += 1.0
    if sent["text"].rstrip().endswith("?"):
        score += 1.0
    if any(m in low for m in CONTRAST_MARKERS):
        score += 1.0
    boni = _typ_boni(p)
    score += sum(boni.get(k, 0.0) for k in p.typen_im_text(sent["text"]))
    return score


def _structure_for(span: list[dict]) -> str:
    first_low = span[0]["text"].lower()
    text_low = " ".join(s["text"] for s in span).lower()
    if span[0]["text"].rstrip().endswith("?"):
        return "tension_first"
    if _NUMBER.search(span[0]["text"]):
        return "payoff_first"
    if any(m in first_low for m in ("ich war", "wir haben damals", "der moment, als", "und dann")):
        return "hook_build_payoff"
    if any(m in text_low for m in ("der fehler war", "mein größter fehler", "was ich gelernt habe")):
        return "decision_story"
    if any(m in text_low for m in ("zum beispiel", "konkret heißt das", "das heißt konkret", "erstens", "zweitens")):
        return "how_to_list"
    return "hook_build_payoff"


def propose_moments(user: str) -> dict:
    """Bis zu drei nicht überlappende Satz-Spannen um Anker, direkt im Längenfenster der Grundlage.

    Zwei Dinge kommen aus ``clip_policy_v<N>.yaml``: die Moment-Typen gehen als zusätzliches Gewicht
    in die Ankerwahl ein (``_anchor_score``), und das Längenfenster wird schon hier beachtet, nicht
    erst beim Bewerten. Ein Vorschlag wächst vom Anker nach hinten bis ``ziel_s``, danach nach vorne
    bis ``gut_von_s``, und nie über ``gut_bis_s`` hinaus. Was ``hart_min_s`` nicht erreicht, wird
    nicht vorgeschlagen: kürzer ist als Clip unbrauchbar, und die Grundlage verbietet nur das
    Unterdrücken von Bewertungen, nicht das Zuschneiden eines Vorschlags.
    """
    sents = parse_numbered(user)
    if not sents:
        return {"moments": []}
    p = policy()
    ziel, von, bis, minimum = p.ziel_s, p.gut_von_s, p.gut_bis_s, p.hart_min_s
    anchors = sorted(((_anchor_score(s, p), i) for i, s in enumerate(sents)), key=lambda x: (-x[0], x[1]))
    chosen: list[tuple[int, int]] = []
    moments = []
    for score, i in anchors:
        if score <= 0 or len(moments) >= PROPOSE_MAX_MOMENTS:
            break
        if any(a <= i <= b for a, b in chosen):
            continue
        a, b = i, i
        while estimate_seconds(sents[a : b + 1]) < ziel and b + 1 < len(sents):
            if estimate_seconds(sents[a : b + 2]) > bis:
                break
            if any(x <= b + 1 <= y for x, y in chosen):
                break
            b += 1
        while estimate_seconds(sents[a : b + 1]) < von and a > 0:
            if estimate_seconds(sents[a - 1 : b + 1]) > bis:
                break
            if any(x <= a - 1 <= y for x, y in chosen):
                break
            a -= 1
        if estimate_seconds(sents[a : b + 1]) < minimum:
            continue
        chosen.append((a, b))
        span = sents[a : b + 1]
        text = " ".join(s["text"] for s in span)
        low = text.lower()
        typen = p.typen_im_text(text)
        reasons = []
        if typen:
            namen = {t.schluessel: t.name for t in p.moment_typen}
            reasons.append("Moment-Typ " + ", ".join(namen.get(k, k) for k in typen))
        markers = _markers_in(low)
        if markers:
            reasons.append(f"Diskursmarker „{markers[0]}“")
        if _NUMBER.search(text):
            reasons.append("Zahl im Abschnitt")
        if any(s["text"].rstrip().endswith("?") for s in span):
            reasons.append("Frage im Abschnitt")
        reasons.append(f"geschätzt {round(estimate_seconds(span))} Sekunden")
        why = "Heuristik ohne Sprachmodell: " + ", ".join(reasons) + "."
        moments.append(
            {"first_sent": span[0]["idx"], "last_sent": span[-1]["idx"], "structure": _structure_for(span), "why": why}
        )
    return {"moments": moments}


@dataclass
class _Merkmale:
    """Was sich aus dem Text allein ablesen lässt. Einmal berechnet, von allen Kriterien genutzt."""

    sents: list[dict]
    text: str
    low: str
    first: dict
    last: dict
    first_low: str
    numbers: list[str]
    markers: list[str]
    gastgeberfrage: bool
    frage_wird_beantwortet: bool
    frage_am_ende: bool
    offenes_ende: bool
    negation: bool
    contrast: bool
    typen: list[str]


def _merkmale(sents: list[dict], p: editorial.Policy) -> _Merkmale:
    text = " ".join(s["text"] for s in sents)
    low = text.lower()
    first, last = sents[0], sents[-1]
    # Hauptsprecher ist, wer die meisten Wörter im Abschnitt hat. Beginnt der Abschnitt mit der
    # Frage eines anderen, ist das die Gastgeberfrage aus ``einstieg.keine_gastgeberfrage``.
    gewicht: dict[str, int] = {}
    for s in sents:
        gewicht[s.get("speaker", "?")] = gewicht.get(s.get("speaker", "?"), 0) + len(s["text"].split())
    haupt = max(gewicht, key=lambda k: (gewicht[k], k)) if gewicht else "?"
    fragen = [i for i, s in enumerate(sents) if s["text"].rstrip().endswith("?")]
    tokens = set(re.findall(r"[a-zäöüß]+", low))
    return _Merkmale(
        sents=sents,
        text=text,
        low=low,
        first=first,
        last=last,
        first_low=first["text"].lower(),
        numbers=_NUMBER.findall(text),
        markers=_markers_in(low),
        gastgeberfrage=bool(
            p.einstieg.get("keine_gastgeberfrage")
            and first["text"].rstrip().endswith("?")
            and first.get("speaker", "?") != haupt
        ),
        frage_wird_beantwortet=any(i < len(sents) - 1 for i in fragen),
        frage_am_ende=bool(fragen) and fragen[-1] == len(sents) - 1,
        offenes_ende=dach_nlp.ends_with_open_loop(last["text"]),
        negation=bool(tokens & dach_nlp.NEGATIONS),
        contrast=bool(CONTRAST_WORDS.search(low)) or any(m in low for m in CONTRAST_MARKERS),
        typen=p.typen_im_text(text),
    )


def _anteil(v: float) -> float:
    return max(0.0, min(1.0, v))


def _standalone(m: _Merkmale, p: editorial.Policy) -> float:
    """„Versteht man es ohne Vorwissen?“ — gemessen an den Regeln aus ``einstieg``.

    Abzug für: Pronomen ohne Bezug als erstes Wort (``einstieg.pronomen``), Anschlusskonjunktion am
    Satzanfang, Rückverweis irgendwo im Text, Einleitungsfloskel, Frage eines anderen Sprechers.
    Ein Clip, der mit „Er ist ja offensichtlich …“ beginnt, verliert hier; „Krankschreibungen werden
    massiv missbraucht.“ verliert nichts.
    """
    ein = p.einstieg
    a = 1.0
    erstes_wort = re.sub(r"[^\wäöüß]", "", m.first_low.split()[0]) if m.first_low.split() else ""
    if ein.get("keine_pronomen_ohne_bezug") and erstes_wort in {x.lower() for x in ein.get("pronomen", [])}:
        a -= 0.40
    if m.first_low.startswith(CONTEXT_STARTS):
        a -= 0.35
    if any(r in m.low for r in REFERENCE_PHRASES):
        a -= 0.25
    if ein.get("einleitungen_kappen") and any(f in m.first_low for f in ein.get("einleitungsfloskeln", [])):
        a -= 0.15
    if m.gastgeberfrage:
        a -= 0.30
    return _anteil(a)


def _hook(m: _Merkmale, p: editorial.Policy) -> float:
    """„Gibt es einen Satz, der in drei Sekunden stoppt?“

    Textmerkmale: kurzer erster Satz, Behauptung statt Anlauf, rhetorische Frage des Sprechers
    selbst, Zahl im ersten Satz, Diskursmarker. Die Frage eines anderen Sprechers zählt nicht als
    Hook (``einstieg.keine_gastgeberfrage``), sie ist Anlauf.
    """
    a = 0.30
    if len(m.first["text"].split()) <= HOOK_MAX_WORDS:
        a += 0.20
    eigene_frage = m.first["text"].rstrip().endswith("?") and not m.gastgeberfrage
    behauptung = not m.first["text"].rstrip().endswith("?") and len(m.first["text"].split()) >= 4
    if eigene_frage:
        a += 0.25
    if behauptung:
        a += 0.20
    if _NUMBER.search(m.first["text"]):
        a += 0.15
    if any(x in m.first_low for x in DISCOURSE_MARKERS):
        a += 0.20
    if any(f in m.first_low for f in p.einstieg.get("einleitungsfloskeln", [])):
        a -= 0.20
    return _anteil(a)


def _offene_frage(m: _Merkmale, p: editorial.Policy) -> float:
    """„Entsteht eine Neugierlücke?“ — eine Frage, die im Clip noch beantwortet wird, plus Spannungsmarker.

    Eine Frage im letzten Satz zählt fast nichts: dann bleibt sie offen, das ist kein Bogen,
    sondern ein Abbruch (``ausstieg``/``ends_before_answer``).
    """
    a = 0.20
    if m.frage_wird_beantwortet:
        a += 0.35
    elif m.frage_am_ende:
        a += 0.05
    if m.contrast:
        a += 0.20
    if m.negation:
        a += 0.10
    return _anteil(a)


def _spezifitaet(m: _Merkmale, p: editorial.Policy) -> float:
    """„Gibt es Zahlen, Namen, Bilder?“ — Zahlen, Eigennamen mitten im Satz, angekündigte Beispiele."""
    eigennamen = re.findall(r"(?<!^)(?<![.!?] )\b[A-ZÄÖÜ][a-zäöüß]{3,}", m.text)
    a = 0.10
    a += 0.20 * min(len(m.numbers), 3)
    if len(eigennamen) >= 3:
        a += 0.15
    if "zum beispiel" in m.low or "konkret" in m.low:
        a += 0.15
    return _anteil(a)


def _emotion(m: _Merkmale, p: editorial.Policy) -> float:
    """„Trägt der Moment eine klare Emotion?“ — Näherung über vier Textmerkmale.

    GEMESSEN WIRD: Wertungswörter und starke Adjektive aus ``EMOTION_WERTUNG`` (Teilstring, damit
    Beugungen mitgehen), Verstärker aus ``EMOTION_VERSTAERKER``, Ausrufezeichen, und Verneinung mit
    Nachdruck (``EMOTION_NACHDRUCK``, zusätzlich zur blossen Verneinung). Dazu der Bonus der
    Moment-Typen ``contrarian`` und ``gestaendnis``, die laut Grundlage über Emotion tragen.

    NICHT GEMESSEN WIRD, und das ist der grössere Teil:
      * Alles Hörbare. Lautstärke, Stimmlage, Tempo, Zittern, Lachen, Pause vor der Aussage. Genau
        das nennt die Grundlage in ``audio`` als Merkmal, und genau das sieht Text nicht. Die
        Heuristik bekommt den Prompt, nicht die Spur.
      * Ironie und Sarkasmus. „Ja super gelaufen“ zählt hier als positiv.
      * Emotion ohne Wertungswort. Ein ruhig erzählter Todesfall hat kein einziges Wort aus der
        Liste und bekommt trotzdem nur den Grundwert.
      * Dialekt. Die Listen sind standarddeutsch; Schweizer oder österreichische Wertungswörter
        fehlen.
    Der Wert ist deshalb eher eine Untergrenze als eine Messung.
    """
    a = 0.20
    a += 0.15 * min(sum(1 for w in EMOTION_WERTUNG if w in m.low), 2)
    a += 0.10 * min(sum(1 for w in EMOTION_VERSTAERKER if w in m.low), 2)
    if "!" in m.text:
        a += 0.15
    if any(w in m.low for w in EMOTION_NACHDRUCK):
        a += 0.20
    return _anteil(a)


def _aufloesung(m: _Merkmale, p: editorial.Policy, laenge_ok: bool) -> float:
    """„Endet es auf einem Hochpunkt?“ — vollständiger Schlusssatz, Merksatz, kein offenes Ende.

    Die Abschwächungsmarker aus ``ausstieg.abschwaechung_marker`` im letzten Satz kosten: dort hätte
    der Schnitt davor sitzen müssen.
    """
    aus = p.ausstieg
    letzter = m.last["text"].rstrip()
    a = 0.25
    if aus.get("satz_zu_ende") and letzter.endswith((".", "!", "…")):
        a += 0.25
    if m.offenes_ende:
        a -= 0.25
    if m.frage_am_ende:
        a -= 0.15
    if aus.get("vor_der_abschwaechung") and any(w in letzter.lower() for w in aus.get("abschwaechung_marker", [])):
        a -= 0.20
    if laenge_ok:
        a += 0.20
    if m.markers:
        a += 0.10
    return _anteil(a)


def _zielgruppe(m: _Merkmale, p: editorial.Policy, laenge_ok: bool) -> float:
    """„Trifft es die Bewusstseinsstufe des Zuschauers?“ — ohne Wissen über die Zielgruppe nicht messbar.

    Die Heuristik kennt weder Profil noch Bewusstseinsstufe nach Schwartz. Sie gibt deshalb den
    neutralen Mittelwert und korrigiert ihn nur um das eine, was sie wirklich sieht: ob die Länge
    zum Format passt. Alles andere wäre vorgetäuschte Genauigkeit. Ein Sprachmodell mit Brief kann
    das beantworten, diese Funktion nicht.
    """
    return _anteil(NEUTRAL + (0.10 if laenge_ok else 0.0))


def score_clip(user: str) -> dict:
    """Rubrik der Grundlage aus einfachen Textmerkmalen; Belege sind wörtliche Satzanfänge.

    Liefert die sieben Kriterien unter ``rubrik`` auf der Skala 0 bis ``policy.skala_max`` und
    zusätzlich die alten fünf Schlüssel auf 0 bis 10, weil Bestandsdaten, ``RUBRIC_SCHEMA`` und die
    Web-App daran hängen: hook bleibt hook, payoff ist aufloesung, specificity ist spezifitaet,
    tension ist offene_frage, audience_fit ist zielgruppe.

    ``punkte`` ist die gewichtete Gesamtwertung der Grundlage (0 bis ``punkte_gesamt``), nach Abzug
    für die Länge. Kein Moment wird unterdrückt: ``bewertung.modus`` steht auf ``sortieren``.
    """
    p = policy()
    sents = parse_numbered(user)
    if not sents:
        sents = [{"idx": 0, "speaker": "?", "text": user.strip() or "-"}]
    m = _merkmale(sents, p)
    est_s = estimate_seconds(sents)
    laenge_ok = p.laenge_ok(est_s)
    abzug = p.laenge_abzug(est_s)
    organisatorisch = p.ist_organisatorisch(m.text)

    anteile = {
        "standalone": _standalone(m, p),
        "hook": _hook(m, p),
        "offene_frage": _offene_frage(m, p),
        "spezifitaet": _spezifitaet(m, p),
        "emotion": _emotion(m, p),
        "aufloesung": _aufloesung(m, p, laenge_ok),
        "zielgruppe": _zielgruppe(m, p, laenge_ok),
    }
    boni = _typ_boni(p)
    for typ in m.typen:
        for kriterium in TYP_WIRKT_AUF.get(typ, ()):
            if kriterium in anteile:
                anteile[kriterium] = _anteil(anteile[kriterium] + TYP_BONUS_PRO_PUNKT * boni.get(typ, 0.0))
    if organisatorisch:
        # Reine Logistik („Wo liegt das ungefähr?“). Sehr niedrig bewerten, aber sichtbar lassen.
        anteile = {k: v * ORGANISATORISCH_FAKTOR for k, v in anteile.items()}

    rubrik = {k: round(v * p.skala_max, 2) for k, v in anteile.items()}
    punkte = round(p.gesamtwert(rubrik) * (1.0 - abzug), 2)

    def alt(neu: str) -> int:
        return int(max(0, min(ALT_SKALA_MAX, round(anteile[neu] * ALT_SKALA_MAX))))

    number_sent = next((s for s in sents if _NUMBER.search(s["text"])), m.last)
    tension_sent = next(
        (s for s in sents if s["text"].rstrip().endswith("?") or CONTRAST_WORDS.search(s["text"].lower())), m.first
    )

    unresolved = [x for x in REFERENCE_PHRASES if x in m.low]
    needs_earlier = m.first_low.startswith(CONTEXT_STARTS)
    ends_before = m.offenes_ende or m.frage_am_ende
    sensitive = any(t in m.low for t in SENSITIVE_TERMS)

    parts = [f"{len(m.numbers)} Zahlen" if m.numbers else "keine Zahlen"]
    if m.typen:
        parts.append("Moment-Typ " + ", ".join(m.typen))
    if m.gastgeberfrage:
        parts.append("Frage eines anderen Sprechers am Anfang")
    if m.contrast:
        parts.append("Kontrastmarker")
    if organisatorisch:
        parts.append("reines Organisationsgespräch")
    parts.append(f"geschätzt {round(est_s)} Sekunden" + ("" if laenge_ok else f", Längenabzug {abzug:.2f}"))
    return {
        "unresolved_references": unresolved,
        "needs_earlier_context": bool(needs_earlier),
        "ends_before_answer": bool(ends_before),
        "hook": alt("hook"),
        "hook_evidence": _evidence(m.first),
        "payoff": alt("aufloesung"),
        "payoff_evidence": _evidence(number_sent),
        "specificity": alt("spezifitaet"),
        "specificity_evidence": _evidence(number_sent),
        "tension": alt("offene_frage"),
        "tension_evidence": _evidence(tension_sent),
        "audience_fit": alt("zielgruppe"),
        "audience_fit_evidence": _evidence(m.first),
        "rubrik": rubrik,
        "skala_max": p.skala_max,
        "moment_typen": m.typen,
        "organisatorisch": bool(organisatorisch),
        "gastgeberfrage": bool(m.gastgeberfrage),
        "laenge_s": round(est_s, 1),
        "laenge_ok": bool(laenge_ok),
        "laenge_abzug": round(abzug, 2),
        "punkte": punkte,
        "punkte_gesamt": p.punkte_gesamt,
        "policy_version": editorial.policy_version(p.version),
        "is_humor": False,
        "sensitive_topic": sensitive,
        "suggested_title_card": "",
        "why": "Heuristik ohne Sprachmodell: " + ", ".join(parts) + ".",
    }


def confirm_qualification(user: str) -> dict:
    """Ohne Sprachmodell nicht entscheidbar: ``misleading_without = None``, der Aufrufer setzt ``confirmed = null``."""
    return {
        "misleading_without": None,
        "reason": "Ohne Sprachmodell nicht prüfbar, Mensch entscheidet",
        "repair": "none",
    }


# -- Phase 3: Copy (Hooks, Post-Captions) ------------------------------------------------------------
_ADDRESS = re.compile(r"Anrede:\s*(DU|SIE|du|sie|Du|Sie)\b")
_PLATFORM = re.compile(r"für\s+(tiktok|reels|shorts|linkedin)\b", re.IGNORECASE)
_HOOK_ONSCREEN = re.compile(r"nicht wörtlich:\s*(.*)")
_NUMBER_PHRASE = re.compile(r"\d[\d.,]*(?:\s?(?:%|€|Prozent|Euro|Franken|Jahre|Jahren|Tage|Stunden|Minuten|Kunden|Mitarbeiter|Leute|Mal))?")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
SPOKEN_MAX_WORDS = 12
ONSCREEN_MAX_WORDS = 9
HOOK_PATTERNS = ("identity_call", "contrarian", "open_loop", "results_first", "mistake_warning")


def clip_text_of(user: str) -> str:
    """Text nach der letzten Zeile ``CLIP:`` im gerenderten Prompt."""
    marker = "CLIP:"
    idx = user.rfind(marker)
    return user[idx + len(marker) :].strip() if idx >= 0 else user.strip()


def address_of(user: str) -> str:
    """Anrede aus dem Prompt (``du`` | ``sie``), Default ``du``."""
    m = _ADDRESS.search(user)
    return m.group(1).lower() if m else "du"


def sentences_of(text: str) -> list[str]:
    return [x.strip() for x in _SENT_SPLIT.split(" ".join(text.split())) if x.strip()]


def _core(sentence: str, max_words: int) -> str:
    """Satzanfang ohne Schlusszeichen, maximal ``max_words`` Wörter (nur Wörter aus dem Clip)."""
    toks = sentence.split()
    cut = toks[:max_words]
    out = " ".join(cut).rstrip(".,;:!?")
    return out[:1].upper() + out[1:] if out else out


def _fit(prefix: str, sentence: str, limit: int, suffix: str = "") -> str:
    """``prefix`` plus Satzanfang, so gekürzt, dass die Wortzahl ``limit`` nicht überschreitet."""
    used = len(prefix.split()) + len(suffix.split())
    core = _core(sentence, max(1, limit - used))
    text = f"{prefix} {core}".strip()
    return f"{text}{suffix}" if suffix else text


def write_hooks(user: str) -> dict:
    """Fünf Hook-Varianten aus Satzanfängen, erster Zahl und Kontrastmarker des Clips. Keine neuen Zahlen."""
    clip = clip_text_of(user)
    address = address_of(user)
    sents = sentences_of(clip) or [clip or "-"]
    first = sents[0]
    number = _NUMBER_PHRASE.search(clip)
    number_sent = next((x for x in sents if _NUMBER.search(x)), first)
    contrast_sent = next((x for x in sents if CONTRAST_WORDS.search(x.lower())), None)
    du = address == "du"
    variants = [
        {
            "pattern": "identity_call",
            "spoken": _fit("Du kennst das sicher:" if du else "Sie kennen das sicher:", first, SPOKEN_MAX_WORDS),
            "onscreen": _fit("Kennst du das:" if du else "Kennen Sie das:", first, ONSCREEN_MAX_WORDS),
        },
        {
            "pattern": "contrarian",
            "spoken": _fit("Das Gegenteil stimmt:", contrast_sent or first, SPOKEN_MAX_WORDS),
            "onscreen": _fit("Das Gegenteil:", contrast_sent or first, ONSCREEN_MAX_WORDS),
        },
        {
            "pattern": "open_loop",
            "spoken": _fit("Was dahinter steckt:", first, SPOKEN_MAX_WORDS),
            "onscreen": _fit("Was dahinter steckt:", first, ONSCREEN_MAX_WORDS),
        },
        {
            "pattern": "results_first",
            "spoken": _fit(f"{number.group(0).strip()}:" if number else "Das Ergebnis:", number_sent, SPOKEN_MAX_WORDS),
            "onscreen": _fit(f"{number.group(0).strip()}:" if number else "Das Ergebnis:", number_sent, ONSCREEN_MAX_WORDS),
        },
        {
            "pattern": "mistake_warning",
            "spoken": _fit("Dieser Fehler kostet dich viel:" if du else "Dieser Fehler kostet Sie viel:", first, SPOKEN_MAX_WORDS),
            "onscreen": _fit("Dieser Fehler kostet:", first, ONSCREEN_MAX_WORDS),
        },
    ]
    return {"variants": variants}


def write_post_caption(user: str) -> dict:
    """Post-Text pro Plattform nur aus Sätzen des Clips; CTA in der Anrede des Profils."""
    clip = clip_text_of(user)
    address = address_of(user)
    m = _PLATFORM.search(user.split("CLIP:", 1)[0])
    platform = m.group(1).lower() if m else "linkedin"
    hook = (_HOOK_ONSCREEN.search(user.split("CLIP:", 1)[0]) or [None, ""])[1]
    hook = hook.strip() if isinstance(hook, str) else ""
    sents = [x for x in sentences_of(clip) if x != hook] or [clip or "-"]
    du = address == "du"
    if platform in ("tiktok", "reels"):
        text = "\n".join(sents[:2])
        cta = "Was ist deine Erfahrung damit?" if du else "Was ist Ihre Erfahrung damit?"
    elif platform == "shorts":
        title = _core(sents[0], 8)
        if len(title) > 60:
            title = title[:57].rstrip() + "..."
        text = f"{title}\n{sents[1] if len(sents) > 1 else sents[0]}"
        cta = "Mehr dazu im ganzen Gespräch."
    else:
        statement = _core(sents[0], 8)
        paragraphs = [statement, *sents[1:4]]
        text = "\n\n".join(paragraphs)
        cta = "Wie siehst du das?" if du else "Wie sehen Sie das?"
    return {"text": text, "cta": cta}


HANDLERS = {
    "propose_moments": propose_moments,
    "score_clip": score_clip,
    "confirm_qualification": confirm_qualification,
    "write_hooks": write_hooks,
    "write_post_caption": write_post_caption,
}


def answer(tool_name: str, user: str, schema: dict | None = None) -> dict:
    """Deterministische Antwort für ein bekanntes Tool-Schema."""
    handler = HANDLERS.get(tool_name)
    if handler is None:
        raise RuntimeError(f"Heuristik-Provider kennt das Tool {tool_name} nicht")
    return handler(user)


__all__ = [
    "ALT_AUS_NEU",
    "ALT_SKALA_MAX",
    "HANDLERS",
    "HOOK_PATTERNS",
    "MODEL_ID",
    "ONSCREEN_MAX_WORDS",
    "ORGANISATORISCH_FAKTOR",
    "SPOKEN_MAX_WORDS",
    "TYP_WIRKT_AUF",
    "WORDS_PER_SECOND",
    "address_of",
    "answer",
    "clip_text_of",
    "confirm_qualification",
    "estimate_seconds",
    "parse_numbered",
    "policy",
    "propose_moments",
    "score_clip",
    "sentences_of",
    "write_hooks",
    "write_post_caption",
]
