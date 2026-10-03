from __future__ import annotations

import pytest

from chopstr_worker import prompts


def test_all_repo_prompts_load():
    """``load`` ohne Version nimmt die höchste vorhandene; ``score_clip`` steht auf 2."""
    expected = {
        "system_editor": (None, 1),
        "propose_moments": ("propose_moments", 1),
        "score_clip": ("score_clip", 2),
        "story_graph_confirm": ("confirm_qualification", 1),
        "hooks": ("write_hooks", 1),
        "post_caption": ("write_post_caption", 1),
    }
    for name, (tool, version) in expected.items():
        p = prompts.load(name)
        assert p.name == name
        assert p.version == version
        assert p.tool == tool
        assert p.prompt_version == f"{name}_v{version}"


def test_bestandsfassung_score_clip_v1_bleibt_ladbar():
    """``candidates.prompt_version`` in der Datenbank zeigt auf v1. Die Datei muss bleiben."""
    p = prompts.load("score_clip", 1)
    assert p.prompt_version == "score_clip_v1"
    assert p.inputs == ["audience", "platform", "candidate_numbered"]


def test_render_replaces_inputs_and_joins_lists():
    p = prompts.load("hooks")
    out = p.render(address="DU", country="AT", platform="tiktok", protected_terms=["Jause", "Marille"], clip_text="Text hier")
    assert "Anrede: DU" in out
    assert "Jause, Marille" in out
    assert "Text hier" in out
    assert "{clip_text}" not in out


def test_render_missing_input_raises():
    p = prompts.load("score_clip")
    with pytest.raises(KeyError):
        p.render(audience="x")


def test_parse_frontmatter_and_unknown_braces(tmp_path):
    text = '---\nname: demo\nversion: 3\ntool: t\ninputs: [a]\n---\nHallo {a}. JSON: {"k": 1} bleibt.\n'
    p = prompts.parse(text, tmp_path / "demo_v3.md")
    assert p.prompt_version == "demo_v3"
    assert p.render(a="Welt") == 'Hallo Welt. JSON: {"k": 1} bleibt.\n'
    assert p.render(a=None).startswith("Hallo -")


def test_load_specific_and_latest_version(tmp_path, monkeypatch):
    (tmp_path / "x_v1.md").write_text("---\nname: x\nversion: 1\n---\neins\n", encoding="utf-8")
    (tmp_path / "x_v2.md").write_text("---\nname: x\nversion: 2\n---\nzwei\n", encoding="utf-8")
    monkeypatch.setenv("PROMPTS_DIR", str(tmp_path))
    prompts.clear_cache()
    assert prompts.load("x").version == 2
    assert prompts.load("x", 1).render().strip() == "eins"
    with pytest.raises(FileNotFoundError):
        prompts.load("nope")
    prompts.clear_cache()


def test_score_clip_weights_kommen_aus_der_grundlage_nicht_aus_dem_frontmatter():
    """Bis Fassung 1 standen die Gewichte im Frontmatter. Jetzt gewinnt die Grundlage.

    Die ausführlichen Tests dazu stehen in ``test_score_policy.py``; hier bleibt nur die Wache
    dagegen, dass jemand die Gewichte wieder aus dem Prompt zieht.
    """
    from chopstr_worker import editorial
    from chopstr_worker.pipeline import story_score

    w = story_score.weights()
    assert sum(w.values()) == pytest.approx(1.0)
    assert story_score.policy_weights() == editorial.load().gewichte
    alt = prompts.load("score_clip", 1).meta["weights"]
    assert w["hook"] != pytest.approx(alt["hook"])  # 0,3077 aus der Grundlage statt 0,30 aus v1


# -- Pinning über die Policy (AP0b) ----------------------------------------------------------------
@pytest.fixture
def prompts_copy(tmp_path, monkeypatch):
    """Alle Repo-Prompts in einem temporären ``PROMPTS_DIR``, damit dort neue Dateien liegen dürfen."""
    import shutil

    for src in prompts.prompts_dir().glob("*.md"):
        shutil.copy(src, tmp_path / src.name)
    monkeypatch.setenv("PROMPTS_DIR", str(tmp_path))
    prompts.clear_cache()
    yield tmp_path
    prompts.clear_cache()


@pytest.mark.parametrize("policy_version", ["1", "2"])
def test_new_prompt_file_does_not_switch_the_path(prompts_copy, monkeypatch, policy_version):
    """Eine ``score_clip_v99.md`` ändert nichts, solange keine Policy sie pinnt."""
    from chopstr_worker import editorial
    from chopstr_worker.pipeline import story_engine

    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", policy_version)
    editorial.load.cache_clear()
    before = story_engine.prompt_versions()
    v2 = (prompts_copy / "score_clip_v2.md").read_text(encoding="utf-8")
    (prompts_copy / "score_clip_v99.md").write_text(v2.replace("version: 2", "version: 99"), encoding="utf-8")
    prompts.clear_cache()

    assert prompts.load("score_clip").version == 99  # ungepinnt nähme sie die neue Datei
    assert prompts.load_pinned("score_clip").version == 2
    assert story_engine.prompt_versions() == before == ["propose_moments_v1", "score_clip_v2", "story_graph_confirm_v1"]
    editorial.load.cache_clear()


def test_load_without_version_warns(prompts_copy, caplog):
    with caplog.at_level("WARNING", logger="chopstr.prompts"):
        prompts.load("hooks")
    assert any("ohne Version" in r.getMessage() and "hooks_v1.md" in r.getMessage() for r in caplog.records)


def test_load_pinned_follows_the_given_policy():
    from chopstr_worker import editorial

    for version in (1, 2):
        pol = editorial.load(version)
        for name, pin in pol.prompt_pins.items():
            assert prompts.load_pinned(name, pol).prompt_version == f"{name}_v{pin}"


def test_load_pinned_without_pin_fails_loudly():
    from chopstr_worker import editorial

    with pytest.raises(editorial.PolicyError, match="nicht gepinnt"):
        prompts.load_pinned("gibt_es_nicht", editorial.load(1))


def test_production_code_loads_prompts_only_pinned():
    """Wache gegen Rückfälle: ``prompts.load(`` ohne Pin hat im Worker-Paket keinen Aufrufer."""
    import re
    from pathlib import Path

    package = Path(prompts.__file__).resolve().parent
    hits = [
        f"{path.relative_to(package)}:{lineno}"
        for path in package.rglob("*.py")
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if re.search(r"\bprompts\.load\(", line)
    ]
    assert hits == []
