# Review des Master-Prompts „Launch-ready machen“ (übergeben am 20.10.2026)

Wörtlich übernommen, wie vom Auftraggeber übergeben. Die Review prüft den Entwicklungsauftrag
(`docs/MASTER-PROMPT-LAUNCH-ORIGINAL.md`), nicht den Repository-Code. „Jobster“ meint durchgehend chopstr.
Die überarbeitete Fassung des Auftrags, in die diese Korrekturen eingearbeitet sind, steht in
`docs/MASTER-PROMPT-LAUNCH.md`.

---

**Ich würde den Prompt vor der Übergabe an einen Coding-Agenten überarbeiten.** Er setzt den richtigen Schwerpunkt auf die Qualität der erzeugten Clips. Mehrere Vorgaben könnten den Agenten jedoch zu unnötigen Umbauten führen, die Entwicklung blockieren oder eine Qualität suggerieren, die das Messverfahren gar nicht nachweist.

**Die wichtigsten Korrekturen betreffen das Testverfahren, einige zu starre Sprachregeln, die Verarbeitung von Schweizerdeutsch und die Abnahme des fertigen Exports.** Für ein Produkt ohne sichtbare Timeline müssen außerdem automatische Reparatur, Ablehnung ungeeigneter Kandidaten und interne Zeitzuordnung klar definiert sein.

Ich habe den Prompt gegen die bisherigen Unterlagen geprüft und zentrale technische Aussagen anhand offizieller Modellkarten und Dokumentationen verifiziert. Das ist eine Prüfung des Entwicklungsauftrags; den aktuellen Repository-Code habe ich dabei nicht geprüft.

## 1. Die größte Engineering-Schwäche: Der Auftrag kann sich selbst blockieren

### Gate 0 verlangt Ergebnisse, bevor deren technische Voraussetzungen existieren

Der Prompt verlangt gleichzeitig:

- Keine Pipeline-Änderung vor der Messung.
- Baseline-Zahlen für sämtliche Metriken.
- Keine nächste Phase ohne bestandenes Gate.
- Eine Bestandsaufnahme, bei der sich erst herausstellen soll, ob die Pipeline überhaupt durchläuft.

Wenn der Renderer noch nicht funktioniert, können Schnittqualität, fertige Untertitel, vollständige Laufzeit und der Vergleich fertiger Clips nicht gemessen werden. Der Agent müsste zuerst reparieren, darf laut Auftrag aber vorher nichts verändern. Das ist ein konkreter Widerspruch zwischen Abschnitt 6 und Phase 0.

**Meine Ersatzregel:**

> Phase 0 liefert eine Bestandsaufnahme und alle bereits messbaren Baselines. Fehlende Messwerte werden mit Ursache als „nicht messbar“ ausgewiesen. Minimale Reparaturen zur Herstellung eines durchgängigen Baseline-Laufs sind erlaubt und werden getrennt von Qualitätsverbesserungen dokumentiert.

Dazu gehört eine weitere Regel: **Ein fehlender Messwert darf weder als bestanden noch als null eingetragen werden.**

### Die Phasen sind zu stark voneinander abhängig gemacht

Die Momentfindung sollte nicht warten müssen, bis beispielsweise die Schweizerdeutsch-Route oder jedes Wort-Highlight seine Zielwerte erreicht. Umgekehrt sollte Sinntreue bereits im ersten vollständigen Durchlauf geprüft werden.

Ich würde die Phasen als **Prioritäten mit konkreten Nachweisen** formulieren. Ein Gate blockiert nur die Arbeiten, die tatsächlich davon abhängen, sowie die abschließende Freigabe. Unabhängige Verbesserungen können parallel laufen.

Auch die acht Wochen sind vor der Inventur zunächst ein Planungsziel. Ob sie realistisch sind, hängt unter anderem vom tatsächlichen Codezustand und der Verfügbarkeit des Referenzmaterials und der Redakteure ab.

## 2. Das Messsystem ist noch kein belastbarer Nachweis für Launch-Reife

Hier liegen die schwerwiegendsten methodischen Probleme.

### A. Entwicklung und Abschlusstest verwenden dieselben Videos

Die fünf Videos sollen Fehler aufdecken, die Kandidatensuche verbessern, Ranking-Gewichte kalibrieren, jede Änderung bewerten und anschließend den Launch belegen. Dadurch kann sich das System immer stärker an genau diese Videos anpassen.

**Das muss der Prompt ändern:**

> Entwicklungs-, Kalibrierungs- und Abschlussmaterial werden nach vollständigen Quellvideos getrennt. Der abschließende Testsatz bleibt während der Entwicklung unangetastet. Bewertungsregeln und Schwellen werden vor seiner ersten Auswertung festgeschrieben.

Ausschnitte derselben Aufnahme gehören dabei zusammen. Zwei Clips aus derselben Debatte sind keine unabhängigen Belege dafür, dass das System auch andere Produktionen beherrscht.

**Fünf Videos sind ein vernünftiger Einstieg für die Fehlersuche und einen begrenzten Pilot.** Daraus würde ich keine allgemeine Freigabe für sämtliche genannten Formate und DACH-Sprachvarianten ableiten.

### B. „Gold = von zwei Clippern gewählt“ bescheinigt keine Korrektheit

Zwei Clipper können denselben aufmerksamkeitsstarken Ausschnitt wählen und beide eine relevante Einschränkung weglassen. Ein guter Moment kann umgekehrt nur einer Person auffallen.

Die Anzahl unabhängiger Auswahlen ist ein nützliches Signal für Übereinstimmung. Sie darf nicht automatisch zur Qualitätsgarantie werden.

Ich würde drei Dinge getrennt erfassen:

| Frage | Geeignete Bewertung |
|---|---|
| **Wurde ein guter Moment gefunden?** | Abdeckung redaktionell geprüfter Referenzmomente |
| **Ist der erzeugte Ausschnitt verständlich und korrekt?** | Prüfung des tatsächlichen Clips gegen die Quelle |
| **Würde jemand diesen Clip veröffentlichen?** | Direktes redaktionelles Urteil über die fertige Ausgabe |

Damit fällt auch ein guter, neu entdeckter Moment nicht automatisch durch, nur weil er außerhalb der ursprünglichen Redakteurs-Top-10 liegt.

### C. „Ein Sinnfehler unter 20 Clips“ ist als Freigabebeleg zu schwach

Ein Fehler unter 20 geprüften Clips ergibt **beobachtete fünf Prozent**. Er beweist keine tatsächliche Fehlerquote von höchstens fünf Prozent.

Ich habe dazu eine exakte Binomialrechnung durchgeführt:

| Beobachtung | Einseitige obere 95%-Konfidenzgrenze |
|---|---:|
| Kein Fehler in 20 Clips | rund **13,9 %** |
| Ein Fehler in 20 Clips | rund **21,6 %** |

Das sind illustrative Rechnungen unter der Annahme unabhängiger, repräsentativer Beobachtungen. Clips aus wenigen gemeinsamen Quellen erfüllen diese Annahme nur eingeschränkt. Die Berechnung folgt dem von NIST beschriebenen Verfahren für exakte Binomial-Konfidenzgrenzen (itl.nist.gov, Dataplot, exact binomial confidence interval).

**Meine Änderung:**

> Kritische Sinnfehler werden separat erfasst. Ein bekannter, bestätigter kritischer Sinnfehler verhindert die Freigabe des betroffenen Clips. Für die Systembewertung werden beobachtete Fehlerzahl, Stichprobengröße, Unsicherheit und Verteilung über Quellvideos berichtet.

Ein kleiner fehlerfreier Test bleibt begrenzte Evidenz. Das sollte der Launch-Bericht ausdrücklich sagen.

### D. Der OpusClip-Blindtest geht rechnerisch nicht auf

Abschnitt 1 fordert **100 Paare**. Abschnitt 6.4 beschreibt **20 eigene Clips und 20 OpusClip-Clips**. Ohne Wiederverwendung entstehen daraus 20 Paare. Drei Bewerter liefern dazu 60 Einzelurteile, keine 100 unabhängigen Vergleichspaare.

Außerdem muss vorher feststehen, was verglichen wird:

- Die Auswahl der interessantesten Momente.
- Die Schnittqualität desselben Moments.
- Der vollständige Systemoutput inklusive Untertiteln und Bildausschnitt.

Für den Vergleich fertiger Produkte würde ich gleiche Quellen, ein vergleichbares Briefing und dasselbe Ausgabebudget vorgeben. Die Bewerter brauchen zusätzlich die Optionen **„gleich gut“ und „beide unbrauchbar“**. Sonst gewinnt zwangsläufig auch einmal der weniger schlechte von zwei schlechten Clips.

### E. Die Suche lässt sich mit Recall@20 allein nicht diagnostizieren

Die Regel „Recall@20 unter 70 Prozent bedeutet, dass die Suche das Problem ist“ ist zu grob.

Wenn ein guter Moment im vollständigen Kandidatenpool vorhanden ist, anschließend aber von einem Gate verworfen oder schlecht einsortiert wird, liegt der Fehler an einer anderen Stelle.

**Besser ist eine getrennte Messung der Abdeckung:**

1. Im vollständigen Kandidatenpool.
2. Nach den Qualitätsfiltern.
3. Nach dem Ranking in den ersten Vorschlägen.

So erkennt ihr, ob die Pipeline gute Momente **übersieht, fälschlich verwirft oder zu weit hinten einordnet**.

## 3. Einige „unverhandelbare“ Sprachregeln würden gute Clips blockieren

Die Ziele hinter den Regeln sind sinnvoll. Ihre aktuelle Formulierung ist teilweise zu pauschal.

| Vorgabe im Prompt | Problem | Präzisere Regel |
|---|---|---|
| **Kein Pronomen am Anfang mit Bezug außerhalb des Clips** | Verständliche Einstiege wie „Es gibt drei häufige Fehler …“ brauchen kein vorher genanntes Bezugswort. | Nur ungelöste Verweise blockieren, deren Auflösung zum Verständnis der Kernaussage notwendig ist. |
| **Hooks spitzen nicht zu** | Das kann prägnante, aufmerksamkeitsstarke Verpackung verhindern. | Hooks dürfen verdichten und gewichten. Aussage, Zuschreibung, Sicherheit, Zeitraum, Größenordnung und Kausalität müssen erhalten bleiben. |
| **Modalpartikeln bleiben; POS-Tags entscheiden** | Ein Wort oder grammatisches Label allein erklärt seine Funktion im Gespräch nicht zuverlässig. | Bedeutung, Unsicherheit und Sprecherhaltung schützen. Bei unklarer Funktion bleibt die Formulierung erhalten. |
| **Eine fehlende Bedingung kann auf eine Titelkarte** | Eine kleine Einblendung kann untergehen, während der Ton eine uneingeschränkte Aussage vermittelt. | Bedeutungsentscheidende Bedingungen bevorzugt im gesprochenen Ausschnitt erhalten. Jede Reparatur am vollständigen Ergebnis erneut prüfen. |
| **Teaser bis sechs Sekunden, anschließend vollständige Wiederholung** | Bei kurzen Clips kann ein erheblicher Teil aus Wiederholung bestehen. | Teaser als optionale Variante gegen die chronologische Fassung bewerten: Verständlichkeit, Redundanz und Wirkung. |
| **Keine Gesundheits-, Rendite- oder Superlativ-Aussagen in Hooks** | Vermischt erfundene Systemversprechen mit korrekt wiedergegebenen Aussagen aus der Quelle. | Keine unbelegten Versprechen erzeugen. Quellaussagen korrekt zuordnen und sensible Inhalte gesondert prüfen. Quelltreue bestätigt nicht deren sachliche Richtigkeit. |

Diese Regeln stehen insbesondere in Abschnitt 5 und werden in den späteren Phasen verbindlich umgesetzt. Deshalb sollten sie vor dem Coding präzisiert werden.

### Ein Beispiel für zulässige Hook-Verdichtung

*Erfundenes Beispiel zur Illustration:*

Gesprochen:

> „Ich habe in einer Woche rund 40.000 Euro verloren.“

Eine sinntreue Verdichtung wäre:

> „Rund 40.000 Euro Verlust in einer Woche.“

Ohne weitere Aussage in der Quelle wäre dagegen dieser Hook falsch:

> „Diese Methode kostet dich 40.000 Euro.“

Damit würden Sprecherbezug, Geltungsbereich und möglicherweise die behauptete Ursache verändert.

**Für eure Clipping-Qualität ist diese genaue Bedeutungsgrenze hilfreicher als ein pauschales Verbot von Zuspitzung.**

### „Deterministische Koreferenz“ ist keine verlässliche semantische Garantie

Eine Verweisliste kann bestimmte Formulierungen deterministisch markieren. Ob ein Zuschauer den Bezug tatsächlich versteht, ist damit noch nicht entschieden.

Auch spaCy beschreibt seine Koreferenzauflösung als Modellvorhersage von zusammengehörigen Erwähnungen. Das ist kein formaler Beweis, dass ein Clip eigenständig verständlich ist (spacy.io/api/coref).

Der Prompt sollte daher **regelbasierte Hinweise, modellbasierte Bewertung und bestätigte Fehler** unterscheiden. Ein negativer Test pro Regel reicht ebenfalls nicht aus: Ihr braucht zulässige Gegenbeispiele, damit der Prüfer nicht einfach alles Verdächtige ablehnt.

## 4. Drei technische Korrekturen sind für den DACH-Kern besonders wichtig

### A. Schweizerdeutsch: Normalisierte Untertitel und gesprochene Wörter auseinanderhalten

Das vorgeschriebene Flix-Modell überträgt laut Modellkarte Schweizerdeutsch in grammatisches Standarddeutsch. Die Modellkarte nennt zudem mögliche Änderungen der Wortreihenfolge und Unterschiede zu wortgetreuer Transkription. Die dort berichteten 13,8 Prozent cWER sind eine spezifische Fehlerdefinition und kein Nachweis eurer Produktqualität (huggingface.co/Flix-AI/flix-swissgerman-full).

**Meine technische Ableitung:** Ein normalisierter Standardsatz darf nicht automatisch als exakt gesprochene Wortfolge für Schnittgrenzen und Wort-Highlights behandelt werden.

Der Prompt braucht deshalb folgenden Datenvertrag:

> Trenne am Quellaudio verankerte Sprach- und Zeitinformationen von normalisiertem Untertiteltext. Dokumentiere pro ASR-Route, ob sie wortgetreu transkribiert oder sprachlich überträgt. Wort-Highlights benötigen eine belastbare Zuordnung zum gesprochenen Material.

Wenn diese Zuordnung nicht zuverlässig möglich ist, sind größere zeitlich verankerte Untertitelgruppen eine sinnvollere Ausgabe.

Auch das Routing sollte sich nach der tatsächlichen Sprache der Aufnahme richten. Ein Schweizer Kunde kann Standarddeutsch sprechen; ein österreichischer Kunde kann Material mit mehreren Sprachvarianten hochladen.

### B. Bei pyannote ist die verwendete Ausgabe entscheidend

Community-1 liefert laut offizieller Modellkarte **reguläre Diarisierung und zusätzlich eine exklusive Sprecherzuordnung**. Die exklusive Variante dient unter anderem dazu, Sprecherzeiten leichter mit Transkriptzeiten zu verbinden (huggingface.co/pyannote/speaker-diarization-community-1).

Die Engineering-Aufgabe lautet deshalb genauer:

> Prüfe, welche Ausgabe die bestehende Pipeline verwendet. Erhalte die überlappungsfähige Sprecherzeitstruktur. Nutze eine exklusive Darstellung nur dort, wo sie für die Ausgabe sinnvoll ist.

Bevor eine neue Separation eingebaut wird, sollte geprüft werden, ob vorhandene Informationen schlicht verloren gehen.

Die feste Schwelle **„Separation bei mehr als fünf Prozent Overlap pro Kapitel“** würde ich ebenfalls als Hypothese behandeln. Relevant ist, welche konkrete Passage falsch transkribiert wird und ob die Separation dort hilft.

### C. Forced Alignment muss gegen echte Audioanker gemessen werden

Im Prompt wird der Highlight-Versatz teilweise als „Forced Alignment versus Whisper“ beschrieben. Dieser Abstand zeigt zunächst nur, dass beide Verfahren unterschiedliche Zeitpunkte liefern.

Er zeigt nicht, welches richtig liegt.

WhisperX nennt selbst Grenzen bei überlappender Sprache und fehlenden Wortzuordnungen, unter anderem für bestimmte Zahlen- und Währungsdarstellungen. Gerade diese Fälle sind für euren Business- und Debattencontent relevant (github.com/m-bain/whisperX).

**Meine Ersatzregel:**

> Messe Wortanfang und Wortende gegen manuell kontrollierte Audioanker. Berichte typische Abweichungen, hohe Perzentile und fehlende Alignments. Prüfe anschließend das Timing im tatsächlich gerenderten Clip.

Dazu würde ich **Namen, Beträge, Prozentzahlen, Negationen und Einschränkungen separat bewerten**. Eine gute durchschnittliche Wortfehlerrate kann einzelne gravierende Inhaltsfehler verdecken.

## 5. Das System braucht klare Regeln für schlechte und unsichere Kandidaten

Der Prompt fordert automatisch fertige Clips und erlaubt gleichzeitig:

> Sprecherzuordnung korrekt oder Clip geflaggt.

Ein Warnsymbol verbessert keine falsche Zuordnung. Wenn der Mensch ausschließlich annehmen oder ablehnen soll, muss vorher klar sein, was die Pipeline selbst tut.

Ich würde drei Fälle unterscheiden:

| Ergebnis | Verhalten |
|---|---|
| **Qualitätsprüfungen bestanden** | Als verwendbaren Kandidaten ausgeben. |
| **Bewertung unsicher** | Konkreten Prüfgrund und passende Quellstelle zeigen. Menschliche Prüfung kann die Unsicherheit auflösen. |
| **Fehler bestätigt** | Begrenzte automatische Reparatur mit erneuter Prüfung. Bleibt der Fehler bestehen, Kandidaten als nicht freigabefähig behandeln. |

Ein bestätigter Sinnfehler darf nicht durch bloßes Anklicken verschwinden.

### Weniger als zehn Clips müssen erlaubt sein

Nicht jedes Video enthält zehn eigenständige, starke Kurzclips. Die Pipeline muss auch drei gute oder begründet gar keine geeigneten Kandidaten liefern dürfen.

Gleichzeitig darf sie nicht durch übermäßiges Aussortieren scheinbar perfekt werden. Deshalb müssen drei Größen gemeinsam steigen beziehungsweise sinnvoll zusammenpassen:

- Anteil veröffentlichungsfähiger Vorschläge.
- Anzahl unterschiedlicher guter Clips pro Quellstunde.
- Abdeckung der redaktionell geprüften Referenzmomente.

Das ist für ein Produkt ohne Timeline eine wesentlich bessere Erfolgsdefinition als eine isolierte Quote von sechs verwendbaren Clips unter zehn Vorschlägen.

## 6. Die interne Schnittgrundlage und der fertige Export fehlen als verbindliche Abnahme

### Die sichtbare Timeline kann entfallen; die interne Schnittbeschreibung bleibt zentral

Mit mehreren Segmenten, getrennten Mikrofonspuren, Füllwortschnitten und wiederholten Teasern müssen alle Komponenten dieselbe Zeitbasis verwenden.

Der Prompt sollte ausdrücklich verlangen:

> Jeder verwendete Quellbereich wird mit seiner Position im fertigen Clip gespeichert. Audio, Bild, Untertitel und Belegstellen werden aus derselben Schnittbeschreibung abgeleitet. Mehrspuraufnahmen erhalten eine überprüfte gemeinsame Zeitbasis.

Sonst können einzelne Module korrekte Ergebnisse liefern und der zusammengesetzte Clip trotzdem falsche Untertitel oder Belegstellen enthalten.

Zusätzlich gilt für das vorgesehene Reframing: **Eine Sprecher-ID ist noch keine Zuordnung zu einem Gesicht oder Bildbereich.** Ein automatischer Split-Screen bei Überlappung ist erst sinnvoll, wenn diese Verbindung abgesichert ist. Für unklare Fälle braucht die bestehende Ausgabe eine konservative verfügbare Ansicht.

### „Fertig“ muss eine tatsächlich nutzbare Videodatei bedeuten

Der Auftrag endet sprachlich häufig bei Kandidatenliste oder Freigabe. Die Exportdatei sollte das zentrale Abnahmeobjekt werden:

> Ein Clip gilt erst als fertig, wenn die vollständige Exportdatei abrufbar ist und Bild, Ton, Schnittfolge, Synchronität und Untertitel der freigegebenen Fassung entsprechen.

Zur vorhandenen Kernpipeline gehören außerdem überprüfbare Fehlerzustände: Ein abgebrochener Render darf keinen Fertigstatus erzeugen, und Wiederholungsversuche dürfen keine widersprüchlichen oder doppelten Freigabeobjekte produzieren.

### „Nie gefiltertes Audio“ widerspricht der vorgesehenen Verarbeitung

Der Prompt verbietet gefilterte Spuren und verlangt später Loudnorm und Fades. Das muss präziser werden:

> Das Original bleibt unverändert als Referenz erhalten. Der Export verwendet Original- beziehungsweise freigegebene Mikrofonspuren. Erlaubte Pegelanpassungen und Übergangsfades werden definiert. KI-separierte Analysespuren ersetzen das Ausgangsaudio nicht automatisch.

## 7. Die übrigen Launch-Metriken brauchen eindeutige Definitionen

Mehr Zahlen allein machen den Auftrag nicht messbarer.

| Vorgabe | Erforderliche Korrektur |
|---|---|
| **85 % Sprecherzuordnung bei Overlap** | Definieren, ob Wörter, Zeitanteile oder Segmente bewertet werden. Unaufgelöste und falsch zugeordnete Stellen getrennt ausweisen. |
| **cpWER und DER erreichen Launch-Schwellen** | Die entsprechenden numerischen Schwellen fehlen in Abschnitt 1. Referenzformat, Auswertungsbereich und Zielwerte müssen erst festgelegt werden. |
| **Highlight-Versatz unter 120 ms** | Wortbeginn oder Wortende, Median oder hohes Perzentil und Umgang mit fehlenden Alignments definieren. |
| **Gleiche Top-5 in vier von fünf Läufen** | Gespeicherte Wiederholung und frische Modellinferenz getrennt testen. Jaccard allein ignoriert die Rangfolge. |
| **90 % natürliche Schnittpunkte** | Zusätzlich vollständige Clips beurteilen. Ein einzelner schlechter Schnitt kann einen ansonsten guten Clip unbrauchbar machen. |
| **Unter 20 Minuten Verarbeitung; Upload bis Freigabe unter zehn Minuten** | Wartezeit und aktive Bedienzeit trennen. Hardware, Cachezustand und Zahl der gerenderten Clips dokumentieren. |
| **Keine Verschlechterung um mehr als zwei Punkte** | Pro Metrik eigene Einheit, Richtung, Toleranz und Stichprobe definieren. |

Bei der Sprecherbewertung ist die Unterscheidung fachlich relevant: DER enthält verpasste Sprache, Fehlalarme und Sprecherverwechslungen. Sie entspricht keiner einfachen Quote korrekt zugeordneter Wörter. Für unterschiedliche Transkriptions- und Sprecherfragen existieren entsprechend unterschiedliche Metriken, etwa WER, cpWER und DER (pyannote.github.io/pyannote-metrics).

## 8. Mehrere technische Hypothesen werden zu früh verpflichtend gemacht

Abschnitt 4 erklärt Verfahren zu Hypothesen. Später sind unter anderem zwei Modelle an allen Gates, logistische Regression, ein bestimmtes CH-Modell und konkrete Separation-Schwellen bereits Pflicht.

**Das widerspricht dem angekündigten Vorgehen anhand von Messwerten.**

Meine Ersatzregel wäre:

> Verbindlich sind Fehlerfall, gewünschtes Verhalten und Abnahmekriterium. Modell, Schwelle und Verfahren bleiben austauschbar. Übernommen wird eine Änderung, wenn sie gegenüber der Baseline einen nachvollziehbaren Nutzen zeigt und relevante Regressionen geprüft wurden.

Das betrifft besonders:

- **Pairwise-Ranking:** Ein sinnvoller Kandidat für bessere Sortierung. Auch Paarvergleiche können jedoch Positionsbias zeigen; die Forschung liefert keine pauschale Garantie für korrektes Ranking eurer Clips (arxiv.org/abs/2406.07791).
- **Zwei-Modell-Verifikation:** Kann zusätzliche Fehler finden. Zwei Modelle können aber denselben fehlerhaften Transkripttext übernehmen oder denselben Kontext übersehen. Gemessen werden müssen zusätzlich entdeckte Fehler und zusätzlich fälschlich abgelehnte gute Clips.
- **Hook-Gewicht 0,30:** Dass dieses Gewicht automatisch der Positionierung „Anfragen statt Views“ widerspricht, ist im Prompt nicht belegt. Redaktionelle Präferenz und tatsächliche Anfragen sind unterschiedliche Zielgrößen.
- **Ein-Satz-Paraphrase als Sinntreueprüfung:** Eine kurze Paraphrase kann gerade die entscheidende Bedingung weglassen. Die Prüfung sollte Zuschreibung, Verneinung, Sicherheit, Bedingungen, Zahlen und zeitlichen Bezug gezielt vergleichen.
- **Claim-Index über das ganze Video:** Ein größerer Suchraum ist hilfreich. Ein nicht gefundener Kontextbezug beweist trotzdem nicht, dass keiner existiert. Die Begründungen an den Nutzer müssen diese Grenze respektieren.

## 9. Den Arbeitsauftrag würde ich schlanker und eindeutiger machen

Vier Änderungen betreffen unmittelbar die Steuerung des Coding-Agenten:

**Erstens: „Timeline raus“ präzisieren.**
Der Prompt erweitert deine bisherige Vorgabe zu „kein Editor“. Das kann auch bestehende Untertitelkorrekturen oder andere einfache Korrekturmöglichkeiten betreffen. Die Entfernung der sichtbaren Timeline sollte ausdrücklich beschrieben werden; andere Funktionen dürfen daraus nicht automatisch zur Löschung abgeleitet werden.

**Zweitens: Die Tarifentscheidung aus Phase 0 entfernen.**
„Standard versus Sovereign“ widerspricht dem ausgeschlossenen Preismodell und lenkt vom Clipping-Kern ab. Bestehende Vorgaben zu zulässigen Providern und Verarbeitungsregionen können technisch übernommen werden, ohne daraus eine Tarifentscheidung zu machen.

**Drittens: Die erzwungene Drei-Rollen-Diskussion ersetzen.**
Die Perspektiven Produktnutzen, redaktionelle Qualität und Engineering sind hilfreich. Die Forderung, immer Streit zu erzeugen und zu erklären, warum zwei Rollen „verloren haben“, fördert inszenierte Debatten.

Eine Entscheidungsnotiz sollte stattdessen enthalten: Problem, relevante Alternativen, Evidenz, Unsicherheit, Entscheidung und Konsequenzen. Routineentscheidungen brauchen keine eigene Diskussion.

**Viertens: Tests nach Umfang der Änderung staffeln.**
Der vollständige Harness umfasst menschliche Hörtests und Wettbewerbervergleiche. Das ist nach jeder kleinen Änderung nicht sinnvoll. Automatisierte und gezielte Regressionstests gehören an die einzelne Änderung; umfangreiche menschliche Bewertungen an definierte Meilensteine und die abschließende Abnahme.

## Meine empfohlene Reihenfolge für die überarbeitete Fassung

| Schritt | Konkretes Ergebnis |
|---|---|
| **1. Tatsächlichen Stand feststellen** | Nachvollziehbare Bestandsaufnahme, verfügbare Daten, funktionierende Teile und konkrete Blocker |
| **2. Einen vollständigen Baseline-Durchlauf herstellen** | Ein echtes Video liefert überprüfbare, abspielbare Exportclips |
| **3. Referenzen und Fehlerklassen festlegen** | Getrennte Entwicklungs- und Abschlussdaten; Bewertung von Momentwahl, Bedeutung, Schnitt und Ausgabe |
| **4. Größte Fehlerquelle verbessern** | Je nach Befund Transkript, Suche, Filter, Ranking, Kontext oder Rendering |
| **5. Am fertigen Clip gegenprüfen** | Qualität, Ausbeute, verpasste Momente und verbleibende Fehler gemeinsam bewerten |
| **6. Freigabe für den belegten Materialumfang treffen** | Aussage darüber, welche Formate und Sprachvarianten ausreichend geprüft sind und welche offen bleiben |

**Die zentrale Anforderung an den Coding-Agenten sollte lauten: Erhöhe nachweisbar die Zahl eigenständiger, sinntreuer und direkt verwendbarer Clips aus unserem realen DACH-Material. Beurteile jede Änderung am fertigen Export und dokumentiere sowohl Qualitätsgewinn als auch neu entstandene Fehler.**

Damit bekommt der Agent einen klaren technischen Auftrag, ohne an unbelegten Modellentscheidungen oder widersprüchlichen Gates festzuhängen.
