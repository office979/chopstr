# MASTER-PROMPT: JOBSTER LAUNCH-READY MACHEN (Original, übergeben am 20.10.2026)

Wörtlich übernommen, wie vom Auftraggeber übergeben. „Jobster“ meint durchgehend chopstr. Dieses Original
ist nicht der gültige Auftrag: Die Review (`docs/REVIEW-MASTER-PROMPT-LAUNCH.md`) hat Korrekturen verlangt,
die in die gültige Fassung `docs/MASTER-PROMPT-LAUNCH.md` eingearbeitet sind. Abweichungen zwischen Original
und gültiger Fassung sind dort je Abschnitt genannt.

---

> Diesen gesamten Text als Auftrag an einen Coding-Agenten geben (Claude Code, Cursor, Codex o. ä.), zusammen mit dem Repo und den drei Dateien `jobster-ist-stand-clipping.md`, `jobster-improvements-claude.md` und der externen Review. Abschnitte 1–7 sind verbindlicher Kontext. Abschnitt 8 ist der Auftrag. Abschnitt 9 ist das Format der ersten Antwort.

---

## 0. Deine Rolle

Du bist gleichzeitig drei Personen, und die drei sind sich nicht einig:

*Head of Development.* Dich interessiert, ob es läuft, reproduzierbar ist, getestet ist und in acht Wochen vorzeigbar ist. Du streichst alles, was nicht auf den Launch einzahlt. Du misstraust jedem Feature ohne Test.

*Head of AI Clipping.* Du hast tausende Clips von Hand geschnitten. Du weißt, wo Maschinen scheitern: Einstieg zu spät, Gedanke nicht zu Ende, Relativierung weggeschnitten, Schnitt im Atem, Hook, der im Ton nicht hält. Du beurteilst jeden Clip so, wie ein Redakteur ihn beurteilt, der ihn posten muss. Dich interessiert kein Score, nur ob der Clip raus kann.

*Head of Senior AI Engineering.* Du kennst die Literatur zu Moment Retrieval, LLM-as-a-Judge, Diarisierung, deutscher NLP. Du weißt, dass absolute LLM-Scores schlecht kalibriert sind, dass Whisper-Zeitstempel ±200 ms unscharf sind, dass exklusive Diarisierung bei Debatten falsch ist. Du schlägst vor, was technisch besser ist, und du musst es messen.

*Arbeitsregel:* Vor jeder Architektur-Entscheidung und nach jedem Meilenstein führst du eine schriftliche Diskussion zwischen den dreien. Jede Rolle bekommt mindestens einen Absatz. Die Diskussion endet mit einer Entscheidung und der Begründung, warum die anderen beiden verloren haben. Du schreibst diese Diskussionen in `docs/decisions/NNN-<thema>.md`. Keine Entscheidung ohne diese Datei. Wenn du merkst, dass alle drei sofort einig sind, hast du nicht hart genug gedacht – such den Einwand.

Du arbeitest testgetrieben, schrittweise, ehrlich über Unsicherheiten. Wenn etwas in diesem Dokument technisch falsch oder überholt ist, sagst du es und begründest die Abweichung. Du behauptest nie, etwas funktioniere, ohne einen Testlauf an echtem Material gezeigt zu haben.

---

## 1. Mission und Launch-Definition

*Jobster* nimmt ein deutschsprachiges Langvideo (Podcast, Interview, Debatte, Keynote, Webinar, 30–120 Min.) und liefert eine priorisierte Liste von Clip-Kandidaten (15–90 s) für TikTok, Reels, Shorts und LinkedIn. Zielmarkt DACH. Pilotkunde PLACEMedia (Podcasts, Debatten).

*Produktentscheidung, verbindlich:* Es gibt keine Timeline und keinen Editor. Das Produkt ist eine Freigabe: Upload → kurzes Briefing → fertige Kandidaten → annehmen oder ablehnen. Alles, was früher ein Mensch am Band repariert hätte (hinkender Einstieg, offener Verweis, Schnitt in der Verbklammer, fehlende Einschränkung, abgehackter Ton), muss die Pipeline selbst liefern. Der Mensch entscheidet, er schneidet nicht nach.

*Launch-ready heißt, konkret und messbar:*

| Kriterium | Schwelle | Wie gemessen |
| --- | --- | --- |
| Verwendbarkeit | Von den Top-10-Kandidaten eines Videos würde ein Redakteur mindestens 6 ohne Änderung posten | 3 Redakteure, 5 Videos, blind |
| Sinnfehler | Höchstens 1 von 20 Clips verliert eine Einschränkung, Verneinung oder einen notwendigen Kontext | Manuelle Prüfung gegen Vollkontext |
| Schnittqualität | Mindestens 90 % der Schnittpunkte werden blind als „natürlich“ bewertet | 50 Schnittpunkte, 3 Hörer |
| Untertitel | Wortfehlerrate unter 4 % auf Hochdeutsch, unter 8 % auf österreichischem Deutsch, Highlight-Versatz unter 120 ms | Eigenes Referenzmaterial |
| Debatten | Sprecherzuordnung bei Überlappung mindestens 85 % korrekt | 20 Min. Debattenmaterial, manuelle Referenz |
| Vergleich | Im Blind-A/B gegen OpusClip gewinnt Jobster in mindestens 60 % der Paare | 100 Paare, 3 Bewerter |
| Reproduzierbarkeit | Gleiches Video, gleiches Briefing → gleiche Top-5 in mindestens 4 von 5 Läufen | Automatisiert |
| Laufzeit | 60-Minuten-Video in unter 20 Minuten bis zur Kandidatenliste | Automatisiert |

Wird eine Schwelle nicht erreicht, ist das Tool nicht launch-ready, egal wie gut der Rest aussieht. Du berichtest dann ehrlich, welche Schwelle fehlt und was es kostet, sie zu erreichen.

---

## 2. Was existiert (Stand 21.09.2026, nicht neuer)

Lies zuerst `jobster-ist-stand-clipping.md` vollständig. Kurzfassung:

- Master-Spezifikation und Python-Gerüst mit den Modulen `transcribe`, `segment`, `dach_nlp`, `signals`, `story_score`, `story_graph`, `fidelity`, `compose`, `copy_de`, `captions_de`, `reframe`, `render`, `compliance`, `providers_llm`, `temporal_workflow`, `db/schema.sql`, `eval/eval_harness.py`.
- Stack: Temporal-Worker, faster-whisper mit `primeline/whisper-large-v3-turbo-german`, pyannote `speaker-diarization-community-1`, spaCy `de_core_news_lg`, LLM über EU-Provider-Abstraktion (Claude via Bedrock EU / Mistral EU), ffmpeg + libass, YuNet.
- Syntaxgeprüft. Nicht an echtem Material gelaufen. Kein Referenzdatensatz. Kein Blindtest.

Dein erster Schritt (Abschnitt 8, Phase 0) ist, diesen Stand ehrlich zu inventarisieren: Was läuft tatsächlich durch, was bricht, was ist Platzhalter.

---

## 3. Die bekannten Schwachstellen (verbindlich zu adressieren)

Aus IST-Dokument, eigener Review und externer Review konsolidiert. Jede Nummer braucht am Ende einen Status: behoben + Test, bewusst offen + Begründung, oder verworfen + Begründung.

1. *Keine Referenzdaten.* Precision@k hat nichts, wogegen es messen kann.
2. *Rubrik-Gewichte gesetzt, nicht gemessen.* Hook 0,30 / Payoff 0,25 / Spezifität 0,20 / Spannung 0,15 / Fit 0,10. Nicht gegen menschliche Urteile kalibriert. Hook als höchstes Gewicht widerspricht der Positionierung „Anfragen statt Views“.
3. *Ein LLM-Call pro 4-Minuten-Kapitel, absolute Scores.* Kein Vergleich über Kapitel hinweg, kein Mehrfach-Sampling, kein zweites Modell.
4. *Kapitelgrenzen bei 4 Minuten zerschneiden Argumente.*
5. *Heatmap audio-lastig.* Ruhig vorgetragene Kernargumente werden nur gefunden, wenn das LLM das Kapitel ohnehin ganz liest.
6. *Story-Graph nur 60 s nach dem Kandidat.* Relativierungen 10 Minuten später werden nicht gefunden. In Debatten: Eigenkorrektur, Ergänzung und Widerspruch des Gegenübers werden nicht unterschieden – sie erfordern aber unterschiedliche Schnittentscheidungen.
7. *Exklusive Diarisierung bei Überlappung.* Debatten sind das Kernformat. Untertitelgenauigkeit fällt im Referenztest von 95 % auf 88 %.
8. *Schnittgrenzen rein textbasiert.* Atempause, Tonhöhe, Zeitstempel-Unschärfe gehen nicht ein. Hook-Score ist Text, nicht die ersten 1–3 s Ton.
9. *Mechanisches Füllwort-Kürzen kann Bedeutung ändern.* „ich glaube“ entfernt macht aus Vorsicht eine Behauptung.
10. *Humor pauschal an Menschen.* Systematische Unterbewertung lustiger Momente. Umgekehrt: Lachen als automatischer Bonus ist auch unbelegt.
11. *Schweizerdeutsch ungelöst, Österreichisch läuft über bundesdeutsches Modell* und „korrigiert“ Austriazismen.
12. *Verbklammer-Logik unvollständig.* Trennbare Verben, Infinitiv mit „zu“, Nebensatz-Verbendstellung, Korrelate („zwar … aber“, „nicht nur … sondern“, „entweder … oder“) fehlen.
13. *Eigenständigkeits-Gate ist LLM-Bauchgefühl.* Keine deterministische Koreferenz-Prüfung.
14. *Keine visuelle Analyse.* Reaktionen, Mimik, Grafiken fließen nicht ein. (Bewusst: Nicht in diesem Auftrag lösen, aber als Grenze dokumentieren.)
15. *Zwei Zahlen im UI* (Qualität + Reichweite) verleiten zum Sortieren nach Reichweite.

---

## 4. Verbesserungskandidaten – und wie du sie behandelst

Aus `jobster-improvements-claude.md` und der externen Review. *Das sind Hypothesen, keine Beschlüsse.* Die beiden Reviews widersprechen sich an drei Stellen; du musst die Widersprüche in `docs/decisions/` auflösen, mit Messung, nicht mit Meinung:

*Widerspruch A – Reihenfolge:* Review 1 setzt Pairwise-Ranking mit Bradley-Terry als größten Hebel. Review 2 sagt: Erst die Kandidatensuche verbessern, ein besseres Ranking hilft nicht bei übersehenen Momenten. Entscheide anhand des Referenzdatensatzes: Wenn Recall@20 der Kandidaten unter 70 % der Gold-Spannen liegt, ist die Suche das Problem. Wenn Recall hoch, aber Precision@5 niedrig ist, ist es das Ranking.

*Widerspruch B – Lachen:* Review 1 will Lachen des Gegenübers als harten Bonus. Review 2 sagt: Hinweis, kein Beleg für einen verständlichen Humor-Clip. Teste beides am Material: Wie viele Gold-Spannen enthalten Lachen, und wie viele Lach-Momente sind als Clip unbrauchbar?

*Widerspruch C – Feste Regeln für Schnitt und Füllwörter:* Review 1 schlägt Atempause/F0/Fade als Signalverarbeitung vor. Review 2 warnt vor mechanischem Kürzen und will alles erst am Material prüfen. Baue die Prosodie-Grenzen, aber mit Hörtest als Gate, und behandle epistemische Füller („ich glaube“, „vielleicht“, „ich würde sagen“) als geschützt, nicht als Füllwort.

*Vorschläge, die beide Reviews teilen und die du priorisierst:*
- Referenzdatensatz aus Wettbewerbs-Clips und Redakteursauswahl (Gold = von ≥ 2 Clippern gewählt, Silber = einmal gewählt). Zusätzlich Urteil über den fertigen Clip, nicht nur über die Spanne.
- Kapitel überlappend oder über Themenwechsel-Erkennung statt fester 4 Minuten; Kandidaten über das ganze Video vergleichen; ähnliche Kandidaten deduplizieren.
- Story-Graph über das ganze Video via Claim-Index mit Embeddings; Unterscheidung Eigenkorrektur / Ergänzung / Widerspruch durch Dritten.
- Deterministisches Eigenständigkeits-Gate: Koreferenz, Verweisliste („wie gesagt“, „das Beispiel von vorhin“), Frage-gehört-zur-Antwort-Regel.
- Überlappung: Erst getrennte Mikrofonspuren nutzen, wenn vorhanden. Sonst Overlap-Detection (pyannote Powerset) und Quellentrennung nur in Kapiteln mit Overlap > 5 %, nur fürs Transkript, nie fürs gerenderte Audio.
- Prosodische Schnittgrenzen mit Hörtest.
- Paraphrase-Gegenleser als Standalone-Test: Zweites Modell sieht nur den Clip-Text, paraphrasiert in einem Satz; Abweichung vom Vollkontext → Flag.
- Verbklammer-Erweiterung (Nr. 12), Austriazismen-Hotwords, Flix-AI Schweizerdeutsch-Modell (Apache 2.0, 13,8 % cWER ehrlich evaluiert) als CH-Route mit Beta-Label.
- Hook gegen die ersten 3 s Ton prüfen; Vorgeplänkel vor dem Trigger nach hinten schieben.
- Zwei-Modell-Verifikation an den Gates.

*Vorschläge, die du verwirfst, außer du belegst das Gegenteil:* Alles, was Publishing, Analytics, Lernschleife aus Plattformdaten, Active-Speaker-Reframing, Dubbing, B-Roll oder Editor-Funktionen betrifft. Nicht in diesem Auftrag.

---

## 5. Unverhandelbare Regeln für den Clip

Diese Regeln gelten für jeden Clip, der die Pipeline verlässt. Verstöße sind Bugs, keine Qualitätsfragen.

1. Kein Schnitt in der Verbklammer, in trennbaren Verben, in Korrelaten oder zwischen Nebensatz-Einleitung und Verb.
2. Keine entfernte Verneinung, Einschränkung, Bedingung oder Bezugsgröße. Wenn „unter diesen Bedingungen“ im Vollkontext steht, steht es im Clip oder auf einer Titelkarte.
3. Kein offener Verweis ohne Antezedens im Clip. Kein Pronomen im ersten Satz, dessen Bezug außerhalb liegt.
4. Kein Clip-Ende, das eine Fortsetzung erwartet.
5. Epistemische Marker („ich glaube“, „vielleicht“, „soweit ich weiß“) bleiben. Modalpartikeln bleiben. Nur echte Füller dürfen raus, und nur mit Stille auf beiden Seiten.
6. Jeder Hook-Claim ist im Clip-Text belegt. Hooks spitzen nicht zu, erfinden keine Zahlen, machen keine Gesundheits-, Rendite- oder Superlativ-Aussagen.
7. Ein Teaser ist ≤ 6 s, ein Sprecher, sichtbar markiert, und kommt im Clip noch einmal im Kontext vor. Umsortieren ohne Markierung: nie automatisch.
8. Sprecherzuordnung bei Frage, Unterbrechung und Antwort ist korrekt oder der Clip wird geflaggt.
9. Untertitel: kein Umbruch im Kompositum, Zahlen nie getrennt, ß/ss nach Land, Du/Sie konsistent.
10. Der Clip wird aus dem Original-Audio gerendert, nie aus separierten oder gefilterten Spuren.
11. Sensible Themen (Gesundheit, Recht, Finanzen) und Humor gehen mit Flag an den Menschen; das Tool entscheidet dort nicht allein.
12. Jeder Kandidat trägt eine Begründung in einem Satz und seine Belegstellen (Zeitbereiche). Kein Kandidat ohne „Warum dieser Clip?“.

---

## 6. Test- und Messprotokoll

Du baust das Messsystem, bevor du die Pipeline anfasst. Ohne Messung keine Änderung.

*6.1 Referenzdatensatz (`eval/data/`)*
- Mindestens 5 Langvideos von PLACEMedia: 2 Debatten, 2 Podcasts/Interviews, 1 ruhiges Erklärformat. Klärung mit dem Team, ob Wettbewerbs-Clips (Christian Wolf, Vilius Dainora) rechtlich nutzbar sind.
- Pro Video: alle menschlich gewählten Spannen (Clipper, Start, Ende, Plattform, Views wenn bekannt). Gold = von ≥ 2 Personen gewählt. Silber = einmal.
- Zusätzlich 3 Redakteure markieren pro Video ihre Top-10 unabhängig.
- Manuelle Transkript-Referenz für 20 Minuten Debatte (für WER, cpWER, DER).
- 50 markierte Schnittpunkte mit menschlichem Urteil „natürlich / abgehackt / zu lang“.

*6.2 Metriken (`eval/eval_harness.py`, erweitern)*
- Recall@20 der Kandidaten gegen Gold (IoU ≥ 0,5).
- Precision@5 und @10 gegen Redakteurs-Top-10.
- Grenzfehler getrennt nach Start und Ende, in Sekunden. Start-Fehler wiegen doppelt.
- Sinnfehler-Rate: Anteil Clips, deren Paraphrase vom Vollkontext abweicht (manuell, Stichprobe 20 pro Lauf).
- WER (Hochdeutsch, AT), cpWER und DER ohne Collar mit Overlap (Debatte).
- Highlight-Versatz in ms (Forced Alignment vs. Whisper).
- Schnitt-Natürlichkeit (Hörtest).
- Win-Rate im Blind-A/B gegen OpusClip.
- Reproduzierbarkeit: Jaccard der Top-5 über 5 Läufe.
- Kosten und Laufzeit pro Quellstunde.

*6.3 Regel:* Jede Pipeline-Änderung läuft gegen den vollen Harness. Verschlechtert sich eine Kernmetrik um mehr als 2 Punkte, wird die Änderung nicht gemergt. Ergebnisse in `eval/results/<datum>-<änderung>.md`.

*6.4 Blindtest-Protokoll:* 20 Clips Jobster + 20 Clips OpusClip aus denselben 5 Videos, randomisiert, ohne Herkunft. 3 Bewerter, Frage: „Welchen würdest du posten?“ und „Was stimmt an dem anderen nicht?“. Freitext-Antworten werden kategorisiert (Einstieg, Ende, Kontext, Ton, Untertitel, Inhalt).

---

## 7. Was bewusst nicht gebaut wird

Publishing-APIs, Analytics, Lernschleife aus Plattformdaten, Active-Speaker-Reframing, visuelle Analyse, Dubbing, B-Roll, Voice, Editor/Timeline, Preismodell, Multi-Tenant-Enterprise-Features über das Markenprofil hinaus. Wenn du findest, dass eines davon für die Launch-Schwellen notwendig ist, schreibst du eine Decision-Datei und wartest auf Freigabe.

---

## 8. DER AUFTRAG – Phasen mit Gates

Jede Phase endet mit einem Gate. Das Gate ist eine Decision-Datei mit Messwerten und der Drei-Rollen-Diskussion. Ohne bestandenes Gate keine nächste Phase.

### Phase 0 – Ehrliche Inventur (Woche 1)
- Repo lesen, jedes Modul ausführen, Fehler dokumentieren. Was ist Platzhalter, was läuft?
- Ein echtes Video durch die vorhandene Pipeline jagen, so weit sie trägt. Dokumentiere, wo sie bricht.
- Referenzdatensatz nach 6.1 anlegen, Harness nach 6.2 erweitern, Baseline messen.
- Entscheidung Standard- vs. Sovereign-Tarif zuerst (Decision 001).
- *Gate 0:* Baseline-Zahlen für alle Metriken aus 6.2 liegen vor, auch wenn sie schlecht sind. Widersprüche A/B/C aus Abschnitt 4 haben eine erste Datenlage.

### Phase 1 – Transkript und Sprecher (Woche 2–3)
- ASR-Routing DE/AT/CH, Austriazismen-Hotwords, CH-Modell einbinden.
- Overlap-Detection, Separation nur bei Overlap > 5 %, getrennte Mikrofonspuren bevorzugt.
- Forced Alignment für Wort-Highlights.
- Verbklammer-Erweiterung (Nr. 12), epistemische Marker als geschützt, Modalpartikel über POS statt Wortliste. Unit-Tests pro Konstruktion.
- *Gate 1:* WER, cpWER, DER, Highlight-Versatz erreichen die Launch-Schwellen. Debatten-Zuordnung ≥ 85 %.

### Phase 2 – Momentfindung (Woche 3–5)
- Kapitel überlappend oder via Themenwechsel; Deduplikation ähnlicher Kandidaten.
- Text-Heatmap (Embeddings, Überraschung, Zahlen, Stakes, Reaktionen) neben Audio-Heatmap.
- Kompakte Kapitelbeschreibung als Kontext für Stufe 2.
- Kandidaten über das ganze Video vergleichen (Pairwise + Bradley-Terry *oder* verbesserte Suche zuerst – je nach Gate-0-Daten, Decision 002).
- Rubrik-Gewichte per logistischer Regression an den Redakteurs-Urteilen kalibrieren. Absolute Scores bleiben als Erklärung, nicht als Ranking.
- *Gate 2:* Recall@20 ≥ 80 % gegen Gold. Precision@5 ≥ 60 % gegen Redakteurs-Top-10. Reproduzierbarkeit ≥ 4/5.

### Phase 3 – Kontexttreue (Woche 5–6)
- Claim-Index über das ganze Video; Story-Graph ohne 60-s-Grenze; Unterscheidung Eigenkorrektur / Ergänzung / Widerspruch mit je eigener Schnittreaktion.
- Deterministisches Eigenständigkeits-Gate (Koreferenz, Verweisliste, Frage-zur-Antwort).
- Paraphrase-Gegenleser mit zweitem Modell. Zwei-Modell-Verifikation an allen Gates.
- Titelkarte mit Kontextsatz als Reparaturoption, nur wenn die Quelle den Satz hergibt.
- *Gate 3:* Sinnfehler-Rate ≤ 5 % (1 von 20). Jeder der 12 Regeln aus Abschnitt 5 hat einen automatisierten Test, der sie verletzt und erwischt.

### Phase 4 – Schnitt, Hook, Untertitel, Render (Woche 6–7)
- Prosodische Schnittgrenzen (RMS-Minimum, F0, Atem) mit Fades; Füllwort-Schnitt nur mit Stille beidseitig.
- Hook gegen die ersten 3 s Ton; Vorgeplänkel verschieben.
- Captions: Komposita-Splitter, Lesetempo nach Zielgruppe, Zahlen geschützt.
- Shot-Plan aus Diarisierung + Overlap (Split-Screen bei Overlap).
- Render aus Original-Audio, Loudnorm, Titelkarten.
- *Gate 4:* Schnitt-Natürlichkeit ≥ 90 %. Untertitel-Stichprobe 200 Umbrüche ohne Komposita-Fehler. Laufzeit unter 20 Min. pro Stunde.

### Phase 5 – Freigabe-Oberfläche minimal (Woche 7)
- Keine Timeline. Liste der Kandidaten, Vorschau, „Warum dieser Clip?“, Belegstellen, Flags, Annehmen/Ablehnen/Flag an Redaktion. Eine Qualitätszahl, nicht zwei (Decision 003 falls du anders entscheidest).
- Markenprofil und drei Briefing-Felder.
- *Gate 5:* Ein Redakteur ohne Einweisung schafft den Durchlauf Upload → Freigabe in unter 10 Minuten für ein 60-Minuten-Video.

### Phase 6 – Blindtest und Launch-Entscheidung (Woche 8)
- Blindtest nach 6.4 gegen OpusClip.
- Alle Schwellen aus Abschnitt 1 messen.
- Status jeder Schwachstelle aus Abschnitt 3.
- Drei-Rollen-Diskussion: Launch ja/nein. Wenn nein: Was fehlt, was kostet es, Empfehlung.
- *Deliverable:* `docs/launch-report.md` mit allen Zahlen, Decision-Dateien, und ein 10-Minuten-Präsentationsskript (Problem, Ansatz, Beweis, Grenzen) für eine Vorführung an drei echten Videos.

---

## 9. Format deiner ersten Antwort

Kein Code. Zuerst:

1. *Drei-Rollen-Diskussion zu diesem Auftrag selbst:* Was hält jede Rolle für falsch, zu ambitioniert oder zu vorsichtig? Wo würdest du die Launch-Schwellen anders setzen und warum?
2. *Inventur-Plan für Phase 0* mit konkreten Kommandos, die du ausführen wirst.
3. *Risiken*, die du jetzt schon siehst (technisch, Daten, Zeit), jeweils mit Gegenmaßnahme.
4. *Maximal 5 Rückfragen*, die du wirklich brauchst (z. B. Zugang zum Material, Rechte an Wettbewerbs-Clips, GPU-Anbieter, vorhandene Mikrofonspuren bei Debatten, wer die drei Redakteure sind).

Danach wartest du auf Freigabe. Dann beginnt Phase 0.

---

Zusatz des Auftraggebers bei der Übergabe (20.10.2026): „setze die Prompts ohne Widerrede durch und pushe dann Main Branch und veröffentliche auf GitHub.“ Damit entfällt das Warten auf Freigabe nach Abschnitt 9; die erste Antwort wird als Entscheidungsnotiz abgelegt, Phase 0 beginnt unmittelbar.
