# 041: Export als Abnahmeobjekt (Regel 16) und Tonregel 10

Stand 20.10.2026, Lane P4 (Launch Phase 4). Auftrag: `docs/MASTER-PROMPT-LAUNCH.md` Regeln 10 und 16, Phase 4
(„Render nach Regel 10 und 16; Export als Abnahmeobjekt“); Review `docs/REVIEW-MASTER-PROMPT-LAUNCH.md` Abschnitt 6.
Code: `workers/chopstr_worker/pipeline/ausgabe_pruefung.py` (`export_rules`, `abnahme_pruefen`, `abrufbar_befund`,
`abnahme_zusammenfassung`, `export_ok_aus`, `anrede_befund`), `activities/render.py` (`_render`,
`_export_ok_stored`). Policy: `export.strict` (false), `export.duration_tolerance_s` (0,2 s, H), Schalter
`implementation.export.strict` (true, gebaut). Tests: `workers/tests/test_launch_p4_export.py`.

**Problem.** Drei Lücken aus der Inventur. (1) Die Ausgabeprüfung misst Datei, Bild, Ton, Dauer gegen die Summe der
Segmente, Pegel und Untertitel im Bild, aber nicht, ob Untertitel und Schnittbeschreibung zusammenpassen. (2) Bei
einem Prüffehler bleibt `file_key` gesetzt; ein zweiter Aufruf mit demselben Plan-Hash fand die Datei und setzte
`status = rendered` ohne erneute Prüfung (`activities/render.py`, Abzweig „Render bereits vorhanden“). Ein nicht
abgenommener Export konnte so durch eine Wiederholung fertig werden. (3) Regel 10 war nur im Code zu lesen, nicht
geprüft.

**Alternativen.** (a) Wie bisher. (b) Zusätzliche Prüfungen und `export_ok` hinter einem Schalter, Fassung 1
unverändert. (c) Dasselbe ohne Schalter für alle Fassungen. (d) Eigene Tabelle für Exporte.

**Evidenz.** Unit-Tests je Prüfung mit gezielten Defekten (Dauer, Untertitel über das Clipende, Untertitel aus
anderen Segmenten als der Plan, Wort ausserhalb jedes Segments, Stille, Schwarzbild). Activity mit echtem ffmpeg:
bestandene Abnahme ergibt `rendered`, `file_key` und `export_ok: true`; zweiter Aufruf erzeugt keine zweite
Clip-Zeile, keine zweite Datei und keine neue Caption-Version; nicht abrufbare Datei ergibt `failed`, `file_key`
leer, eine Wiederholung bleibt `failed`, erst mit abrufbarer Datei `rendered`; ein abgebrochener Render
(`RenderError`) endet `failed`. Medientest (`tests/test_render_media.py`): Datei 10,000 s bei geplanten 10,000 s.
Tonregel: Filterkette mit und ohne Musik, mit und ohne Kompressor zerlegt; auf dem Weg der Sprache nur `asetpts`,
`afade`, `concat`, `asplit`, `amix`, `acompressor`, `loudnorm`, `aresample`; Musik nur `atrim`, `asetpts`, `apad`,
`volume`, `afade`, `sidechaincompress` (Sprache nur als Auslöser), `amix`; alle Segment-Eingänge sind das
Original, nicht das 16-kHz-WAV; ein eingeschleuster `highpass` wird erkannt.

**Unsicherheit.** Die Toleranz 0,2 s ist ein Startwert (ein Bild bei 25 fps je Naht plus AAC-Rahmen); gepaddete
Segmente sind nicht bildgenau, das Verhalten bei variabler Bildrate bleibt ungeprüft (P48). „Abrufbar“ prüft den
Speicher des Workers, nicht die signierte URL des Webs. Die Synchronität ist an den Zeiten geprüft (Wortanfang in
einem geschnittenen Abschnitt, Zeiten aus derselben Schnittbeschreibung), nicht am Bild.

**Entscheidung.** (b). Unter `export.strict` kommen sieben Einträge zu `export_checks` (`timeline_dauer`,
`untertitel_abdeckung`, `untertitel_zeiten`, `synchron`, `ton_stumm`, `bild_schwarz`, `abrufbar`) und als letzter
`{"pruefung": "abnahme", "ergebnis", "text", "gemessen": null, "export_ok": bool}`. `rendered` und `file_key` nur mit
`export_ok`; sonst `failed`, `render_error` mit dem ersten Fehler, die Datei bleibt im Speicher, ist aber nicht
freigegeben. Der Abzweig „bereits vorhanden“ verlangt unter `export.strict` ein gespeichertes `export_ok`. Mit
Lesetempo oder Abnahme steht keine Untertitelkarte über das Clipende hinaus (`CaptionRules.clip_end_s`). (c)
nicht, weil Fassung 1 byte-gleich bleiben muss; (d) nicht, weil `export_checks` die Liste ist, die das Web schon
liest (`apps/web/lib/clips/pruefstand.ts` zeigt jeden Eintrag mit Text, `fehler` sperrt das Veröffentlichen).

**Konsequenzen.** Ohne Regel ändert sich nichts, auch nicht der Plan-Hash. Mit Regel: ein nicht abgenommener Clip
hat keinen `file_key` und damit im Web „datei_fehlt“ und „clippen_gescheitert“; Download und Veröffentlichen sind
gesperrt. Der Fehler in (2) bleibt unter Fassung 1 bestehen (offener Punkt, bewusst nicht ohne Schalter geändert).
`exported` setzt weiter das Web beim Download.

**Perspektive Produkt.** „Fertig“ heisst nach Regel 16: die Datei ist abrufbar und Bild, Ton, Schnittfolge,
Synchronität und Untertitel entsprechen der Fassung. Ein Kunde bekommt nie einen Clip, der nur beinahe stimmt.

**Perspektive Redaktion.** Untertitel, die aus anderen Segmenten stammen als das Video, wären ein Sinnfehler im
Bild (falsche Worte zur falschen Zeit). Die Prüfung leitet die erwarteten Wortzeiten nur aus der
Schnittbeschreibung ab und vergleicht.

**Perspektive Engineering.** Jede Prüfung ist eine reine Funktion mit eigenem Test; die Activity fügt nur
zusammen. Rollback je Schalter (`export.strict: false`). Offen: Regel einschalten nach einem Lauf an echtem
Material, bei dem die Quote der Abnahmefehler bekannt ist.
