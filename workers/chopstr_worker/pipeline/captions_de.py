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
from dataclasses import dataclass, field, replace

from .dach_nlp import NEGATIONS

W, H = 1080, 1920
NEWLINE = "\\N"  # ASS-Zeilenumbruch
AVG_CHAR_EM = 0.56  # mittlere Zeichenbreite in em für Inter Bold; pro Font messen
MAX_CPS = 17.0
# Hoechstens so viele Tempo-Hinweise je Clip, die schnellsten zuerst.
MAX_WARNUNGEN = 20
BREAK_WORDS = {"und", "aber", "weil", "dass", "denn", "oder", "wenn", "sondern", "also", "obwohl", "damit"}
TEXT_FIELDS = ("text", "text_norm")

def check_text_field(text_field: str | None) -> str:
    """``text`` oder ``text_norm``; alles andere ist ein Programmierfehler."""
    field_name = text_field or "text"
    if field_name not in TEXT_FIELDS:
        raise ValueError(f"Unbekanntes Caption-Textfeld {text_field!r} (erlaubt: {', '.join(TEXT_FIELDS)})")
    return field_name


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


def hyphenate(word: str, limit: int) -> list[str]:
    """Teilt ein zu langes Wort an Silben-/Morphemgrenzen (pyphen). Jede Zeile außer der letzten endet auf '-'."""
    if len(word) <= limit:
        return [word]
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


def build_cards(
    words: list[dict],
    limit: int | None = None,
    max_lines: int = 2,
    text_field: str = "text",
    words_per_card: int | None = None,
) -> list[list[dict]]:
    """Gruppiert Wörter zu Karten. Bricht an Satzzeichen, Konjunktionen, Pausen und vor langen Komposita.
    ``text_field`` bestimmt, welche Wortform Länge und Satzzeichen liefert (siehe ``word_text``).

    ``words_per_card`` schaltet auf feste Gruppengröße um: 1 bedeutet ein Wort je Einblendung, der
    Karaoke-Stil der Kurzformate. Satzzeichen bleiben am Wort, die Zeiten kommen unverändert aus dem
    Transkript. Ohne den Parameter gilt die sinngemäße Gruppierung."""
    if words_per_card and words_per_card > 0:
        return [words[i : i + words_per_card] for i in range(0, len(words), words_per_card)]
    limit = limit or PRESETS["tiktok_bold"].max_chars
    cap = limit * max_lines
    cards: list[list[dict]] = []
    cur: list[dict] = []
    cur_len = 0
    for i, w in enumerate(words):
        t = word_text(w, text_field)
        is_long = len(t) > limit
        if is_long and cur and cur_len > 8:
            cards.append(cur)
            cur, cur_len = [], 0
        starts_clause = t.lower().strip(",.") in BREAK_WORDS
        if cur and not is_long and (cur_len + len(t) + 1 > cap or (starts_clause and cur_len > 8)):
            cards.append(cur)
            cur, cur_len = [], 0
        cur.append(w)
        cur_len += len(t) + 1
        nxt = words[i + 1] if i + 1 < len(words) else None
        if is_long or t.endswith((".", "!", "?", ",")) or (nxt and float(nxt["start"]) - float(w["end"]) > 0.4):
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


def card_lines(card: list[dict], preset: CaptionPreset, text_field: str = "text") -> list[list[tuple[dict, str]]]:
    """Zeilen einer Karte als Liste von (Wort, Textstück)-Paaren, inklusive Silbentrennung.

    ``all_caps`` wird hier angewendet und nicht erst beim Setzen: Grossbuchstaben brauchen mehr
    Platz, und die Silbentrennung muss mit der Form rechnen, die spaeter im Bild steht. Beim
    deutschen ``ß`` macht ``upper()`` daraus ``SS``, also ein Zeichen mehr - genau deshalb darf die
    Umwandlung nicht hinter der Laengenrechnung passieren."""
    pieces: list[tuple[dict, str]] = []
    for w in card:
        text = word_text(w, text_field)
        if preset.all_caps:
            text = text.upper()
        for piece in hyphenate(text, preset.max_chars):
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


def to_ass(
    words: list[dict],
    clip_start: float = 0.0,
    preset: str | CaptionPreset = "tiktok_bold",
    play_res: tuple[int, int] = (W, H),
    font_family: str | None = None,
    text_field: str = "text",
) -> str:
    """ASS mit Wort-Highlight: pro Wort ein Event, aktives Wort eingefärbt (bei ``highlight_words``).

    ``play_res`` ist die Ausgabegröße; das Preset muss dazu passen (siehe ``scaled_preset``).
    ``font_family`` überschreibt den ``Fontname`` des Presets (Marken-Font aus ``brand_assets``).
    ``text_field`` wählt Original (``text``) oder normalisierte Form (``text_norm``, Fallback ``text``)."""
    text_field = check_text_field(text_field)
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
    for card in build_cards(words, p.max_chars, p.max_lines, text_field, p.words_per_card):
        lines = card_lines(card, p, text_field)
        if not p.highlight_words:
            s, e = float(card[0]["start"]) - clip_start, float(card[-1]["end"]) - clip_start
            text = NEWLINE.join(" ".join(_ass_escape(piece) for _, piece in ln) for ln in lines)
            events.append(f"Dialogue: 0,{_fmt_t(s)},{_fmt_t(e)},Cap,{text}")
            continue
        for w in card:
            s, e = float(w["start"]) - clip_start, float(w["end"]) - clip_start
            rendered = []
            for ln in lines:
                parts = [f"{{\\c{p.highlight_color if tw is w else p.base_color}}}{_ass_escape(piece)}" for tw, piece in ln]
                rendered.append(" ".join(parts))
            events.append(f"Dialogue: 0,{_fmt_t(s)},{_fmt_t(e)},Cap,{NEWLINE.join(rendered)}")
    return head + "\n".join(events) + "\n"


def to_srt(words: list[dict], clip_start: float = 0.0, limit: int | None = None, text_field: str = "text") -> str:
    text_field = check_text_field(text_field)
    out = []
    for i, card in enumerate(build_cards(words, limit, text_field=text_field), start=1):
        s, e = float(card[0]["start"]) - clip_start, float(card[-1]["end"]) - clip_start
        text = "\n".join(wrap_lines([word_text(w, text_field) for w in card], limit or PRESETS["tiktok_bold"].max_chars))
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


def to_vtt(words: list[dict], clip_start: float = 0.0, limit: int | None = None, text_field: str = "text") -> str:
    """WebVTT mit denselben Karten wie ``to_srt`` (Punkt statt Komma in den Zeiten, Kopfzeile WEBVTT)."""
    text_field = check_text_field(text_field)
    out = ["WEBVTT", ""]
    for i, card in enumerate(build_cards(words, limit, text_field=text_field), start=1):
        s, e = float(card[0]["start"]) - clip_start, float(card[-1]["end"]) - clip_start
        text = "\n".join(wrap_lines([word_text(w, text_field) for w in card], limit or PRESETS["tiktok_bold"].max_chars))
        out.append(f"{i}\n{_vtt_t(s)} --> {_vtt_t(e)}\n{text}\n")
    return "\n".join(out)


def cards_for(
    words: list[dict], preset: str | CaptionPreset = "tiktok_bold", clip_start: float = 0.0, text_field: str = "text"
) -> list[dict]:
    """Karten als JSON für ``caption_versions.cards``: ``{start, end, lines}`` auf der Ausgabe-Timeline."""
    text_field = check_text_field(text_field)
    p = preset if isinstance(preset, CaptionPreset) else preset_for(preset)
    out = []
    for card in build_cards(words, p.max_chars, p.max_lines, text_field, p.words_per_card):
        lines = [" ".join(piece for _, piece in ln) for ln in card_lines(card, p, text_field)]
        out.append(
            {
                "start": round(float(card[0]["start"]) - clip_start, 3),
                "end": round(float(card[-1]["end"]) - clip_start, 3),
                "lines": lines,
            }
        )
    return out


__all__ = [
    "AVG_CHAR_EM",
    "BREAK_WORDS",
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
    "to_srt",
    "to_vtt",
    "word_text",
    "wrap_lines",
]
