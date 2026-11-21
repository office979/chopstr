from __future__ import annotations

import pytest

from chopstr_worker import editorial
from chopstr_worker.pipeline import copy_de


def test_lint_em_dash_and_floskeln():
    p = copy_de.BrandProfile(address="du", country="AT")
    out, notes = copy_de.lint("Das ist essenziell — wirklich ein Game Changer", p)
    assert "—" not in out
    assert any("Em-Dash" in n for n in notes)
    assert any("essenziell" in n for n in notes)
    assert any("game changer" in n for n in notes)


def test_lint_address_consistency():
    p = copy_de.BrandProfile(address="sie")
    _, notes = copy_de.lint("Du musst das wissen.", p)
    assert "Du-Form in Sie-Profil" in notes
    p = copy_de.BrandProfile(address="du")
    _, notes = copy_de.lint("Das sollten Sie wissen.", p)
    assert any("Sie-Form" in n for n in notes)


def test_lint_swiss_and_gender():
    p = copy_de.BrandProfile(country="CH", gender_mode="doppelpunkt")
    out, notes = copy_de.lint("Die Grösse der Straße. Mitarbeiter*innen", p)
    assert "ß" not in out
    assert "Mitarbeiter:innen" in out
    p = copy_de.BrandProfile(gender_mode="neutral")
    _, notes = copy_de.lint("Mitarbeiter:innen", p)
    assert any("Genderzeichen" in n for n in notes)


def test_lint_compound_hint_and_banned():
    p = copy_de.BrandProfile(banned_phrases=["Jetzt zuschlagen"])
    _, notes = copy_de.lint("Unsere AI Modelle. Jetzt zuschlagen!", p)
    assert any("Durchkopplung" in n for n in notes)
    assert any("jetzt zuschlagen" in n for n in notes)


def test_worn_hooks_flagged():
    _, notes = copy_de.lint("Du glaubst nicht, was dann passiert", copy_de.BrandProfile())
    assert any("Abgenutzter Hook" in n for n in notes)


def test_hook_prompt_uses_versioned_prompt():
    p = copy_de.BrandProfile(address="du", country="AT", platform="linkedin", protected_terms=["Jause"])
    user, pr = copy_de.build_hook_prompt("Wir haben 40.000 Euro verloren.", p)
    assert pr.prompt_version == "hooks_v1"
    assert "Anrede: DU" in user
    assert "Jause" in user
    assert "40.000 Euro" in user


def test_ad_disclosure():
    assert copy_de.ad_disclosure(copy_de.BrandProfile(country="DE"), True, False) == "Anzeige"
    assert copy_de.ad_disclosure(copy_de.BrandProfile(country="AT"), False, True) == "Werbung"
    assert copy_de.ad_disclosure(copy_de.BrandProfile(country="CH"), False, False) is None


@pytest.fixture
def policy_version(monkeypatch):
    """Setzt CHOPSTR_POLICY_VERSION und leert den Policy-Cache davor und danach."""

    def set_version(version: int) -> None:
        monkeypatch.setenv("CHOPSTR_POLICY_VERSION", str(version))
        editorial.clear_cache()

    yield set_version
    editorial.clear_cache()


def test_hyperbole_comes_from_policy_v2_only(policy_version):
    """AP6a: Hyperbel-Liste aus ``hook.hyperbole`` (origin R, Research Abschnitt 7 Anti-Hyperbel)."""
    text = "Das verändert alles: das ist das Geheimnis"
    policy_version(1)
    _, notes_v1 = copy_de.lint(text, copy_de.BrandProfile())
    assert not any("Hyperbel" in n for n in notes_v1)  # Fassung 1 unverändert
    policy_version(2)
    assert "das verändert alles" in editorial.load().hyperbole
    _, notes_v2 = copy_de.lint(text, copy_de.BrandProfile())
    assert "Hyperbel: 'das verändert alles' ersetzt keine Substanz" in notes_v2
    assert "Hyperbel: 'das ist das geheimnis' ersetzt keine Substanz" in notes_v2
    assert copy_de.lint_violations(notes_v2) == notes_v2


def test_hyperbole_list_can_be_passed_and_hints_are_no_violations():
    _, notes = copy_de.lint(
        "Niemand redet darüber", copy_de.BrandProfile(), hyperbole=["niemand redet darüber"]
    )
    assert notes == ["Hyperbel: 'niemand redet darüber' ersetzt keine Substanz"]
    _, hints = copy_de.lint(
        "Unsere AI Modelle — nicht teuer, sondern günstig", copy_de.BrandProfile(), hyperbole=()
    )
    assert (
        hints and copy_de.lint_violations(hints) == []
    )  # Em-Dash korrigiert, Durchkopplung und Muster nur Hinweis


def test_word_bounds_under_policy_v2_only(policy_version):
    """Fassung 1 prüft Floskeln als Teilstring („spannend“ in „hochspannend“), Fassung 2 an Wortgrenzen."""
    text = "Hochspannend und nahtlose Abläufe"
    policy_version(1)
    _, notes_v1 = copy_de.lint(text, copy_de.BrandProfile())
    assert "Floskel: 'spannend'" in notes_v1 and "Floskel: 'nahtlos'" in notes_v1
    policy_version(2)
    _, notes_v2 = copy_de.lint(text, copy_de.BrandProfile())
    assert not any("Floskel" in n for n in notes_v2)
    _, notes_word = copy_de.lint("Das ist spannend", copy_de.BrandProfile())
    assert notes_word == ["Floskel: 'spannend'"]


# -- SOP-Regeln für den Text-Hook (A2.2, hook.sop_v3) ---------------------------------------------
CLIP_SOP = "Wir haben 40 Prozent Marge verloren. Der Koffer kostete 300 Euro, und das war zu viel."


def test_sop_removes_trailing_full_stop_but_keeps_other_endings():
    assert copy_de.lint_sop("Warum du zu billig verkaufst.")[0] == "Warum du zu billig verkaufst"
    assert "Schlusspunkt entfernt" in copy_de.lint_sop("Warum du zu billig verkaufst.")[1]
    for text in ("Warum verkaufst du so billig?", "Hör auf damit!", "Und dann kam der Anruf…", "Und dann..."):
        assert copy_de.lint_sop(text)[0] == text


def test_sop_two_short_lines():
    assert copy_de.lint_sop("Kurzer Hook")[1] == []
    _, notes = copy_de.lint_sop("Eins\nZwei\nDrei")
    assert "Mehr als 2 Zeilen" in notes
    _, notes = copy_de.lint_sop("Diese erste Zeile ist eindeutig viel zu lang geraten\nkurz")
    assert any(n.startswith("Zeile über 32 Zeichen") for n in notes)
    _, notes = copy_de.lint_sop("Ein Hook ohne festen Umbruch, der für zwei Zeilen zu je zweiunddreißig Zeichen viel zu lang ist")
    assert any(n.startswith("Passt nicht in 2 Zeilen") for n in notes)


def test_sop_isolated_demonstrative():
    for text in ("Darum", "Das ist es", "Das war der Grund"):
        assert any(n.startswith("Rückbezug ohne Nomen") for n in copy_de.lint_sop(text)[1]), text
    assert not any(n.startswith("Rückbezug") for n in copy_de.lint_sop("Das ist der teuerste Fehler im Vertrieb")[1])


def test_sop_number_needs_reference_and_must_be_in_clip():
    _, notes = copy_de.lint_sop("40 Prozent Marge weg", CLIP_SOP)
    assert notes == []
    _, notes = copy_de.lint_sop("Am Ende waren es 40", CLIP_SOP)
    assert "Zahl ohne Bezug: '40'" in notes
    _, notes = copy_de.lint_sop("50 Prozent Marge weg", CLIP_SOP)
    assert "Zahl nicht im Clip: '50'" in notes
    assert copy_de.lint_violations(notes) == ["Zahl nicht im Clip: '50'"]
    # Schreibweisen derselben Zahl gelten als dieselbe
    clip = "Wir hatten 40.000 Euro Schulden."
    for text in ("40 000 Euro Schulden", "Vierzigtausend Euro Schulden", "40.000 Euro Schulden"):
        assert not any(n.startswith("Zahl nicht im Clip") for n in copy_de.lint_sop(text, clip)[1]), text
    # Ohne Clip-Text keine Zahlenprüfung gegen den Clip
    assert not any(n.startswith("Zahl nicht im Clip") for n in copy_de.lint_sop("50 Prozent Marge weg")[1])


def test_sop_more_than_one_idea():
    _, notes = copy_de.lint_sop("Preise rauf, Kunden weg und Marge weg und alles neu")
    assert any(n.startswith("Mehr als ein Gedanke") for n in notes)
    assert not any(n.startswith("Mehr als ein Gedanke") for n in copy_de.lint_sop("Preise rauf und Kunden weg")[1])


def test_sop_fixes_dashes_and_emojis():
    out, notes = copy_de.lint_sop("Preise rauf – Kunden weg 🚀")
    assert out == "Preise rauf, Kunden weg"
    assert "Emoji entfernt" in notes and "Gedankenstrich ersetzt" in notes
    assert copy_de.lint_sop("Preise rauf - Kunden weg")[0] == "Preise rauf, Kunden weg"
    assert copy_de.lint_sop("E-Mail-Marketing wirkt")[0] == "E-Mail-Marketing wirkt"  # Bindestrich bleibt
    assert copy_de.lint_sop("5 - 10 Euro mehr")[0] == "5 - 10 Euro mehr"  # Zahlenbereich bleibt
    assert copy_de.lint_sop("5 – 10 Euro mehr")[0] == "5 – 10 Euro mehr"


def test_lint_applies_sop_only_to_onscreen_and_only_with_switch():
    p = copy_de.BrandProfile()
    text = "Warum du zu billig verkaufst."
    assert copy_de.lint(text, p, onscreen=True, sop_v3=True)[0] == "Warum du zu billig verkaufst"
    assert copy_de.lint(text, p, onscreen=True, sop_v3=False)[0] == text
    assert copy_de.lint(text, p, sop_v3=True)[0] == text  # gesprochener Hook, Post-Text: unverändert
    # Ohne Angabe gilt der Schalter der aktiven Grundlage, und der ist aus
    assert editorial.load(2).hook_sop_v3 is False
    assert copy_de.lint(text, p, onscreen=True)[0] == text


@pytest.fixture
def policy_sop_v3(tmp_path, monkeypatch):
    """Fassung 2 mit implementation.hook.sop_v3: true in einer Kopie der Grundlage."""
    import shutil

    for f in editorial.policy_dir().glob("clip_policy_v*.yaml"):
        shutil.copy(f, tmp_path / f.name)
    path = tmp_path / "clip_policy_v2.yaml"
    text = path.read_text(encoding="utf-8")
    assert "    sop_v3: false\n" in text
    path.write_text(text.replace("    sop_v3: false\n", "    sop_v3: true\n"), encoding="utf-8")
    monkeypatch.setenv("EDITORIAL_DIR", str(tmp_path))
    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "2")
    editorial.clear_cache()
    yield editorial.load(2)
    editorial.clear_cache()


def test_switch_pins_hooks_v3_and_turns_on_sop(policy_sop_v3):
    from chopstr_worker import prompts

    assert policy_sop_v3.hook_sop_v3 is True
    assert policy_sop_v3.prompt_pins["hooks"] == 3
    # Alle anderen Pins bleiben, wie die Datei sie nennt; dort steht hooks weiter auf 2
    assert policy_sop_v3.roh["prompts"]["hooks"] == 2
    assert {k: v for k, v in policy_sop_v3.prompt_pins.items() if k != "hooks"} == {k: v for k, v in policy_sop_v3.roh["prompts"].items() if k != "hooks"}
    pr = prompts.load_pinned("hooks", policy_sop_v3)
    assert pr.prompt_version == "hooks_v3" and "funnel_stage" in pr.inputs
    user = pr.render(address="DU", country="AT", platform="tiktok", protected_terms=[], funnel_stage="TOF", clip_text="x")
    assert "Trichterstufe: TOF" in user and "<clip>\nx\n</clip>" in user
    assert "Kein Punkt am Ende" in user and "mindestens 3 verschiedenen Familien" in user
    assert copy_de.lint("Warum du zu billig verkaufst.", copy_de.BrandProfile(), onscreen=True)[0] == "Warum du zu billig verkaufst"


def test_switch_off_keeps_hooks_v2_pin():
    editorial.clear_cache()
    assert editorial.load(2).prompt_pins["hooks"] == 2
    assert editorial.load(1).prompt_pins["hooks"] == 1


def test_heuristic_copy_runs_offline_with_hooks_v3(policy_sop_v3):
    from chopstr_worker import config, providers_llm
    from chopstr_worker.pipeline import copy_engine
    from chopstr_worker.providers_llm import LLM
    from chopstr_worker.residency import Tenant

    llm = LLM(Tenant(id="ws"), provider=providers_llm.HEURISTIC_PROVIDER, s=config.settings())
    res = copy_engine.write_copy(llm, CLIP_SOP + " Der Grund war ein falsches Preismodell.", copy_de.BrandProfile(platform="tiktok"))
    assert res.prompt_version == "hooks_v3"
    assert not res.onscreen_hook.endswith(".") or res.onscreen_hook.endswith("...")
    assert all(v["pattern"] in copy_engine.HOOK_PATTERNS_V3 for v in res.variants)


def test_pattern_families_map_overlaps():
    from chopstr_worker.pipeline import copy_engine

    assert copy_engine.pattern_family("widerspruch") == copy_engine.pattern_family("contrarian") == "contrarian"
    assert copy_engine.pattern_family("teurer_fehler") == "mistake_warning"
    assert copy_engine.pattern_family("konkrete_zahl") == "results_first"
    assert copy_engine.pattern_family("sachfrage") == "sachfrage"
    assert set(copy_engine.HOOK_PATTERNS) <= set(copy_engine.HOOK_PATTERNS_V3)
    v3 = copy_engine.hooks_schema(3)["properties"]["variants"]["items"]
    assert "payoff_ts" in v3["properties"] and "sachfrage" in v3["properties"]["pattern"]["enum"]
    assert copy_engine.hooks_schema(2) is copy_engine.HOOKS_SCHEMA
