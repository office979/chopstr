"""Compliance beim Export (Phase 3).

1) C2PA Content Credentials in jede MP4 (via c2patool CLI).
   - Reiner Schnitt/Crop/Captions: c2pa.edited ohne KI-Quellentyp
   - KI-Stimme, KI-Dubbing, generiertes B-Roll: digitalSourceType compositeWithTrainedAlgorithmicMedia
2) Sichtbarer Label-Entscheid (AI Act Art. 50) für UI und Caption-Vorschlag
3) Quellenangabe bei Fremdmaterial (§ 63 UrhG) für die Post-Caption
Keine Rechtsberatung: Defaults plus Audit-Log, finale Freigabe durch Kunden.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile

AI_COMPOSITE = "http://cv.iptc.org/newscodes/digitalsourcetype/compositeWithTrainedAlgorithmicMedia"
GENERATOR = {"name": "chopstr", "version": os.environ.get("APP_VERSION", "0.1.0")}
AI_LABEL_FEATURES = {"ai_voice", "ai_dubbing", "ai_broll_realistic", "ai_lipsync"}
LABEL_TEXT = {"DE": "KI-generierte Stimme", "AT": "KI-generierte Stimme", "CH": "KI-generierte Stimme"}


def manifest(title: str, ai_features: list[str]) -> dict:
    actions = [
        {"action": "c2pa.opened", "softwareAgent": GENERATOR},
        {"action": "c2pa.cropped", "softwareAgent": GENERATOR},
        {"action": "c2pa.edited", "softwareAgent": GENERATOR, "description": "Ausschnitt, vertikales Reframing, Untertitel"},
    ]
    for feat in ai_features:
        actions.append({"action": "c2pa.edited", "softwareAgent": GENERATOR, "digitalSourceType": AI_COMPOSITE, "description": feat})
    return {
        "claim_generator_info": [GENERATOR],
        "title": title,
        "assertions": [{"label": "c2pa.actions.v2", "data": {"actions": actions}}],
    }


def c2patool_available() -> bool:
    return shutil.which("c2patool") is not None


def sign_mp4(src: str, dst: str, title: str, ai_features: list[str]) -> str:
    """Erfordert c2patool plus Signierzertifikat (C2PA_SIGN_CERT / C2PA_PRIVATE_KEY in der Tool-Config)."""
    if not c2patool_available():
        raise RuntimeError("c2patool ist nicht installiert; Signatur nicht möglich")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(manifest(title, ai_features), f, ensure_ascii=False)
        mpath = f.name
    try:
        subprocess.run(["c2patool", src, "-m", mpath, "-o", dst, "-f"], check=True, capture_output=True, text=True)
    finally:
        os.unlink(mpath)
    return dst


def needs_visible_ai_label(ai_features: list[str]) -> bool:
    """Reiner Schnitt aus echtem Footage = kein Deepfake. KI-Stimme/-Bild, das echt wirken kann = Label."""
    return any(f in AI_LABEL_FEATURES for f in ai_features)


def source_credit(source_owner: str | None, source_title: str | None, url: str | None) -> str | None:
    """Quellenangabe für Fremdmaterial (Zitatrecht setzt korrekte Quellenangabe voraus)."""
    if not source_owner:
        return None
    parts = [f"Quelle: {source_owner}"]
    if source_title:
        parts.append(f"„{source_title}“")
    if url:
        parts.append(url)
    return ", ".join(parts)


__all__ = ["AI_COMPOSITE", "AI_LABEL_FEATURES", "GENERATOR", "LABEL_TEXT", "c2patool_available", "manifest", "needs_visible_ai_label", "sign_mp4", "source_credit"]
