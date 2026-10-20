# 042: Hook gegen die ersten Sekunden Ton, Vorgeplänkel

Stand 20.10.2026, Lane P4 (Launch Phase 4). Auftrag: `docs/MASTER-PROMPT-LAUNCH.md` Phase 4 („Hook gegen die
ersten Sekunden Ton; Vorgeplänkel verschieben“), Regeln 5 und 7. Code: `workers/chopstr_worker/pipeline/
transitions.py` (`hook_audio_rules`, `shift_preamble`, `is_preamble`, `preamble_phrases`, `hook_audio_report`),
`render_plan.build_plan` (`hook_info`), `activities/render.py`. Policy: `cut.hook_audio.enabled` (false),
`cut.hook_audio.max_lead_s` (1,0 s, H), `cut.hook_audio.hook_window_s` (3,0 s, H), Schalter
`implementation.cut.hook_audio` (true, gebaut). Tests: `workers/tests/test_launch_p4_hook_audio.py`.

**Problem.** Der Hook-Wert der Kandidatensuche nutzt Text und RMS/Flux; ob im fertigen Clip in der ersten Sekunde
überhaupt gesprochen wird und ob der Satz, der den Clip trägt, in den ersten drei Sekunden beginnt, prüft niemand.
Beginnt ein Clip mit „Also. Ja gut.“, verliert er genau die Sekunden, in denen entschieden wird, ob jemand
weiterschaut.

**Alternativen.** (a) Nur prüfen und melden. (b) Prüfen und Vorgeplänkel aus ganzen Sätzen überspringen. (c)
Zusätzlich einen späteren Satz als Teaser vorziehen. (d) Neue Satzlogik für Teilsätze („Also, ich glaube …“
kürzen).

**Evidenz.** Tests mit Wortlisten und synthetischem Audio: zwei Sätze Vorgeplänkel werden entfernt, der Einstieg
liegt auf dem Hook-Satz; „Also ich glaube nicht.“ bleibt (Inhalt), „Ja gut“ ohne Satzende bleibt (Satzgrenze
erlaubt es nicht); Begrüssungen aus `trim.removal.edge_markers` zählen; ein Teaser vorne und geschützte Wörter
verhindern das Verschieben; ein zweiter Render nach dem Rückschreiben ergibt denselben Befund. Sprachbeginn wird
aus dem Pegel gemessen (über einem Viertel des Sprachpegels des ersten Wortes, Raumton bleibt darunter), ohne
Audio aus den Wortzeiten (`basis: "words"`).

**Unsicherheit.** Die Liste der Füllwörter für Vorgeplänkel (`PREAMBLE_WORDS`: also, gut, so, na, nun, hallo, hi,
hey, servus, moin, okay, ok, dazu `dach_nlp.HARD_FILLERS` und `BACKCHANNEL` und die Wendungen der Policy) ist
gesetzt (H). Ein „Ja.“ als Antwort auf eine Frage vor dem Clip ist kein Vorgeplänkel, wird hier aber so behandelt,
wenn es am Clipanfang steht; die Frage liegt dann ohnehin ausserhalb. Ob ein früherer Einstieg die Wirkung
verbessert, zeigt erst der Blindvergleich.

**Entscheidung.** (b), hinter Schalter und Regel, Regel aus. Nur das erste Segment, nur Rolle `body`, nur ganze
Sätze mit hartem Satzende (`punct` oder `speaker_change` aus `dach_nlp.sentence_end_kinds` mit der Satzregel der
Fassung), höchstens zwei Sätze und 6 s, nie über eine geschützte Spanne (`trim_plan.protected_spans`). Befund im
Plan: `hook_audio = {speech_onset_s, hook_onset_s, preamble_removed_s, ok, basis}`, `ok` heisst Sprache bis
`max_lead_s` und Hook-Satz bis `hook_window_s`. (c) bleibt die Teaser-Logik der Kandidatensuche (Regel 7, nie
automatisch umsortiert). (d) widerspricht dem Auftrag (keine neue Satzlogik) und Regel 5.

**Konsequenzen.** Ohne Regel: kein Befund, kein Verschieben, Plan byte-gleich. Mit Regel wirkt der verschobene
Einstieg auf Copy, Reframe, Captions und Plan; nach dem Rückschreiben (P48) steht er in `clips.composition`. Der
Kandidat bleibt unverändert; `preamble_removed_s` wird gegen dessen Beginn gerechnet, damit Wiederholungen
denselben Plan ergeben. Wirksam nur mit `cut.padding`.

**Perspektive Produkt.** Der Clip beginnt mit dem Satz, der ihn trägt; Stille oder Geplänkel am Anfang werden
sichtbar (`ok: false`), auch wenn nichts verschoben wird.

**Perspektive Redaktion.** Entfernt werden nur ganze Sätze ohne Inhalt; Modalpartikeln und epistemische Marker in
einem Inhaltssatz bleiben (Regel 5). Der Hook-Text bleibt Sache von Lane P3 und Copy.

**Perspektive Engineering.** Die Satzgrenzen kommen aus der vorhandenen Zerlegung, die Wortlisten aus der Policy;
neu sind nur die Prüfung und das Verschieben. Offen: Blindvergleich mit und ohne Regel (Kriterien Wirkung und
Quellentreue), danach Regel und Schwellen einzeln.
