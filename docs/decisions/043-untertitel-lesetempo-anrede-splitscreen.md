# 043: Untertitel (Lesetempo, Du/Sie, Stichprobe) und Split-Screen nur mit Bindung

Stand 20.10.2026, Lane P4 (Launch Phase 4). Auftrag: `docs/MASTER-PROMPT-LAUNCH.md` Regeln 9 und 16, Phase 4 und
Gate 4. Code: `workers/chopstr_worker/pipeline/captions_de.py` (`reading_speed`, `CaptionRules.reading_cps`,
`CaptionRules.clip_end_s`, `anrede_pruefen`, `address_check_enabled`, `sample_breaks`), `pipeline/tracking.py`
(`speaker_face_binding`, `overlap_spans`, `split_bei_overlap`, `split_screen_rules`), `pipeline/reframe.py`
(`verfolgen`, `plan_reframe`). Tests: `workers/tests/test_launch_p4_captions.py`, `test_launch_p4_split_screen.py`.

**Problem.** Lesetempo war nur eine Warnung (17 Zeichen je Sekunde), keine Grenze der Kartendauer; Du/Sie wurde
nur im Copy-Linter geprüft; für Gate 4 (200 Umbrüche ohne Komposita-Fehler) gab es kein Werkzeug. Split-Screen gab
es nur über Zeitmarken von Hand; eine automatische Teilung bei Überlappung hätte die Sprecher-ID der Diarisierung
mit einem Gesicht gleichgesetzt (Regel 16 verbietet das).

**Alternativen.** Lesetempo: (a) Warnung lassen, (b) Mindeststandzeit je Karte nach Profil, (c) Karten kürzen.
Profil: aus `brief.audience` (nicht ableitbar, freier Text) oder aus einem Feld im Untertitelstil. Split-Screen:
(d) nie automatisch, (e) automatisch mit gemessener Bindung, (f) automatisch mit `speaker_positions`.

**Evidenz.** Karten stehen bei 15 Zeichen je Sekunde 17/15 s statt 0,8 s, bei 12 Zeichen 17/12 s, nie in die
nächste Karte, nie über das Clipende; Kopf und Text der ASS-Datei bleiben gleich. Du/Sie: gemischte Formen
ergeben einen Hinweis, „Sie“ am Satzanfang zählt nicht, „Ihnen“ immer. Stichprobe: 200 Umbrüche deterministisch;
mit AP10a keine getrennte Zahl mit Einheit, ohne AP10a wird die Trennung gefunden; Silbentrennung in langen
Komposita wird als Befund gezählt. Split-Screen: Bindung aus Mundbewegung bei Alleinrede (Vertrauen ab 0,9 im
Test), keine Bindung bei gleicher Bewegung, beide ungebunden bei gleicher Position, Teilung nur mit Bindung beider
Sprecher und Überlappung ab 1,2 s, Zeitmarken von Hand gehen vor.

**Unsicherheit.** 15 und 12 Zeichen je Sekunde sind gesetzt (H). Das Feld `reading_speed` im Untertitelstil
setzt heute keine Oberfläche, es gilt also `standard`. Die Du/Sie-Zählung kennt keine Zitate (wörtliche Rede in
Sie-Form ist erlaubt); deshalb nur Hinweis, nie Textänderung. Die Bindung ist ohne Gesichtsdetektor (YuNet und
OpenCV fehlen lokal und im Image) nirgends gelaufen; an echtem Material ungeprüft.

**Entscheidung.** (b) mit Profil aus `caption_style.reading_speed`, Schalter `implementation.captions.reading_speed`
(an, nur mit AP10a). Du/Sie als Eintrag `anrede` in `export_checks` (`hinweis` bei Mischung), Schalter
`implementation.captions.address_check` (an). `sample_breaks(words, n)` als Werkzeug für Gate 4. Split-Screen (e)
mit Regel `cut.split_screen.enabled` (aus) und `min_binding_confidence` 0,8; (f) nicht, weil die Sitzordnung aus
der UI oder dem Vorschlag keine Messung ist.

**Konsequenzen.** Unter Fassung 2 ändern Lesetempo und Clipende die Kartendauer und den Plan-Hash
(`captions.reading_speed` im Caption-Block), nicht Schrift, Farbe, Position oder Animation. Ohne Detektor bleibt
die Ansicht konservativ, mit Regel steht `speaker_face_binding` im Reframe-Block (leere Liste ohne Messung) und ein
Hinweis in `notes`.

**Perspektive Produkt.** Langsamer Lesende bekommen mehr Zeit, ohne dass sich der Look ändert. Split-Screen
erscheint nur, wenn sicher ist, wer spricht.

**Perspektive Redaktion.** Untertitel geben wieder, was gesagt wurde; gemischte Anrede wird gezeigt, nicht
korrigiert. Ein falsch zugeordnetes Gesicht wäre eine falsche Sprecherzuordnung im Bild (Regel 8).

**Perspektive Engineering.** Gate 4 braucht echte Transkripte für die Stichprobe; das Werkzeug ist bereit. Die
Bindung braucht ein Image mit Detektor und einen Lauf an Gesprächsmaterial mit Überlappung.
