"""Multimodal-Provider für den Szenen-Scan (Stufe 0, T2), provider-unabhängig wie ``providers_llm``.

  gemini  -> Google Gemini (Standard Flash) über
             - Google AI Studio mit ``GEMINI_API_KEY`` (Host ``generativelanguage.googleapis.com``, kein EU-Anbieter:
               nur mit ``CHOPSTR_ALLOW_NON_EU_PROVIDERS=1``), oder
             - Vertex AI mit ``GOOGLE_APPLICATION_CREDENTIALS`` plus ``VERTEX_PROJECT`` und ``VERTEX_LOCATION``
               (EU-Region ``europe-west*`` gilt als EU, andere Regionen sperrt der Residency-Guard).
             Vertex hat Vorrang, wenn ``VERTEX_PROJECT`` gesetzt ist.
  mock    -> feste Ereignisse für Tests und Trockenläufe, kein Netz.
  none    -> kein Provider; ``pipeline.mm_scan`` nimmt dann den lokalen Fallback (``source: local``).

Auswahl über ``CHOPSTR_MM_PROVIDER`` (Standard ``none``), Modell über ``CHOPSTR_MODEL_MM`` (Standard
``DEFAULT_MM_MODEL``). Sovereign-Workspaces bekommen nie ``gemini``.

Ein Aufruf schickt ein heruntergerechnetes Fenster (Video als ``inline_data``) und den Prompt, die Antwort ist
JSON nach ``EVENT_SCHEMA`` (``responseSchema``). Inline-Daten sind bei der API auf etwa 20 MB je Anfrage begrenzt;
``MAX_INLINE_BYTES`` bricht vorher mit einer klaren Meldung ab (kürzere Fenster oder kleinere Auflösung wählen).
"""

from __future__ import annotations

import base64
import json
import logging
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import config, residency
from .residency import ResidencyError, Tenant

log = logging.getLogger("chopstr.mm")

MM_PROVIDERS = ("gemini", "mock", "none")
DEFAULT_MM_MODEL = "gemini-2.5-flash"
MAX_INLINE_BYTES = 19 * 1024 * 1024
EVENT_TYPES = (
    "laughter", "reaction", "emotion_peak", "visual_action", "speaker_change", "shout", "applause", "topic_shift",
)  # fmt: skip

# Kompaktes Schema (wenige, kurze Felder): die Ausgabe-Tokens sind beim Scan der größte Kostenblock.
EVENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "t_start": {"type": "number"},
                    "t_end": {"type": "number"},
                    "type": {"type": "string", "enum": list(EVENT_TYPES)},
                    "intensity": {"type": "number", "minimum": 0, "maximum": 1},
                    "speaker": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["t_start", "t_end", "type", "intensity"],
            },
        }
    },
    "required": ["events"],
}


def _gemini_schema(schema: Any) -> Any:
    """JSON-Schema in die OpenAPI-Teilmenge von ``responseSchema`` (Typen groß, ohne min/max)."""
    if isinstance(schema, dict):
        out: dict[str, Any] = {}
        for k, v in schema.items():
            if k == "type" and isinstance(v, str):
                out[k] = v.upper()
            elif k in ("minimum", "maximum"):
                continue
            else:
                out[k] = _gemini_schema(v)
        return out
    if isinstance(schema, list):
        return [_gemini_schema(x) for x in schema]
    return schema


class MMProvider:
    """Schnittstelle: ``scan_window`` liefert ``(antwort, usage)``; ``available`` False heißt lokaler Fallback."""

    name = "none"
    available = False

    def __init__(self, s: config.Settings | None = None, cost_sink: Callable[[dict], None] | None = None):
        self.s = s or config.settings()
        self.cost_sink = cost_sink

    def model(self) -> str:
        return ""

    def scan_window(self, media_path: str | Path, t0: float, t1: float, prompt: str, schema: dict | None = None) -> dict:
        raise NotImplementedError

    def _sink(self, usage: dict[str, Any], prompt_version: str) -> None:
        if self.cost_sink:
            self.cost_sink({"provider": self.name, "model": self.model(), "prompt": prompt_version, "job_type": "mm_scan", "stage": "mm_scan", **usage})


class NoneMM(MMProvider):
    name = "none"
    available = False


class MockMM(MMProvider):
    """Feste Ereignisse (absolute Quellzeit); je Fenster nur die, die darin liegen. Kein Netz, 0 €."""

    name = "mock"
    available = True

    def __init__(self, events: list[dict] | Callable[[float, float], list[dict]] | None = None, **kw: Any):
        super().__init__(**kw)
        self._events = events or []
        self.calls: list[tuple[float, float]] = []

    def model(self) -> str:
        return "mock-mm-v1"

    def scan_window(self, media_path, t0, t1, prompt, schema=None, prompt_version: str = "mm_scan_v1") -> dict:
        self.calls.append((float(t0), float(t1)))
        evs = self._events(t0, t1) if callable(self._events) else [e for e in self._events if t0 <= float(e["t_start"]) < t1]
        # Wie ein echtes Modell: Zeiten relativ zum Fensteranfang
        rel = [{**e, "t_start": float(e["t_start"]) - t0, "t_end": float(e["t_end"]) - t0} for e in evs]
        self._sink({"in": 0, "out": 0, "billing": "local"}, prompt_version)
        return {"events": rel}


class GeminiMM(MMProvider):
    """Gemini über AI Studio oder Vertex AI (``generateContent``, JSON-Antwort nach Schema)."""

    name = "gemini"
    available = True

    def __init__(
        self,
        s: config.Settings | None = None,
        cost_sink: Callable[[dict], None] | None = None,
        transport: Any = None,
        token_provider: Callable[[], str] | None = None,
    ):
        super().__init__(s, cost_sink)
        self._transport = transport
        self._token_provider = token_provider
        self.mode = "vertex" if self.s.vertex_project else "aistudio"
        if self.mode == "vertex":
            loc = self.s.vertex_location or ""
            if loc not in residency.VERTEX_EU_REGIONS:
                raise ResidencyError(
                    f"VERTEX_LOCATION {loc!r} ist keine EU-Region (erlaubt: {', '.join(sorted(residency.VERTEX_EU_REGIONS))})"
                )
        else:
            if not self.s.allow_non_eu_providers:
                raise ResidencyError(
                    "Google AI Studio verarbeitet nicht in der EU; nur mit CHOPSTR_ALLOW_NON_EU_PROVIDERS=1 "
                    "oder über Vertex AI in einer EU-Region (VERTEX_PROJECT, VERTEX_LOCATION)"
                )
            if not self.s.gemini_api_key:
                raise RuntimeError("GEMINI_API_KEY fehlt (oder Vertex AI mit VERTEX_PROJECT konfigurieren)")

    def model(self) -> str:
        return self.s.model_mm or DEFAULT_MM_MODEL

    def endpoint(self) -> str:
        m = self.model()
        if self.mode == "vertex":
            loc = self.s.vertex_location
            return (
                f"https://{loc}-aiplatform.googleapis.com/v1/projects/{self.s.vertex_project}/locations/{loc}"
                f"/publishers/google/models/{m}:generateContent"
            )
        return self.s.gemini_base_url.rstrip("/") + f"/v1beta/models/{m}:generateContent"

    def _headers(self) -> dict[str, str]:
        if self.mode == "vertex":
            token = (self._token_provider or (lambda: vertex_access_token(self.s, self._transport)))()
            return {"Authorization": f"Bearer {token}", "content-type": "application/json"}
        return {"x-goog-api-key": self.s.gemini_api_key, "content-type": "application/json"}

    def request_body(self, data: bytes, mime: str, prompt: str, schema: dict) -> dict:
        return {
            "contents": [{
                "role": "user",
                "parts": [
                    {"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode("ascii")}},
                    {"text": prompt},
                ],
            }],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
                "responseSchema": _gemini_schema(schema),
            },
        }  # fmt: skip

    def scan_window(self, media_path, t0, t1, prompt, schema=None, prompt_version: str = "mm_scan_v1") -> dict:
        path = Path(media_path)
        data = path.read_bytes()
        if len(data) > MAX_INLINE_BYTES:
            raise ValueError(
                f"Fenster {path.name} hat {len(data) // (1024 * 1024)} MB, erlaubt sind {MAX_INLINE_BYTES // (1024 * 1024)} MB "
                "inline; kürzere Fenster (mm_scan.window_s) oder kleinere Auflösung wählen"
            )
        mime = "video/mp4" if path.suffix.lower() == ".mp4" else ("audio/wav" if path.suffix.lower() == ".wav" else "video/webm")
        url = self.endpoint()
        residency.assert_eu_host(url, self.s)
        extra = {"transport": self._transport} if self._transport is not None else {}
        body = self.request_body(data, mime, prompt, schema or EVENT_SCHEMA)
        with residency.guarded_client(self.s, timeout=600, **extra) as client:
            r = client.post(url, headers=self._headers(), json=body)
        if r.status_code >= 400:
            raise RuntimeError(f"Gemini ({self.mode}) antwortet {r.status_code}: {r.text[:300]}")
        payload = r.json()
        try:
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
            out = json.loads(text)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Gemini-Antwort nicht lesbar: {exc.__class__.__name__}") from exc
        u = payload.get("usageMetadata") or {}
        cached = int(u.get("cachedContentTokenCount", 0) or 0)
        self._sink({
            "in": max(0, int(u.get("promptTokenCount", 0) or 0) - cached), "cached_in": cached,
            "out": int(u.get("candidatesTokenCount", 0) or 0) + int(u.get("thoughtsTokenCount", 0) or 0),
            "billing": "api",
        }, prompt_version)  # fmt: skip
        return out if isinstance(out, dict) else {"events": out if isinstance(out, list) else []}


_TOKEN_CACHE: dict[str, tuple[str, float]] = {}


def vertex_access_token(s: config.Settings, transport: Any = None) -> str:
    """Zugriffstoken für Vertex AI aus ``GOOGLE_APPLICATION_CREDENTIALS``.

    Ohne neue Abhängigkeit: ist ``cryptography`` installiert, signiert der Worker das JWT des Dienstkontos selbst
    und tauscht es bei ``oauth2.googleapis.com``; sonst fragt er ``gcloud auth application-default
    print-access-token``. Das Token wird bis kurz vor Ablauf wiederverwendet."""
    cached = _TOKEN_CACHE.get(s.google_application_credentials)
    if cached and cached[1] > time.time() + 60:
        return cached[0]
    token, ttl = "", 3000.0
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError:
        serialization = None  # type: ignore[assignment]
    if serialization is not None and s.google_application_credentials and Path(s.google_application_credentials).is_file():
        info = json.loads(Path(s.google_application_credentials).read_text(encoding="utf-8"))
        now = int(time.time())

        def b64(obj: Any) -> str:
            raw = obj if isinstance(obj, bytes) else json.dumps(obj, separators=(",", ":")).encode()
            return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

        claims = {
            "iss": info["client_email"], "scope": "https://www.googleapis.com/auth/cloud-platform",
            "aud": "https://oauth2.googleapis.com/token", "iat": now, "exp": now + 3600,
        }  # fmt: skip
        signing_input = f"{b64({'alg': 'RS256', 'typ': 'JWT'})}.{b64(claims)}".encode()
        key = serialization.load_pem_private_key(info["private_key"].encode(), password=None)
        sig = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())  # type: ignore[union-attr]
        assertion = signing_input.decode() + "." + b64(sig)
        extra = {"transport": transport} if transport is not None else {}
        with residency.guarded_client(s, timeout=30, **extra) as client:
            r = client.post(
                "https://oauth2.googleapis.com/token",
                data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
            )
        r.raise_for_status()
        body = r.json()
        token, ttl = str(body["access_token"]), float(body.get("expires_in", 3000))
    else:
        try:
            proc = subprocess.run(
                ["gcloud", "auth", "application-default", "print-access-token"], capture_output=True, text=True, timeout=60, check=True
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(
                "Kein Vertex-Token: weder cryptography installiert noch gcloud verfügbar "
                "(GOOGLE_APPLICATION_CREDENTIALS mit Dienstkonto setzen)"
            ) from exc
        token = proc.stdout.strip()
    _TOKEN_CACHE[s.google_application_credentials] = (token, time.time() + ttl)
    return token


def select_mm(
    tenant: Tenant | None = None,
    s: config.Settings | None = None,
    provider: str | None = None,
    cost_sink: Callable[[dict], None] | None = None,
    **kw: Any,
) -> MMProvider:
    """Provider aus ``CHOPSTR_MM_PROVIDER`` (oder ``provider``); Sovereign bekommt nie ``gemini``."""
    s = s or config.settings()
    name = (provider or s.mm_provider or "none").strip().lower()
    if name not in MM_PROVIDERS:
        raise ValueError(f"Unbekannter MM-Provider {name!r}, erlaubt: {', '.join(MM_PROVIDERS)}")
    if name == "gemini":
        if tenant is not None and tenant.tier == config.TIER_SOVEREIGN:
            raise ResidencyError(f"MM-Provider gemini ist für Sovereign-Workspace {tenant.id} nicht erlaubt")
        if tenant is not None and not s.vertex_project and not tenant.allow_us_subprocessors:
            # AI Studio ist ein US-Unterauftragnehmer; Vertex AI in einer EU-Region braucht keine Zustimmung
            raise ResidencyError(f"Google AI Studio: Workspace {tenant.id} hat US-Unterauftragnehmern nicht zugestimmt")
        return GeminiMM(s, cost_sink=cost_sink, **kw)
    if name == "mock":
        return MockMM(events=kw.get("events"), s=s, cost_sink=cost_sink)
    return NoneMM(s, cost_sink)


__all__ = [
    "DEFAULT_MM_MODEL",
    "EVENT_SCHEMA",
    "EVENT_TYPES",
    "MAX_INLINE_BYTES",
    "MM_PROVIDERS",
    "GeminiMM",
    "MMProvider",
    "MockMM",
    "NoneMM",
    "select_mm",
    "vertex_access_token",
]
