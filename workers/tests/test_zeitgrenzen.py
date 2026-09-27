"""Zeitgrenzen der Verarbeitung richten sich nach der Laenge der Quelle.

Hintergrund: Das Upload-Limit lag bei 5 GB, also rund eineinhalb Stunden 1080p. Dazu passten
Festwerte von 120 Minuten fuer die Transkription und 60 fuer die Kandidatensuche. Mit 25 GB sind
sieben Stunden moeglich; dann reisst nicht die Dateigroesse, sondern der Timeout mitten im Lauf.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from chopstr_worker.workflows.clip_project import (
    ZEITGRENZE_MAX_MIN,
    ZEITGRENZEN,
    zeitgrenze,
)

STUFEN = list(ZEITGRENZEN)


@pytest.mark.parametrize("stufe", STUFEN)
def test_kurze_quellen_verhalten_sich_unveraendert(stufe):
    """Bis zur Untergrenze gilt weiter der alte Festwert - keine Regression fuer kurze Videos."""
    basis_min = ZEITGRENZEN[stufe][0]
    assert zeitgrenze(stufe, 0) == timedelta(minutes=basis_min)
    assert zeitgrenze(stufe, 600) == timedelta(minutes=basis_min)


@pytest.mark.parametrize("stufe", STUFEN)
def test_lange_quellen_bekommen_mehr_zeit(stufe):
    kurz = zeitgrenze(stufe, 30 * 60)
    lang = zeitgrenze(stufe, 7 * 3600)
    assert lang > kurz, f"{stufe}: sieben Stunden Quelle brauchen mehr als eine halbe"


@pytest.mark.parametrize("stufe", STUFEN)
def test_notbremse_greift(stufe):
    """Auch eine absurd lange Quelle darf keinen Arbeiter unbegrenzt binden."""
    assert zeitgrenze(stufe, 1000 * 3600) == timedelta(minutes=ZEITGRENZE_MAX_MIN)


@pytest.mark.parametrize("stufe", STUFEN)
def test_monoton(stufe):
    """Laengere Quelle heisst nie weniger Zeit."""
    werte = [zeitgrenze(stufe, h * 3600) for h in (0, 1, 2, 4, 8, 16)]
    assert werte == sorted(werte)


def test_transkription_deckt_sieben_stunden_ab():
    """Der Fall, der die Aenderung ausgeloest hat: 25 GB entsprechen rund sieben Stunden."""
    assert zeitgrenze("asr", 7 * 3600) >= timedelta(hours=7)


def test_untergrenze_kann_uebersteuert_werden():
    """Die Workflow-Parameter ingest_timeout_min und asr_timeout_min wirken weiter."""
    assert zeitgrenze("asr", 0, untergrenze_min=300) == timedelta(minutes=300)
    # Die Uebersteuerung hebt die Notbremse nicht auf.
    assert zeitgrenze("asr", 0, untergrenze_min=99999) == timedelta(minutes=ZEITGRENZE_MAX_MIN)


def test_negative_dauer_faellt_auf_die_untergrenze():
    assert zeitgrenze("ingest", -5) == timedelta(minutes=ZEITGRENZEN["ingest"][0])


def test_alle_stufen_des_workflows_sind_abgedeckt():
    assert set(ZEITGRENZEN) == {"ingest", "asr", "nlp", "detect"}
