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
