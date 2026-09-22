"""Reframing als „virtuelle Kamera" (Phase 3): Schnitt zwischen Sprechern, kein Wackel-Pan.

Strategien (Vertrag ``packages/schema/CLIPS.md``):
- ``talking_head``: eine Sitzposition, ruhiger Crop auf die Position, Augen im oberen Drittel
  (Gesichtsmitte bei ``EYE_LINE`` = 37 % der Ausgabehöhe).
- ``two_speakers``: zwei oder mehr Positionen, Schnitt auf den aktiven Sprecher (Diarisierung),
  Mindestlänge pro Shot ``MIN_SHOT_S``, ``speaker_positions`` bestimmt die Zuordnung.
- ``neutral``: keine Gesichter oder kein Detektor, mittiger Crop; im Plan sichtbar (``detector = "none"``).

DSGVO-Design: nur Gesichts-DETEKTION (Position), keine Erkennung (Identität), keine Embeddings.
YuNet (OpenCV, Apache-2.0) läuft nur, wenn ``YUNET_MODEL_PATH`` auf eine Datei zeigt und OpenCV
importierbar ist. OpenCV wird ausschließlich innerhalb der Funktionen importiert.
``plan_shots_for_positions`` ist eine reine Planungsfunktion und ohne Video testbar.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field

SAMPLE_FPS = 5
MIN_SHOT_S = 1.2  # kürzer wirkt hektisch
EYE_LINE = 0.37  # Gesichtsmitte bei 37 % der Ausgabehöhe (Augen im oberen Drittel)
REFRAME_VERSION = "reframe_v1"
STRATEGIES = ("talking_head", "two_speakers", "neutral")
DEFAULT_YUNET_MODEL = "models/face_detection_yunet_2023mar.onnx"
ASPECTS = {"9:16": (9, 16), "4:5": (4, 5), "1:1": (1, 1), "16:9": (16, 9)}


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


@dataclass
class Shot:
    start: float
    end: float
    crop_x: int  # linke Kante des Ausschnitts im Quellframe
    crop_y: int  # obere Kante des Ausschnitts im Quellframe
    crop_w: int
    crop_h: int
    layout: str = "single"  # "single" | "split"

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

    def plan_block(self) -> dict:
        """Block ``reframe`` des Render-Plans."""
        return {
            "strategy": self.strategy,
            "detector": self.detector,
            "faces_detected": self.faces_detected,
            "positions": [round(float(p), 1) for p in self.positions],
            "min_shot_s": self.min_shot_s,
        }

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
) -> ReframeResult:
    """Kompletter Reframe-Plan: Detektor (wenn vorhanden), Positionen, Strategie, Shots.

    Ohne Detektor oder ohne Gesichter: ``neutral`` mit ``detector = "none"`` und einem Hinweis in ``notes``.
    ``src_w``/``src_h`` können übergeben werden (aus ``sources``), sonst wird die Datei per ffprobe gelesen."""
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

    strategy = strategy_for(positions)
    spk_pos = dict(speaker_positions or {})
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
    "STRATEGIES",
    "ReframeResult",
    "Shot",
    "aspect_ratio",
    "cluster_positions",
    "crop_geometry",
    "crop_origin",
    "detect_faces",
    "detector_available",
    "face_centers",
    "plan_reframe",
    "plan_shots",
    "plan_shots_for_positions",
    "propose_speaker_positions",
    "strategy_for",
    "yunet_model_path",
]
