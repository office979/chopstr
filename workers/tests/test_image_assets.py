"""Worker-Image (AP0a, Research Befund 13): Policy, Schriftenliste und Ausgaberegeln liegen im Container.

Liest beide Dockerfiles und beide Compose-Dateien als Text und prüft, dass die gemeinsamen Ordner
kopiert werden, dass die Pfadvariablen für ``worker`` und ``worker-gpu`` gesetzt sind und dass jeder
Pfad auf eine Datei zeigt, die es im Repo wirklich gibt. Ohne diese Prüfung fällt eine fehlende
Datei erst im laufenden Container auf, mitten in der Kandidatensuche oder nach dem Encode.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
DOCKERFILES = (REPO / "workers" / "Dockerfile", REPO / "workers" / "Dockerfile.gpu")
COMPOSE = REPO / "infra" / "docker-compose.yml"
SOVEREIGN = REPO / "infra" / "docker-compose.sovereign.yml"
IMAGE_ROOT = "/app/"
PACKAGES = ("prompts", "editorial", "design", "schema")
# Variable, Art des Ziels und eine Datei, die darunter liegen muss (bei Ordnern)
PATH_VARS = {
    "PROMPTS_DIR": ("dir", "score_clip_v2.md"),
    "EDITORIAL_DIR": ("dir", "clip_policy_v1.yaml"),
    "CHOPSTR_CAPTION_FONTS": ("file", None),
    "CHOPSTR_AUSGABE_REGELN": ("file", None),
}


def _repo_path(image_path: str) -> Path:
    """``/app/packages/x`` im Image entspricht ``<repo>/packages/x`` (das Dockerfile kopiert 1:1)."""
    assert image_path.startswith(IMAGE_ROOT + "packages/"), image_path
    return REPO / image_path[len(IMAGE_ROOT):]


def _services() -> list[tuple[str, dict]]:
    base = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    sovereign = yaml.safe_load(SOVEREIGN.read_text(encoding="utf-8"))["services"]
    return [
        ("docker-compose.yml:worker", base["worker"]),
        ("docker-compose.sovereign.yml:worker", sovereign["worker"]),
        ("docker-compose.sovereign.yml:worker-gpu", sovereign["worker-gpu"]),
    ]


@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: p.name)
def test_dockerfile_copies_shared_packages(dockerfile):
    lines = [" ".join(line.split()) for line in dockerfile.read_text(encoding="utf-8").splitlines()]
    for pkg in PACKAGES:
        assert f"COPY packages/{pkg} /app/packages/{pkg}" in lines, f"{dockerfile.name}: packages/{pkg} fehlt"
        assert (REPO / "packages" / pkg).is_dir()


SPACY_MODEL_WHEEL = (
    "de_core_news_md @ https://github.com/explosion/spacy-models/releases/download/"
    "de_core_news_md-${SPACY_MODEL_VERSION}/de_core_news_md-${SPACY_MODEL_VERSION}-py3-none-any.whl"
)


@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: p.name)
def test_dockerfile_installs_the_spacy_model_at_build_time(dockerfile):
    """P28: das Sprachmodell de_core_news_md liegt im Image (Release-Wheel, im selben pip-Aufruf wie das Extra
    nlp, damit die spaCy-Version zum Modell passt); kein Download zur Laufzeit."""
    text = dockerfile.read_text(encoding="utf-8")
    lines = [" ".join(line.split()) for line in text.replace("\\\n", " ").splitlines()]
    install = [line for line in lines if "pip install" in line and "nlp]" in line]
    assert install and all(SPACY_MODEL_WHEEL in line for line in install), dockerfile.name
    assert any(line.startswith("ARG SPACY_MODEL_VERSION=3.") for line in lines)
    assert "spacy download" not in text


@pytest.mark.parametrize("name,service", _services(), ids=lambda v: v if isinstance(v, str) else "")
def test_compose_sets_path_variables_for_workers(name, service):
    env = service.get("environment") or {}
    for var, (kind, inner) in PATH_VARS.items():
        value = env.get(var)
        assert value, f"{name}: {var} ist nicht gesetzt"
        target = _repo_path(str(value))
        if kind == "dir":
            assert target.is_dir(), f"{name}: {var}={value} zeigt auf keinen Ordner im Repo"
            assert (target / inner).is_file(), f"{name}: {var}={value} enthält {inner} nicht"
        else:
            assert target.is_file(), f"{name}: {var}={value} zeigt auf keine Datei im Repo"


def test_compose_paths_are_inside_copied_packages():
    """Jeder gesetzte Pfad liegt unter einem Ordner, den beide Dockerfiles kopieren."""
    copied = {f"/app/packages/{pkg}" for pkg in PACKAGES}
    for name, service in _services():
        for var in PATH_VARS:
            value = str(service["environment"][var])
            assert any(value == c or value.startswith(c + "/") for c in copied), f"{name}: {var}={value}"


def test_path_variables_are_the_ones_the_code_reads():
    """Die Namen stammen aus dem Code; ändert sich dort einer, muss dieser Test mitziehen."""
    worker = REPO / "workers" / "chopstr_worker"
    sources = {
        "PROMPTS_DIR": worker / "prompts.py",
        "EDITORIAL_DIR": worker / "editorial.py",
        "CHOPSTR_CAPTION_FONTS": worker / "pipeline" / "captions_de.py",
        "CHOPSTR_AUSGABE_REGELN": worker / "pipeline" / "ausgabe_pruefung.py",
    }
    for var, path in sources.items():
        assert f'"{var}"' in path.read_text(encoding="utf-8"), f"{path.name} liest {var} nicht"


def test_policy_version_is_documented_without_overriding_the_default():
    """L6: ``CHOPSTR_POLICY_VERSION`` steht in Compose, ``.env.example`` und ``local_env.sh``, setzt aber
    nirgends einen eigenen Standard; ohne Wert gilt ``editorial.POLICY_VERSION``."""
    for name, service in _services():
        assert service["environment"].get("CHOPSTR_POLICY_VERSION") == "${CHOPSTR_POLICY_VERSION:-}", name
    env_example = (REPO / ".env.example").read_text(encoding="utf-8").splitlines()
    assert "CHOPSTR_POLICY_VERSION=" in env_example
    local_env = (REPO / "workers" / "scripts" / "local_env.sh").read_text(encoding="utf-8")
    assert "CHOPSTR_POLICY_VERSION" in local_env
    assert not any(
        line.strip().startswith("export CHOPSTR_POLICY_VERSION") for line in local_env.splitlines()
    ), "local_env.sh darf den Standard nicht überschreiben"
