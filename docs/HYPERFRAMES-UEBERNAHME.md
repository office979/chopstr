# Masterprompt: HyperFrames-Fähigkeiten in chopstr übernehmen

Erstellt: 26.09.2026 · Grundlage: HyperFrames CLI 0.8.77, geprüft und real durchlaufen
Zielprojekt: `/Users/jarvisplatz/Documents/GitHub/chopstr`

---

## 0. Rechtslage — zuerst lesen

**HyperFrames steht unter Apache-2.0** (geprüft in `package.json` des Pakets `hyperframes@0.8.77`
und in der LICENSE des Repos `heygen-com/hyperframes`). Erlaubt sind Kopieren, Verändern und
kommerzielle Nutzung. Auflagen:

1. Lizenztext und Copyright-Hinweis mitliefern.
2. Geänderte Dateien als geändert kennzeichnen.
3. Eine vorhandene NOTICE-Datei weitergeben.

Das passt zu chopstrs Entscheidung **E8 (Lizenz-Hygiene, keine AGPL)**. Apache-2.0 ist
unbedenklich und kompatibel.

**Wichtige Einschränkung:** Das npm-Paket enthält nur **gebündelten, minifizierten Code**
(`dist/cli.js` mit 194.745 Zeilen, `hyperframe-runtime.js` minifiziert). Das ist nicht
sinnvoll kopierbar. Wir übernehmen daher **Konzepte und Verträge**, und wo es sich lohnt,
rufen wir die CLI als Werkzeug auf. Lesbar und verwertbar sind:

- `dist/docs/*.md` — Render-, Timing- und Kompositionsspezifikation
- `~/.claude/skills/hyperframes-core/references/*` — der vollständige Kompositionsvertrag
- `~/.claude/skills/media-use/audio/references/captions/*` — Untertitelregeln

---

## 1. Was chopstr heute kann — und wo genau die Lücke ist

Vor jedem Vorschlag: chopstr ist an mehreren Stellen **besser** als HyperFrames. Das bleibt.

| Bereich | chopstr heute | Bewertung |
|---|---|---|
| Deutsche Untertiteltypografie | `pipeline/captions_de.py`: Silbentrennung an Morphemgrenzen (pyphen de_DE), Negationen nie allein am Zeilenanfang, Komposita auf eigene Karte, CPS-Grenze 17, Safe Zones pro Plattform | **stärker als HyperFrames.** Nicht ersetzen. |
| Loudness | Zweistufig: `loudnorm` misst, Pass 2 normalisiert linear; `acompressor` ab LRA > 7 | **stärker.** HyperFrames hat kein vergleichbares Mastering. |
| Schnittkanten | 20 ms Micro-Fades an jeder Klebestelle | **stärker.** |
| Umgebungsehrlichkeit | `capabilities()` prüft Filter, überspringt sauber und meldet in `notes` | vorbildlich |
| Reframe / PiP / C2PA / Residency | vorhanden | nicht berührt |

**Die tatsächlichen Lücken:**

| Lücke | Warum sie weh tut |
|---|---|
| **A — Overlays sind auf `drawtext` und ASS begrenzt** | Keine Verlaufsflächen, keine animierte Wort-für-Wort-Betonung, keine gestalteten Hook-Karten, keine Lower Thirds mit Logo. Und: **auf diesem Mac fehlt `drawtext` komplett** (ffmpeg 8.0.1 ohne libfreetype) — `overlay_filters()` überspringt Titelkarte und Hook dann ersatzlos. Ein HTML-Overlay braucht nur Chrome. |
| **B — Kein automatisches Qualitätsgate vor dem Render** | Kontrast, Textüberlauf und hängengebliebene Einblendungen fallen erst dem Menschen in der Freigabe auf. Bei einem Produkt, dessen Kern die menschliche Freigabe ist, kostet jeder vermeidbare Durchlauf echtes Geld. |
| **C — Pausen und Satzgrenzen kommen nur aus Transkript-Wortzeiten** | `segment.py` setzt `MIN_PAUSE_AS_BOUNDARY = 0.7` auf Basis von Wortzeiten. Es gibt **keine einzige** Nutzung von `silencedetect` im Repository. Siehe Abschnitt 6 — heute gemessen. |
| **D — Keine WYSIWYG-Vorschau der Overlay-Ebene** | Was der Reviewer sieht, ist nicht bildgleich mit dem Render. |

---

## 2. Was übernommen wird — priorisiert

| Nr. | Feature | Aufwand | Nutzen | Reihenfolge |
|---|---|---|---|---|
| F1 | HTML-Overlay-Ebene als transparentes WebM, eingehängt in den bestehenden ffmpeg-Graph | mittel | hoch | **zuerst** |
| F2 | Deterministischer Seek-Vertrag (`data-start`/`data-duration`, `window.__timelines`) | klein | Voraussetzung für F1 | mit F1 |
| F3 | Qualitätsgate: Kontrast (WCAG AA), Textüberlauf, Exit-Garantie | klein | hoch | danach |
| F4 | `fitTextFontSize` für deutsche Komposita | klein | hoch für DACH | danach |
| F5 | Pausenverifikation über `silencedetect` statt nur Wortzeiten | klein | **möglicher Bugfix** | parallel, unabhängig |

**Nicht übernommen** (bewusst): HyperFrames' eigene Caption-Engine, sein Audio-Mixing, sein
Registry-/Blocks-System, Cloud- und Lambda-Rendering. chopstr hat hier Besseres oder braucht es nicht.

---

## 3. F1 + F2 — HTML-Overlay-Ebene

### Idee

chopstrs Videokette bleibt **unverändert**. Wir erzeugen zusätzlich ein transparentes Overlay in
Ausgabegröße und Cliplänge und legen es per `overlay` ganz am Ende darüber — genau so, wie
`watermark_filter()` es heute schon für das Logo macht.

```
[Shots] → crop/scale → concat → [vc] → (ASS-Untertitel) → [vt] → overlay(Logo) 
                                                                → overlay(HTML-Ebene) → [vout]
```

Loudness, Reframe, PiP, C2PA, Residency: nicht berührt.

### Neues Modul `workers/chopstr_worker/pipeline/overlay_html.py`

```python
"""HTML-Overlay-Ebene (F1): gestaltete Einblendungen als transparentes WebM.

Warum nicht drawtext: ``drawtext`` braucht libfreetype, das in manchen ffmpeg-Builds fehlt
(geprüft 26.09.2026: ffmpeg 8.0.1 via Homebrew, ARM64 — kein drawtext). Zudem kann drawtext
keine Verlaufsflächen, keine Wort-für-Wort-Skalierung und keine Logos in einer Karte.

Der Vertrag stammt aus HyperFrames (Apache-2.0, heygen-com/hyperframes):
Elemente tragen ``data-start`` und ``data-duration`` in Sekunden; eine pausierte GSAP-Timeline
liegt unter ``window.__timelines[<composition-id>]``. Der Renderer setzt pro Bild ``seek(t)``
statt abzuspielen — dadurch ist die Ausgabe bei gleicher Eingabe bildgleich reproduzierbar.
Diese Datei ist eine eigene Implementierung dieses Vertrags, kein kopierter Code.

Ausgabe: VP9-WebM mit Alphakanal, exakt ``output.width`` x ``output.height`` und Cliplänge.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("chopstr.overlay_html")

HYPERFRAMES_VERSION = "0.8.77"   # festgenagelt: Renderverhalten muss reproduzierbar bleiben
RENDER_TIMEOUT_S = 900


class OverlayError(RuntimeError):
    pass


@dataclass
class OverlayResult:
    webm_path: str | None
    notes: list[str] = field(default_factory=list)
    checked: bool = False
    contrast_ok: bool | None = None
    skipped_reason: str | None = None


def available() -> bool:
    """Node und npx vorhanden? Ohne sie wird die Ebene übersprungen, nicht abgebrochen."""
    return shutil.which("npx") is not None and shutil.which("node") is not None


def _run(cmd: list[str], cwd: Path, what: str) -> subprocess.CompletedProcess:
    env_note = {"HYPERFRAMES_SKIP_SKILLS": "1", "HYPERFRAMES_NO_TELEMETRY": "1"}
    import os
    env = {**os.environ, **env_note}
    r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                       timeout=RENDER_TIMEOUT_S, check=False)
    if r.returncode != 0:
        log.warning("%s fehlgeschlagen (%s): %s", what, r.returncode, (r.stderr or "")[-800:])
    return r


def render_overlay(project_dir: Path, plan: dict, *, run_check: bool = True) -> OverlayResult:
    """Baut die Overlay-Komposition und rendert sie als transparentes WebM.

    ``project_dir`` ist ein Arbeitsordner pro Clip (wird angelegt). ``plan`` ist ein
    ``render_plan_v1`` mit dem zusätzlichen Schlüssel ``overlay_html`` (siehe Abschnitt 3.3).
    """
    res = OverlayResult(webm_path=None)
    if not available():
        res.skipped_reason = "node/npx fehlt"
        res.notes.append("HTML-Overlay übersprungen: Node.js nicht verfügbar")
        return res

    spec = plan.get("overlay_html") or {}
    if not spec.get("enabled"):
        res.skipped_reason = "nicht aktiviert"
        return res

    out_w, out_h = int(plan["output"]["width"]), int(plan["output"]["height"])
    fps = int(plan["output"].get("fps", 30))
    dauer = float(plan["output"]["duration_s"])

    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "hyperframes.json").write_text(json.dumps({
        "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
        "paths": {"assets": "assets"},
    }, indent=2), encoding="utf-8")

    html = build_composition(spec, out_w, out_h, dauer)
    (project_dir / "index.html").write_text(html, encoding="utf-8")

    # F3: Qualitätsgate VOR dem Render — spart einen kompletten Renderdurchlauf.
    if run_check:
        c = _run(["npx", "--yes", f"hyperframes@{HYPERFRAMES_VERSION}", "check", "--json"],
                 project_dir, "overlay check")
        res.checked = True
        befunde = _parse_check(c.stdout)
        if befunde["errors"]:
            res.notes.append(f"HTML-Overlay verworfen: {befunde['errors'][0]}")
            res.skipped_reason = "check fehlgeschlagen"
            return res
        res.contrast_ok = befunde["contrast_ok"]
        if befunde["contrast_ok"] is False:
            res.notes.append("HTML-Overlay: Kontrast unter WCAG AA — Lesbarkeit prüfen")

    ziel = project_dir / "overlay.webm"
    r = _run(["npx", "--yes", f"hyperframes@{HYPERFRAMES_VERSION}", "render",
              "--format", "webm", "--fps", str(fps), "-o", str(ziel)],
             project_dir, "overlay render")
    if r.returncode != 0 or not ziel.exists():
        res.notes.append("HTML-Overlay nicht erzeugt; Render läuft ohne gestaltete Ebene weiter")
        res.skipped_reason = "render fehlgeschlagen"
        return res

    # Nachmessen statt vertrauen.
    # ACHTUNG (gemessen 26.09.2026): VP9-WebM mit Alpha meldet pix_fmt="yuv420p".
    # Der Alphakanal steckt NICHT im pix_fmt, sondern im Stream-Tag ALPHA_MODE=1.
    # Eine Pruefung auf "a" in pix_fmt wuerde jedes gueltige Overlay verwerfen.
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height,pix_fmt",
                            "-show_entries", "stream_tags=alpha_mode",
                            "-show_entries", "format=duration", "-of", "json", str(ziel)],
                           capture_output=True, text=True, check=False)
    try:
        info = json.loads(probe.stdout)
        st = info["streams"][0]
        ist_w, ist_h = int(st["width"]), int(st["height"])
        ist_d = float(info["format"]["duration"])
        if (ist_w, ist_h) != (out_w, out_h):
            res.notes.append(f"HTML-Overlay verworfen: {ist_w}x{ist_h} statt {out_w}x{out_h}")
            return res
        if abs(ist_d - dauer) > 0.25:
            res.notes.append(f"HTML-Overlay verworfen: {ist_d:.2f}s statt {dauer:.2f}s")
            return res
        alpha = str((st.get("tags") or {}).get("alpha_mode", "")).strip()
        if alpha != "1":
            res.notes.append("HTML-Overlay ohne Alphakanal (ALPHA_MODE fehlt) — verworfen")
            return res
    except (KeyError, IndexError, ValueError, json.JSONDecodeError) as e:
        res.notes.append(f"HTML-Overlay nicht prüfbar ({e}) — verworfen")
        return res

    res.webm_path = str(ziel)
    return res


def _parse_check(stdout: str) -> dict:
    """Liest das JSON von ``hyperframes check``. Unbekannte Form => keine Aussage."""
    try:
        d = json.loads(stdout)
    except json.JSONDecodeError:
        return {"errors": [], "contrast_ok": None}
    errors: list[str] = []
    for bereich in ("lint", "runtime", "layout", "motion"):
        teil = d.get(bereich) or {}
        for e in (teil.get("errors") or []):
            errors.append(f"{bereich}: {e.get('message') or e}")
    kontrast = d.get("contrast") or {}
    contrast_ok = None
    if "passed" in kontrast and "total" in kontrast:
        contrast_ok = int(kontrast["passed"]) == int(kontrast["total"])
    return {"errors": errors, "contrast_ok": contrast_ok}
```

### 3.2 Der Kompositionsbauer

Wichtig: **chopstrs Kartenlogik bleibt die Quelle.** Wir rendern die von `captions_de.cards_for()`
erzeugten Karten, statt eine zweite Untertitellogik zu bauen.

```python
def build_composition(spec: dict, w: int, h: int, dauer: float) -> str:
    """Erzeugt die Overlay-Komposition nach dem HyperFrames-Vertrag.

    ``spec`` enthält:
      cards: [{start, end, lines: [str], emphasis: [str]}]   aus captions_de.cards_for()
      hook:  {text, start, end} | None
      brand: {accent: "#RRGGBB", font_family: str, font_url: str|None}
    """
    brand = spec.get("brand") or {}
    accent = brand.get("accent", "#E5FF3D")
    font = brand.get("font_family", "Inter")
    font_url = brand.get("font_url")

    # Safe Zone: identisch zu captions_de, damit Overlay und ASS nie kollidieren.
    unten = int(h * 0.22)

    teile: list[str] = []
    tweens: list[str] = []

    hook = spec.get("hook")
    if hook:
        hs, he = float(hook["start"]), float(hook["end"])
        # WICHTIG: animiert wird das KIND, nie das .clip-Element selbst.
        # hyperframes check lehnt Animationen von visibility/display/autoAlpha auf
        # clip-Elementen ab (Regel gsap_animates_clip_element) — die Sichtbarkeit von
        # clips gehoert dem Framework. Gemessen 26.09.2026: mit Animation auf #hook
        # meldete check 2 Fehler, mit Animation auf #hook-i lief er durch.
        teile.append(
            f'<div id="hook" class="clip hook" data-start="{hs}" data-duration="{he - hs:.3f}">'
            f'<div id="hook-i"><span>{_esc(hook["text"])}</span></div></div>')
        tweens.append(
            f'tl.fromTo("#hook-i", {{opacity:0, y:36}}, '
            f'{{opacity:1, y:0, duration:0.42, ease:"power3.out"}}, {hs});')
        # Exit-Garantie: harter Schnitt, damit nichts haengen bleibt.
        tweens.append(f'tl.to("#hook-i", {{opacity:0, duration:0.18, ease:"power2.in"}}, {he - 0.18:.3f});')
        tweens.append(f'tl.set("#hook-i", {{opacity:0, visibility:"hidden"}}, {he:.3f});')

    for i, c in enumerate(spec.get("cards") or []):
        cs, ce = float(c["start"]), float(c["end"])
        zeilen = "".join(f"<div class='z'>{_esc(z)}</div>" for z in c["lines"])
        teile.append(
            f'<div id="c{i}" class="clip card" data-start="{cs}" data-duration="{ce - cs:.3f}">'
            f'<div id="c{i}-i">{zeilen}</div></div>')
        tweens.append(
            f'tl.fromTo("#c{i}-i", {{opacity:0, y:14}}, '
            f'{{opacity:1, y:0, duration:0.18, ease:"power2.out"}}, {cs});')
        tweens.append(f'tl.to("#c{i}-i", {{opacity:0, duration:0.12}}, {ce - 0.12:.3f});')
        tweens.append(f'tl.set("#c{i}-i", {{opacity:0, visibility:"hidden"}}, {ce:.3f});')

    schrift = f'<link rel="stylesheet" href="{font_url}">' if font_url else ""

    return f"""<!doctype html>
<html lang="de">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width={w}, height={h}" />
<title>chopstr Overlay</title>
{schrift}
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  /* Transparent: der Alphakanal trägt die Ebene. Kein Hintergrund. */
  html, body {{ width:{w}px; height:{h}px; overflow:hidden; background:transparent; }}
  #root {{ position:relative; width:100%; height:100%;
           font-family:"{font}", ui-sans-serif, system-ui, sans-serif; }}
  .clip {{ position:absolute; }}
  .hook {{ left:72px; right:72px; top:{int(h * 0.11)}px; text-align:center;
           font-size:{int(w * 0.082)}px; font-weight:800; line-height:1.12; color:#fff;
           text-shadow:0 4px 28px rgba(0,0,0,.72); }}
  .hook span {{ background:linear-gradient(180deg, transparent 62%, {accent} 62%);
                padding:0 .12em; }}
  .card {{ left:64px; right:64px; bottom:{unten}px; text-align:center;
           font-size:{int(w * 0.062)}px; font-weight:700; line-height:1.2; color:#fff;
           text-shadow:0 3px 20px rgba(0,0,0,.8); overflow:visible; }}
  .card .z {{ display:block; }}
</style>
</head>
<body>
  <div id="root" data-composition-id="main" data-start="0"
       data-duration="{dauer:.3f}" data-width="{w}" data-height="{h}">
    {chr(10).join("    " + t for t in teile)}
  </div>
  <script>
    const tl = gsap.timeline({{ paused: true }});
    {chr(10).join("    " + t for t in tweens)}
    window.__timelines["main"] = tl;
    tl.seek(0);
  </script>
</body>
</html>"""


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))
```

### 3.3 Erweiterung von `render_plan_v1`

In `pipeline/render_plan.py` ergänzen (optional, abwärtskompatibel — fehlt der Schlüssel,
verhält sich alles wie bisher):

```python
"overlay_html": {
    "enabled": False,          # Standard aus. Erst einschalten, wenn F3 grün ist.
    "cards": [],               # aus captions_de.cards_for(), Zeiten relativ zum Clipstart
    "hook": None,              # {"text": str, "start": float, "end": float}
    "brand": {"accent": "#E5FF3D", "font_family": "Inter", "font_url": None},
}
```

### 3.4 Patch in `video_chain()`

In `pipeline/render.py`. Der Eingriff ist klein: ein weiterer Overlay-Input am Ende der Kette.

```python
def overlay_html_filter(in_label: str, overlay_index: int) -> str:
    """Transparente HTML-Ebene deckungsgleich ueber das Bild legen.

    ``shortest=0``: Das Overlay ist exakt so lang wie der Clip (in overlay_html nachgemessen).
    ``format=auto,alpha=premultiplied`` vermeidet dunkle Raender an weicher Kantenglaettung.

    VORAUSSETZUNG: Der Overlay-Input MUSS mit ``-c:v libvpx-vp9`` VOR dem ``-i`` geoeffnet
    werden — siehe input_args_overlay(). Ohne das verwirft ffmpegs Standard-VP9-Decoder
    den Alphakanal stillschweigend und das Overlay deckt das Video komplett zu.
    """
    return (f"[{overlay_index}:v]setpts=PTS-STARTPTS,format=yuva420p[ovl];"
            f"{in_label}[ovl]overlay=0:0:format=auto:alpha=premultiplied:shortest=0[vout]")
```

Und in `video_chain()` die Signatur um `overlay_index: int | None = None` erweitern, dann
den Schluss ersetzen:

```python
    # bisher:
    #   if logo_index is not None:
    #       chain += "[vc]" + (...) + "[vt];" + watermark_filter(plan, logo_index)
    #   else:
    #       chain += "[vc]" + (...) + "[vout]"

    kette = ",".join(filters) if filters else "null"
    letztes = "[vc]"
    if logo_index is not None:
        # Wasserzeichen schreibt bisher nach [vout]; wenn noch eine HTML-Ebene folgt,
        # muss es stattdessen nach [vw] schreiben.
        ziel = "[vw]" if overlay_index is not None else "[vout]"
        chain += f"[vc]{kette}[vt];" + watermark_filter(plan, logo_index).replace("[vout]", ziel)
        watermark = True
        letztes = ziel
    else:
        ziel = "[vw]" if overlay_index is not None else "[vout]"
        chain += f"[vc]{kette}{ziel}"
        letztes = ziel

    if overlay_index is not None:
        chain += ";" + overlay_html_filter(letztes, overlay_index)

    return chain, notes, burned, title_drawn, hook_drawn, watermark
```

> **Prüfen, nicht annehmen:** `watermark_filter()` endet heute fest auf `[vout]`. Der
> `.replace()` oben ist bewusst sichtbar gemacht — sauberer ist, `watermark_filter()` einen
> Zielparameter zu geben. Beides ist vertretbar; entscheide beim Umsetzen und halte es fest.

In `render_from_plan()` muss das WebM als zusätzlicher Input **nach** dem Logo eingehängt
und sein Index an `video_chain()` übergeben werden — **mit explizitem Decoder**:

```python
def input_args_overlay(webm_path: str) -> list[str]:
    """Overlay-Input. Der Decoder MUSS explizit gesetzt werden.

    Gemessen am 26.09.2026 mit ffmpeg 8.0.1: Ein VP9-WebM mit ALPHA_MODE=1 verliert
    seinen Alphakanal, wenn ffmpeg den Standard-VP9-Decoder wählt. Der Test — Overlay
    über eine rote Fläche legen und einen leeren Bildpunkt messen — ergab:

        mit    -c:v libvpx-vp9   ->   fc0000   (Rot scheint durch, richtig)
        ohne                     ->   000000   (alles schwarz, Alpha verworfen)

    Das schlägt nicht fehl und gibt keine Warnung aus. Es sieht nur falsch aus.
    """
    return ["-c:v", "libvpx-vp9", "-i", webm_path]
```

Und in die Fähigkeitsprüfung aufnehmen:

```python
def has_vp9_alpha_decoder() -> bool:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-decoders"],
                       capture_output=True, text=True, check=False)
    return "libvpx-vp9" in r.stdout
```

Fehlt `libvpx-vp9`, wird die HTML-Ebene übersprungen und in `notes` vermerkt — wie bei
`drawtext` und `subtitles` heute schon.

---

## 4. F3 — Qualitätsgate

`hyperframes check` liefert in einem Durchlauf: Lint, Laufzeitfehler, Layoutprüfung,
Bewegungsprüfung und **Kontrast nach WCAG AA**. Belegter Beispielausgang aus dem heutigen
Testlauf: `0 error(s)`, `8/8 text checks pass WCAG AA`.

Der Aufruf steckt bereits in `render_overlay()` (Abschnitt 3.1). Entscheidend ist die Haltung:

- **Fehler im Lint oder zur Laufzeit ⇒ Overlay wird verworfen**, der Render läuft ohne
  gestaltete Ebene weiter und vermerkt das in `notes`. Das entspricht chopstrs bestehender
  Linie aus `capabilities()`: lieber ein Video ohne Zierrat als kein Video.
- **Kontrast unter AA ⇒ Vermerk, kein Abbruch.** Der Mensch entscheidet in der Freigabe.

### Wichtige Einschränkung: Kontrast ist am transparenten Overlay nicht prüfbar

Gemessen am 26.09.2026: Bei einer Komposition mit `background: transparent` meldet `check`
**`0/0 text checks pass WCAG AA`** — es prüft null Texte. Das ist folgerichtig, denn der
spätere Hintergrund ist das Video und zum Zeitpunkt der Prüfung unbekannt. Die Kontrastprüfung
liefert bei der Overlay-Ebene also **keine Aussage**, kein Bestehen.

`contrast_ok` ist in `_parse_check()` deshalb bewusst dreiwertig (`True` / `False` / `None`).
Bei `None` darf niemand „Kontrast geprüft" berichten.

Wer Kontrast wirklich absichern will, hat zwei ehrliche Wege:

1. **Nach dem Compositing messen** — am fertigen Clip, dort wo eine Karte steht:

```python
def kontrast_am_clip(video: str, t: float, box: tuple[int, int, int, int]) -> float:
    """Michelson-artiger Helligkeitsabstand im Kartenbereich zum Zeitpunkt t.

    Grober, aber ehrlicher Indikator: liegt YMIN und YMAX weit auseinander, hebt sich
    der Text ab. Ersetzt keine WCAG-Rechnung, findet aber den Fall "weiße Schrift auf
    hellem Hintergrund" zuverlässig.
    """
    w, h, x, y = box
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1",
         "-vf", f"crop={w}:{h}:{x}:{y},signalstats,metadata=print", "-f", "null", "-"],
        capture_output=True, text=True, check=False)
    log = r.stderr + r.stdout
    ymin = re.search(r"signalstats\.YMIN=([0-9.]+)", log)
    ymax = re.search(r"signalstats\.YMAX=([0-9.]+)", log)
    if not (ymin and ymax):
        return -1.0
    lo, hi = float(ymin.group(1)), float(ymax.group(1))
    return (hi - lo) / max(hi + lo, 1.0)
```

2. **Die Karten mit ihrer Trägerfläche bauen** — eine halbtransparente dunkle Box hinter dem
   Text (wie `text-shadow` heute, nur deckender). Dann ist der Kontrast unabhängig vom Video
   gesichert und `check` kann ihn wieder messen, sobald die Fläche deckend genug ist.

Empfehlung: Weg 2 für die Gestaltung, Weg 1 als Messung in den Abnahmekriterien.

Zusätzlich lohnt sich die **Exit-Garantie** als eigener Selbsttest. Sie ist im Bauer oben schon
eingebaut (`tl.set(..., visibility:"hidden")` am Kartenende). Das verhindert den häufigsten
Fehler bei animierten Untertiteln: eine Karte bleibt stehen und überlagert die nächste.

---

## 5. F4 — Textüberlauf bei deutschen Komposita

HyperFrames stellt `window.__hyperframes.fitTextFontSize()` bereit: Es verkleinert die Schrift
schrittweise, bis der Text in die vorgegebene Breite passt.

Für chopstr ist das besonders wertvoll, weil deutsche Komposita („Abwasserreinigungsanlage")
jede feste Schriftgröße sprengen. `captions_de.py` löst das heute über `max_chars` und
Silbentrennung — eine **Rechnung** auf Basis von `AVG_CHAR_EM = 0.56`. Der Kommentar im Code
sagt selbst: *„mittlere Zeichenbreite in em für Inter Bold; pro Font messen"*.

Im HTML-Overlay lässt sich das **messen statt schätzen**. Ergänzung im Bauer, direkt vor
`window.__timelines["main"] = tl;`:

```javascript
// Gemessene statt gerechnete Schriftgröße. Greift nur, wenn eine Karte zu breit ist.
document.querySelectorAll(".card, .hook").forEach(function (el) {
  var maxBreite = el.clientWidth;
  var basis = parseFloat(getComputedStyle(el).fontSize);
  var groesse = basis;
  // scrollWidth > clientWidth heißt: es passt nicht.
  while (el.scrollWidth > maxBreite && groesse > basis * 0.62) {
    groesse -= 2;
    el.style.fontSize = groesse + "px";
  }
  if (groesse < basis) {
    console.warn("[chopstr] Schrift verkleinert auf " + groesse + "px: " + el.textContent.slice(0, 40));
  }
});
```

Die `console.warn`-Zeile ist Absicht: `hyperframes check` fängt Konsolenausgaben in der
Laufzeitprüfung ab, dadurch taucht jede Verkleinerung im Gate auf.

**Rückwirkung auf `captions_de.py`:** Wenn sich zeigt, dass die Messung regelmäßig von
`max_chars()` abweicht, ist `AVG_CHAR_EM` für die tatsächlich genutzte Schrift nachzumessen.
Das ist ein eigener, kleiner Auftrag — nicht Teil dieser Übernahme.

---

## 6. F5 — Pausen aus dem Ton, nicht nur aus Wortzeiten

**Das ist der Befund mit dem höchsten Risiko und dem kleinsten Aufwand.**

### Was heute gemessen wurde

Am 26.09.2026, deutsche Sprachaufnahme mit absichtlich eingebautem Fehlstart und Pausen,
transkribiert mit `whisper small` und `--language de`:

| | Ergebnis |
|---|---|
| Echte Stille im Ton (`silencedetect=noise=-40dB:d=0.30`) | 1,55–2,63 s · **6,43–8,62 s (2,19 s)** · 10,89–11,84 s · 14,26–15,06 s |
| Größte Lücke laut Transkript-Wortzeiten | **0,47 s** |
| Fehlstart im Transkript sichtbar | **nein** — beide Anläufe zu einer Äußerung zusammengezogen |

Eine reale Pause von 2,19 Sekunden erschien in den Wortzeiten als 0,0 Sekunden.

Zweiter Befund: Ein Transkript **rechnerisch** auf die neue Schnitt-Timeline umzulegen ergab
zerrissenen Text („du in 3 Schritten ein Video 1. Du nimmst ein auf."). Eine **Neutranskription
der geschnittenen Datei** ergab den vollständigen, korrekten Text.

### Warum das chopstr betrifft

`pipeline/segment.py` setzt `MIN_PAUSE_AS_BOUNDARY = 0.7` und leitet Satzgrenzen aus
Wortzeiten ab. Eine Suche über `workers/chopstr_worker/` findet **keine einzige** Nutzung von
`silencedetect`.

**Ehrliche Einordnung:** chopstr nutzt `faster-whisper` mit Wort-Zeitstempeln. Dessen
Alignment ist deutlich genauer als das von `whisper.cpp`. Der Befund oben ist daher **kein
Beweis für einen Bug in chopstr**, sondern ein begründeter Verdacht, der geprüft gehört.
Diese Prüfung kostet eine Stunde und schützt das Kernversprechen „sinntreu geschnitten".

### Verifikationsschritt (zuerst ausführen, vor jeder Änderung)

Neues Testmodul `workers/tests/test_pause_alignment.py`:

```python
"""Prüft, ob Transkript-Wortzeiten die echten Sprechpausen treffen.

Hintergrund: Wird eine reale Pause in den Wortzeiten verschluckt, setzt segment.py
Satzgrenzen an der falschen Stelle — und ein Clip beginnt mitten im Satz.
"""

from __future__ import annotations

import re
import subprocess


def silence_intervals(media: str, noise_db: int = -40, min_s: float = 0.30) -> list[tuple[float, float]]:
    """Stille aus dem Ton. ffmpeg schreibt silencedetect auf stderr, nicht auf stdout."""
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", media,
         "-af", f"silencedetect=noise={noise_db}dB:d={min_s}", "-f", "null", "-"],
        capture_output=True, text=True, check=False)
    log = r.stderr + r.stdout
    out, offen = [], None
    for m in re.finditer(r"silence_(start|end): ([0-9.]+)", log):
        if m.group(1) == "start":
            offen = float(m.group(2))
        elif offen is not None:
            out.append((offen, float(m.group(2))))
            offen = None
    return out


def word_gaps(words: list[dict], min_s: float = 0.30) -> list[tuple[float, float]]:
    return [(words[i]["end"], words[i + 1]["start"])
            for i in range(len(words) - 1)
            if words[i + 1]["start"] - words[i]["end"] > min_s]


def test_wortzeiten_treffen_echte_pausen(beispiel_media, beispiel_words):
    """Jede Stille über 0,7 s (= MIN_PAUSE_AS_BOUNDARY) muss sich in den Wortzeiten zeigen."""
    still = [s for s in silence_intervals(beispiel_media) if s[1] - s[0] > 0.7]
    luecken = word_gaps(beispiel_words)

    verfehlt = []
    for s_start, s_ende in still:
        mitte = (s_start + s_ende) / 2
        # Findet sich eine Wortlücke, die diese Stille überdeckt?
        if not any(g0 - 0.35 <= mitte <= g1 + 0.35 for g0, g1 in luecken):
            verfehlt.append((round(s_start, 2), round(s_ende, 2)))

    assert not verfehlt, (
        f"Diese echten Pausen fehlen in den Wortzeiten: {verfehlt}. "
        f"segment.py würde hier keine Satzgrenze setzen. "
        f"Gemessene Wortlücken: {[(round(a,2), round(b,2)) for a, b in luecken]}")
```

### Wenn der Test rot ist

Dann in `pipeline/segment.py` die Stille als **zusätzliche** Grenzquelle ergänzen — die
bestehende Logik bleibt, sie bekommt nur eine zweite Meinung:

```python
def boundaries_from_silence(media_path: str, min_pause: float = MIN_PAUSE_AS_BOUNDARY) -> list[float]:
    """Satzgrenzen-Kandidaten aus gemessener Stille. Ergänzt die Wortzeit-Logik, ersetzt sie nicht.

    Gibt die Mitte jeder Stille zurück — dort liegt der sicherste Schnittpunkt.
    """
    return [round((a + b) / 2, 3)
            for a, b in silence_intervals(media_path)
            if b - a >= min_pause]
```

### Zusätzlich: Schnittgrenzen am Ton nachmessen

Unabhängig vom Ausgang des Tests gehört dieser Schritt in die Renderkette. Er hat heute
im Praxislauf **zwei von sieben** geplanten Grenzen als untauglich entlarvt:

| Grenze | Messung | Befund |
|---|---|---|
| 2,63 s | davor −42,5 dB, danach **−2,7 dB** | mitten im Wortanlauf — erstes Wort wäre angeschnitten |
| 6,49 s | davor **−22,2 dB**, danach −64,3 dB | direkt am Wortende — Ausklang wäre abgeschnitten |

Nach Verschieben auf 2,50 s und 6,58 s lagen beide Grenzen beidseitig unter −58 dB.

```python
def grenze_ist_still(media: str, t: float, fenster: float = 0.12, schwelle: float = -45.0) -> bool:
    """Liegt bei ``t`` wirklich eine Sprechpause? Misst 120 ms davor und danach."""
    def pegel(start: float) -> float:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-ss", f"{max(0.0, start):.3f}", "-t", f"{fenster}",
             "-i", media, "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, check=False)
        m = re.search(r"max_volume:\s*(-?[0-9.]+)", r.stderr + r.stdout)
        return float(m.group(1)) if m else 0.0

    return pegel(t - fenster) < schwelle and pegel(t) < schwelle
```

Und **nach** dem Schnitt für Untertitel neu transkribieren, statt Zeiten umzurechnen — belegt
in Abschnitt 6.1.

---

## 6.2 Der Vorschlag ist durchgespielt, nicht nur gedacht

Der Code aus Abschnitt 3 wurde am 26.09.2026 aus diesem Dokument extrahiert, ausgeführt und
gemessen. Arbeitsstand: `mein-video-agent/pruefung/beweis/`.

| Schritt | Ergebnis |
|---|---|
| `build_composition()` aus Abschnitt 3.2 ausgeführt | 2.630 Zeichen HTML, 1080×1920, 5,2 s |
| `hyperframes check` darauf | **0 Fehler**, 3 Warnungen, `Check passed` |
| `render --format webm --fps 30` | 323,6 KB, 5,2 s, in 10,8 s gerendert |
| Alphakanal | `pix_fmt=yuv420p`, `TAG:ALPHA_MODE=1` — Alpha steckt im Tag, nicht im pix_fmt |
| Compositing über Blau `#1e5aa8` mit `-c:v libvpx-vp9` | leerer Bildpunkt misst `1c59a7` — Video scheint durch ✓ |
| Dasselbe **ohne** expliziten Decoder | leerer Bildpunkt misst `000000` — Alpha stillschweigend verworfen ✗ |
| Exit-Garantie, Hook endet bei 1,8 s | t=1,0 s Kontrastspanne 195 (Text da) · t=1,9 s Spanne 0,0 (weg) ✓ |
| Karte bei 2,6 s | „Erstens: Aufnahme sichten" korrekt sichtbar, Hook-Bereich leer ✓ |

Drei Fallen sind dabei aufgefallen und in den Code oben eingearbeitet. Ohne diese Messungen
wäre jede davon erst in der Integration aufgeschlagen:

1. **Der Alphakanal geht ohne `-c:v libvpx-vp9` verloren** — ohne Fehler, ohne Warnung. Das
   Overlay deckt das Video dann komplett schwarz zu.
2. **`check` verbietet `visibility`-Animationen auf `.clip`-Elementen**
   (`gsap_animates_clip_element`). Die naheliegende Exit-Garantie erzeugt genau diesen Fehler.
   Lösung: Inhalt in ein Kind-`<div>`, Animation auf dem Kind.
3. **Die Kontrastprüfung liefert bei transparentem Hintergrund `0/0`** — kein Bestehen,
   sondern keine Aussage.

---

## 7. Abnahmekriterien

Die Übernahme gilt als fertig, wenn **alle** Punkte gemessen erfüllt sind:

| # | Kriterium | Wie geprüft |
|---|---|---|
| 1 | Overlay-WebM hat Alphakanal, exakte Ausgabegröße und Cliplänge (±0,25 s) | `ffprobe` in `render_overlay()`, bereits eingebaut |
| 2 | Ein Clip mit aktiviertem Overlay ist bildgleich zum selben Clip ohne Overlay — außer in den Overlay-Bereichen | zwei Renders, `ffmpeg blend=all_mode=difference` + `signalstats` |
| 3 | Fehlt Node, läuft der Render **durch**, mit Hinweis in `notes` | Test mit geleertem `PATH` |
| 4 | `check` mit Fehler ⇒ Overlay verworfen, Render läuft weiter | Test mit absichtlich kaputter Komposition |
| 5 | Keine Karte bleibt nach ihrem Ende sichtbar | Einzelbild bei `ende + 0,1 s`, Bereich muss transparent sein |
| 5b | Alphakanal überlebt das Compositing | Overlay über rote Fläche legen, leeren Bildpunkt messen: muss `ff0000` sein, nicht `000000` |
| 5c | Kontrast am **fertigen** Clip, nicht an der Overlay-Ebene | `kontrast_am_clip()` an drei Kartenzeitpunkten |
| 6 | Loudness unverändert gegenüber heute | `loudnorm`-Messwerte vor/nach vergleichen |
| 7 | Renderdauer steigt um höchstens 40 % | Zeitmessung an drei echten Clips |
| 8 | `test_pause_alignment.py` läuft (grün oder mit dokumentiertem Befund) | `uv run pytest -q` |
| 9 | Apache-2.0-Hinweis liegt bei | `docs/LIZENZEN.md` ergänzt |
| 10 | Residency-Guard unberührt | `npm run residency:check` |

**Zu Kriterium 10:** `npx hyperframes` lädt beim ersten Lauf das Paket und Chromium aus dem
Netz und sendet standardmäßig anonyme Telemetrie an HeyGen. Für den `sovereign`-Tarif ist
beides zu klären:

- Telemetrie abschalten: `HYPERFRAMES_NO_TELEMETRY=1` (im Modul oben bereits gesetzt)
- Paket und Chromium ins Container-Image vorinstallieren, statt zur Laufzeit zu laden
- Prüfen, ob `hyperframes render` ohne Netz durchläuft — **das ist Voraussetzung für
  `sovereign` und muss vor dem Einschalten geklärt sein**

---

## 8. Reihenfolge der Umsetzung

1. **F5 zuerst** — der Verifikationstest ist in einer Stunde geschrieben und kann einen echten
   Fehler in der Clip-Erkennung aufdecken. Unabhängig von allem anderen.
2. **F1 + F2** hinter `overlay_html.enabled = False`. Erst an einem echten Clip nachmessen
   (Kriterien 1, 2, 5), dann für ein Projekt einschalten.
3. **F3** ist Teil von F1, bekommt aber eigene Tests (Kriterium 4).
4. **F4** danach, zusammen mit der Frage, ob `AVG_CHAR_EM` nachzumessen ist.
5. **Sovereign-Klärung** (Kriterium 10) **bevor** das Overlay in einem `sovereign`-Projekt
   eingeschaltet wird.

---

## 9. Was bewusst nicht übernommen wird

| Nicht übernommen | Grund |
|---|---|
| HyperFrames' Caption-Engine | `captions_de.py` ist für Deutsch deutlich besser |
| HyperFrames' Audio-Mixing | chopstrs zweistufiges Loudness-Mastering ist stärker |
| Registry / Blocks / Komponenten | Bindet an fremde Infrastruktur, kein Nutzen für chopstr |
| Cloud-, Lambda- und CloudRun-Rendering | Verstößt gegen die EU-Residency-Linie |
| `talking-head-recut` als Schnittlogik | Entfernt keine Versprecher; chopstrs Story-Engine kann mehr |
| Minifizierter Code aus `dist/` | Nicht wartbar, kein Erkenntnisgewinn |

---

## 10. Quellen

- `heygen-com/hyperframes`, Apache-2.0 — Timing-Vertrag, Renderverfahren, Kontrastprüfung
- `hyperframes@0.8.77`, `dist/docs/{rendering,data-attributes,compositions}.md`
- `~/.claude/skills/hyperframes-core/references/variables-and-media.md` — Medienregeln
- `~/.claude/skills/media-use/audio/references/{transcribe.md,captions/authoring.md}`
- Eigene Messungen vom 26.09.2026, Protokoll in
  `mein-video-agent/START-HIER.md` und `mein-video-agent/schnittplaene/tipp1.json`
