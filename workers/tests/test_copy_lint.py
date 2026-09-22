from __future__ import annotations

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
