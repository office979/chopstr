"""workers/scripts/local_env.sh: INTERNAL_API_SECRET kommt aus apps/web/.env.local, wenn nicht gesetzt.

Der Test baut die Ordnerstruktur in einem Temp-Verzeichnis nach, damit die echte .env.local nie gelesen
wird, und prüft, dass der Wert nicht in der Ausgabe des Skripts steht.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "workers" / "scripts" / "local_env.sh"
SECRET = "geheim-0123456789abcdef"


def _layout(tmp_path: Path, env_line: str | None) -> Path:
    (tmp_path / "workers" / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, tmp_path / "workers" / "scripts" / "local_env.sh")
    if env_line is not None:
        (tmp_path / "apps" / "web").mkdir(parents=True)
        (tmp_path / "apps" / "web" / ".env.local").write_text(
            f"DATABASE_URL=postgres://x\n{env_line}\nOTHER=1\n", encoding="utf-8"
        )
    return tmp_path / "workers" / "scripts" / "local_env.sh"


def _run(shell: str, script: Path, preset: str | None = None) -> tuple[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "INTERNAL_API_SECRET"}
    env["LOCAL_STORAGE_DIR"] = str(script.parent / "storage")
    env["WORKER_WORK_DIR"] = str(script.parent / "work")
    if preset is not None:
        env["INTERNAL_API_SECRET"] = preset
    cmd = f'source "{script}"; printf "\\nRESULT=%s" "$INTERNAL_API_SECRET"'
    res = subprocess.run([shell, "-c", cmd], env=env, capture_output=True, text=True, timeout=60)
    out, _, value = res.stdout.rpartition("\nRESULT=")
    return value, out + res.stderr


SHELLS = [s for s in ("bash", "zsh") if shutil.which(s)]


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize(
    "line",
    [f"INTERNAL_API_SECRET={SECRET}", f'INTERNAL_API_SECRET="{SECRET}"', f"export INTERNAL_API_SECRET='{SECRET}'"],
)
def test_secret_from_web_env_local(tmp_path, shell, line):
    value, output = _run(shell, _layout(tmp_path, line))
    assert value == SECRET
    assert SECRET not in output


@pytest.mark.parametrize("shell", SHELLS)
def test_preset_secret_wins(tmp_path, shell):
    value, _ = _run(shell, _layout(tmp_path, f"INTERNAL_API_SECRET={SECRET}"), preset="vorher")
    assert value == "vorher"


@pytest.mark.parametrize("shell", SHELLS)
def test_missing_env_local_stays_empty(tmp_path, shell):
    value, _ = _run(shell, _layout(tmp_path, None))
    assert value == ""
