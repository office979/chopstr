# 040: Prosodische Schnittgrenzen (Pegelminimum, Atem)

Stand 20.10.2026, Lane P4 (Launch Phase 4). Auftrag: `docs/MASTER-PROMPT-LAUNCH.md` Phase 4 (prosodische
Schnittgrenzen mit Fades), Regeln 5 und 10; Entscheidungen P31 und P48. Code:
`workers/chopstr_worker/pipeline/transitions.py` (`prosody_rules`, `prosody_edges`, `frame_analysis`, `find_breath`,
`WavAudio`, `PcmAudio`), `pipeline/render_plan.py` (`_padded`, `cut_segments`, `timeline_block`),
`activities/render.py` (`_load_analysis_audio`, `protected_ranges`). Policy: `cut.prosody.enabled` (false),
`cut.prosody.search_window_s` (0,35 s, H), Schalter `implementation.cut.prosody` (true, gebaut). Tests:
`workers/tests/test_launch_p4_prosody.py`.

**Problem.** Seit P48 liegt jede Schnittkante an der Wortgrenze aus der ASR plus festem Vor- und Nachlauf (0,06 s
und 0,18 s). Die Wortzeiten von Whisper sind auf Text ausgerichtet, nicht auf das Signal; ein Atemzug vor dem
ersten Wort, ein Nachhall oder ein Lippengeräusch liegt deshalb oft im Vorlauf. Ein Schnitt mitten in einem
Atemzug oder einer ansteigenden Energie ist hörbar, auch mit 20-ms-Blende. Es gab keine Prosodie im Schnitt
(Inventur: kein RMS, kein F0, kein Atem an den Kanten).

**Alternativen.** (a) Bei P48 bleiben. (b) Kante auf das Pegelminimum (RMS) in einem Fenster an der Wortgrenze,
Atem als eigener Fall. (c) Zusätzlich Grundfrequenz und Satzmelodie (fallende F0 als Satzende). (d) Forced
Alignment gegen das Signal und dann (b).

**Evidenz.** Synthetisches Audio mit numpy (16 kHz): Pegelloch in einer Lücke mit Raumton wird gefunden (Fenster
von 20 ms ganz im Loch), Atem (Rauschen mit Anteil über 2 kHz, 0,26 s, 40 ms vor dem Wort) bleibt draussen, in
gleichmässiger Stille bleibt die Kante beim Padding, 60 zufällige Lücken von 0 bis 0,6 s ohne einen Schnitt im
Nachbarwort (`check_transitions` ohne `transition_cut_in_word`), geschützte Spannen werden nie angefasst, Nähte
bleiben in ihrer Hälfte der Pause. Im Activity-Test liest der Render weiter das Original (`original.mp4`), nur die
Analyse liest das 16-kHz-WAV. Eine Messung an echtem Material fehlt; es liegt keins vor.

**Unsicherheit.** Schnitt-Natürlichkeit (Gate 4, mindestens 90 Prozent) ist ohne Hörer nicht messbar; diese Notiz
behauptet sie nicht. Die Konstanten (Fenster 20 ms, Schritt 10 ms, Atem 0,08 bis 0,6 s, Hochfrequenzanteil ab
0,35 über 2 kHz, Pegel zwischen dreimal Grundrauschen und halber Sprache, Abstand zum Wort 10 ms, Faktor 1,5 für
„gleich leise“) sind gesetzt, nicht gemessen (H). Raumton mit starkem Rauschen über 2 kHz (Hiss) kann als Atem
gelten; dann liegt der Schnitt früher in der Stille, nie im Wort. Liegen Wörter lückenlos, gibt es keinen Raum und
die Kante bleibt beim Padding (`rms_min_s` ist dann `null`).

**Entscheidung.** (b), hinter Schalter und Regel, Regel aus. Je Kante: Suchfenster `search_window_s` vor dem
ersten beziehungsweise nach dem letzten Wort, begrenzt durch das Nachbarwort (bei Naht oder niedriger Sicherheit
durch die Mitte der Lücke wie in `pad_segments`) und 10 ms Abstand zum eigenen Wort. Unter den Fenstern, die
höchstens 1,5-mal so laut sind wie das leiseste, gewinnt das, das der gepaddeten Kante am nächsten liegt. Atem
unmittelbar vor einem Wortbeginn verschiebt die Kante vor den Atem (beim Einstieg) beziehungsweise beendet das
Segment vor dem Atem des Folgeworts. Die 20-ms-Blenden bleiben. Ergebnis je Kante im Plan:
`timeline[k].edges = {"in": edge, "out": edge}` mit `edge = {chosen_s, text_s, rms_min_s, breath, confidence}`.
(c) und (d) erst, wenn ein Hörtest (b) als nicht ausreichend zeigt.

**Konsequenzen.** Ohne Regel ist der Plan byte-gleich (Test `test_plan_carries_edges_only_with_the_rule_...`). Mit
Regel ändert sich der Plan-Hash, jeder Clip wird einmal neu gerendert; danach ist der Plan stabil, weil die Wahl
nur von Wörtern, Audio und Grenzen abhängt (zweiter Render übersprungen, Activity-Test). Reframe, Captions und
Effekte schneiden dieselben Kanten (`render_plan.cut_segments` mit demselben Audio). Ein fehlendes WAV kostet nur
die Messung (Hinweis in `notes`, Kante wie bisher), nie den Render.

**Perspektive Produkt.** Ein Clip, der mit einem halben Atemzug beginnt, wirkt abgeschnitten, auch wenn kein Wort
fehlt. Die Funktion verschiebt nur Stille und nie Inhalt; deshalb ist sie gefahrlos zuschaltbar, aber ihr Nutzen
ist erst nach einem Hörtest belegt.

**Perspektive Redaktion.** Regel 5 bleibt unberührt: kein Wort fällt weg, keine Partikel, kein Füllwort. Regel 10
bleibt: das Ausgangsaudio wird nicht verändert, nur die Kantenzeit; geschnitten wird das Original.

**Perspektive Engineering.** Gemessen ist, was ohne Hörer messbar ist (Minimum gefunden, Nachbarwort nie
angeschnitten, Atem draussen, Stabilität über zwei Renders). Für die Abnahme fehlt ein Hörtest mit mindestens 50
Kanten je Bedingung (Padding gegen Prosodie, blind), getrennt nach Einstieg und Ende; danach Regel einschalten oder
Konstanten einzeln anpassen.
