"""Caption-Engine für deutsche Short-Form-Clips (ASS/libass, eingebrannt via ffmpeg).

Regeln:
- Karten nach Bedeutung (Satzteile), nicht nach fixer Wortzahl
- Zeichen pro Zeile aus der Schriftgröße (``max_chars``), 1 bis 2 Zeilen, Lesetempo-Check (Zeichen/Sekunde)
- „nicht" (und andere Negationen) steht nie allein in einer neuen Zeile
- lange Komposita: eigene Karte; wenn breiter als die Zeile, Silbentrennung an Morphemgrenze (pyphen de_DE)
- Substantiv-Großschreibung bleibt (keine ALL-CAPS als Default)
- Presets mit Safe Zones pro Plattform (Pixel bei 1080x1920)
- Wortform wählbar (Phase 5c, Schweizerdeutsch-Beta): ``text_field = "text"`` (Original) oder ``"text_norm"``
  (normalisierte Form aus ``dach_nlp``); fehlt ``text_norm`` an einem Wort, gilt ``text`` (Entscheidung P2)
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field, replace

from .. import editorial
from .dach_nlp import NEGATIONS

W, H = 1080, 1920
NEWLINE = "\\N"  # ASS-Zeilenumbruch
AVG_CHAR_EM = 0.56  # mittlere Zeichenbreite in em für Inter Bold; pro Font messen
MAX_CPS = 17.0
# Hoechstens so viele Tempo-Hinweise je Clip, die schnellsten zuerst.
MAX_WARNUNGEN = 20
BREAK_WORDS = {"und", "aber", "weil", "dass", "denn", "oder", "wenn", "sondern", "also", "obwohl", "damit"}
TEXT_FIELDS = ("text", "text_norm")


@dataclass(frozen=True)
class CaptionRules:
    """Regeln aus AP10a (Abschnitt ``captions`` der Policy, Fassung 2).

    ``enabled`` ist der Schalter ``implementation.captions.word_bridge`` (Rollback). Aus heisst: genau das
    Verhalten vor AP10a, Wort fuer Wort (Fassung 1 und Rollback). An heisst zusaetzlich zu den
    Werten unten: Zahl plus Einheit ist ein Token, Bindestrichwoerter werden nur am vorhandenen
    Bindestrich getrennt, Komposita bevorzugt an Morphemgrenzen. Stil, Farben, Schrift, Groesse,
    Position, Woerter je Karte und Highlight bleiben in beiden Faellen gleich."""

    enabled: bool = False
    bridge_words: bool = False
    bridge_max_s: float = 0.0
    min_event_s: float = 0.0
    comma_break_only_on_overflow: bool = False


LEGACY_RULES = CaptionRules()


def caption_rules(policy: editorial.Policy | None = None) -> CaptionRules:
    """Regeln der aktiven (oder uebergebenen) Policy; ohne Schalter ``LEGACY_RULES``."""
    settings = editorial.caption_settings(policy if policy is not None else editorial.load())
    return LEGACY_RULES if settings is None else CaptionRules(enabled=True, **settings)


def _rules(rules: CaptionRules | None) -> CaptionRules:
    return caption_rules() if rules is None else rules


# Zahl plus Einheit bleibt ein Token und wird nie getrennt („40 Prozent", „3,5 Mio. Euro", „14.30 Uhr").
# Netflix German Timed Text Style Guide (RK 5). Dieselbe Liste steht in apps/web/lib/clips/captions.ts;
# packages/editorial/parity/caption_cards_v1.json haelt beide gleich.
NUMBER_RE = re.compile(r"^[+-]?\d+(?:[.,:]\d+)*$")  # 40, 3,5, 40.000, 14.30, 14:30
UNIT_WORDS = frozenset({
    "%", "prozent", "prozentpunkte", "promille",
    "€", "euro", "eur", "cent", "$", "dollar", "usd", "chf", "franken", "rappen", "£", "pfund",
    "tsd.", "tausend", "mio.", "mio", "million", "millionen", "mrd.", "mrd", "milliarde", "milliarden",
    "uhr", "sekunde", "sekunden", "minute", "minuten", "stunde", "stunden", "tag", "tage", "tagen",
    "woche", "wochen", "monat", "monate", "monaten", "jahr", "jahre", "jahren",
    "km", "m", "cm", "mm", "kg", "g", "kwh", "grad", "°c", "°", "km/h", "mal", "punkte",
})  # fmt: skip
MAX_UNITS_PER_NUMBER = 2  # „3,5 Mio. Euro": Groessenordnung und Waehrung

# Haeufige Kompositaglieder (klein) fuer die Trennung an Morphemgrenzen. Bewusst klein: sie wird nur
# fuer Woerter gebraucht, die breiter als die Zeile sind; was hier fehlt, trennt pyphen.
COMPOUND_MEMBERS = (
    "anfrage", "arbeit", "bearbeitung", "beitrag", "bemessung", "beratung", "bereich", "betrieb",
    "bildung", "bundes", "daten", "dienst", "energie", "entwicklung", "fahrt", "familie", "forschung",
    "frage", "führung", "geld", "geschäft", "gesellschaft", "gesetz", "gesundheit", "gewinnung",
    "grenze", "handel", "haus", "jahr", "kampagne", "kinder", "klima", "konzept", "kosten", "kranken",
    "krise", "kunde", "kunden", "land", "leistung", "leitung", "lösung", "markt", "ministerium",
    "mitarbeiter", "mittel", "netz", "ordnung", "personal", "pflege", "planung", "politik", "preis",
    "programm", "projekt", "prozess", "prüfung", "qualität", "recht", "rente", "schiff", "schutz",
    "sicherheit", "sozial", "staat", "stadt", "stelle", "steuer", "strategie", "system", "technik",
    "umwelt", "unternehmen", "verband", "verkehr", "versicherung", "vertrag", "vertrieb", "verwaltung",
    "wandel", "welt", "wert", "wirtschaft", "wissen", "zeit", "ziel", "zins", "erhöhung", "verlag",
    "hilfe", "sofort",
)  # fmt: skip
# Fugenelemente zwischen zwei Gliedern (Fugen-s, Fugen-n und Verwandte).
COMPOUND_JOINTS = ("es", "en", "er", "s", "n", "e")
# Untrennbare Vorsilben: „be|arbeitung" ist keine Fuge, die Grenze liegt davor.
INSEPARABLE_PREFIXES = ("miss", "zer", "ver", "ent", "be", "ge", "er")
# Ableitungsendungen: dahinter beginnt kein neues Glied („Zeit|ung" ist keine Fuge).
SUFFIXES = ("ung", "heit", "keit", "schaft", "lich", "isch", "nis", "tum", "bar", "sam", "haft", "ig", "in", "er", "en", "e")  # fmt: skip
MIN_MORPHEME = 3
# Gleitkomma-Toleranz für den Vergleich mit bridge_max_s (0,4 s Lücke aus 1,2 minus 0,8).
BRIDGE_EPS = 1e-6


def check_text_field(text_field: str | None) -> str:
    """``text`` oder ``text_norm``; alles andere ist ein Programmierfehler."""
    field_name = text_field or "text"
    if field_name not in TEXT_FIELDS:
        raise ValueError(f"Unbekanntes Caption-Textfeld {text_field!r} (erlaubt: {', '.join(TEXT_FIELDS)})")
    return field_name


def sichtbare_woerter(words: list[dict], text_field: str = "text") -> list[dict]:
    """Woerter ohne Anzeigetext fallen aus den Untertiteln heraus.

    Im Clip-Editor lassen sich einzelne Woerter aus dem Untertitel loeschen: gesagt bleibt gesagt,
    geschrieben steht es nicht mehr. Gedacht fuer Fuellwoerter und Versprecher. Gespeichert wird das
    als leerer Text am Wort - die Zeiten bleiben, damit das folgende Wort an seiner Stelle bleibt.

    Ohne diesen Filter liefe ein leeres Wort durch den Kartenbau und erzeugte doppelte Leerzeichen
    oder eine Karte ohne Inhalt. Beides sieht im Bild nach einem Fehler aus."""
    return [w for w in words if word_text(w, text_field).strip()]


def word_text(word: dict, text_field: str = "text") -> str:
    """Anzeigetext eines Wortes; ``text_norm`` fällt auf ``text`` zurück, wenn es fehlt oder leer ist."""
    if text_field != "text":
        norm = word.get(text_field)
        if norm is not None and str(norm).strip():
            return str(norm)
    return str(word["text"])


@dataclass(frozen=True)
class SafeZone:
    """Bereich, in dem Text nicht von Plattform-UI verdeckt wird (px von oben/links)."""

    top: int
    bottom: int  # y-Koordinate der Unterkante des sicheren Bereichs
    left: int
    right: int  # x-Koordinate der rechten Kante des sicheren Bereichs

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass(frozen=True)
class CaptionPreset:
    name: str
    safe: SafeZone
    font: str = "Inter"
    font_px: int = 78
    bold: bool = True
    max_lines: int = 2
    base_color: str = "&H00FFFFFF"
    highlight_color: str = "&H0000D7FF"
    # Farbe der Kontur und des Kastens dahinter. Beides war fest schwarz; wer eine farbige Kontur
    # oder einen farbigen Balken wollte, kam nicht heran.
    outline_color: str = "&H00000000"
    box_color: str = "&H80000000"
    outline_px: int = 5
    box: bool = False
    bottom_margin_px: int = 260  # Abstand der Textunterkante zur Unterkante der Safe Zone
    highlight_words: bool = True
    all_caps: bool = False
    # 1 = ein Wort je Einblendung (Karaoke-Stil der Kurzformate), None = nach Sinn gruppieren
    words_per_card: int | None = None
    extra: dict = field(default_factory=dict)

    @property
    def max_chars(self) -> int:
        return max_chars(self.font_px, self.safe.width)

    @property
    def baseline_y(self) -> int:
        return self.safe.bottom - self.bottom_margin_px


# TikTok: oben 108, unten 320, links 60, rechts 120. Reels: 210 bis 1610. Shorts: 120 bis 1620.
PRESETS: dict[str, CaptionPreset] = {
    "tiktok_bold": CaptionPreset("tiktok_bold", SafeZone(108, H - 320, 60, W - 120), font_px=78, bold=True),
    "reels_clean": CaptionPreset("reels_clean", SafeZone(210, 1610, 60, W - 120), font_px=66, bold=True, outline_px=3),
    "shorts_clean": CaptionPreset("shorts_clean", SafeZone(120, 1620, 60, W - 120), font_px=66, bold=True, outline_px=3),
    # Ein Wort je Einblendung, größer gesetzt: der Karaoke-Stil, der auf TikTok und Reels üblich ist.
    # Wortweise gibt es nie eine zweite Zeile, deshalb max_lines = 1.
    "tiktok_words": CaptionPreset(
        "tiktok_words", SafeZone(108, H - 320, 60, W - 120), font_px=104, bold=True, max_lines=1, words_per_card=1,
    ),
    "reels_words": CaptionPreset(
        "reels_words", SafeZone(210, 1610, 60, W - 120), font_px=92, bold=True, outline_px=4, max_lines=1, words_per_card=1,
    ),
    "shorts_words": CaptionPreset(
        "shorts_words", SafeZone(120, 1620, 60, W - 120), font_px=92, bold=True, outline_px=4, max_lines=1, words_per_card=1,
    ),
    "linkedin_static": CaptionPreset(
        "linkedin_static", SafeZone(120, 1700, 80, W - 80), font_px=54, bold=False, outline_px=0, box=True,
        highlight_words=False, bottom_margin_px=200,
    ),
    "corporate_third": CaptionPreset(
        "corporate_third", SafeZone(120, 1700, 80, W - 80), font_px=48, bold=False, outline_px=0, box=True,
        highlight_words=False, max_lines=2, bottom_margin_px=160,
    ),
}
# Kurzformate wortweise (Karaoke-Stil), LinkedIn bleibt ruhig und mehrwortig (Entscheidung P7).
# Die mehrwortigen Varianten bleiben als Preset wählbar: tiktok_bold, reels_clean, shorts_clean.
PLATFORM_DEFAULT_PRESET = {"tiktok": "tiktok_words", "reels": "reels_words", "shorts": "shorts_words", "linkedin": "linkedin_static"}


def preset_for(name_or_platform: str) -> CaptionPreset:
    if name_or_platform in PRESETS:
        return PRESETS[name_or_platform]
    return PRESETS[PLATFORM_DEFAULT_PRESET.get(name_or_platform, "linkedin_static")]


def scaled_preset(preset: str | CaptionPreset, out_w: int, out_h: int) -> CaptionPreset:
    """Preset (definiert für 1080x1920) proportional auf eine andere Ausgabegröße umrechnen.

    Vertikale Werte (Safe Zone oben/unten, Schriftgröße, Abstand zur Unterkante, Kontur) skalieren mit
    der Höhe, horizontale (links/rechts) mit der Breite. Für 9:16 kommt das Preset unverändert zurück."""
    p = preset if isinstance(preset, CaptionPreset) else preset_for(preset)
    if (out_w, out_h) == (W, H):
        return p
    fy, fx = out_h / H, out_w / W
    safe = SafeZone(
        top=int(round(p.safe.top * fy)),
        bottom=int(round(p.safe.bottom * fy)),
        left=int(round(p.safe.left * fx)),
        right=int(round(p.safe.right * fx)),
    )
    return CaptionPreset(
        name=p.name,
        safe=safe,
        font=p.font,
        font_px=max(12, int(round(p.font_px * fy))),
        bold=p.bold,
        max_lines=p.max_lines,
        base_color=p.base_color,
        highlight_color=p.highlight_color,
        outline_color=p.outline_color,
        box_color=p.box_color,
        outline_px=int(round(p.outline_px * fy)),
        box=p.box,
        bottom_margin_px=int(round(p.bottom_margin_px * fy)),
        highlight_words=p.highlight_words,
        all_caps=p.all_caps,
        words_per_card=p.words_per_card,
        extra=dict(p.extra),
    )


# Untertitel-Stil, den ein Nutzer je Clip einstellen darf. Der Wertebereich steht hier und nicht in
# der Oberflaeche: was der Renderer nicht annimmt, darf gar nicht erst eingestellt werden koennen.
#
# Die Grenzen sind keine Geschmacksfrage. Unter 28 Punkten ist auf einem Telefon nichts mehr zu
# lesen, ueber 180 passt kein deutsches Wort mehr in eine Zeile. Mehr als sechs Woerter je
# Einblendung ist kein Kurzformat mehr, und mehr als vier Zeilen verdecken das Bild.
STIL_GRENZEN: dict[str, tuple[float, float]] = {
    "font_px": (28, 180),
    "words_per_card": (1, 6),
    "max_lines": (1, 4),
    "outline_px": (0, 20),
    "bottom_margin_px": (0, 900),
}
STIL_SCHALTER = ("bold", "all_caps", "highlight_words", "box")
STIL_FARBEN = ("base_color", "highlight_color", "outline_color", "box_color")

FONTS_DATEI = "caption_fonts.json"


def _fonts_pfad() -> str:
    """Pfad zur gemeinsamen Schriftenliste (packages/design/caption_fonts.json).

    Wie bei der redaktionellen Grundlage liegt die Liste ausserhalb des Workers, damit Oberflaeche
    und Renderer dieselbe lesen. ``CHOPSTR_CAPTION_FONTS`` sticht, damit ein Image sie woanders
    ablegen kann.
    """
    env = (os.environ.get("CHOPSTR_CAPTION_FONTS") or "").strip()
    if env:
        return env
    hier = os.path.dirname(os.path.abspath(__file__))
    wurzel = os.path.abspath(os.path.join(hier, "..", "..", ".."))
    return os.path.join(wurzel, "packages", "design", FONTS_DATEI)


_fonts_zwischenspeicher: dict | None = None


def schriften() -> dict:
    """Die Schriftenliste, einmal gelesen und behalten."""
    global _fonts_zwischenspeicher
    if _fonts_zwischenspeicher is None:
        with open(_fonts_pfad(), encoding="utf-8") as f:
            _fonts_zwischenspeicher = json.load(f)
    return _fonts_zwischenspeicher


def schrift_namen() -> list[str]:
    return [str(s["id"]) for s in schriften().get("schriften", [])]


def schrift_datei(name: str) -> str | None:
    """Dateiname der Schrift, oder None wenn der Name nicht in der Liste steht."""
    for s in schriften().get("schriften", []):
        if str(s["id"]) == name:
            return str(s.get("datei") or "") or None
    return None


def ass_farbe(wert: str) -> str | None:
    """``#RRGGBB`` in die ASS-Schreibweise ``&H00BBGGRR``. Bereits gesetzte ASS-Werte gehen durch.

    ASS dreht die Reihenfolge um und stellt die Deckkraft voran. Ein falsch herum uebernommener
    Wert faellt nicht auf, er sieht nur falsch aus: aus Rot wird Blau.
    """
    w = (wert or "").strip()
    if not w:
        return None
    if w.upper().startswith("&H"):
        return w
    if w.startswith("#"):
        w = w[1:]
    if len(w) != 6 or any(c not in "0123456789abcdefABCDEF" for c in w):
        return None
    r, g, b = w[0:2], w[2:4], w[4:6]
    return f"&H00{b}{g}{r}".upper()


def _zahl_im_rahmen(wert, grenzen: tuple[float, float]) -> int | None:
    """Zahl auf den erlaubten Bereich ziehen, oder None wenn es keine brauchbare Zahl ist.

    NaN muss ausdruecklich abgefangen werden. ``min(180, nan)`` liefert 180, weil jeder Vergleich
    mit NaN falsch ist - aus einem unsinnigen Wert wuerde damit stillschweigend die groesste
    erlaubte Schrift. Ein Bool ist ebenfalls keine Zahl: ``True`` wuerde sonst zu 1.
    """
    if isinstance(wert, bool):
        return None
    try:
        z = float(wert)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(z):
        return None
    unten, oben = grenzen
    return int(round(max(unten, min(oben, z))))


def style_anwenden(preset: CaptionPreset, style: dict | None, skala: float = 1.0) -> CaptionPreset:
    """Nutzereinstellungen auf ein Preset legen. Unbekanntes und Unsinniges wird verworfen.

    Die eingestellten Werte gelten immer fuer 1080x1920, weil die Oberflaeche in dieser Groesse
    zeigt. ``skala`` ist ``out_h / H`` und rechnet sie auf die Ausgabegroesse um. Den Faktor aus dem
    Preset zurueckzurechnen waere falsch: die Presets haben unterschiedliche Safe Zones, aus einem
    Verhaeltnis von 1610 zu 1600 wuerde eine Skalierung von 1,006 statt 1,0.

    Es wird NICHTS abgelehnt und nichts geworfen: ein unsinniger Wert darf keinen Render stoppen.
    Er wird auf den erlaubten Bereich gezogen oder uebergangen, und das Ergebnis bleibt ein
    brauchbares Preset.
    """
    if not style:
        return preset
    aenderungen: dict = {}

    name = str(style.get("font") or "").strip()
    if name and name in schrift_namen():
        aenderungen["font"] = name

    for feld, grenzen in STIL_GRENZEN.items():
        if feld not in style:
            continue
        z = _zahl_im_rahmen(style[feld], grenzen)
        if z is None:
            continue
        aenderungen[feld] = z if feld in ("words_per_card", "max_lines") else max(0, int(round(z * skala)))

    for feld in STIL_SCHALTER:
        if feld in style and isinstance(style[feld], bool):
            aenderungen[feld] = style[feld]

    for feld in STIL_FARBEN:
        if feld in style:
            farbe = ass_farbe(str(style[feld] or ""))
            if farbe:
                aenderungen[feld] = farbe

    # Ein Wort je Einblendung kann nie zwei Zeilen fuellen. Das still mitzuziehen ist richtig: sonst
    # rechnet ``max_chars`` mit einer Zeile, die es nicht gibt.
    if aenderungen.get("words_per_card") == 1:
        aenderungen["max_lines"] = 1
    return replace(preset, **aenderungen) if aenderungen else preset




def safe_zone_margins(p: CaptionPreset, out_w: int = W, out_h: int = H) -> dict[str, int]:
    """Safe Zone als Abstände zu den vier Rändern (so steht sie im Render-Plan und in der Web-Vorschau)."""
    return {"top": p.safe.top, "bottom": out_h - p.safe.bottom, "left": p.safe.left, "right": out_w - p.safe.right}


def max_chars(font_px: int, safe_width: int = W - 180) -> int:
    """Zeichen pro Zeile aus Schriftgröße (18 bei 78 px auf 900 px Breite)."""
    return max(8, int(safe_width / (max(font_px, 1) * AVG_CHAR_EM)))


_hyph = None


def _hyphenator():
    global _hyph
    if _hyph is None:
        import pyphen

        _hyph = pyphen.Pyphen(lang="de_DE")
    return _hyph


def hyphenate(word: str, limit: int, rules: CaptionRules | None = None) -> list[str]:
    """Teilt ein zu langes Wort an Silben-/Morphemgrenzen (pyphen). Jede Zeile außer der letzten endet auf '-'.

    Mit den Regeln aus AP10a (``rules.enabled``): ein Bindestrichwort nur am vorhandenen Bindestrich,
    nie darin; sonst bevorzugt an Morphemgrenzen (``COMPOUND_MEMBERS``, Fugen), pyphen nur fuer ein
    Glied, das allein breiter als die Zeile ist."""
    if len(word) <= limit:
        return [word]
    if _rules(rules).enabled:
        return _hyphenate_v2(word, limit)
    parts = _hyphenator().inserted(word, hyphen="|").split("|")
    if len(parts) == 1:
        return [word[i : i + limit] for i in range(0, len(word), limit)]
    lines, cur = [], ""
    for p in parts:
        if cur and len(cur) + len(p) + 1 > limit:
            lines.append(cur + "-")
            cur = p
        else:
            cur += p
    if cur:
        lines.append(cur)
    return lines


def _hyphen_segments(word: str) -> list[str]:
    """``Kunden-Anfrage-Bearbeitung`` zu ``Kunden-``, ``Anfrage-``, ``Bearbeitung``; nur innere Bindestriche."""
    segments, cur = [], ""
    for i, ch in enumerate(word):
        cur += ch
        if ch == "-" and 0 < i < len(word) - 1 and word[i + 1] != "-" and cur.strip("-"):
            segments.append(cur)
            cur = ""
    if cur:
        segments.append(cur)
    return segments


def _morpheme_boundaries(word: str) -> list[int]:
    """Trennstellen an Morphemgrenzen aus ``COMPOUND_MEMBERS`` und ``COMPOUND_JOINTS``, links nach rechts.

    Eine Stelle innerhalb eines laengeren erkannten Gliedes zaehlt nicht (``anfrage`` schlaegt
    ``frage``), jedes Teilstueck hat mindestens ``MIN_MORPHEME`` Zeichen."""
    low = word.lower()
    n = len(low)
    spans = []
    for m in COMPOUND_MEMBERS:
        i = low.find(m)
        while i != -1:
            spans.append((i, i + len(m)))
            i = low.find(m, i + 1)
    starts = {s for s, _ in spans}
    cands: set[int] = set()
    for s, e in spans:
        b = s
        for pre in INSEPARABLE_PREFIXES:
            if low[:b].endswith(pre) and b - len(pre) >= MIN_MORPHEME:
                b -= len(pre)
                break
        cands.add(b)
        # Ende des Gliedes: direkt ein neues Glied, ein Glied hinter einer Fuge, sonst Fuge oder nichts,
        # solange danach keine Ableitungsendung beginnt.
        if e in starts:
            cands.add(e)
            continue
        fuge = next((f for f in COMPOUND_JOINTS if low.startswith(f, e) and e + len(f) in starts), None)
        if fuge is not None:
            cands.add(e + len(fuge))
            continue
        for f in ("s", "n", ""):
            # Eine Ableitungsendung zählt nur, wenn dort kein bekanntes Glied beginnt.
            if low.startswith(f, e) and (e + len(f) in starts or not low[e + len(f) :].startswith(SUFFIXES)):
                cands.add(e + len(f))
                break
    return sorted(
        b for b in cands if MIN_MORPHEME <= b <= n - MIN_MORPHEME and not any(s < b < e for s, e in spans)
    )


def _syllables(piece: str, size: int) -> list[str]:
    """pyphen-Silben eines Gliedes; einzelne Buchstaben haengen am Nachbarn (``be|ar|bei|tung``)."""
    parts = _hyphenator().inserted(piece, hyphen="|").split("|")
    if len(parts) == 1:
        chunks = [piece[i : i + size] for i in range(0, len(piece), max(1, size))]
        if len(chunks) > 1 and len(chunks[-1]) == 1 and len(chunks[-2]) > 2:
            # Kein Rest von einem Zeichen: einen Buchstaben vom vorigen Stück herübernehmen.
            chunks[-2], chunks[-1] = chunks[-2][:-1], chunks[-2][-1] + chunks[-1]
        return chunks
    merged: list[str] = []
    carry = ""
    for p in parts:
        p = carry + p
        carry = ""
        if len(p) == 1:
            carry = p
            continue
        merged.append(p)
    if carry:
        if merged:
            merged[-1] += carry
        else:
            merged.append(carry)
    return merged


def _split_compound(word: str, limit: int, trailing_dash: bool = False) -> list[str]:
    """Ein Wort ohne Bindestrich an Morphemgrenzen, ein zu breites Glied mit pyphen. Jede Zeile
    ausser der letzten bekommt einen Trennstrich; ``trailing_dash`` reserviert auch in der letzten
    Zeile Platz für einen Bindestrich, der danach angehängt wird."""
    cuts = [0, *_morpheme_boundaries(word), len(word)]
    pieces = [word[a:b] for a, b in zip(cuts, cuts[1:])]
    end_dash = 1 if trailing_dash else 0
    lines, cur = [], ""
    for k, piece in enumerate(pieces):
        last_piece = k == len(pieces) - 1
        # Die letzte Zeile braucht keinen Trennstrich, jede andere einen.
        if len(piece) + (end_dash if last_piece else 1) <= limit:
            units = [piece]
        else:
            # Ein Glied breiter als die Zeile: erst an der Morphemgrenze davor brechen, dann pyphen.
            if cur:
                lines.append(cur + "-")
                cur = ""
            units = _syllables(piece, max(1, limit - 1))
        for j, u in enumerate(units):
            dash = end_dash if last_piece and j == len(units) - 1 else 1
            if cur and len(cur) + len(u) + dash > limit:
                lines.append(cur + "-")
                cur = u
            else:
                cur += u
    if cur:
        lines.append(cur)
    return lines


def _hyphenate_v2(word: str, limit: int) -> list[str]:
    """Zwischen Bindestrich-Segmenten nur am Bindestrich; ein Segment, das allein breiter als die
    Zeile ist, wird an Morphemgrenzen und notfalls mit pyphen weiter geteilt. Ein Bindestrich am
    Wortende („Kunden-“ in „Kunden- und Lieferantendaten“) bleibt am Ende stehen."""
    core = word.rstrip("-")
    tail = word[len(core) :]
    if not core:
        return [word]
    segments = _hyphen_segments(core)
    lines: list[str] = []
    cur = ""
    for k, seg in enumerate(segments):
        last = k == len(segments) - 1
        seg_text = seg + tail if last else seg
        if len(seg_text) <= limit:
            if cur and len(cur) + len(seg_text) > limit:
                lines.append(cur)
                cur = seg_text
            else:
                cur += seg_text
            continue
        # Segment allein zu breit: vorige Zeile abschliessen, Segment ohne seinen Bindestrich teilen.
        if cur:
            lines.append(cur)
            cur = ""
        inner = seg[:-1] if seg.endswith("-") else seg
        dash = seg[len(inner) :] + (tail if last else "")
        parts = _split_compound(inner, limit, trailing_dash=bool(dash))
        parts[-1] += dash
        lines.extend(parts[:-1])
        cur = parts[-1]
    if cur:
        lines.append(cur)
    return lines


def _is_negation(token: str) -> bool:
    return token.lower().strip(".,!?;:") in NEGATIONS


def wrap_lines(tokens: list[str], limit: int, max_lines: int = 2) -> list[str]:
    """Greedy-Umbruch mit Regel: eine Negation steht nie allein in einer neuen Zeile."""
    lines: list[list[str]] = []
    cur: list[str] = []
    for tok in tokens:
        if cur and len(" ".join([*cur, tok])) > limit:
            lines.append(cur)
            cur = [tok]
        else:
            cur.append(tok)
    if cur:
        lines.append(cur)
    # „nicht" nie allein: vorheriges Wort mit nach unten ziehen oder Zeilen verschmelzen
    for i in range(1, len(lines)):
        if len(lines[i]) == 1 and _is_negation(lines[i][0]) and lines[i - 1]:
            if len(lines[i - 1]) > 1:
                lines[i].insert(0, lines[i - 1].pop())
            else:
                lines[i - 1].extend(lines[i])
                lines[i] = []
    lines = [ln for ln in lines if ln]
    out = [" ".join(ln) for ln in lines]
    if len(out) > max_lines:  # zu viel für eine Karte: Rest kommt auf die letzte Zeile (Aufrufer sollte Karten kleiner halten)
        out = [*out[: max_lines - 1], " ".join(out[max_lines - 1 :])]
    return out


def _kartenlaenge(card: list[dict], text_field: str, all_caps: bool) -> int:
    """Zeichen einer Karte, so wie sie im Bild stehen werden.

    ``all_caps`` gehoert dazu: aus dem deutschen ``ß`` macht ``upper()`` ein ``SS``, also ein
    Zeichen mehr. Wer die Laenge vor der Umwandlung misst, misst die falsche Karte.
    """
    stuecke = [word_text(w, text_field) for w in card]
    if all_caps:
        stuecke = [t.upper() for t in stuecke]
    return len(" ".join(stuecke))


def _passend_teilen(
    group: list[list[dict]], limit: int, max_lines: int, text_field: str, all_caps: bool
) -> list[list[dict]]:
    """Eine Karte so aufteilen, dass jeder Teil in die erlaubten Zeilen passt.

    Geteilt wird gierig von links: es entstehen so wenige Karten wie moeglich, und die Zeiten
    stimmen weiter, weil jede Teilkarte die Zeiten ihrer eigenen Woerter traegt.

    Ein einzelnes Wort, das fuer sich schon zu lang ist, bleibt allein stehen: es weiter zu
    zerlegen hiesse, mitten im Wort umzubrechen, und dafuer gibt es die Silbentrennung.

    ``group`` besteht aus Tokens (siehe ``_tokens``): ein Token ist ein Wort, mit den Regeln aus
    AP10a auch Zahl plus Einheit, und wird nie geteilt.
    """
    card = [w for tok in group for w in tok]
    budget = max(1, limit * max_lines)
    if len(group) <= 1 or _kartenlaenge(card, text_field, all_caps) <= budget:
        return [card]
    aus: list[list[dict]] = []
    lauf: list[dict] = []
    for tok in group:
        versuch = [*lauf, *tok]
        if lauf and _kartenlaenge(versuch, text_field, all_caps) > budget:
            aus.append(lauf)
            lauf = list(tok)
        else:
            lauf = versuch
    if lauf:
        aus.append(lauf)
    return aus


def _is_unit(text: str) -> bool:
    key = text.lower().rstrip(",;:!?")
    return key in UNIT_WORDS or key.rstrip(".") in UNIT_WORDS


def _tokens(
    words: list[dict], text_field: str, rules: CaptionRules, limit: int | None = None, all_caps: bool = False
) -> list[list[dict]]:
    """Woerter zu Tokens. Ohne AP10a ist jedes Wort ein Token; mit AP10a bilden eine Zahl und bis zu
    ``MAX_UNITS_PER_NUMBER`` folgende Einheiten ein Token („3,5 Mio. Euro"). Eine Einheit mit
    Satzzeichen (ausser dem Punkt einer Abkuerzung wie „Mio.") schliesst das Token ab.

    Ein Token steht immer in einer Zeile. Ist es breiter als ``limit``, bleibt nur Zahl plus erste
    Einheit, sonst die Zahl allein („3,5 Milliarden Euro" bei 15 Zeichen: „3,5 Milliarden", „Euro")."""
    if not rules.enabled:
        return [[w] for w in words]
    out: list[list[dict]] = []
    i = 0
    while i < len(words):
        tok = [words[i]]
        if NUMBER_RE.match(word_text(words[i], text_field)):
            while len(tok) <= MAX_UNITS_PER_NUMBER and i + len(tok) < len(words):
                prev = word_text(tok[-1], text_field)
                if len(tok) > 1 and prev.lower() not in UNIT_WORDS:
                    break
                if not _is_unit(word_text(words[i + len(tok)], text_field)):
                    break
                tok.append(words[i + len(tok)])
            while limit and len(tok) > 1 and _token_len(tok, text_field, all_caps) > limit:
                tok.pop()
        out.append(tok)
        i += len(tok)
    return out


def _token_text(tok: list[dict], text_field: str) -> str:
    return " ".join(word_text(w, text_field) for w in tok)


def _token_len(tok: list[dict], text_field: str, all_caps: bool) -> int:
    text = _token_text(tok, text_field)
    return len(text.upper() if all_caps else text)


def _comma_overflows(tokens: list[list[dict]], i: int, cur_len: int, cap: int, text_field: str) -> bool:
    """P30: bricht die Karte nach dem Komma von Token ``i`` nur, wenn sie sonst ueberliefe.

    Gemessen wird der folgende Satzteil bis zum naechsten Satzzeichen oder einer Pause ueber 0,4 s.
    Passt er nicht mehr in die Karte (Zeichen je Zeile mal Zeilen), ist das Komma die bessere Stelle."""
    total = cur_len
    for k in range(i + 1, len(tokens)):
        if float(tokens[k][0]["start"]) - float(tokens[k - 1][-1]["end"]) > 0.4:
            break
        t = _token_text(tokens[k], text_field)
        total += len(t) + 1
        if total - 1 > cap:
            return True
        if t.endswith((".", "!", "?", ",")):
            break
    return False


def build_cards(
    words: list[dict],
    limit: int | None = None,
    max_lines: int = 2,
    text_field: str = "text",
    words_per_card: int | None = None,
    all_caps: bool = False,
    rules: CaptionRules | None = None,
) -> list[list[dict]]:
    """Gruppiert Wörter zu Karten. Bricht an Satzzeichen, Konjunktionen, Pausen und vor langen Komposita.
    ``text_field`` bestimmt, welche Wortform Länge und Satzzeichen liefert (siehe ``word_text``).

    ``words_per_card`` schaltet auf feste Gruppengröße um: 1 bedeutet ein Wort je Einblendung, der
    Karaoke-Stil der Kurzformate. Satzzeichen bleiben am Wort, die Zeiten kommen unverändert aus dem
    Transkript. Ohne den Parameter gilt die sinngemäße Gruppierung.

    Die feste Gruppengröße ist eine OBERGRENZE, keine Vorgabe: passt eine Gruppe nicht in die
    erlaubten Zeilen, wird sie geteilt. Vorher entstand daraus eine Karte, deren Rest in die letzte
    Zeile gequetscht wurde (siehe ``wrap_lines``) - der Text war dann nicht weg, stand aber über
    die sichere Fläche hinaus oder in einer Zeile mehr, als eingestellt war. Beides sieht im Bild
    falsch aus, und beides kann niemand von aussen reparieren.

    ``rules`` (Standard: aktive Policy, siehe ``caption_rules``): mit AP10a zaehlt Zahl plus Einheit
    als ein Token (auch bei ``words_per_card``), und ein Komma bricht die Karte nur, wenn sie sonst
    ueberliefe (P30). Ohne AP10a ist jedes Wort ein Token und alles wie zuvor."""
    rules = _rules(rules)
    limit = limit or PRESETS["tiktok_bold"].max_chars
    words = sichtbare_woerter(words, text_field)
    tokens = _tokens(words, text_field, rules, limit, all_caps)
    if words_per_card and words_per_card > 0:
        roh = [tokens[i : i + words_per_card] for i in range(0, len(tokens), words_per_card)]
        aus: list[list[dict]] = []
        for gruppe in roh:
            aus.extend(_passend_teilen(gruppe, limit, max_lines, text_field, all_caps))
        return aus
    cap = limit * max_lines
    cards: list[list[dict]] = []
    cur: list[dict] = []
    cur_len = 0
    for i, tok in enumerate(tokens):
        t = _token_text(tok, text_field)
        is_long = len(t) > limit
        if is_long and cur and cur_len > 8:
            cards.append(cur)
            cur, cur_len = [], 0
        starts_clause = t.lower().strip(",.") in BREAK_WORDS
        if cur and not is_long and (cur_len + len(t) + 1 > cap or (starts_clause and cur_len > 8)):
            cards.append(cur)
            cur, cur_len = [], 0
        cur.extend(tok)
        cur_len += len(t) + 1
        nxt = tokens[i + 1][0] if i + 1 < len(tokens) else None
        comma = t.endswith(",") and (
            not rules.comma_break_only_on_overflow or _comma_overflows(tokens, i, cur_len, cap, text_field)
        )
        if is_long or t.endswith((".", "!", "?")) or comma or (nxt and float(nxt["start"]) - float(tok[-1]["end"]) > 0.4):
            cards.append(cur)
            cur, cur_len = [], 0
    if cur:
        cards.append(cur)
    return cards


def cps_warnings(cards: list[list[dict]], max_cps: float = MAX_CPS, text_field: str = "text") -> list[str]:
    """Karten, die schneller durchlaufen, als sich lesen laesst.

    Nur fuer Karten mit MEHREREN Woertern. Dort muss der Zuschauer einen Block lesen, waehrend die
    Stimme weiterlaeuft; schafft er das nicht, ist der Untertitel wertlos.

    Bei EINEM Wort je Einblendung gibt es nichts zu melden. Das Wort steht genau so lange, wie es
    gesprochen wird, und der Zuschauer folgt der Stimme statt vorauszulesen. An echtem Material
    gemessen: von 2007 Woertern lagen 1574 ueber der Grenze, darunter "Der" mit drei Buchstaben.
    Das ist keine Aussage ueber den Clip, sondern ueber normales Sprechtempo - und eine Warnung,
    die an zwei Dritteln aller Woerter haengt, nimmt niemand mehr ernst.
    """
    treffer: list[tuple[float, str]] = []
    for c in cards:
        if len(c) < 2:
            continue
        dur = max(float(c[-1]["end"]) - float(c[0]["start"]), 0.01)
        chars = sum(len(word_text(w, text_field)) for w in c)
        cps = chars / dur
        if cps > max_cps:
            treffer.append((cps, f"Zu schnell ({cps:.0f} Z/s): '{' '.join(word_text(w, text_field) for w in c)}'"))
    # Die schnellsten zuerst und hoechstens MAX_WARNUNGEN. Bei einem zuegigen Sprecher liegt die
    # halbe Folge ueber der Grenze; eine Liste mit vierhundert Eintraegen ist keine Aufgabenliste
    # mehr, sondern Rauschen. Wer die schlimmsten Stellen entschaerft, hat das Meiste getan.
    treffer.sort(key=lambda x: -x[0])
    return [t for _, t in treffer[:MAX_WARNUNGEN]]


def _fmt_t(t: float) -> str:
    h, rem = divmod(max(t, 0.0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def card_lines(
    card: list[dict], preset: CaptionPreset, text_field: str = "text", rules: CaptionRules | None = None
) -> list[list[tuple[dict, str]]]:
    """Zeilen einer Karte als Liste von (Wort, Textstück)-Paaren, inklusive Silbentrennung.

    ``all_caps`` wird hier angewendet und nicht erst beim Setzen: Grossbuchstaben brauchen mehr
    Platz, und die Silbentrennung muss mit der Form rechnen, die spaeter im Bild steht. Beim
    deutschen ``ß`` macht ``upper()`` daraus ``SS``, also ein Zeichen mehr - genau deshalb darf die
    Umwandlung nicht hinter der Laengenrechnung passieren.

    Mit AP10a geht ein Token aus Zahl plus Einheit als eine Umbrucheinheit an ``wrap_lines``, damit
    „40 Prozent" oder „14.30 Uhr" nie über zwei Zeilen verteilt werden."""
    rules = _rules(rules)
    if rules.enabled:
        return _card_lines_v2(card, preset, text_field, rules)
    pieces: list[tuple[dict, str]] = []
    for w in card:
        text = word_text(w, text_field)
        if preset.all_caps:
            text = text.upper()
        for piece in hyphenate(text, preset.max_chars, rules):
            pieces.append((w, piece))
    tokens = [p for _, p in pieces]
    lines_text = wrap_lines(tokens, preset.max_chars, preset.max_lines)
    lines: list[list[tuple[dict, str]]] = []
    k = 0
    for line in lines_text:
        n = len(line.split(" "))
        lines.append(pieces[k : k + n])
        k += n
    return lines


# Bindet die Wörter eines Tokens für ``wrap_lines`` zu einer Einheit (zählt wie ein Leerzeichen).
_TOKEN_JOINER = "\u00a0"


def _card_lines_v2(
    card: list[dict], preset: CaptionPreset, text_field: str, rules: CaptionRules
) -> list[list[tuple[dict, str]]]:
    units: list[list[tuple[dict, str]]] = []
    for tok in _tokens(card, text_field, rules, preset.max_chars, preset.all_caps):
        texts = [word_text(w, text_field) for w in tok]
        if preset.all_caps:
            texts = [t.upper() for t in texts]
        if len(tok) > 1:
            units.append(list(zip(tok, texts, strict=True)))
            continue
        units.extend([(tok[0], piece)] for piece in hyphenate(texts[0], preset.max_chars, rules))
    lines_text = wrap_lines(
        [_TOKEN_JOINER.join(piece for _, piece in u) for u in units], preset.max_chars, preset.max_lines
    )
    lines: list[list[tuple[dict, str]]] = []
    k = 0
    for line in lines_text:
        n = len(line.split(" "))
        lines.append([pair for u in units[k : k + n] for pair in u])
        k += n
    return lines


def _min_card_end(card: list[dict], end: float, next_card: float | None, rules: CaptionRules) -> float:
    """Ende einer Karte nach AP10a, nie über den Beginn der nächsten Karte und nie kürzer als das
    gesprochene Ende.

    Überbrückung zwischen Karten: ist die Lücke bis zur nächsten Karte höchstens ``bridge_max_s``,
    steht die Karte bis zu deren Start (jede Caption bis zur nächsten sichtbar, deckt die Presets mit
    einem Wort je Karte ab). Danach Mindestdauer ``min_event_s`` ab Kartenbeginn, nur für Karten mit
    mehreren Wörtern."""
    if not rules.enabled:
        return end
    if next_card is not None and next_card > float(card[-1]["start"]):
        if end > next_card:
            end = next_card  # ASR-Zeiten überlappen: nie in die nächste Karte hinein
        elif rules.bridge_words and next_card - end <= rules.bridge_max_s + BRIDGE_EPS:
            end = next_card
    if len(card) < 2 or rules.min_event_s <= 0:
        return end
    target = float(card[0]["start"]) + rules.min_event_s
    if next_card is not None:
        target = min(target, next_card)
    return max(end, target)


def _next_start(cards: list[list[dict]], i: int) -> float | None:
    return float(cards[i + 1][0]["start"]) if i + 1 < len(cards) else None


def to_ass(
    words: list[dict],
    clip_start: float = 0.0,
    preset: str | CaptionPreset = "tiktok_bold",
    play_res: tuple[int, int] = (W, H),
    font_family: str | None = None,
    text_field: str = "text",
    rules: CaptionRules | None = None,
) -> str:
    """ASS mit Wort-Highlight: pro Wort ein Event, aktives Wort eingefärbt (bei ``highlight_words``).

    ``play_res`` ist die Ausgabegröße; das Preset muss dazu passen (siehe ``scaled_preset``).
    ``font_family`` überschreibt den ``Fontname`` des Presets (Marken-Font aus ``brand_assets``).
    ``text_field`` wählt Original (``text``) oder normalisierte Form (``text_norm``, Fallback ``text``).

    ``rules`` (Standard: aktive Policy): mit AP10a endet ein Wort-Ereignis erst beim Start des
    nächsten Wortes, wenn die Lücke höchstens ``bridge_max_s`` beträgt; das gilt innerhalb einer
    Karte und vom letzten Wort einer Karte bis zum Start der nächsten. Eine Karte mit mehreren
    Wörtern steht mindestens ``min_event_s``, nie in die nächste Karte hinein.
    Stil, Farben und Text der Ereignisse bleiben gleich, nur die Zeiten ändern sich."""
    text_field = check_text_field(text_field)
    rules = _rules(rules)
    p = preset if isinstance(preset, CaptionPreset) else preset_for(preset)
    font = (font_family or "").strip() or p.font
    play_w, play_h = play_res
    margin_v = play_h - p.baseline_y
    border_style = 3 if p.box else 1
    # Ohne Kasten dient BackColour dem Schatten; mit Kasten ist es der Balken hinter dem Text.
    back = p.box_color if p.box else "&H64000000"
    head = (
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {play_w}\nPlayResY: {play_h}\nWrapStyle: 2\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, "
        "Alignment, MarginL, MarginR, MarginV, Outline, Shadow, BorderStyle\n"
        f"Style: Cap,{font},{p.font_px},{p.base_color},{p.outline_color},{back},{-1 if p.bold else 0},2,"
        f"{p.safe.left},{play_w - p.safe.right},{margin_v},{p.outline_px},0,{border_style}\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Text\n"
    )
    events = []
    cards = build_cards(words, p.max_chars, p.max_lines, text_field, p.words_per_card, p.all_caps, rules)
    for ci, card in enumerate(cards):
        lines = card_lines(card, p, text_field, rules)
        next_card = float(cards[ci + 1][0]["start"]) if ci + 1 < len(cards) else None
        if not p.highlight_words:
            s, e = float(card[0]["start"]), float(card[-1]["end"])
            e = _min_card_end(card, e, next_card, rules)
            text = NEWLINE.join(" ".join(_ass_escape(piece) for _, piece in ln) for ln in lines)
            events.append(f"Dialogue: 0,{_fmt_t(s - clip_start)},{_fmt_t(e - clip_start)},Cap,{text}")
            continue
        for j, w in enumerate(card):
            s, e = float(w["start"]), float(w["end"])
            if rules.bridge_words and j + 1 < len(card):
                nxt = float(card[j + 1]["start"])
                if s < nxt and nxt - e <= rules.bridge_max_s + BRIDGE_EPS:
                    e = nxt
            if j == len(card) - 1:
                e = _min_card_end(card, e, next_card, rules)
            s, e = s - clip_start, e - clip_start
            rendered = []
            for ln in lines:
                parts = [f"{{\\c{p.highlight_color if tw is w else p.base_color}}}{_ass_escape(piece)}" for tw, piece in ln]
                rendered.append(" ".join(parts))
            events.append(f"Dialogue: 0,{_fmt_t(s)},{_fmt_t(e)},Cap,{NEWLINE.join(rendered)}")
    return head + "\n".join(events) + "\n"


def beiblatt_karten(
    words: list[dict],
    preset: str | CaptionPreset | int | None = None,
    text_field: str = "text",
    rules: CaptionRules | None = None,
) -> tuple[list[list[dict]], int]:
    """Die Karten für die Beiblätter SRT und VTT, und die Zeilenbreite dazu.

    WARUM DAS EINE EIGENE FUNKTION IST: die eingebrannten Untertitel (ASS) und die Beiblätter
    wurden bisher verschieden gebaut. ``to_ass`` übergab dem Kartenbau das ganze Preset, ``to_srt``
    und ``to_vtt`` nur die Zeichenbreite. Bei ``tiktok_words`` - dem Stil, den jeder hochkante Clip
    bekommt - heisst das: im Bild steht ein Wort je Einblendung, in der SRT stehen ganze Sätze über
    zwei Zeilen. Zwei verschiedene Untertitel zu demselben Video, und niemand hat es gesehen, weil
    niemand beides gleichzeitig ansieht.

    Angeglichen werden Zeilenbreite und Zeilenzahl: davon hängt ab, wo umgebrochen wird, und das
    ist der sichtbare Unterschied.

    Nicht angeglichen wird ``words_per_card``. Eine Untertiteldatei mit einem Wort je Eintrag ist
    im Video richtig und als Datei unbrauchbar: YouTube, Vimeo und jeder Player zeigen sie so an,
    wie sie dasteht, und ein Wort im Sekundentakt liest niemand. Ebenso ``all_caps``: Grossschrift
    ist eine Gestaltung fürs Bild, Vorleseprogramme buchstabieren sie. Beides ist eine bewusste
    Entscheidung und keine Auslassung."""
    text_field = check_text_field(text_field)
    if isinstance(preset, int):
        # Alter Aufruf mit blosser Zeichenbreite. Bleibt lesbar und tut genau das, was er bisher
        # tat, damit ein vorhandener Aufruf nicht stillschweigend etwas anderes liefert.
        return build_cards(words, preset, PRESETS["tiktok_bold"].max_lines, text_field=text_field, rules=rules), preset
    p = (
        PRESETS["tiktok_bold"]
        if preset is None
        else preset
        if isinstance(preset, CaptionPreset)
        else preset_for(preset)
    )
    return build_cards(words, p.max_chars, p.max_lines, text_field=text_field, rules=rules), p.max_chars


def to_srt(
    words: list[dict], clip_start: float = 0.0, preset: str | CaptionPreset | int | None = None, text_field: str = "text"
) -> str:
    text_field = check_text_field(text_field)
    rules = caption_rules()
    karten, breite = beiblatt_karten(words, preset, text_field, rules)
    out = []
    for i, card in enumerate(karten, start=1):
        e = _min_card_end(card, float(card[-1]["end"]), _next_start(karten, i - 1), rules)
        s, e = float(card[0]["start"]) - clip_start, e - clip_start
        text = "\n".join(wrap_lines([word_text(w, text_field) for w in card], breite))
        out.append(f"{i}\n{_srt_t(s)} --> {_srt_t(e)}\n{text}\n")
    return "\n".join(out)


def _srt_t(t: float) -> str:
    ms = int(round(max(t, 0.0) * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _vtt_t(t: float) -> str:
    return _srt_t(t).replace(",", ".")


def to_vtt(
    words: list[dict], clip_start: float = 0.0, preset: str | CaptionPreset | int | None = None, text_field: str = "text"
) -> str:
    """WebVTT mit denselben Karten wie ``to_srt`` (Punkt statt Komma in den Zeiten, Kopfzeile WEBVTT)."""
    text_field = check_text_field(text_field)
    rules = caption_rules()
    karten, breite = beiblatt_karten(words, preset, text_field, rules)
    out = ["WEBVTT", ""]
    for i, card in enumerate(karten, start=1):
        e = _min_card_end(card, float(card[-1]["end"]), _next_start(karten, i - 1), rules)
        s, e = float(card[0]["start"]) - clip_start, e - clip_start
        text = "\n".join(wrap_lines([word_text(w, text_field) for w in card], breite))
        out.append(f"{i}\n{_vtt_t(s)} --> {_vtt_t(e)}\n{text}\n")
    return "\n".join(out)


def cards_for(
    words: list[dict], preset: str | CaptionPreset = "tiktok_bold", clip_start: float = 0.0, text_field: str = "text"
) -> list[dict]:
    """Karten als JSON für ``caption_versions.cards``: ``{start, end, lines}`` auf der Ausgabe-Timeline."""
    text_field = check_text_field(text_field)
    p = preset if isinstance(preset, CaptionPreset) else preset_for(preset)
    out = []
    rules = caption_rules()
    cards = build_cards(words, p.max_chars, p.max_lines, text_field, p.words_per_card, p.all_caps, rules)
    for ci, card in enumerate(cards):
        lines = [" ".join(piece for _, piece in ln) for ln in card_lines(card, p, text_field, rules)]
        # Mit AP10a dasselbe Kartenende wie im eingebrannten Video (Brücke, Mindestdauer).
        end = _min_card_end(card, float(card[-1]["end"]), _next_start(cards, ci), rules)
        out.append(
            {
                "start": round(float(card[0]["start"]) - clip_start, 3),
                "end": round(end - clip_start, 3),
                "lines": lines,
            }
        )
    return out


__all__ = [
    "AVG_CHAR_EM",
    "BREAK_WORDS",
    "COMPOUND_MEMBERS",
    "LEGACY_RULES",
    "UNIT_WORDS",
    "CaptionRules",
    "caption_rules",
    "MAX_CPS",
    "MAX_WARNUNGEN",
    "PLATFORM_DEFAULT_PRESET",
    "PRESETS",
    "TEXT_FIELDS",
    "CaptionPreset",
    "SafeZone",
    "build_cards",
    "card_lines",
    "cards_for",
    "check_text_field",
    "cps_warnings",
    "hyphenate",
    "max_chars",
    "preset_for",
    "safe_zone_margins",
    "scaled_preset",
    "to_ass",
    "beiblatt_karten",
    "sichtbare_woerter",
    "to_srt",
    "to_vtt",
    "word_text",
    "wrap_lines",
]
