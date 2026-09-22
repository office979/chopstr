"""Caption-Engine für deutsche Short-Form-Clips (ASS/libass, eingebrannt via ffmpeg).

Regeln:
- Karten nach Bedeutung (Satzteile), nicht nach fixer Wortzahl
- Zeichen pro Zeile aus der Schriftgröße (``max_chars``), 1 bis 2 Zeilen, Lesetempo-Check (Zeichen/Sekunde)
- „nicht" (und andere Negationen) steht nie allein in einer neuen Zeile
- lange Komposita: eigene Karte; wenn breiter als die Zeile, Silbentrennung an Morphemgrenze (pyphen de_DE)
- Substantiv-Großschreibung bleibt (keine ALL-CAPS als Default)
- Presets mit Safe Zones pro Plattform (Pixel bei 1080x1920)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .dach_nlp import NEGATIONS

W, H = 1080, 1920
NEWLINE = "\\N"  # ASS-Zeilenumbruch
AVG_CHAR_EM = 0.56  # mittlere Zeichenbreite in em für Inter Bold; pro Font messen
MAX_CPS = 17.0
BREAK_WORDS = {"und", "aber", "weil", "dass", "denn", "oder", "wenn", "sondern", "also", "obwohl", "damit"}


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
    outline_px: int = 5
    box: bool = False
    bottom_margin_px: int = 260  # Abstand der Textunterkante zur Unterkante der Safe Zone
    highlight_words: bool = True
    all_caps: bool = False
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
    "linkedin_static": CaptionPreset(
        "linkedin_static", SafeZone(120, 1700, 80, W - 80), font_px=54, bold=False, outline_px=0, box=True,
        highlight_words=False, bottom_margin_px=200,
    ),
    "corporate_third": CaptionPreset(
        "corporate_third", SafeZone(120, 1700, 80, W - 80), font_px=48, bold=False, outline_px=0, box=True,
        highlight_words=False, max_lines=2, bottom_margin_px=160,
    ),
}
PLATFORM_DEFAULT_PRESET = {"tiktok": "tiktok_bold", "reels": "reels_clean", "shorts": "shorts_clean", "linkedin": "linkedin_static"}


def preset_for(name_or_platform: str) -> CaptionPreset:
    if name_or_platform in PRESETS:
        return PRESETS[name_or_platform]
    return PRESETS[PLATFORM_DEFAULT_PRESET.get(name_or_platform, "linkedin_static")]


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


def build_cards(words: list[dict], limit: int | None = None, max_lines: int = 2) -> list[list[dict]]:
    """Gruppiert Wörter zu Karten. Bricht an Satzzeichen, Konjunktionen, Pausen und vor langen Komposita."""
    limit = limit or PRESETS["tiktok_bold"].max_chars
    cap = limit * max_lines
    cards: list[list[dict]] = []
    cur: list[dict] = []
    cur_len = 0
    for i, w in enumerate(words):
        t = str(w["text"])
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


def cps_warnings(cards: list[list[dict]], max_cps: float = MAX_CPS) -> list[str]:
    out = []
    for c in cards:
        chars = sum(len(str(w["text"])) for w in c)
        dur = max(float(c[-1]["end"]) - float(c[0]["start"]), 0.01)
        if chars / dur > max_cps:
            out.append(f"Zu schnell ({chars / dur:.0f} Z/s): '{' '.join(str(w['text']) for w in c)}'")
    return out


def _fmt_t(t: float) -> str:
    h, rem = divmod(max(t, 0.0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def card_lines(card: list[dict], preset: CaptionPreset) -> list[list[tuple[dict, str]]]:
    """Zeilen einer Karte als Liste von (Wort, Textstück)-Paaren, inklusive Silbentrennung."""
    pieces: list[tuple[dict, str]] = []
    for w in card:
        for piece in hyphenate(str(w["text"]), preset.max_chars):
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


def to_ass(words: list[dict], clip_start: float = 0.0, preset: str | CaptionPreset = "tiktok_bold") -> str:
    """ASS mit Wort-Highlight: pro Wort ein Event, aktives Wort eingefärbt (bei ``highlight_words``)."""
    p = preset if isinstance(preset, CaptionPreset) else preset_for(preset)
    margin_v = H - p.baseline_y
    border_style = 3 if p.box else 1
    back = "&H80000000" if p.box else "&H64000000"
    head = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 2\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, "
        "Alignment, MarginL, MarginR, MarginV, Outline, Shadow, BorderStyle\n"
        f"Style: Cap,{p.font},{p.font_px},{p.base_color},&H00000000,{back},{-1 if p.bold else 0},2,"
        f"{p.safe.left},{W - p.safe.right},{margin_v},{p.outline_px},0,{border_style}\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Text\n"
    )
    events = []
    for card in build_cards(words, p.max_chars, p.max_lines):
        lines = card_lines(card, p)
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


def to_srt(words: list[dict], clip_start: float = 0.0, limit: int | None = None) -> str:
    out = []
    for i, card in enumerate(build_cards(words, limit), start=1):
        s, e = float(card[0]["start"]) - clip_start, float(card[-1]["end"]) - clip_start
        text = "\n".join(wrap_lines([str(w["text"]) for w in card], limit or PRESETS["tiktok_bold"].max_chars))
        out.append(f"{i}\n{_srt_t(s)} --> {_srt_t(e)}\n{text}\n")
    return "\n".join(out)


def _srt_t(t: float) -> str:
    ms = int(round(max(t, 0.0) * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


__all__ = [
    "AVG_CHAR_EM",
    "BREAK_WORDS",
    "MAX_CPS",
    "PLATFORM_DEFAULT_PRESET",
    "PRESETS",
    "CaptionPreset",
    "SafeZone",
    "build_cards",
    "card_lines",
    "cps_warnings",
    "hyphenate",
    "max_chars",
    "preset_for",
    "to_ass",
    "to_srt",
    "wrap_lines",
]
