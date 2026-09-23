"""Reframing als „virtuelle Kamera" (Phase 3): Schnitt zwischen Sprechern, kein Wackel-Pan.

Strategien (Vertrag ``packages/schema/CLIPS.md``):
- ``talking_head``: eine Sitzposition, ruhiger Crop auf die Position, Augen im oberen Drittel
  (Gesichtsmitte bei ``EYE_LINE`` = 37 % der Ausgabehöhe).
- ``two_speakers``: zwei oder mehr Positionen, Schnitt auf den aktiven Sprecher (Diarisierung),
  Mindestlänge pro Shot ``MIN_SHOT_S``, ``speaker_positions`` bestimmt die Zuordnung.
- ``neutral``: keine Gesichter oder kein Detektor, mittiger Crop; im Plan sichtbar (``detector = "none"``).
- ``slide_pip`` (Phase 5c): Folie oder Bildschirmfreigabe oben (auf volle Ausgabebreite skaliert, höchstens
  ``SLIDE_MAX_HEIGHT_RATIO`` der Ausgabehöhe), Sprecher unten als Bild-im-Bild (Talking-Head-Regel auf die
  Restfläche, ohne Gesicht neutral). ``detect_slide_region`` sucht mit OpenCV das größte Rechteck aus
  Rasterzellen mit geringer Bewegung und hoher Kantendichte, das über mindestens ``SLIDE_STABLE_RATIO`` der
  abgetasteten Frames stabil ist. Ohne OpenCV oder mit ``confidence < SLIDE_MIN_CONFIDENCE`` bleibt es beim
  Fallback mit Hinweis; ``clips.reframe_override`` erzwingt eine Strategie je Clip.

DSGVO-Design: nur Gesichts-DETEKTION (Position), keine Erkennung (Identität), keine Embeddings.
YuNet (OpenCV, Apache-2.0) läuft nur, wenn ``YUNET_MODEL_PATH`` auf eine Datei zeigt und OpenCV
importierbar ist. OpenCV wird ausschließlich innerhalb der Funktionen importiert.
``plan_shots_for_positions`` ist eine reine Planungsfunktion und ohne Video testbar.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field

from . import tracking

SAMPLE_FPS = 5
MIN_SHOT_S = 1.2  # kürzer wirkt hektisch
EYE_LINE = 0.37  # Gesichtsmitte bei 37 % der Ausgabehöhe (Augen im oberen Drittel)
REFRAME_VERSION = "reframe_v1"

STRATEGIES = ("talking_head", "two_speakers", "neutral", "slide_pip")
DEFAULT_YUNET_MODEL = "models/face_detection_yunet_2023mar.onnx"
ASPECTS = {"9:16": (9, 16), "4:5": (4, 5), "1:1": (1, 1), "16:9": (16, 9)}

# Folien-Crop (Phase 5c). Schwellen: Bewegung als mittlere absolute Graustufendifferenz (0 bis 255) je Zelle
# zwischen zwei Abtastframes, Kantendichte als Anteil der Canny-Kantenpixel je Zelle.
SLIDE_GRID = (16, 9)  # Rasterzellen (Spalten, Zeilen)
SLIDE_SAMPLE_FPS = 1.0
SLIDE_MAX_FRAMES = 90  # Obergrenze abgetasteter Frames je Clip (bei langen Clips wird ausgedünnt)
SLIDE_ANALYSIS_WIDTH = 640  # Frames werden vor der Analyse auf diese Breite verkleinert
SLIDE_MOTION_MAX = 4.0  # Zelle gilt als ruhig, wenn die mittlere Differenz darunter liegt
SLIDE_EDGE_MIN = 0.015  # mittlere Kantendichte über das Rechteck (Folien haben Text und Linien, Wände nicht)
SLIDE_STABLE_RATIO = 0.6  # Zelle muss in mindestens 60 % der Framepaare ruhig sein
SLIDE_MIN_AREA = 0.25  # Rechteck mindestens 25 % der Bildfläche
SLIDE_MIN_CONFIDENCE = 0.6  # darunter kein automatisches slide_pip
SLIDE_ASPECT_RANGE = (0.75, 2.6)  # Breite/Höhe des Rechtecks: halbes 16:9-Bild (0,89) bis 21:9, keine schmalen Streifen
SLIDE_MAX_HEIGHT_RATIO = 0.55  # Folie belegt höchstens 55 % der Ausgabehöhe
SLIDE_CAPTION_GAP_RATIO = 0.02  # Abstand der Caption-Safe-Zone unter der Folie (Anteil der Ausgabehöhe)
SLIDE_NEUTRAL_STRIP_MIN = 0.2  # Reststreifen neben der Folie zählt erst ab 20 % der Quellbreite als Sprecherfläche


def yunet_model_path() -> str:
    return os.environ.get("YUNET_MODEL_PATH", "").strip() or DEFAULT_YUNET_MODEL


def detector_available() -> tuple[bool, str]:
    """(verfügbar, Grund). Der Grund erklärt in einem Satz, was fehlt (Modelldatei oder OpenCV)."""
    path = yunet_model_path()
    if not os.path.isfile(path):
        return False, f"YuNet-Modell fehlt ({os.path.basename(path)}), Reframe läuft neutral"
    try:
        import cv2  # noqa: F401
    except ImportError:
        return False, "OpenCV nicht installiert (Extra 'vision'), Reframe läuft neutral"
    return True, ""


def slide_detector_available() -> tuple[bool, str]:
    """(verfügbar, Grund) für die Folienerkennung: braucht nur OpenCV, kein Modell."""
    try:
        import cv2  # noqa: F401
    except ImportError:
        return False, "OpenCV nicht installiert (Extra 'vision'), keine Folienerkennung"
    return True, ""


@dataclass
class SlideRegion:
    """Erkanntes Folien- oder Bildschirmrechteck im Quellframe (Pixel, gerade Kanten)."""

    x: int
    y: int
    w: int
    h: int
    confidence: float
    stability: float = 0.0  # mittlerer Anteil ruhiger Framepaare über die Zellen des Rechtecks
    area_ratio: float = 0.0  # Anteil an der Bildfläche
    frames_sampled: int = 0

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h, "confidence": round(float(self.confidence), 3)}


@dataclass
class Shot:
    start: float
    end: float
    crop_x: int  # linke Kante des Ausschnitts im Quellframe
    crop_y: int  # obere Kante des Ausschnitts im Quellframe
    crop_w: int
    crop_h: int
    layout: str = "single"  # "single" | "split" | "pip" (Sprecher-Crop unter der Folie)

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        d = asdict(self)
        d["start"], d["end"] = round(self.start, 3), round(self.end, 3)
        return d


@dataclass
class ReframeResult:
    strategy: str
    detector: str  # "yunet" | "none"
    faces_detected: bool
    positions: list[float]  # x-Zentren der Sitzpositionen im Quellframe
    shots: list[Shot]
    src_w: int
    src_h: int
    out_w: int
    out_h: int
    min_shot_s: float = MIN_SHOT_S
    face_y: list[float] = field(default_factory=list)  # y-Zentren, parallel zu positions
    speaker_positions: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    slide_region: SlideRegion | None = None  # erkannte Folie (auch wenn nicht genutzt)
    pip: dict | None = None  # Sprecherfläche in der Ausgabe {x, y, w, h}, nur bei slide_pip
    override: str | None = None  # clips.reframe_override, falls gesetzt

    def plan_block(self) -> dict:
        """Block ``reframe`` des Render-Plans. ``slide_region`` und ``pip`` nur bei ``slide_pip``."""
        block = {
            "strategy": self.strategy,
            "detector": self.detector,
            "faces_detected": self.faces_detected,
            "positions": [round(float(p), 1) for p in self.positions],
            "min_shot_s": self.min_shot_s,
        }
        if self.strategy == "slide_pip" and self.slide_region is not None and self.pip is not None:
            block["slide_region"] = self.slide_region.to_dict()
            block["pip"] = {k: int(self.pip[k]) for k in ("x", "y", "w", "h")}
        if self.override:
            block["override"] = self.override
        return block

    def shots_json(self) -> list[dict]:
        return [s.to_dict() for s in self.shots]


def aspect_ratio(aspect: str) -> float:
    if aspect not in ASPECTS:
        raise ValueError(f"Unbekanntes Seitenverhältnis {aspect!r}")
    w, h = ASPECTS[aspect]
    return w / h


def _even(n: float) -> int:
    """Auf die nächste gerade Zahl abrunden (Codecs brauchen gerade Kanten)."""
    return int(n) // 2 * 2


def crop_geometry(src_w: int, src_h: int, out_w: int, out_h: int) -> tuple[int, int]:
    """(crop_w, crop_h) im Quellframe: größter Ausschnitt mit dem Ziel-Seitenverhältnis, gerade Zahlen."""
    ratio = out_w / out_h
    if src_w / src_h >= ratio:
        crop_h = _even(src_h)
        crop_w = _even(crop_h * ratio)
    else:
        crop_w = _even(src_w)
        crop_h = _even(crop_w / ratio)
    return max(2, min(crop_w, _even(src_w))), max(2, min(crop_h, _even(src_h)))


def crop_origin(src_w: int, src_h: int, crop_w: int, crop_h: int, face_cx: float | None, face_cy: float | None) -> tuple[int, int]:
    """Linke obere Ecke des Ausschnitts: horizontal auf das Gesicht zentriert, vertikal so, dass die
    Gesichtsmitte bei ``EYE_LINE`` der Ausgabehöhe liegt. Ohne Gesicht: mittig, bei Vollhöhe oben (crop_y 0)."""
    x = (src_w - crop_w) / 2 if face_cx is None else face_cx - crop_w / 2
    if face_cy is None:
        y = 0.0 if crop_h >= src_h else (src_h - crop_h) / 2
    else:
        y = face_cy - EYE_LINE * crop_h
    x = int(max(0, min(round(x), src_w - crop_w)))
    y = int(max(0, min(round(y), src_h - crop_h)))
    return x, y


def detect_faces(video_path: str, t0: float, t1: float) -> list[tuple[float, list[tuple[int, int, int, int]]]]:
    """Gesichtsboxen (x, y, w, h) pro Abtastzeitpunkt. Benötigt opencv-python-headless und das YuNet-Modell."""
    import cv2

    model = yunet_model_path()
    if not os.path.isfile(model):
        raise FileNotFoundError(f"YuNet-Modell fehlt: {model}")
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    det = cv2.FaceDetectorYN.create(model, "", (w, h), 0.7)
    out, t = [], t0
    while t < t1:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
        ok, frame = cap.read()
        if not ok:
            break
        _, faces = det.detect(frame)
        boxes = [tuple(map(int, f[:4])) for f in (faces if faces is not None else [])]
        out.append((t, boxes))
        t += 1 / SAMPLE_FPS
    cap.release()
    return out


def abtasten(video_path: str, t0: float, t1: float) -> list[tracking.Abtastung]:
    """Ein Durchlauf über den Abschnitt: Gesichter, Bildwechsel und Mundbewegung zugleich.

    Drei Messungen in einem Durchgang, weil jedes Aufsetzen der Leseposition teuer ist:

    GESICHTER wie bisher über YuNet.

    BILDWECHSEL als Abstand der Farbverteilung zum vorigen Abtastpunkt. Ein Kameraschnitt ändert
    das Histogramm sprunghaft, eine Bewegung im Bild nicht. Das ist das Signal, an dem Einstellungen
    getrennt werden; ohne es werden Gesichter aus unvereinbaren Einstellungen vermischt.

    MUNDBEWEGUNG als Änderung im unteren Teil jeder Gesichtsbox. Wer spricht, bewegt dort etwas.
    Verglichen wird mit demselben Bildbereich des vorigen Abtastpunkts, deshalb ist der Wert
    unmittelbar nach einem Schnitt bedeutungslos und wird verworfen.
    """
    import cv2
    import numpy as np

    model = yunet_model_path()
    if not os.path.isfile(model):
        raise FileNotFoundError(f"YuNet-Modell fehlt: {model}")
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    det = cv2.FaceDetectorYN.create(model, "", (w, h), 0.7)

    out: list[tracking.Abtastung] = []
    vor_hist = None
    vor_grau = None
    t = t0
    while t < t1:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
        ok, frame = cap.read()
        if not ok:
            break
        _, faces = det.detect(frame)
        boxen = [tuple(map(int, f[:4])) for f in (faces if faces is not None else [])]

        klein = cv2.resize(frame, (160, 90))
        hist = cv2.calcHist([klein], [0, 1, 2], None, [8, 8, 8], [0, 256] * 3)
        cv2.normalize(hist, hist)
        wechsel = None if vor_hist is None else float(1.0 - cv2.compareHist(vor_hist, hist, cv2.HISTCMP_CORREL))

        grau = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        munde: list[float] = []
        if vor_grau is not None and (wechsel is None or wechsel < tracking.SCHNITT_SCHWELLE):
            for x, y, bw, bh in boxen:
                # Unteres Drittel der Box, waagerecht auf die Mitte beschränkt: dort liegt der Mund.
                mx0 = max(0, x + int(bw * 0.2))
                mx1 = min(grau.shape[1], x + int(bw * 0.8))
                my0 = max(0, y + int(bh * 0.55))
                my1 = min(grau.shape[0], y + bh)
                if mx1 <= mx0 or my1 <= my0:
                    munde.append(0.0)
                    continue
                a = grau[my0:my1, mx0:mx1].astype("float32")
                b = vor_grau[my0:my1, mx0:mx1].astype("float32")
                munde.append(float(np.abs(a - b).mean()))
        else:
            munde = [0.0] * len(boxen)

        out.append(tracking.Abtastung(t=t, boxen=boxen, bildwechsel=wechsel, mundbewegung=munde))
        vor_hist, vor_grau = hist, grau
        t += 1 / SAMPLE_FPS
    cap.release()
    return out


def cluster_positions(samples, n_max: int = 3) -> list[float]:
    """Stabile Sitzpositionen (x-Zentren) über den Clip, ohne Identität. 1-D-k-Means in numpy."""
    return [x for x, _y in face_centers(samples, n_max)]


def face_centers(samples, n_max: int = 3) -> list[tuple[float, float]]:
    """Sitzpositionen als (x, y)-Zentren, nach x sortiert. k-Means über x, y als Mittel des Clusters."""
    import numpy as np

    pts = np.array([(x + bw / 2, y + bh / 2) for _, boxes in samples for (x, y, bw, bh) in boxes], dtype=np.float32)
    if len(pts) == 0:
        return []
    xs = pts[:, 0]
    k = int(min(n_max, len(np.unique(xs.round(-1)))))
    centers = np.linspace(xs.min(), xs.max(), k) if k > 1 else np.array([xs.mean()])
    labels = np.zeros(len(xs), dtype=int)
    for _ in range(25):
        labels = np.argmin(np.abs(xs[:, None] - centers[None, :]), axis=1)
        new = np.array([xs[labels == j].mean() if np.any(labels == j) else centers[j] for j in range(k)])
        if np.allclose(new, centers):
            break
        centers = new
    out = []
    for j in range(k):
        sel = labels == j
        if not np.any(sel):
            continue
        out.append((float(pts[sel, 0].mean()), float(pts[sel, 1].mean())))
    return sorted(out)


def propose_speaker_positions(words: list[dict], n_positions: int) -> dict[str, int]:
    """Vorschlag ``{SPEAKER_00: 0, ...}``: Sprecher in Reihenfolge ihres ersten Auftretens auf Positionen von links."""
    order: list[str] = []
    for w in words:
        spk = w.get("speaker")
        if spk and spk not in order:
            order.append(spk)
    return {spk: min(i, max(n_positions - 1, 0)) for i, spk in enumerate(order)}


def _runs_for_segment(seg_start: float, seg_end: float, words: list[dict], speaker_to_pos: dict[str, int], n_pos: int, min_shot_s: float) -> list[tuple[float, float, int]]:
    """Läufe (start, end, position) innerhalb eines Segments, lückenlos, jeder mindestens ``min_shot_s``
    (außer das Segment selbst ist kürzer)."""
    raw = []
    for w in words:
        ws, we = float(w["start"]), float(w["end"])
        if ws < seg_start or we > seg_end:
            continue
        pos = speaker_to_pos.get(w.get("speaker"), 0)
        raw.append((ws, we, min(max(int(pos), 0), n_pos - 1)))
    if not raw:
        return [(seg_start, seg_end, 0)]
    runs: list[list] = []
    for s, e, p in raw:
        if runs and runs[-1][2] == p:
            runs[-1][1] = e
        else:
            runs.append([s, e, p])
    # lückenlos: jeder Lauf endet, wo der nächste beginnt
    runs[0][0] = seg_start
    for a, b in zip(runs, runs[1:]):
        a[1] = b[0]
    runs[-1][1] = seg_end
    # Mindestlänge: zu kurze Läufe in den Vorgänger (oder Nachfolger) einschmelzen
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for i, r in enumerate(runs):
            if r[1] - r[0] < min_shot_s:
                if i > 0:
                    runs[i - 1][1] = r[1]
                else:
                    runs[i + 1][0] = r[0]
                del runs[i]
                changed = True
                break
    merged: list[list] = []
    for r in runs:
        if merged and merged[-1][2] == r[2]:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return [(float(s), float(e), int(p)) for s, e, p in merged]


# -- Folien-Crop (Phase 5c) ----------------------------------------------------------------------
def _sample_times(segments: list[dict], sample_fps: float, max_frames: int) -> list[list[float]]:
    """Abtastzeitpunkte je Segment; bei zu vielen Frames gleichmäßig ausgedünnt."""
    step = 1.0 / max(sample_fps, 0.05)
    per_seg: list[list[float]] = []
    for seg in segments:
        s0, s1 = float(seg["start"]), float(seg["end"])
        times, t = [], s0
        while t < s1:
            times.append(round(t, 3))
            t += step
        per_seg.append(times)
    total = sum(len(t) for t in per_seg)
    if total > max_frames:
        keep_every = total / max_frames
        per_seg = [[t for j, t in enumerate(times) if int(j % keep_every) == 0] for times in per_seg]
    return per_seg


def _cell_means(arr, cols: int, rows: int) -> list[list[float]]:
    """Mittelwert eines 2-D-Arrays je Rasterzelle (Zeilen x Spalten)."""
    import numpy as np

    h, w = arr.shape[:2]
    ys = np.linspace(0, h, rows + 1).astype(int)
    xs = np.linspace(0, w, cols + 1).astype(int)
    out = []
    for r in range(rows):
        row = []
        for c in range(cols):
            cell = arr[ys[r] : ys[r + 1], xs[c] : xs[c + 1]]
            row.append(float(cell.mean()) if cell.size else 0.0)
        out.append(row)
    return out


def slide_region_from_grid(
    stability: list[list[float]],
    edges: list[list[float]],
    src_w: int,
    src_h: int,
    min_stable: float = SLIDE_STABLE_RATIO,
    min_edge: float = SLIDE_EDGE_MIN,
    min_area: float = SLIDE_MIN_AREA,
    frames_sampled: int = 0,
) -> SlideRegion | None:
    """Reine Auswertung: größtes Rechteck aus Zellen mit ``stability >= min_stable``, dessen mittlere
    Kantendichte ``min_edge`` erreicht, mindestens ``min_area`` der Fläche, Seitenverhältnis in
    ``SLIDE_ASPECT_RANGE``. ``confidence = 0,6 * Stabilität + 0,4 * min(1, Fläche / 0,5)``."""
    rows = len(stability)
    cols = len(stability[0]) if rows else 0
    if not rows or not cols:
        return None
    best: tuple[int, float, tuple[int, int, int, int]] | None = None  # (Fläche in Zellen, Kanten, Rechteck)
    for r0 in range(rows):
        for r1 in range(r0, rows):
            for c0 in range(cols):
                for c1 in range(c0, cols):
                    area = (r1 - r0 + 1) * (c1 - c0 + 1)
                    if best is not None and area < best[0]:
                        continue
                    cells = [(r, c) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)]
                    if any(stability[r][c] < min_stable for r, c in cells):
                        continue
                    edge = sum(edges[r][c] for r, c in cells) / area
                    if edge < min_edge:
                        continue
                    if best is None or area > best[0] or (area == best[0] and edge > best[1]):
                        best = (area, edge, (r0, r1, c0, c1))
    if best is None:
        return None
    area_cells, _edge, (r0, r1, c0, c1) = best
    area_ratio = area_cells / float(rows * cols)
    if area_ratio < min_area:
        return None
    x0 = _even(c0 * src_w / cols)
    x1 = _even((c1 + 1) * src_w / cols)
    y0 = _even(r0 * src_h / rows)
    y1 = _even((r1 + 1) * src_h / rows)
    w, h = max(2, x1 - x0), max(2, y1 - y0)
    aspect = w / h
    if not (SLIDE_ASPECT_RANGE[0] <= aspect <= SLIDE_ASPECT_RANGE[1]):
        return None
    stab = sum(stability[r][c] for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)) / area_cells
    confidence = round(0.6 * stab + 0.4 * min(1.0, area_ratio / 0.5), 3)
    return SlideRegion(x0, y0, w, h, confidence, round(stab, 3), round(area_ratio, 3), frames_sampled)


def detect_slide_region(
    video_path: str,
    segments: list[dict],
    sample_fps: float = SLIDE_SAMPLE_FPS,
    notes: list[str] | None = None,
) -> SlideRegion | None:
    """Folie oder Bildschirmfreigabe im Video finden (OpenCV, lazy). ``None`` ohne OpenCV, bei zu wenigen
    Frames oder wenn kein Rechteck die Schwellen erreicht; der Grund landet in ``notes``."""
    ok, reason = slide_detector_available()
    if not ok:
        if notes is not None:
            notes.append(reason)
        return None
    import cv2
    import numpy as np

    cols, rows = SLIDE_GRID
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        if notes is not None:
            notes.append("Folienerkennung: Video konnte nicht geöffnet werden")
        return None
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    scale = min(1.0, SLIDE_ANALYSIS_WIDTH / float(src_w or SLIDE_ANALYSIS_WIDTH))
    quiet = np.zeros((rows, cols), dtype=np.float64)
    edge_sum = np.zeros((rows, cols), dtype=np.float64)
    pairs = frames = 0
    try:
        for times in _sample_times(segments, sample_fps, SLIDE_MAX_FRAMES):
            prev = None
            for t in times:
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
                ok_read, frame = cap.read()
                if not ok_read:
                    break
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if scale < 1.0:
                    gray = cv2.resize(gray, (int(src_w * scale), int(src_h * scale)), interpolation=cv2.INTER_AREA)
                edges = (cv2.Canny(gray, 100, 200) > 0).astype(np.float32)
                edge_sum += np.array(_cell_means(edges, cols, rows))
                frames += 1
                if prev is not None:
                    diff = cv2.absdiff(gray, prev).astype(np.float32)
                    motion = np.array(_cell_means(diff, cols, rows))
                    quiet += (motion < SLIDE_MOTION_MAX).astype(np.float64)
                    pairs += 1
                prev = gray
    finally:
        cap.release()
    if pairs < 2:
        if notes is not None:
            notes.append("Folienerkennung: zu wenige Frames abgetastet")
        return None
    stability = (quiet / pairs).tolist()
    edge_density = (edge_sum / max(frames, 1)).tolist()
    region = slide_region_from_grid(stability, edge_density, src_w, src_h, frames_sampled=frames)
    if region is None and notes is not None:
        notes.append("Keine Folie erkannt (kein ruhiges Rechteck mit Kanten über 25 % der Fläche)")
    return region


def plan_slide_layout(
    src_w: int,
    src_h: int,
    out_w: int,
    out_h: int,
    region: SlideRegion,
    positions: list[float] | None = None,
    face_y: list[float] | None = None,
    max_slide_ratio: float = SLIDE_MAX_HEIGHT_RATIO,
) -> dict:
    """Reine Layoutplanung für ``slide_pip``: Folie oben auf volle Breite (Höhe proportional, gedeckelt bei
    ``max_slide_ratio`` der Ausgabehöhe, dann mittig mit Rand), Sprecherfläche darunter über die volle
    Breite, Sprecher-Crop im Quellframe nach der Talking-Head-Regel (Augenlinie), ohne Gesicht neutral im
    größten Streifen neben der Folie. Liefert ``slide_out``, ``pip``, ``crop`` und ``caption_top``."""
    max_h = out_h * max_slide_ratio
    scale = min(out_w / float(region.w), max_h / float(region.h))
    slide_w = min(_even(out_w), max(2, _even(region.w * scale)))
    slide_h = min(_even(max_h), max(2, _even(region.h * scale)))
    slide_x = _even((out_w - slide_w) / 2)
    pip = {"x": 0, "y": slide_h, "w": _even(out_w), "h": _even(out_h) - slide_h}
    crop_w, crop_h = crop_geometry(src_w, src_h, pip["w"], pip["h"])
    positions = list(positions or [])
    face_y = list(face_y or [])
    cx: float | None = None
    cy: float | None = None
    if positions:
        cx = positions[0] if len(positions) == 1 else sum(positions) / len(positions)
        if face_y:
            cy = face_y[0] if len(face_y) == 1 else sum(face_y) / len(face_y)
    else:
        left = region.x
        right = src_w - (region.x + region.w)
        if max(left, right) >= SLIDE_NEUTRAL_STRIP_MIN * src_w:
            cx = left / 2.0 if left >= right else region.x + region.w + right / 2.0
    x, y = crop_origin(src_w, src_h, crop_w, crop_h, cx, cy)
    return {
        "slide_out": {"x": slide_x, "y": 0, "w": slide_w, "h": slide_h},
        "pip": pip,
        "crop": {"x": x, "y": y, "w": crop_w, "h": crop_h},
        "caption_top": slide_h + int(round(out_h * SLIDE_CAPTION_GAP_RATIO)),
    }


def plan_slide_shots(segments: list[dict], layout: dict) -> list[Shot]:
    """Ein Shot je Segment mit ``layout = "pip"``; die Crop-Felder beschreiben den Sprecher-Ausschnitt."""
    c = layout["crop"]
    shots: list[Shot] = []
    for seg in segments:
        s0, s1 = float(seg["start"]), float(seg["end"])
        if s1 <= s0:
            continue
        shots.append(Shot(s0, s1, int(c["x"]), int(c["y"]), int(c["w"]), int(c["h"]), layout="pip"))
    return shots


def effective_strategy(strategy: str, positions: list[float]) -> str:
    """Was mit den vorhandenen Positionen wirklich möglich ist (Override darf nichts versprechen)."""
    if strategy == "two_speakers" and len(positions) < 2:
        return "talking_head" if positions else "neutral"
    if strategy == "talking_head" and not positions:
        return "neutral"
    return strategy


def plan_shots_for_positions(
    segments: list[dict],
    words: list[dict],
    src_w: int,
    src_h: int,
    out_w: int,
    out_h: int,
    positions: list[float],
    speaker_to_pos: dict[str, int] | None = None,
    face_y: list[float] | None = None,
    strategy: str | None = None,
    min_shot_s: float = MIN_SHOT_S,
) -> list[Shot]:
    """Shots pro Segment, lückenlos in Quellzeit, Mindestlänge ``min_shot_s``.

    ``segments``: ``[{start, end, role}]`` in Abspielreihenfolge. ``positions``: x-Zentren, ``face_y`` parallel.
    ``strategy``: ohne Angabe aus der Zahl der Positionen abgeleitet."""
    crop_w, crop_h = crop_geometry(src_w, src_h, out_w, out_h)
    strategy = strategy or strategy_for(positions)
    speaker_to_pos = dict(speaker_to_pos or {})
    face_y = list(face_y or [])
    shots: list[Shot] = []
    for seg in segments:
        s0, s1 = float(seg["start"]), float(seg["end"])
        if s1 <= s0:
            continue
        if strategy == "neutral" or not positions:
            x, y = crop_origin(src_w, src_h, crop_w, crop_h, None, None)
            shots.append(Shot(s0, s1, x, y, crop_w, crop_h))
            continue
        if strategy == "talking_head" or len(positions) == 1:
            cy = face_y[0] if face_y else None
            x, y = crop_origin(src_w, src_h, crop_w, crop_h, positions[0], cy)
            shots.append(Shot(s0, s1, x, y, crop_w, crop_h))
            continue
        for rs, re_, p in _runs_for_segment(s0, s1, words, speaker_to_pos, len(positions), min_shot_s):
            cy = face_y[p] if p < len(face_y) else None
            x, y = crop_origin(src_w, src_h, crop_w, crop_h, positions[p], cy)
            shots.append(Shot(rs, re_, x, y, crop_w, crop_h))
    return shots


def strategy_for(positions: list[float]) -> str:
    if not positions:
        return "neutral"
    return "talking_head" if len(positions) == 1 else "two_speakers"


def plan_reframe(
    video_path: str | None,
    segments: list[dict],
    words: list[dict],
    speaker_positions: dict[str, int] | None,
    out_aspect: str,
    src_w: int | None = None,
    src_h: int | None = None,
    out_size: tuple[int, int] | None = None,
    reframe_override: str | None = None,
) -> ReframeResult:
    """Kompletter Reframe-Plan: Detektor (wenn vorhanden), Positionen, Folie, Strategie, Shots.

    Ohne Detektor oder ohne Gesichter: ``neutral`` mit ``detector = "none"`` und einem Hinweis in ``notes``.
    ``src_w``/``src_h`` können übergeben werden (aus ``sources``), sonst wird die Datei per ffprobe gelesen.
    ``reframe_override`` (``clips.reframe_override``) erzwingt eine Strategie; ``slide_pip`` ohne erkannte
    Folie legt das ganze Quellbild oben ab. Jede Abweichung zwischen Erkennung und Nutzung steht in ``notes``."""
    if reframe_override is not None and reframe_override not in STRATEGIES:
        raise ValueError(f"Unbekannte Reframe-Strategie {reframe_override!r} (erlaubt: {', '.join(STRATEGIES)})")
    if src_w is None or src_h is None:
        if not video_path:
            raise ValueError("Quellgröße unbekannt und kein Video zum Messen angegeben")
        from .. import ingest

        pr = ingest.probe(video_path)
        src_w, src_h = int(pr.width or 0), int(pr.height or 0)
    if not src_w or not src_h:
        raise ValueError("Quellgröße konnte nicht bestimmt werden")
    if out_size is None:
        ratio = aspect_ratio(out_aspect)
        out_w, out_h = (1080, int(round(1080 / ratio))) if ratio <= 1 else (1920, 1080)
    else:
        out_w, out_h = out_size

    notes: list[str] = []
    detector = "none"
    positions: list[float] = []
    face_y: list[float] = []
    available, reason = detector_available()
    if available and video_path:
        try:
            samples: list = []
            for seg in segments:
                samples.extend(detect_faces(video_path, float(seg["start"]), float(seg["end"])))
            centers = face_centers(samples)
            detector = "yunet"
            positions = [c[0] for c in centers]
            face_y = [c[1] for c in centers]
            if not positions:
                notes.append("Keine Gesichter erkannt, Reframe läuft neutral")
        except Exception as exc:  # Detektor darf den Render nie stoppen
            notes.append(f"Gesichtsdetektion fehlgeschlagen ({exc.__class__.__name__}), Reframe läuft neutral")
            detector, positions, face_y = "none", [], []
    else:
        notes.append(reason or "Kein Detektor, Reframe läuft neutral")

    slide: SlideRegion | None = None
    if video_path:
        slide_ok, slide_reason = slide_detector_available()
        if slide_ok:
            try:
                slide = detect_slide_region(video_path, segments, notes=notes)
            except Exception as exc:  # Folienerkennung darf den Render nie stoppen
                notes.append(f"Folienerkennung fehlgeschlagen ({exc.__class__.__name__})")
        elif reframe_override == "slide_pip":
            notes.append(slide_reason)

    auto = strategy_for(positions)
    slide_usable = slide is not None and slide.confidence >= SLIDE_MIN_CONFIDENCE
    if reframe_override == "slide_pip":
        strategy = "slide_pip"
        if slide is None:
            slide = SlideRegion(0, 0, _even(src_w), _even(src_h), 0.0, 0.0, 1.0, 0)
            notes.append("Override slide_pip ohne erkannte Folie: ganzes Quellbild oben, Sprecher unten")
        elif not slide_usable:
            notes.append(f"Folie mit geringer Sicherheit ({slide.confidence:.2f}) per Override slide_pip genutzt")
    elif reframe_override:
        strategy = effective_strategy(reframe_override, positions)
        if strategy != reframe_override:
            notes.append(f"Override {reframe_override} nicht möglich (Positionen: {len(positions)}), Reframe läuft {strategy}")
        elif strategy != auto:
            notes.append(f"Reframe-Strategie per Override {strategy} statt {auto}")
        if slide_usable:
            notes.append(f"Folie erkannt (Sicherheit {slide.confidence:.2f}), per Override {reframe_override} nicht genutzt")
    elif slide_usable:
        strategy = "slide_pip"
        notes.append(f"Folie erkannt (Sicherheit {slide.confidence:.2f}), Layout Bild-im-Bild")
    else:
        strategy = auto
        if slide is not None:
            notes.append(f"Folie mit geringer Sicherheit ({slide.confidence:.2f}) erkannt, nicht genutzt")

    spk_pos = dict(speaker_positions or {})
    pip: dict | None = None
    if strategy == "slide_pip":
        assert slide is not None
        layout = plan_slide_layout(src_w, src_h, out_w, out_h, slide, positions, face_y)
        pip = layout["pip"]
        shots = plan_slide_shots(segments, layout)
    else:
        if strategy == "two_speakers" and not spk_pos:
            spk_pos = propose_speaker_positions(words, len(positions))
            notes.append("Sprecherpositionen vorgeschlagen, in der UI bestätigen")
        shots = plan_shots_for_positions(segments, words, src_w, src_h, out_w, out_h, positions, spk_pos, face_y, strategy)
    return ReframeResult(
        strategy=strategy,
        detector=detector,
        faces_detected=bool(positions),
        positions=positions,
        shots=shots,
        src_w=src_w,
        src_h=src_h,
        out_w=out_w,
        out_h=out_h,
        face_y=face_y,
        speaker_positions=spk_pos,
        notes=notes,
        slide_region=slide,
        pip=pip,
        override=reframe_override,
    )


def plan_shots(
    words: list[dict],
    clip_start: float,
    clip_end: float,
    src_w: int,
    src_h: int,
    positions: list[float],
    speaker_to_pos: dict[str, int],
) -> list[Shot]:
    """Kompatibler Einstieg (ein zusammenhängender Clip, 9:16): siehe ``plan_shots_for_positions``."""
    return plan_shots_for_positions(
        [{"start": clip_start, "end": clip_end, "role": "body"}], words, src_w, src_h, 1080, 1920, positions, speaker_to_pos
    )


__all__ = [
    "ASPECTS",
    "DEFAULT_YUNET_MODEL",
    "EYE_LINE",
    "MIN_SHOT_S",
    "REFRAME_VERSION",
    "SAMPLE_FPS",
    "SLIDE_MAX_HEIGHT_RATIO",
    "SLIDE_MIN_AREA",
    "SLIDE_MIN_CONFIDENCE",
    "SLIDE_STABLE_RATIO",
    "STRATEGIES",
    "ReframeResult",
    "Shot",
    "SlideRegion",
    "aspect_ratio",
    "cluster_positions",
    "crop_geometry",
    "crop_origin",
    "abtasten",
    "detect_faces",
    "detect_slide_region",
    "detector_available",
    "effective_strategy",
    "face_centers",
    "plan_reframe",
    "plan_shots",
    "plan_shots_for_positions",
    "plan_slide_layout",
    "plan_slide_shots",
    "propose_speaker_positions",
    "slide_detector_available",
    "slide_region_from_grid",
    "strategy_for",
    "yunet_model_path",
]
