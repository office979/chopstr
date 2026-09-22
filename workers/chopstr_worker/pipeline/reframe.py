"""16:9 zu 9:16 Reframing als „virtuelle Kamera" (Phase 3): Schnitt zwischen Sprechern, kein Wackel-Pan.

DSGVO-Design:
- Nur Gesichts-DETEKTION (Position), keine Gesichts-ERKENNUNG (Identität), keine Embeddings gespeichert.
- Sprecher-zu-Gesicht-Zuordnung über einmalige Bestätigung in der UI („SPEAKER_00 sitzt links").
Lizenz: YuNet (OpenCV, Apache-2.0). OpenCV wird nur innerhalb der Funktionen importiert.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

SAMPLE_FPS = 5
MIN_SHOT_S = 1.2  # kürzer wirkt hektisch
YUNET_MODEL = os.environ.get("YUNET_MODEL_PATH", "models/face_detection_yunet_2023mar.onnx")


@dataclass
class Shot:
    start: float
    end: float
    crop_x: int  # linke Kante des 9:16-Ausschnitts im Quellframe
    crop_w: int
    crop_h: int
    layout: str = "single"  # "single" | "split"


def detect_faces(video_path: str, t0: float, t1: float) -> list[tuple[float, list[tuple[int, int, int, int]]]]:
    """Gesichtsboxen (x, y, w, h) pro Abtastzeitpunkt. Benötigt opencv-python-headless und das YuNet-Modell."""
    import cv2

    if not os.path.isfile(YUNET_MODEL):
        raise FileNotFoundError(f"YuNet-Modell fehlt: {YUNET_MODEL}")
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    det = cv2.FaceDetectorYN.create(YUNET_MODEL, "", (w, h), 0.7)
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
    import numpy as np

    xs = np.array([x + bw / 2 for _, boxes in samples for (x, _y, bw, _bh) in boxes], dtype=np.float32)
    if len(xs) == 0:
        return []
    k = int(min(n_max, len(np.unique(xs.round(-1)))))
    centers = np.linspace(xs.min(), xs.max(), k) if k > 1 else np.array([xs.mean()])
    for _ in range(25):
        labels = np.argmin(np.abs(xs[:, None] - centers[None, :]), axis=1)
        new = np.array([xs[labels == j].mean() if np.any(labels == j) else centers[j] for j in range(k)])
        if np.allclose(new, centers):
            break
        centers = new
    return sorted(float(c) for c in centers)


def plan_shots(
    words: list[dict],
    clip_start: float,
    clip_end: float,
    src_w: int,
    src_h: int,
    positions: list[float],
    speaker_to_pos: dict[str, int],
) -> list[Shot]:
    """Aktiver Sprecher (aus Diarisierung) zu Sitzposition zu Crop. Glättung über MIN_SHOT_S."""
    crop_h = src_h
    crop_w = int(src_h * 9 / 16)
    raw = []
    for w in words:
        if float(w["start"]) < clip_start or float(w["end"]) > clip_end:
            continue
        raw.append((float(w["start"]), float(w["end"]), speaker_to_pos.get(w.get("speaker"), 0)))
    if not raw or not positions:
        cx = src_w // 2
        return [Shot(clip_start, clip_end, max(0, cx - crop_w // 2), crop_w, crop_h)]

    shots: list[list] = []
    for s, e, p in raw:
        if shots and shots[-1][2] == p:
            shots[-1][1] = e
        else:
            shots.append([s, e, p])
    merged = [shots[0]]
    for s, e, p in shots[1:]:
        if e - s < MIN_SHOT_S:
            merged[-1][1] = e
        else:
            merged.append([s, e, p])
    merged[0][0], merged[-1][1] = clip_start, clip_end
    for a, b in zip(merged, merged[1:]):
        a[1] = b[0]

    out = []
    for s, e, p in merged:
        cx = int(positions[min(p, len(positions) - 1)])
        x = int(max(0, min(cx - crop_w / 2, src_w - crop_w)))
        out.append(Shot(s, e, x, crop_w, crop_h))
    return out


__all__ = ["MIN_SHOT_S", "SAMPLE_FPS", "Shot", "cluster_positions", "detect_faces", "plan_shots"]
