"""Versionierte Prompts aus ``packages/prompts/<name>_v<N>.md``.

Frontmatter (YAML) enthält ``name``, ``version``, optional ``tool``, ``inputs``, ``weights``, ``role``.
``render(**inputs)`` ersetzt ``{platzhalter}`` wie ``str.format``, lässt aber unbekannte geschweifte
Klammern (z. B. JSON-Beispiele) unangetastet. ``prompt_version`` liefert ``"<name>_v<N>"`` für
``candidates.prompt_version`` und den LLM-Cache-Key.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def prompts_dir() -> Path:
    """Ordner mit den Prompt-Dateien: ``PROMPTS_DIR`` oder ``<monorepo>/packages/prompts``."""
    env = os.environ.get("PROMPTS_DIR", "").strip()
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "packages" / "prompts"
        if cand.is_dir():
            return cand
    return here.parents[1] / "packages" / "prompts"


@dataclass
class Prompt:
    name: str
    version: int
    body: str
    tool: str | None = None
    inputs: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None

    @property
    def prompt_version(self) -> str:
        return f"{self.name}_v{self.version}"

    def render(self, **inputs: Any) -> str:
        """Ersetzt Platzhalter; Listen werden mit ", " verbunden, None wird zu "-"."""
        missing = [k for k in self.inputs if k not in inputs]
        if missing:
            raise KeyError(f"Prompt {self.prompt_version}: fehlende Eingaben {missing}")

        def _fmt(v: Any) -> str:
            if v is None:
                return "-"
            if isinstance(v, (list, tuple, set)):
                return ", ".join(str(x) for x in v) if v else "-"
            return str(v)

        def _sub(m: re.Match) -> str:
            key = m.group(1)
            return _fmt(inputs[key]) if key in inputs else m.group(0)

        return _PLACEHOLDER.sub(_sub, self.body).strip() + "\n"


def parse(text: str, path: Path | None = None) -> Prompt:
    import yaml

    m = _FRONT.match(text)
    if not m:
        raise ValueError(f"Prompt ohne YAML-Frontmatter: {path}")
    meta = yaml.safe_load(m.group(1)) or {}
    body = text[m.end():]
    name = str(meta.get("name") or (path.stem.rsplit("_v", 1)[0] if path else "")).strip()
    version = int(meta.get("version") or (path.stem.rsplit("_v", 1)[1] if path and "_v" in path.stem else 1))
    inputs = [str(x) for x in (meta.get("inputs") or [])]
    return Prompt(name=name, version=version, body=body, tool=meta.get("tool"), inputs=inputs, meta=meta, path=path)


@lru_cache(maxsize=64)
def load(name: str, version: int | None = None) -> Prompt:
    """Lädt ``<name>_v<version>.md``; ohne Version die höchste vorhandene."""
    d = prompts_dir()
    if version is None:
        cands = sorted(d.glob(f"{name}_v*.md"), key=lambda p: int(p.stem.rsplit("_v", 1)[1]))
        if not cands:
            raise FileNotFoundError(f"Kein Prompt {name}_v*.md in {d}")
        path = cands[-1]
    else:
        path = d / f"{name}_v{version}.md"
        if not path.is_file():
            raise FileNotFoundError(f"Prompt {path} fehlt")
    return parse(path.read_text(encoding="utf-8"), path)


def clear_cache() -> None:
    load.cache_clear()


__all__ = ["Prompt", "clear_cache", "load", "parse", "prompts_dir"]
