"""Lane P4, Aufgabe 2: Hook gegen die ersten Sekunden Ton (``transitions.shift_preamble``, ``hook_audio_report``)."""

from __future__ import annotations

import numpy as np
import pytest

from chopstr_worker import editorial
from chopstr_worker.pipeline import reframe, render_plan, transitions
from chopstr_worker.pipeline.transitions import HookAudioRules, PcmAudio
from tests.test_launch_p4_prosody import SR, make_audio, policy_with, w

HOOK = HookAudioRules(max_lead_s=1.0, hook_window_s=3.0)
# Vorgeplänkel aus zwei ganzen Sätzen, danach der Einstieg.
WORDS = [
    w("Also.", 0.0, 0.3), w("Ja", 0.6, 0.75), w("gut.", 0.8, 1.0),
    w("Der", 2.0, 2.2), w("teuerste", 2.25, 2.7), w("Fehler", 2.75, 3.1), w("war", 3.15, 3.3), w("der", 3.35, 3.5),
    w("Preis.", 3.55, 4.0), w("Danach", 4.6, 5.0), w("lief", 5.05, 5.3), w("es.", 5.35, 5.6),
]  # fmt: skip
SEGS = [{"start": 0.0, "end": 5.6, "role": "body"}]


@pytest.fixture(autouse=True)
def _fresh_policy_cache():
    editorial.clear_cache()
    yield
    editorial.clear_cache()


@pytest.fixture
def v2() -> editorial.Policy:
    return editorial.load(2)


def test_preamble_sentences_are_removed_up_to_the_hook_sentence(v2):
    segs, info = transitions.shift_preamble(SEGS, WORDS, v2)
    assert segs[0]["start"] == 2.0 and segs[0]["end"] == 5.6
    assert info == {"preamble_removed_s": 2.0, "hook_word": 3}
    assert SEGS[0]["start"] == 0.0  # Eingabe bleibt unverändert


def test_a_second_render_reports_the_same_removal(v2):
    first, info = transitions.shift_preamble(SEGS, WORDS, v2)
    again, info2 = transitions.shift_preamble(first, WORDS, v2, origin_start=0.0)
    assert again == first and info2 == info


@pytest.mark.parametrize(
    "opening",
    [
        [w("Also", 0.0, 0.3), w("ich", 0.35, 0.5), w("glaube", 0.55, 0.9), w("nicht.", 0.95, 1.3)],  # Inhalt, kein Vorgeplänkel
        [w("Ja", 0.0, 0.2), w("gut", 0.25, 0.5)],  # kein Satzende: die Satzgrenze erlaubt es nicht
    ],
)
def test_no_shift_when_the_sentence_boundaries_do_not_allow_it(v2, opening):
    words = [*opening, *[{**x, "start": x["start"], "end": x["end"]} for x in WORDS[3:]]]
    segs, info = transitions.shift_preamble(SEGS, words, v2)
    assert segs[0]["start"] == 0.0 and info["preamble_removed_s"] == 0.0


def test_greetings_from_the_policy_count_as_preamble(v2):
    words = [w("Hallo", 0.0, 0.3), w("zusammen.", 0.35, 0.8), *WORDS[3:]]
    segs, info = transitions.shift_preamble(SEGS, words, v2)
    assert segs[0]["start"] == 2.0 and info["preamble_removed_s"] == 2.0
    assert transitions.is_preamble("Grüß Gott!", transitions.preamble_phrases(v2))
    assert not transitions.is_preamble("Grüß Gott, heute geht es um Preise.", transitions.preamble_phrases(v2))


def test_teaser_first_and_protected_words_block_the_shift(v2):
    teaser = [{"start": 2.0, "end": 4.0, "role": "teaser"}, *SEGS]
    assert transitions.shift_preamble(teaser, WORDS, v2)[0] == teaser
    segs, info = transitions.shift_preamble(SEGS, WORDS, v2, protected_words=[(1, 2)])
    assert segs[0]["start"] == 0.6 and info["preamble_removed_s"] == 0.6  # „Also." raus, „Ja gut." ist geschützt


def _timeline(start: float, end: float) -> list[dict]:
    return [{"segment_index": 0, "role": "body", "source_in": start, "source_out": end, "output_in": 0.0, "output_out": round(end - start, 3)}]


def test_report_measures_speech_onset_from_the_audio():
    x = make_audio(6.0, WORDS, room=0.0005)
    rep = transitions.hook_audio_report(_timeline(1.94, 5.78), WORDS, PcmAudio(SR, x), HOOK, {"preamble_removed_s": 2.0, "hook_word": 3})
    assert set(rep) == {"speech_onset_s", "hook_onset_s", "preamble_removed_s", "ok", "basis"}
    assert rep["basis"] == "audio" and abs(rep["speech_onset_s"] - 0.06) <= 0.02
    assert rep["hook_onset_s"] == 0.06 and rep["preamble_removed_s"] == 2.0 and rep["ok"] is True


def test_report_flags_silence_and_a_late_hook():
    x = make_audio(6.0, WORDS[3:], room=0.0005)
    late = transitions.hook_audio_report(_timeline(0.5, 5.78), WORDS[3:], PcmAudio(SR, x), HOOK, {})
    assert late["speech_onset_s"] > 1.0 and late["ok"] is False  # 1,5 s Stille vor der ersten Sprache
    no_audio = transitions.hook_audio_report(_timeline(0.0, 5.78), WORDS, None, HOOK, {"hook_word": 9})
    assert no_audio["basis"] == "words" and no_audio["speech_onset_s"] == 0.0
    assert no_audio["hook_onset_s"] == 4.6 and no_audio["ok"] is False  # Hook-Satz erst nach 4,6 s


def test_rules_are_off_by_default_and_the_plan_carries_the_finding():
    assert transitions.hook_audio_rules(editorial.load(1)) is None
    assert transitions.hook_audio_rules(editorial.load(2)) is None
    on = policy_with({"cut.hook_audio.enabled": True})
    assert transitions.hook_audio_rules(on) == HOOK
    assert transitions.hook_audio_rules(policy_with({"cut.hook_audio.enabled": True, "implementation.cut.hook_audio": False})) is None
    rf = reframe.ReframeResult("neutral", "none", False, [], [reframe.Shot(0.0, 6.0, 0, 0, 202, 360)], 640, 360, 1080, 1920)
    segs, info = transitions.shift_preamble(SEGS, WORDS, on)
    kwargs = {
        "platform": "tiktok", "segments": segs, "reframe_result": rf, "caption_preset": "tiktok_words", "caption_cards": 1,
        "sources": {"storage_key": "k", "transcript_version": 1, "hook_version": 1, "candidate_id": "c"}, "words": WORDS,
    }  # fmt: skip
    plan = render_plan.build_plan(**kwargs, policy=on, hook_info=info, audio=PcmAudio(SR, make_audio(6.0, WORDS, room=0.0005)))
    assert plan["hook_audio"]["preamble_removed_s"] == 2.0 and plan["hook_audio"]["ok"] is True
    assert plan["segments"][0]["start"] == pytest.approx(1.94)
    assert "hook_audio" not in render_plan.build_plan(**kwargs, policy=editorial.load(2))


def test_speech_onset_threshold_ignores_room_tone():
    words = WORDS[3:]
    x = make_audio(6.0, words, room=0.01)
    rep = transitions.hook_audio_report(_timeline(1.2, 5.78), words, PcmAudio(SR, x), HOOK, {})
    assert rep["speech_onset_s"] == pytest.approx(0.8, abs=0.02)
    assert np.isfinite(rep["hook_onset_s"])
