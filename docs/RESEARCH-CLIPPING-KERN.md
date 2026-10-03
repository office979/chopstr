# Recherche: Schwachstellen der Kernfunktion und Grundlagen für bessere Clips (DACH)

Stand 03.10.2026. Fünf getrennte Untersuchungen wurden zusammengeführt: ein Code-Audit des Clipping-Kerns
gegen Build-Prompt und Master-Whitepaper, ein Extrakt des gesamten Projektwissens (Whitepaper, Masterfile,
DSCVRY-Skill, Masterclass, Copywriting-Brief, Wissensbasis), eine externe Recherche zur Hook- und
Konsumentenpsychologie, eine Recherche zum Aufbau erfolgreicher DACH-Clips und Plattformsignalen 2026 sowie
eine Wettbewerbsanalyse. Dieses Papier ist die Grundlage für den Auftrag in `MASTER-PROMPT-CORE-CLIPPING.md`.

Statusschreibweise (verbindlich für alle Regeln, die daraus abgeleitet werden):

- **F** Forschungsbefund: in Studie, Meta-Analyse oder offizieller Plattformdokumentation beobachtet.
- **H** Übertragungshypothese: plausibel, aber auf Short-Form-Video oder DACH noch nicht gemessen.
- **R** Produktregel: bewusst gesetzt, auch ohne Beleg, weil Originaltreue oder Recht es verlangen.
- **G** Gelernte Entscheidung: durch eigene chopstr-Daten gestützt. Davon gibt es heute keine einzige.

## 1. Kurzfazit

1. Die größte Schwäche liegt nicht in fehlendem Wissen, sondern darin, dass die gebauten deutschen Schutzregeln
   im Datenfluss nicht wirken: Pausen erzeugen Satzgrenzen mitten im Satz, das Verbklammer-Gate kann per
   Konstruktion nie anschlagen, Gate-Verletzer bleiben in der Kandidatenliste, Füllwort- und Pausenschnitte
   werden nie angewendet, die Heatmap beeinflusst das Ergebnis nicht.
2. Die Kandidatensuche ist einstufig: Kapitel von 240 s werden dem Sprachmodell ohne Episodenkontext,
   Seeds oder Payoff-Suche vorgelegt. Es gibt keine Rückwärtssuche vom Payoff zum Einstieg.
3. Der gesprochene Hook ist vom Clip entkoppelt. Gewählt wird die erste Textvariante ohne Claim-Treffer;
   der Claim-Check vergleicht Teilstrings („40“ gilt durch „400.000“ als gedeckt).
4. Ohne Sprachmodell (lokaler Heuristik-Provider) sind alle Rubrikwerte, das Eigenständigkeits-Gate und die
   Hook-Qualität nicht aussagekräftig. Das muss sichtbar sein, nicht als Zahl mit Scheingenauigkeit.
5. Das Projektwissen enthält keine einzige unabhängig verifizierte Aussage. Die Wissensbasis hat 55 Items,
   keines „verified“; Whitepaper und Masterfile zitieren Hofstede, Loewenstein und Caples „aus dem
   Gedächtnis“. Alle Pacing-, Längen- und Retention-Zahlen sind Priors oder Anbieterangaben.
6. Die externe Literatur stützt wenige, aber wichtige Dinge: Neugier braucht Orientierung (umgekehrt
   U-förmig), offene Schleifen motivieren zur Wiederaufnahme (Ovsiankina), aber nicht zum besseren Erinnern
   (Zeigarnik widerlegt), Selbstbezug wirkt, Negativität steigert Klicks, nicht belegt die Zufriedenheit,
   Frage-Hooks sind umstritten, Negativ-Framing und Verlustaversion sind als Auswahlregel nicht tragfähig.
7. Für den DACH-Raum gibt es keine veröffentlichten Messdaten zu Clip-Aufbau, Schnittdichte oder Hooks.
   Belegt sind nur Redaktionsaussagen (Tagesschau: 15 s optimal, Loop-Ende, Thumbstopper), Plattformregeln
   (Instagram-Originalität, YouTube-Inauthentic-Content, Shorts-Zählung seit 31.03.2025) und
   Untertitelnormen (Netflix Deutsch: 42 Zeichen, 17 Zeichen pro Sekunde, keine Trennung im Bindestrichwort).
8. Wettbewerber arbeiten nicht nur mit Lautstärke. OpusClip bewertet multimodal ab Pro, nutzt Prompts und
   trainiert auf Nutzerfeedback. Ihre dokumentierten Schwächen sind genau unsere Chance: Schnitt mitten im
   Satz, verpasste Pointe, Clips ohne Kontext, Virality-Score ohne Begründung, Füllwortentfernung nur
   Englisch, kein EU-Hosting, Mehrsprecher 48 bis 76 Prozent Genauigkeit.
9. Kein Wettbewerber liefert eine Begründung je Clip mit Satzbezug („warum diese Grenzen, was fehlt davor
   und danach“) und keiner prüft „keine Verfälschung durch Weglassen“ als Produktfunktion. Das ist die
   weiße Fläche, die chopstr besetzen kann.
10. Das Erfolgskriterium ist deshalb nicht „hektischere Clips“, sondern messbar bessere redaktionelle
    Entscheidungen auf identischem Material: richtiger Gedanke, früher verständlicher Einstieg, Ballast
    entfernt, Bedeutung geschützt, überzeugendes Ende.

## 2. Bestandsaufnahme des Codes: wo die Kernfunktion heute versagt

Der Audit hat den Worker-Code gelesen und einzelne Defekte im venv nachgeprüft. Pfade beziehen sich auf
`workers/chopstr_worker` (W) und `apps/web/lib` (A). Drei Problemarten nach Master-Prompt Abschnitt 3.

| Nr. | Befund | Problemart | Fundstelle | Schwere |
|---|---|---|---|---|
| 1 | Pausen ab 0,7 s oder Sprecherwechsel beenden einen Satz auch ohne Satzzeichen; die Spannungspause vor der Zahl wird zur Satzgrenze. Abkürzungsliste enthält „so“, „do“, „i“, „mag“, „max“, „art“, „min“: „Das ist so.“ ist kein Satzende. Gate `sentence_boundaries` steht fest auf bestanden. | Ausführung | W/pipeline/dach_nlp.py:58-66, 125-146; W/pipeline/story_engine.py:241; A/candidates/gates.ts:59 | kritisch |
| 2 | Verbklammer-Gate prüft Satzanfang und Satzende gegen Sperrbereiche innerhalb desselben Satzes und ist damit immer legal. Ohne spaCy-Modell (nicht installiert) meldet es „nicht verfügbar“ und gilt als bestanden. | Ausführung | W/pipeline/dach_nlp.py:154-189; W/pipeline/story_engine.py:183-196; workers/Dockerfile:20 | kritisch |
| 3 | Heatmap-Seeds ordnen nur die Kapitelreihenfolge, jedes Kapitel wird trotzdem bewertet, Seeds fehlen im Prompt, Cache-Key ohne Heatmap. Lachen und Applaus werden nie befüllt. | Auswahl | W/pipeline/story_engine.py:156-165, 514; W/pipeline/story_score.py:85-91; W/activities/analyze.py:53, 86-97 | kritisch |
| 4 | Verwerfen findet nicht statt: bis zu 20 Kandidaten inklusive Gate-Verletzern, keine Mindestpunktzahl, Duplikate nur über IoU 0,6 (ein 20-s-Clip in einem 60-s-Clip hat IoU 0,33 und bleibt). | Auswahl | W/pipeline/story_engine.py:36-40, 451-472 | kritisch |
| 5 | Kandidat ist immer genau ein Segment. `auto_remove_ranges`, `from_keep_ranges`, Teaser-Validator und Splice-Zähler sind gebaut, aber nie aufgerufen; `filler_cuts` ist immer False. Keine Pausenklassen. | Redaktion | W/pipeline/compose.py:17-99; W/pipeline/render_plan.py:141; W/activities/render.py:248 | hoch |
| 6 | Kontexttreue hängt allein am Sprachmodell: Reparatur nur ein Satz pro Runde, höchstens zwei Runden, nur auf LLM-Flags; kein deterministischer Detektor für Pronomen ohne Bezug; Story-Graph nur vorwärts, 60 s, Teilstring-Treffer („außer“ trifft „außerdem“); kein Reward-Ende (Nachlauf nach der Pointe bleibt). | Redaktion | W/pipeline/story_score.py:128-144; W/pipeline/story_graph.py:20-26, 57-82 | hoch |
| 7 | Hook gehört nicht zum Clip: `spoken_hook` wird nie verwendet, erste Variante ohne Claim-Issue gewinnt (faktisch immer `identity_call`), Thompson-Reihenfolge im Worker nicht angeschlossen, Wortlimit- und Lint-Verstöße disqualifizieren nicht. Claim-Check per Teilstring. Heuristik-Hooks stellen eigene Rahmungen voran („Das Gegenteil stimmt:“), die der Clip nicht deckt. | Redaktion | W/pipeline/copy_engine.py:114-158; W/pipeline/fidelity.py:61-71; W/heuristic_llm.py:278-304; W/activities/render.py:468, 525 | hoch |
| 8 | Schnittkanten exakt auf ASR-Wortgrenzen, 20-ms-Fade, kein Vor- und Nachlauf; Anlaute und Endkonsonanten gehen verloren, bei „nicht“ am Satzende sinnrelevant. | Ausführung | W/pipeline/story_engine.py:430; W/pipeline/render.py:215-226 | hoch |
| 9 | Captions: ein ASS-Event je Wort ohne Überbrückung der Wortlücken (Flackern), pyphen-Silbentrennung statt Morpheme („Kundenan-/fragenbea-/rbeitung“), Bruch nach jedem Komma, keine Mindestanzeigedauer, Zahl und Einheit trennbar, Keyword-Highlight nur in der Web-Vorschau. | Ausführung | W/pipeline/captions_de.py:167-243, 319-325; A/clips/captions.ts:101-106 | hoch |
| 10 | Reframing: OpenCV und YuNet nicht installiert, Standard ist Mittelcrop; Positions-Clusterung macht aus einem bewegten Gesicht drei Positionen und wählt `two_speakers`; Sprecherzuordnung wird geraten und gespeichert. | Ausführung | W/pipeline/reframe.py:56-65, 221-254; workers/Dockerfile:20-23 | kritisch (außerhalb des Master-Prompt-Scopes, siehe Abschnitt 8) |
| 11 | Heuristik-Provider: `is_humor` immer False (Pflicht zur menschlichen Humorprüfung entfällt still), `suggested_title_card` immer leer, Story-Graph-Urteile immer null, Spezifitäts-Regex trifft jedes deutsche Substantiv, Zielgruppe wird ignoriert. | Auswahl | W/heuristic_llm.py:104-221 | hoch |
| 12 | Lernschleife: Retention-Kurve wird gespeichert, nie auf die Wortzeitachse gelegt; Web-Revision übernimmt veraltete Gates (standalone, fidelity) nach Grenzänderung. | Redaktion | W/activities/publish.py:271; A/candidates/gates.ts:52-65 | mittel |

Wo der Code mehr leistet als verlangt (behalten): getrennte Normalform für Dialekt mit geschützten Begriffen,
vollständiger Teaser-Validator, ehrliche Unsicherheit (`confirmed = null`, `heuristic_only`, `scores_stale`),
deterministischer Render-Plan mit Hash, zweistufiges Loudnorm nach dem neueren Standard, Residency-Guard auch
für LanguageTool, serverseitiger Claim-Check bei manuell bearbeiteten Hooks.

Wurzelursache: Syntax, Kontext und Pacing sind als nachträgliche Prüfungen gebaut, nicht als Bedingungen der
Erzeugung. Grenzen werden nicht verschoben, Segmente nicht gesplittet, Gates nicht als Ausschluss genutzt.
Optionale Pakete fallen still auf „bestanden“ zurück.

## 3. Was die Forschung trägt und was nicht

Nur wenige Befunde stammen aus Short-Form-Video. Das meiste ist aus Headline-Experimenten, TV-Forschung,
Verhandlungsstudien und Gedächtnislabor übertragen. Jede Übertragung ist eine Hypothese.

| Mechanismus | Status | Beleg | Konsequenz für chopstr |
|---|---|---|---|
| Informationslücke, umgekehrt U-förmig | F (Headlines) | Golman und Loewenstein 2018; Registered Report 2025, 8.977 Upworthy-Experimente: Konkretheit hilft bei vagen Überschriften, schadet bei sehr konkreten | Einstieg nennt Akteur, Thema oder Konflikt, hält die Auflösung zurück. Keine Regel „mehr zurückhalten ist besser“. Zielband für Konkretheit, kein Maximum. |
| Zeigarnik (besseres Erinnern Unerledigter) | F widerlegt | Meta-Analyse Ghibellini und Meier 2025: kein Gedächtnisvorteil | Offene Schleife nicht als Erinnerungstrick begründen. |
| Ovsiankina (Drang zur Wiederaufnahme) | F (mittel) | dieselbe Meta-Analyse: allgemeine Tendenz | Geöffnete Schleife im Clip schließen, sonst Frust. Produktregel R: jede Forward-Referenz im Hook braucht eine Auflösung im Clip. |
| Orientierungsreaktion durch Schnitte | F (TV) | Lang 2006, LC4MP: Schnitte lösen Orientierung aus; folgt unzusammenhängende Information, wird sie schlecht encodiert | Schnitte inhaltlich begründen. Reizdichte nicht als Ziel. „Pattern Interrupt“ ist Praktikerjargon. |
| Negativität in Headlines | F (Klick), umstritten (Engagement) | Robertson et al. 2023: rund 105.000 Varianten, +2,3 Prozent Klickrate je negativem Wort; Preprint 2025: negative Posts weniger Engagement | Nicht automatisch die aggressivste Variante wählen (R). Negativ steigert Auswahl, nicht Zufriedenheit. |
| Verlustaversion im Content | umstritten | Gal und Rucker 2018: 93 Studien, kein Vorteil von Verlustframes; Gegenposition JDM 2022 | Die Whitepaper-Regel „Verluste wiegen doppelt“ ist als Auswahlregel nicht tragfähig. |
| Angst- und Warnappelle | F (mittel) | Tannenbaum et al. 2015: 127 Artikel, d = 0,29, wirksam mit konkreter Handlungsoption | Fehler-Hook nur, wenn die Vermeidung im Clip folgt (R). |
| Hohe Erregung und Weitergabe | F mit Replikationsvorbehalt | Berger und Milkman 2012; Prowten et al. 2024: zwei Replikationen der Arousal-Manipulation ohne Effekt | Emotionale Intensität des Inhalts bewerten, Lautheit nicht in den Score (R). |
| Processing Fluency | F (Urteilsebene) | Oppenheimer 2006; Alter und Oppenheimer 2009 | Einfache Wörter, Kernaussage im Hauptsatz vorn. Keine feste Wortzahl (Kuiken 2017: Headline-Länge ohne Klickeffekt). |
| Selbstbezug | F (stark, Gedächtnis) | Symons und Johnson 1997: 129 Studien; Lai und Farbrot 2014: +175 Prozent Klicks | Direkte Ansprache einer erkennbaren Situation im ersten Satz. Ein eingefügtes „Du“ allein reicht nicht (H). |
| Frage-Hook | umstritten | Lai und Farbrot 2014 pro; Fang und Wheeler 2026: 22.743 A/B-Tests, Fragen senken Engagement | Aussage als Standard, Frage als Testvariante (H). |
| Zahlenpräzision | F (Verhandlungen) | Jerez-Fernandez et al.; Loschelder et al. 2016: bei Experten kippt Präzision ohne Begründung ins Negative | Präzise Zahl nur mit Herleitung, besonders für Fachpublikum (H). |
| Peak-End | F (retrospektive Bewertung) | Alaybek et al. 2022: 174 Effektgrößen, r = 0,58 | Höhepunkt spät, Ende auf Pointe oder Fazit, nicht ausfaden (H für Clips). |
| Von Restorff, Serial Position | F (Labor), Übertrag unbelegt | keine Clip-Studie | Nicht als belegt behandeln. |
| Gesicht im Bild | F (korrelativ, Fotos) | Bakhshi et al. 2014: 1 Mio. Instagram-Fotos, +38 Prozent Likes | Gesicht in den ersten Sekunden ist ein Reframing-Thema, nicht Teil dieses Auftrags. |
| Untertitel, Ton aus | widersprüchlich | Verizon/Publicis 2019: 69 Prozent ohne Ton in der Öffentlichkeit (Selbstauskunft); TikTok: 93 Prozent mit Ton | Hook muss mit und ohne Ton funktionieren. Keine DACH-Daten. |
| Dekor und Seductive Details | F (Lernforschung) | Rey 2012 Meta-Analyse: dekorative Zusätze schaden dem Lernen | Zoom-Overload und Emoji-Captions abwerten, Captions bei Ton aus sind kein Dekor. |
| Clickbait-Backlash | widersprüchlich, plattformseitig dokumentiert | Scacco und Muddiman 2020 (Null-Effekte); Meta demotet Engagement-Bait seit 2017 | Hook und Inhalt müssen übereinstimmen (R). |
| Werbekennzeichnung | F (stark) | Eisend et al. 2020 Meta-Analyse | Kennzeichnung nicht tarnen; Medienanstalten 2024: 55 Prozent lehnen Influencer-Werbung ab. |
| Textbasierter Hook-Score als Prognose | F negativ | Douyin-Studie 2026 (24 Hook-Merkmale): keine Generalisierung auf Engagement; Rhapsody COLM 2025: GPT-4o und Gemini scheitern zero-shot bei „Most Replayed“, feinjustiert mit Sprachsignalen deutlich besser | Qualitätsscore nie als Viralitätswahrscheinlichkeit ausgeben (R). Ohne eigene Ergebnisdaten bleibt jede Prognose unkalibriert. |

Was die Literatur direkt für die Clipping-Technik hergibt: Spotify (arXiv 2505.23908) erzeugt Vorschauen
per Sprachmodell auf satzsegmentiertem Zeitstempel-Transkript mit der harten Anforderung „mit vollständigen
Gedanken starten und enden“; Human Eval 81 Prozent Präferenz oder Gleichstand, A/B-Test +4,6 Prozent
Engagement. Das ist der einzige publizierte Nachweis, dass eine Satzgrenzen-Pflicht im Prompt messbar wirkt.

## 4. Plattformsignale 2026, getrennt nach offiziell und behauptet

| Plattform | Offiziell dokumentiert | Nur behauptet oder Anbieterstudie | Regel für chopstr |
|---|---|---|---|
| YouTube Shorts | Seit 31.03.2025 zählt jeder Start als View, „engaged views“ bestimmt Monetarisierung. Seit 15.07.2025 strengere Policy gegen „inauthentic content“ (massenproduziert, repetitiv); Clip-Formate laut Klarstellung nicht pauschal gemeint. Signale: Entscheidung anzusehen, durchschnittliche Wiedergabedauer, angesehener Anteil, Zufriedenheit. | „Viewed vs. Swiped Away“ als Hook-Kennzahl (Sekundärquellen) | Nicht nur auf Abschlussrate optimieren. Rohaufrufe über den 31.03.2025 hinweg nicht vergleichen. Kein erkennbar identisches Template über viele Clips. |
| Instagram Reels | Originalitätsregel seit 30.04.2026: Aggregatoren und überwiegend unoriginale Konten verlieren Empfehlungen; Rahmen, Wasserzeichen, Captions oder Quellenangabe allein gelten nicht als Eigenleistung. Mosseri (Januar 2025, via Sekundärquellen): Watch Time, Likes per Reach, Sends per Reach. | „Sends zählen 3 bis 5x“ (keine offizielle Zahl); „Completion schlägt Länge“ widerspricht Mosseris Aussage, es zähle absolute Sehzeit (t3n 26.02.2025) | Länge als Folge der Inhaltsdichte, nicht als Zielwert. Eigene Inhalte mit redaktionellem Mehrwert sind unkritisch. `reels_skip_rate` ist auf die ersten drei Sekunden bezogen und geschätzt. |
| TikTok | Faktoren: Nutzerinteraktionen, Videoinformationen, Geräteeinstellungen; starke Signale (vollständiges Ansehen eines längeren Videos) wiegen mehr. Diversität und Originalität werden bevorzugt. AIGC-Regler seit 11/2025. Creator Rewards: mindestens 1 Minute, Deutschland unterstützt. | Buffer 2025: über 60 s +43 Prozent Reichweite; Socialinsider 2026: 15 bis 30 s höchste Engagement-Rate; Metricool 2026: 2 Minuten beste Kombination. Die Studien messen Verschiedenes und haben Selektionsverzerrung. | Keine „genau X Sekunden“-Logik. Die Mindestlänge für Monetarisierung erzeugt Anreizverzerrung in allen Längenstudien. |
| LinkedIn | Feed seit 12.03.2026 mit LLM-Retrieval und Transformer-Ranking; passive Signale (Klick, Skip, Long-Dwell) und aktive (Like, Kommentar, Share); Video im Engineering-Post nicht behandelt. | Video schwächer als Carousel (Metricool 2026, Anbieter); „Frage-Opener minus 34 Prozent“, „External Link minus 60 Prozent“ (Blogs) | Dwell und substanzielle Kommentare als Ziel; Zahlen aus Blogs nicht als Regel. |
| Meta allgemein | Demotion von Engagement-Bait seit 12/2017 | | Keine Aufforderungen mit Gegenleistung im CTA (R). |

## 5. DACH-spezifisch: was belegt ist

Belegt (F oder redaktionelle Primärquelle):

- Tagesschau auf TikTok: maximal 60 s, optimal etwa 15 s, Thumbstopper als Frage oder hohe Energie,
  frontale Moderation, Loop-Übergang zum Anfang statt Outro (dfjv, Redaktionsaussage, nicht gemessen).
- Hoss und Hopf: 860 Mio. TikTok-Views auf rund 60.000 Videos, Großteil über Dritt-Accounts; Kehrseite
  Kontextverlust, Account-Sperre im Februar 2024 wegen Falschinformation (OMR, MOM). Dezentrales Clipping
  ohne Kontextschutz ist ein Reputationsrisiko, kein Vorbild.
- Doppelgänger macht bewusst keine Shorts und ist hochprofitabel: Clipping ist Wachstumshebel, kein Muss.
- Netflix German Timed Text Style Guide: 42 Zeichen pro Zeile, 2 Zeilen, bis 17 Zeichen pro Sekunde, kein
  Umbruch in Bindestrichwörtern außer an natürlichen Fugen, zusammenhängende grammatische Einheit pro Zeile,
  unten breitere Pyramide. Das ist die einzige belastbare Norm für deutsche Untertitel.
- Du/Sie: Appinio 2019 (N = 4.533): 82 Prozent bevorzugen Du auf Instagram, auf LinkedIn und Xing
  überwiegt Sie, bei 16 bis 24 Jahren 41 Prozent Du auf LinkedIn. Daten sieben Jahre alt, nur Markenansprache.
- Dialekt: ARD-Forschungsdienst 10/2024: Dialekt steigert Sympathie bei regionalen Produkten, sonst neutral;
  Standardsprache wirkt auf Markeneinstellung besser als Jugendsprache. Schweizerdeutsch-ASR: bestes
  publiziertes Whisper-Modell 25,6 Prozent WER (arXiv 2606.07608).
- Werbeskepsis: Medienanstalten 2024 (N = 3.050): 55 Prozent lehnen Influencer-Werbung ab, Kennzeichnungen
  werden oft übersehen. EY 2024: nur 25 Prozent in Deutschland vertrauen Social-Media-Empfehlungen.
- Anglizismen: Endmark/YouGov: 64 Prozent verstehen englische Claims nicht korrekt, bewerten sie aber
  positiv. Für Hooks ein Fluency-Risiko, kein belegter Reichweitenkiller.
- Nutzung: ARD/ZDF-Medienstudie 2025 (n = 2.512): Instagram 40 Prozent, TikTok 20 Prozent wöchentlich in der
  Gesamtbevölkerung; bei 14 bis 29 Jahren Instagram 77, TikTok 50 Prozent.

Nicht belegt (H), obwohl im Whitepaper als Regel formuliert:

- „DACH funktioniert rational, Verlust-Hooks schlagen Gewinn-Hooks“ (Hofstede-Werte aus dem Gedächtnis;
  Verlustaversion als Content-Regel umstritten).
- „US-Hype performt in DACH schlechter“: plausibel, keine Datenlage gefunden.
- Alle Pacing-Takte (1,5 s Entertainment bis 15 s B2B), alle Längenfenster je Plattform, alle
  Retention-Benchmarks (Hold 60 Prozent, Completion 40 oder 70 Prozent, Folgequote 5 je 1.000).
- Schnittdichte, Zoomrhythmus, Hook-Archetypen der DACH-Top-Creator: für keinen Kanal öffentlich vermessen.
- Satzklammer, Verbendstellung und Cut-Punkte im deutschen Satz: keine Anleitung oder Beobachtung
  auffindbar. Das ist eine echte Forschungslücke und zugleich der Differenzierungspunkt, den nur ein
  deutschsprachiges Tool besetzen kann.

## 6. Wettbewerber: Stand und weiße Flecken

Fast alle Tools folgen derselben Pipeline (Whisper-Familie, LLM- oder Modell-Scoring, Schnitt, Reframing,
Captions). OpusClip ist am transparentesten: ClipAnything bewertet multimodal (Bild, Audio-Ereignisse,
Sentiment), nimmt Prompts, Virality Score 0 bis 99 aus Hook, Flow, Value, Trend; Basistarife nutzen nur
gesprochene Worte; Modell laut Blog mit Feedback von 6 Mio. Nutzern feinjustiert. Vizard v2 bewirbt
„kohärentere, in sich geschlossene, weniger Clips“ zum 1,25-fachen Preis. Klap schickt Transkripte an
OpenRouter und OpenAI. Reap bietet MCP mit zehn Tools auf allen Plänen.

Dokumentierte Schwächen der Wettbewerber (Reviews, Konkurrenz-Benchmarks, Help-Center):

- Schnitt mitten im Satz, verpasste Pointe, falsch gedeutetes Thema: ScaleReach fand bei 76 OpusClip-Clips
  62 Prozent direkt veröffentlichbar, 13 Prozent unbrauchbar. Vizards v2-Werbung impliziert dieselbe Schwäche.
- Virality Score ohne Begründung, schlecht kalibriert (niedrig bewertete Clips liefen besser).
- Füllwort-Erkennung bei OpusClip nur Englisch (Help-Center, Stand Januar 2025). Schwäbisch wird zu
  Schriftdeutsch überkorrigiert; englische statt deutscher Untertitel als Standardfall berichtet.
- Mehrsprecher: Auto-Tracking „am besten bei einem Hauptsprecher“; Vendor-Benchmark 48 bis 76 Prozent.
- Humor: „kein Tool über 35 Prozent“ (Montage, ohne Methodik).
- Datenstandort: OpusClip US (Google Cloud, SCC, Training mit Individualdaten, Widerspruch per E-Mail),
  Klap US laut eigener Policy, BlitzReels EU/US mit US-Rendering. Kein DACH-Anbieter mit EU-Hosting gefunden.
- Credits je Quellminute unabhängig vom Verwurf: bei 20 bis 40 Prozent Verwurf steigt der Preis je
  nutzbarem Clip.

Weiße Flecken, die niemand besetzt: Begründung je Clip mit Satzbezug; Sinntreue-Prüfung als Produktfunktion;
Deutsch als Qualitätsfeld (Füllwörter, Satzklammer, Dialekt-Normalform, Hochdeutsch für Schweizerdeutsch);
dokumentiertes EU-Hosting; Lernen aus den Freigaben des einzelnen Kunden; Folien als Struktursignal;
reproduzierbare Benchmarks für Deutsch.

Technisch belegte Hebel gegen reines Transkript-Scoring: überwachte Zielgröße statt zero-shot (Rhapsody),
Satzgrenzen-Pflicht im Prompt (Spotify), Themenwechsel-Erkennung plus LLM mit überlappendem Chunking und
Satzgrenzenlogik (ClipsAI-JP), Sprachsignale zusätzlich zum Text.

## 7. Widersprüche im eigenen Projektwissen und Gegenpositionen

Das Projektwissen widerspricht sich an 19 Stellen (vollständige Liste im Extrakt). Die für den Kern
relevanten, mit Entscheidung:

| Thema | Widerspruch | Entscheidung für den Kern |
|---|---|---|
| Impulsabstand | 1,5 s (Kleinecke) vs. 10 bis 15 s (PLACEMedia) vs. Micro-Event-Budget (Masterfile) vs. 4,2 s Zoom (DSCVRY) vs. 8 bis 10 s (DD2) | Kein Takt. Schneiden nach Funktion. „Zeit bis zur verständlichen Relevanz“ intern messen (R, Master-Prompt 15). |
| Pausen | 300 bis 400 ms schneiden (Whitepaper) vs. keine pauschale Grenze, Median 288 ms Wortlücke (DSCVRY, n = 62) | Pausenklassen statt Schwelle; nur technische Leerstelle automatisch kürzen; Pause vor Zahl, Negation, Kontrast, Pointe bleibt (R). |
| Füllwörter | „ähm/also“ raus vs. „halt/eigentlich“ als Modalpartikel behalten vs. „eigentlich“ streichen | Nur Klasse „hart“ (ähm, äh, Wiederholung) als Vorschlag; Modalpartikel nie automatisch; „eigentlich“ ist Kontrastsignal (R). |
| Listicle-Reihenfolge | stärkster Punkt zuletzt vs. zweitbester zuerst vs. nie der schwächste zuletzt | Keine Umordnung im Kern; Originalchronologie (R, Master-Prompt 16). |
| „Niemand redet darüber“ | positives Insider-Signal (Whitepaper) vs. Anti-Hyperbel (Masterfile 3.3) | Anti-Hyperbel. Leere Intensivierung ersetzt keine Substanz (R). |
| Clickbait | Packaging-SOP „etwas irreführend ist ok“ vs. Sinntreue, UWG | Sinntreue. Der Text-Hook darf verdichten, nicht mehr behaupten als der Clip trägt (R). |
| Frage-Hooks | Taxonomie nutzt Fragen vs. „minus 34 Prozent auf LinkedIn“ | Aussage als Standard, Frage als Variante (H, zu testen). |
| Completion | 40 Prozent (SOP) vs. 70 Prozent (DD2, DPS) | Kein Zielwert im Kern; nur gegen den eigenen Account messen (G später). |
| Dialekt-Ausgabe | perfektes Hochdeutsch (DPS) vs. regionale Wörter erhalten (DDE) | Original bleibt, Normalform getrennt, Hochdeutsch nur als Caption-Option je Account (R, bereits so gebaut). |
| Erstes Frame | „Mid-Action“ (DD2) vs. „kein Einstieg mitten in der Bewegung“ (SOP) | Keine Gestaltungsregel im Kern; Einstieg nach Verständlichkeit wählen. |

Gegenpositionen zum Whitepaper, als Diskussionsbeitrag:

1. **Die Hook-Gleichung ist richtig im Geist, falsch als Formel.** „P(Relevanz) × Lückengröße × P(Einlösung)
   × Glaubwürdigkeit“ ist Eigenkonstruktion. Die Literatur stützt den Kern (Lücke mittlerer Größe, Einlösung
   im Clip, Selbstbezug), aber nicht die Multiplikation und keine Gewichte. Deshalb harte Prüfungen vor
   jedem Ranking, kein Produkt aus Teilwerten (Master-Prompt 19).
2. **„DACH ist rational“ ist eine Nationalcharakter-Behauptung.** Hofstede-Aggregate aus alten Erhebungen
   sagen nichts über Verhalten im Feed. Belastbar ist nur die hohe Werbeskepsis. Daraus folgt Belegpflicht
   und Kennzeichnung, nicht „keine Emotion“. Die Tagesschau gewinnt mit Energie, Hoss und Hopf mit Konflikt.
3. **Verlust-Hooks sind kein DACH-Vorteil.** Verlustaversion als Content-Regel ist umstritten, Warnappelle
   wirken nur mit Handlungsoption. Der „teure Fehler“ ist ein guter Hook, weil er Konsequenz und Mechanismus
   verspricht, nicht weil Deutsche Angst hätten.
4. **Die 1,5-Sekunden-Regel widerspricht der eigenen Zielgruppe.** Das Masterfile nennt selbst ein
   Research-Sample deutscher Finance- und Business-Outlier, das „moderat statt fast“ war. Lang 2006 zeigt,
   dass hohe Reizdichte die Encodierung verschlechtert. Semantische Geschwindigkeit ist der richtige Begriff,
   der Takt ist der falsche.
5. **Der Virality Score ist kein Ziel, auch nicht unser eigener.** Alle Hook-Scores in der Literatur
   generalisieren nicht auf Engagement. Wir berichten Qualität und Sicherheit der Quellenprüfung, keine
   Prognose, bis Ergebnisdaten vorliegen.
6. **Kleinecke-SOPs sind YouTube-Longform-Packaging.** Clickbait-Mitte, Thumbnail-Switching und
   „Sei nicht zu ehrlich“ sind weder für Clips validiert noch mit Sinntreue vereinbar. Übernommen wird nur,
   was den Originaltreue-Vorrang nicht verletzt.
7. **Die Konkurrenz ist nicht primitiv.** OpusClip bewertet multimodal und lernt aus Nutzerfeedback. Unser
   Vorteil muss im Nachweis liegen: identisches Material, Blindvergleich, Verwerfungsquote und manuelle
   Nacharbeit berichten (Master-Prompt 26).

## 8. Prioritäten für den Kern

Die Reihenfolge folgt der Priorität des Master-Prompts: Originaltreue, eigenständige Verständlichkeit,
erfülltes Versprechen, Zielgruppenrelevanz, redaktionelle Wirkung, technische Effizienz.

| Prio | Maßnahme | Wirkung | Aufwand | Phase |
|---|---|---|---|---|
| 1 | Satzsegmentierung reparieren: primär Satzzeichen, Pause allein nur mit großgeschriebenem Folgewort und ohne offenes finites Verb; Abkürzungsliste bereinigen; `sentence_boundaries` als echte Prüfung. | behebt Clips, die vor dem Kernwort enden | mittel | 1 |
| 2 | Verbklammer über Grenzen prüfen (Vorsatz und Folgesatz zusammen); fehlendes Modell laut melden statt still bestehen; deterministischer Rückfall ohne spaCy (Satzklammer-Heuristik auf trennbaren Verben und Nebensatzkonnektoren). | Sinnumkehr durch Out-Point verhindert | mittel | 1 |
| 3 | Deterministische Gates vor dem Ranking: Pronomen ohne Antezedens im ersten Satz, Rückverweise („wie gesagt“, „das von vorhin“), offene Frage ohne Antwort, Negation oder Bedingung am Grenzsatz, indirekte Rede, Forward-Referenz ohne Auflösung. Gate-Verletzer werden verworfen, nicht sortiert. | Eigenständigkeit und Versprechen | mittel | 1 und 2 |
| 4 | Versionierter Testsatz mit den 14 Pflichtfällen des Master-Prompts als Fixtures, Tests rot vor der Reparatur. | Nachweis statt Behauptung | niedrig | 1 |
| 5 | Payoff-first-Suche: Payoff-Kandidaten (Erklärung, Ergebnis, Vorgehen, Pointe, Auflösung) finden, rückwärts erforderlichen Kontext und Einstieg bestimmen; Gegenrichtung (Einstieg-first) und Abgleich beider; Kapitel mit Überlappung, Seeds im Prompt, Episodenübersicht. | richtiger Gedanke häufiger gefunden | hoch | 2 |
| 6 | Native Hook-Auswahl: der gesprochene Einstieg ist eine Originalstelle; mehrere substanziell verschiedene Einstiege intern vergleichen; Text-Hook darf nicht mehr behaupten als der Clip (Claim-Check auf normalisierte Zahlentoken, Geltungsbereich „bei uns“ vs. „für alle“); Hyperbel-Liste; Lint-Verstöße disqualifizieren. | Versprechen passt zum Inhalt | mittel | 2 |
| 7 | Remove-/Keep-Logik aktivieren: Komposition aus mehreren Segmenten, Schutzbereiche (Negation, Bedingung, Maßstab, Zeit, Unsicherheit, Definition, Sprecher, Korrektur), Pausenklassen, Reward-Ende (Nachlauf nach Payoff kappen), Splice-Limit, Debatten nie umordnen. | Ballast raus, Bedeutung bleibt | hoch | 2 |
| 8 | Redundanz über Containment statt IoU; Mindestanforderungen statt Mindestpunktzahl; höchstens zehn Kandidaten; Verwerfen als Ergebnis mit Grund. | weniger Doppelungen, ehrliche Listen | niedrig | 2 |
| 9 | Rollen trennen: Analyst (Materialübersicht, Abhängigkeiten, spätere Korrekturen), Editor (Auswahl), Kritiker (gezielte Widerlegung), Evaluator (Anforderungen); Heuristik-Provider als „unkalibriert“ sichtbar; Humor-Flag nicht still False. | Gegenprüfung | mittel | 2 |
| 10 | ClipCandidate-Schema als Adapter über dem bestehenden Kandidatenformat (Herkunftsbereiche, removed_spans, meaning_dependencies, quality_gate_results, editorial_subscores, uncertainties, Versionen). | Auditierbarkeit | mittel | 2 |
| 11 | Echte Zeitstempel: Vor- und Nachlauf an Wortgrenzen, boundary_confidence, konservativer Schnitt bei Unsicherheit, Original- und Clip-Timeline getrennt, Übergangsprüfung (abgeschnittenes Phonem, Atem, Caption-Übertragung). | keine abgeschnittenen Wörter | mittel | 3 |
| 12 | Captions als Folge des Schnitts: Wort-Events bis zum nächsten Wort verlängern, Mindestdauer, Zahl plus Einheit als Token, Morphemgrenzen statt Silben, Bindestrichwörter nicht trennen (Netflix-Norm). Kein Stilwechsel. | Lesbarkeit ohne Flackern | niedrig | 3 |
| 13 | Blindvergleich alt gegen neu auf denselben Quellen mit festem Raster; Verwerfungsquote und Nacharbeit berichten; Rollback-Schalter (Policy-Version). | Fortschritt bewiesen | mittel | 4 |
| 14 | Retention-Kurve auf die Wortzeitachse legen und Ereignisse an Abfallstellen protokollieren; nur mit sauber definierten Metriken (Plattform, Nenner, API-Version, Abrufzeit). | Lernen aus Daten | hoch | 4, nur bei Datenqualität |

Außerhalb des Master-Prompt-Scopes, aber dringend und separat freizugeben: Reframing-Abhängigkeiten (OpenCV,
YuNet) im Build, Positions-Clusterung mit Mindestabstand, Sprecherzuordnung vor dem Render bestätigen,
Szenenwechsel in der Quelle erkennen. Das ändert Gestaltung und UI-Ablauf und gehört in einen eigenen Auftrag.

## 9. Was wir nicht wissen und wie wir es herausfinden

1. Keine veröffentlichten Outlier-Analysen für deutschsprachige Kanäle. Vorschlag: eigene Stichprobe von
   15 bis 20 Kanälen, Top-10 gegen 10 Median-Clips je Kanal (Länge, Hook-Typ, Captions, Schnitte je 10 s,
   Ende). Erst daraus entstehen DACH-Startwerte.
2. Kein Nachweis, dass irgendein Hook-Score Hold-Rate oder Folgequote vorhersagt. Bis eigene Ergebnisdaten
   vorliegen, berichten wir Qualität, nicht Wirkung.
3. Satzklammer und Cut-Punkte im Deutschen sind unerforscht. Unser Testsatz ist der erste Schritt zu einem
   eigenen, offenen Benchmark für deutsche Clip-Grenzen.
4. Du/Sie-, Dialekt- und Anglizismen-Wirkung in Video: nur alte oder markenbezogene Daten. Als
   Account-Parameter führen, nicht als Regel.
5. Längen- und Pacing-Studien messen Verschiedenes und sind durch Monetarisierungsanreize verzerrt. Länge
   bleibt eine Folge des Inhalts.
6. Plattform-Interna (Mosseri-Gewichte, TikTok-Signalreihenfolge, LinkedIn-Video-Ranking): nur Sekundär-
   quellen. Keine Rankinggewichte erfinden.

## 10. Quellen (Auswahl, geprüft am 03.10.2026)

Forschung: Golman und Loewenstein 2018 (Information Gaps); Sci Rep 2024 Registered Report Upworthy;
Ghibellini und Meier 2025, Humanit Soc Sci Commun (Zeigarnik, Ovsiankina); Lang 2006 (LC4MP); Robertson et
al. 2023, Nat Hum Behav; Gal und Rucker 2018, J Consumer Psychol; Tannenbaum et al. 2015 (APA); Berger und
Milkman 2012, JMR; Prowten et al. 2024, Psychol Sci; Oppenheimer 2006; Alter und Oppenheimer 2009; Symons und
Johnson 1997; Lai und Farbrot 2014; Fang und Wheeler 2026, JCP; Loschelder et al. 2016; Alaybek et al. 2022,
OBHDP; Bakhshi et al. 2014; Rey 2012; Scacco und Muddiman 2020; Eisend et al. 2020; Kuiken et al. 2017;
arXiv 2505.23908 (Spotify Previews); arXiv 2505.19429 (Rhapsody); arXiv 2606.07608 (Schweizerdeutsch ASR).

Plattformen: PPC Land zur Shorts-Zählung (31.03.2025); Social Media Today zur YouTube-Policy (15.07.2025);
Instagram Creators Blog (30.04.2026) und MediaPost (01.05.2026) zur Originalität; t3n (26.02.2025) zu
Mosseri; TikTok Newsroom und Transparency Center; Meta Newsroom (12/2017) zu Engagement-Bait; PPC Land zum
LinkedIn-Feed (12.03.2026); Netflix German Timed Text Style Guide.

DACH: dfjv zur Tagesschau; OMR zu Hoss und Hopf und Céline Flores Willers; Founder Mode (Doppelgänger);
ARD/ZDF-Medienstudie 2025; Medienanstalten 2024; Appinio 2019; ARD-Forschungsdienst, Media Perspektiven
10/2024; Endmark/YouGov via Horizont.

Wettbewerb: opus.pro (clipanything, pricing, privacy, help center virality-score, filler-word-recognition,
subject-tracking, claude-connector), docs.vizard.ai, klap.app/privacy-policy, reap.video/mcp, submagic.co,
descript.com/api, status.opus.pro, trustpilot.com (OpusClip, Vizard, Klap, Descript), scalereach.ai,
montage.app Benchmark 2026, reap.video Report 2026, blitzreels.com/privacy.

Projektintern: Whitepaper 21.09.2026, Masterfile 21.09.2026, DSCVRY-Clipping-Skill, Masterclass Psychologie
Content Clips (24.09.2026), Copywriting-Master-Brief, Wissensbasis ai-clipping-knowledge.sqlite3 (55 Items,
7 offene Konflikte CON-001 bis CON-007).
