"""Lane P2 (Launch Phase 2): Text-Heatmap v2 (Schalter ``implementation.heat.text_v2``, Regel ``heat.text_v2``,
Mischung ``heat.text_weight``). Befund der Inventur: Textanteil roh, Audioanteil z-normiert; ein ruhig vorgetragenes
Kernargument fiel gegen jede laute Stelle ab."""

from __future__ import annotations

import numpy as np
import pytest

from chopstr_worker import config, editorial, providers_llm
from chopstr_worker.pipeline import signals, story_engine
from chopstr_worker.providers_llm import LLM
from chopstr_worker.residency import Tenant
from tests.test_story_engine import BRIEF, wired  # noqa: F401
from tests.transcript_fixtures import make_words

# Lauter Smalltalk am Anfang (Audio-Spitze), das Kernargument kommt ruhig, mit Zahl, Einheit und Stakes.
CALM_SCRIPT = [
    ("SPEAKER_01", "Schön, dass du heute da bist und wir reden können.", 5.0),
    ("SPEAKER_00", "Ja, ich freue mich auch sehr auf das Gespräch heute.", 5.0),
    ("SPEAKER_01", "Wie war die Anreise mit dem Zug aus Graz?", 5.0),
    ("SPEAKER_00", "Die Anreise war angenehm und ruhig, danke der Nachfrage.", 5.0),
    ("SPEAKER_01", "Erzähl uns von deinem ersten Unternehmen damals.", 5.0),
    ("SPEAKER_00", "Wir haben damals in drei Monaten 40.000 Euro verloren.", 6.0),
    ("SPEAKER_00", "Das Risiko war existenziell, weil der Kredit an meinem Haus hing.", 6.0),
    ("SPEAKER_00", "Seitdem rechnen wir jede Investition zuerst durch.", 5.0),
    ("SPEAKER_01", "Und wie geht es dir heute damit im Alltag?", 5.0),
    ("SPEAKER_00", "Gut, wir haben inzwischen ein ruhiges Büro am Stadtrand.", 5.0),
]
CORE = (5, 7)  # Satznummern des Kernarguments


def _cfg(pol: editorial.Policy) -> dict:
    raw = pol.roh["heat"]
    return {"text_weight": float(raw["text_weight"]), "markers": {k: tuple(raw["markers"][k]) for k in signals.HEAT_MARKER_KEYS}, "units": tuple(raw["units"])}


def _sentence_spans(words: list[dict]) -> list[tuple[float, float]]:
    from chopstr_worker.pipeline import segment

    return [(s.start, s.end) for s in segment.sentences_from_words(words)]


@pytest.fixture
def heat_cfg(wired):  # noqa: F811
    return _cfg(wired())


def test_calm_core_argument_gets_a_seed_without_an_audio_peak(heat_cfg):
    words = make_words(CALM_SCRIPT)
    spans = _sentence_spans(words)
    n = int(np.ceil(words[-1]["end"])) + 1
    audio = np.zeros(n, dtype=np.float32)
    audio[2:5] = 2.0  # laute Begrüßung, im Kernargument keine Spitze
    core_from, core_to = spans[CORE[0]][0], spans[CORE[1]][1]
    assert float(audio[int(core_from) : int(core_to) + 1].max()) == 0.0
    # Heute: roher Textanteil, der Seed liegt an der Audio-Spitze.
    old = signals.combined("", words, audio=audio)
    (old_seed,) = signals.seeds(old, top_k=1)
    assert 2 <= old_seed <= 4
    # v2: z-normierter Text mit Zahl, Einheit und Stakes, der Seed liegt im Kernargument.
    new, text, stats = signals.combined_v2(audio, words, heat_cfg)
    (new_seed,) = signals.seeds(new, top_k=1)
    assert core_from <= new_seed <= core_to
    assert stats["number_unit"] >= 2 and stats["stakes_loss"] >= 1 and stats["stakes_risk"] >= 1 and stats["stakes_money"] >= 1
    assert float(text.max()) <= 3.0 and float(text.min()) >= -3.0


def test_text_part_is_z_normalised_like_the_audio_part(heat_cfg):
    words = make_words(CALM_SCRIPT)
    raw, _stats = signals.text_heatmap_v2(words, 80, heat_cfg)
    z = signals.zscore(raw)
    assert np.allclose(z, np.clip((raw - np.median(raw)) / np.std(raw), -3, 3), atol=1e-5)
    assert signals.zscore(np.zeros(5, dtype=np.float32)).tolist() == [0.0] * 5


def test_text_weight_mixes_audio_and_text(heat_cfg):
    words = make_words(CALM_SCRIPT)
    audio = np.linspace(-1, 1, 70).astype(np.float32)
    only_audio, text, _ = signals.combined_v2(audio, words, {**heat_cfg, "text_weight": 0.0})
    assert np.allclose(only_audio, audio)
    only_text, text2, _ = signals.combined_v2(audio, words, {**heat_cfg, "text_weight": 1.0})
    assert np.allclose(only_text, text2) and np.allclose(text, text2)


def test_reaction_counts_only_as_a_short_interjection_and_marks_what_came_before(heat_cfg):
    script = [
        ("SPEAKER_00", "Wir haben die Preise damals einfach verdoppelt.", 5.0),
        ("SPEAKER_01", "Wirklich?", 1.0),
        ("SPEAKER_00", "Ja, und keiner der Kunden ist gegangen.", 5.0),
    ]
    words = make_words(script)
    raw, stats = signals.text_heatmap_v2(words, 15, heat_cfg)
    assert stats["short_turn"] == 1 and stats["reaction"] == 1
    reaction_bin = int(words[7]["start"])
    assert raw[reaction_bin - 3] >= 2.0, "die Aussage vor dem Einwurf wird markiert"
    # Dasselbe Wort mitten im Redebeitrag desselben Sprechers ist keine Reaktion.
    mono = make_words([("SPEAKER_00", "Das ist wirklich so passiert, ganz ehrlich.", 5.0)])
    _raw, mono_stats = signals.text_heatmap_v2(mono, 6, heat_cfg)
    assert mono_stats["reaction"] == 0 and mono_stats["short_turn"] == 0


def test_laughter_counts_only_with_data(heat_cfg):
    words = make_words(CALM_SCRIPT[:3])
    n = 20
    none_raw, none_stats = signals.text_heatmap_v2(words, n, heat_cfg, laughter=[])
    laugh = [0.0] * n
    laugh[3] = 1.0
    with_raw, with_stats = signals.text_heatmap_v2(words, n, heat_cfg, laughter=laugh)
    assert none_stats["laughter"] == 0 and with_stats["laughter"] == 1
    assert with_raw[3] == none_raw[3] + 1.0


def test_numbers_need_a_unit(heat_cfg):
    plain = make_words([("SPEAKER_00", "Wir waren 2019 zum ersten Mal dort.", 4.0)])
    unit = make_words([("SPEAKER_00", "Wir hatten 40 Prozent Marge und 12% Rabatt.", 4.0)])
    assert signals.text_heatmap_v2(plain, 6, heat_cfg)[1]["number_unit"] == 0
    assert signals.text_heatmap_v2(unit, 6, heat_cfg)[1]["number_unit"] == 2


def test_payload_without_audio_uses_text_only(heat_cfg):
    words = make_words(CALM_SCRIPT)
    out = signals.payload_with_text_v2(None, words, heat_cfg)
    assert out["text_v2"]["audio_missing"] is True and out["text_v2"]["laughter_used"] is False
    assert out["n_bins"] == len(out["values"]) == len(out["text_values"]) >= int(words[-1]["end"])
    assert out["seeds"] and all(isinstance(s, int) for s in out["seeds"])


def test_settings_follow_switch_and_rule(wired):  # noqa: F811
    assert signals.text_heat_settings(editorial.load(1)) is None
    pol = wired()
    assert pol.roh["heat"]["text_v2"] is False and pol.roh["heat"]["text_weight"] == 0.5, "Standard aus, Mischung 0,5"
    assert signals.text_heat_settings(pol) is None
    cfg = signals.text_heat_settings(wired(**{"heat.text_v2": True}))
    assert cfg["text_weight"] == 0.5 and set(cfg["markers"]) == set(signals.HEAT_MARKER_KEYS) and "prozent" in cfg["units"]
    assert signals.text_heat_settings(wired(**{"heat.text_v2": True, "implementation.heat.text_v2": False})) is None
    with pytest.raises(editorial.PolicyError):
        signals.text_heat_settings(wired(**{"heat.text_v2": True, "heat.text_weight": 2}))


def test_marker_lists_have_a_source_in_the_policy(wired):  # noqa: F811
    pol = wired()
    origins = pol.roh["origins"]
    for key in signals.HEAT_MARKER_KEYS:
        entry = origins[f"heat.markers.{key}"]
        assert entry["origin"] == "H" and "ohne Messung" in entry["source"]
    assert origins["heat.text_weight"]["origin"] == "H"


def test_run_mixes_the_heatmap_only_with_the_rule(wired):  # noqa: F811
    heur = LLM(Tenant(id="ws", tier="standard"), provider=providers_llm.HEURISTIC_PROVIDER, s=config.settings())
    words = make_words(CALM_SCRIPT)
    n = int(np.ceil(words[-1]["end"])) + 1
    audio = [0.0] * n
    audio[2:5] = [2.0, 2.0, 2.0]
    stored = signals.to_payload(signals.combined("", words, audio=np.asarray(audio, dtype=np.float32)), audio=np.asarray(audio, dtype=np.float32))
    wired()
    off = story_engine.run(words, BRIEF, {}, dict(stored), heur)
    assert off.heat == {} and "heat" not in off.to_json()
    wired(**{"heat.text_v2": True})
    on = story_engine.run(words, BRIEF, {}, dict(stored), heur)
    assert on.heat["method"] == "text_v2_zscore" and on.heat["text_weight"] == 0.5
    assert on.heat["hits"]["number_unit"] >= 2 and on.heat["seeds"] >= 1
    assert stored["seeds"] == signals.to_payload(signals.combined("", words, audio=np.asarray(audio, dtype=np.float32)))["seeds"], "gespeicherte Heatmap unverändert"
