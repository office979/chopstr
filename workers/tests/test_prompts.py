from __future__ import annotations

import pytest

from chopstr_worker import prompts


def test_all_repo_prompts_load():
    expected = {
        "system_editor": None,
        "propose_moments": "propose_moments",
        "score_clip": "score_clip",
        "story_graph_confirm": "confirm_qualification",
        "hooks": "write_hooks",
        "post_caption": "write_post_caption",
    }
    for name, tool in expected.items():
        p = prompts.load(name)
        assert p.name == name
        assert p.version == 1
        assert p.tool == tool
        assert p.prompt_version == f"{name}_v1"


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


def test_score_clip_weights_from_frontmatter():
    from chopstr_worker.pipeline import story_score

    w = story_score.weights()
    assert w["hook"] == pytest.approx(0.30)
    assert sum(w.values()) == pytest.approx(1.0)
