"""Synthetische deutsche Transkripte mit Wortzeiten für Story-Engine- und Activity-Tests (kein Modell nötig)."""

from __future__ import annotations

SENTENCE_GAP_S = 0.8  # größer als MIN_PAUSE_AS_BOUNDARY, damit jede Zeile ein Satz ist

# (Sprecher, Satz, Dauer in Sekunden). Satz 6 relativiert die Aussage von Satz 1 (Story-Graph),
# Satz 10 endet auf „aber“ (Open-Loop), Satz 11 beginnt mit „Allerdings“ (Sinntreue-Gate).
DEMO_SCRIPT: list[tuple[str, str, float]] = [
    ("SPEAKER_00", "Ehrlich gesagt war das der teuerste Fehler meiner Karriere.", 5.0),
    ("SPEAKER_00", "Wir haben in unserer Branche 40 Prozent Marge verloren, und das gilt für jede Firma.", 6.0),
    ("SPEAKER_00", "Der eigentliche Grund war ein falsches Preismodell.", 5.0),
    ("SPEAKER_00", "Wir haben 2019 die Preise um 30 Prozent gesenkt.", 5.0),
    ("SPEAKER_00", "Das hat alles verändert, und zwar nach unten.", 4.0),
    ("SPEAKER_00", "Heute machen wir es genau andersrum.", 4.0),
    ("SPEAKER_00", "Das heißt aber nicht, dass das für jede Branche gilt.", 5.0),
    ("SPEAKER_00", "Bei Software sieht das anders aus.", 4.0),
    ("SPEAKER_00", "Was ich gelernt habe: Preise sind Positionierung.", 5.0),
    ("SPEAKER_00", "Und dann kam der zweite Fehler.", 3.0),
    ("SPEAKER_00", "Wir haben zu spät eingestellt und zu lange gewartet, aber", 6.0),
    ("SPEAKER_00", "Allerdings hatten wir Glück mit dem Timing.", 4.0),
    ("SPEAKER_01", "Was würdest du heute anders machen?", 3.0),
    ("SPEAKER_00", "Ich würde die Preise nie wieder unter die Kosten setzen.", 5.0),
    ("SPEAKER_00", "Konkret heißt das: erst rechnen, dann verkaufen.", 5.0),
    ("SPEAKER_00", "Das Problem ist, dass viele Gründer genau das nicht tun.", 5.0),
]


def make_words(script: list[tuple[str, str, float]], t0: float = 0.0, gap_s: float = SENTENCE_GAP_S) -> list[dict]:
    """Wörter mit gleichmäßig verteilten Zeiten pro Satz; zwischen Sätzen eine Pause von ``gap_s``."""
    words: list[dict] = []
    t = t0
    for speaker, text, dur in script:
        toks = text.split()
        step = dur / len(toks)
        for i, tok in enumerate(toks):
            words.append(
                {
                    "text": tok,
                    "start": round(t + i * step, 3),
                    "end": round(t + (i + 1) * step - 0.02, 3),
                    "prob": 0.95,
                    "speaker": speaker,
                }
            )
        t += dur + gap_s
    return words


def demo_words() -> list[dict]:
    return make_words(DEMO_SCRIPT)


def long_script(chapters: int, sentences_per_chapter: int = 20, sentence_s: float = 12.0) -> list[tuple[str, str, float]]:
    """Viele Kapitel (je ``sentences_per_chapter`` Sätze zu ``sentence_s`` Sekunden) für Limit-Tests."""
    script = []
    for c in range(chapters):
        for i in range(sentences_per_chapter):
            script.append(("SPEAKER_00", f"Kapitel {c} Satz {i} enthält eine Zahl wie {c * 10 + i} Prozent und endet hier.", sentence_s))
    return script
