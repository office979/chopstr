# Entscheidungsregister

Verbindliche Architektur- und Produktentscheidungen mit Begründung. Neue Einträge unten anhängen,
bestehende nicht umschreiben (Historie). Quelle: Master-Build-Prompt (21.09.2026), Master Whitepaper
v2.0, Knowledge Base `decisions_log` und `research_conflicts`.

| Nr. | Entscheidung | Begründung | Revisit-Trigger |
|---|---|---|---|
| E1 | Ein Code, zwei Tarife: Standard (Claude über AWS Bedrock EU-Inference-Profil, Supabase eu-central-1) und Sovereign (nur EU-Anbieter: Hetzner, Mistral EU oder self-hosted, Gladia/OVH). | Bedrock verarbeitet im EU-Profil in EU-Regionen, US-Anbieter tragen ein CLOUD-Act-Restrisiko. Sovereign ist das Verkaufsargument für Kanzleien, Kliniken, öffentliche Hand. | Erster Sovereign-Kunde |
| E2 | Temporal statt Celery/RQ ab Phase 0. | Lange GPU-Schritte, Worker-Abstürze, tagelanges Warten auf Freigabe. Self-hosted, weil die Historie Transkripte enthält. | nie |
| E3 | Keine dritte Backend-Sprache: Next.js/TypeScript als Produktschicht, Python nur in Workern. Öffentliche API später als Next.js-Route-Handler. Abweichung vom Master Whitepaper (FastAPI): bewusst, weniger Betriebsaufwand für ein kleines Team. | Kleines Team. | Wenn API-Last eine eigene Schicht verlangt |
| E4 | Hybride Clip-Erkennung in vier Stufen: Heatmap → LLM-Vorschlag → Rubrik mit Reparatur → Story-Graph. | Günstiger und besser als ein LLM, das blind 90 Minuten liest. | Blindtest Woche 8 |
| E5 | Story-Graph prüft jede Clip-Aussage auf spätere Relativierungen. | Kern des Vertrauensversprechens. | nie |
| E6 | Clips sind Kompositionen (Segmentlisten mit Abspielreihenfolge). Teaser max. 6 s, ein Sprecher, markiert, Satz kommt im Clip erneut vor. Max. 2 Splices, Debatten nie umordnen. | Füller-Schnitte und Cold Open, aber nur mit Trust-Regeln. | nie |
| E7 | Eigenes deutsches NLP-Paket `dach_nlp`. | Verbklammer, Modalpartikeln, Negationen, Open-Loop-Enden hat kein US-Tool. | nie |
| E8 | Lizenz-Hygiene: keine Ultralytics/YOLO (AGPL) im SaaS. YuNet/MediaPipe (Apache) oder LR-ASD (MIT). | Rechtssicherheit des Produkts. | nie |
| E9 | Abrechnung nach Stunden Quellmaterial, keine Credits. | Größter Kritikpunkt an OpusClip. | Pilotverbrauch und Zahlungsbereitschaft (Knowledge Base CON-003) |
| E10 | LLM provider-agnostisch, Wahl per Testdatensatz. | Messung statt Meinung. | jede Modelländerung |
| A1 | Audio-Default -16 LUFS / -1,5 dBTP; -14 / -1 als Legacy-Preset. | Master-Edition 8.1. | Plattform-Spezifikation ändert sich |
| A2 | Pacing nicht als globaler Jump-Cut-Takt, sondern als Micro-Event-Budget je Persona und Plattform. | Master-Edition 8.1, Konflikt 1,5 s vs. 10 bis 15 s. | Performance-Daten je Account |
| A3 | Lernen: Regeln + Präferenzdaten → Contextual Bandits. Kein RL im MVP. Kein Lernen ohne Decision Log. | Master-Edition 8.1. | Genug attribuierte eigene Outputs |
| D1 | Design-System „Lichtbruch“. Brand-Blau `#020CF5` aus dem Logo für Marke, Klinge und Lichtkanten; `#2F6BFF` für KI-Zustände im UI, weil `#020CF5` auf Schwarz keinen AA-Kontrast für Text erreicht. | Logo-Farben verbindlich, WCAG AA verbindlich. | Rebranding |
| D2 | Logo als umgerissene Pfade (SF Pro Display Bold über HarfBuzz), Originale unverändert in `docs/brand/`. | `<text>`-Elemente rendern ohne installierte Schrift falsch. | Neuer Designer-Export |
| P1 | Gemäß Knowledge Base: Export vor Autopublishing, Agenturen zuerst, Nordstern-Metrik = menschliche Reviewminuten pro freigegebenem Clip. | `decisions_log`. | Pilotdaten |
| P2 | Dialektausgabe: Original und normalisierte Ausgabe getrennt speichern, Nutzer entscheidet (CON-001). Regionale Wörter nie ins Standarddeutsch umschreiben. | Konflikt in den Quellen. | Dialekt-Evaluation |
| P3 | Füllwörter: äh/ähm hart raus, quasi/sozusagen als Vorschlag mit Undo, Modalpartikeln (halt, eigentlich, mal, ja, doch, eben, schon, wohl) bleiben (CON-005). | Modalpartikeln tragen Ton und Bedeutung. | Nutzerfeedback |

## Bewusst nicht in v1

Generative Avatare und B-Roll, KI-Stimmen als Standard, Emotionserkennung (hart deaktiviert),
automatisches Posten ohne Freigabe, Humor-Versprechen, Schweizerdeutsch als „voll unterstützt“,
Credit-Pricing, zehn Plattform-Integrationen gleichzeitig, eigenes Foundation-Model, Training mit Kundenvideos.

## Zu verifizieren, bevor es in Code oder Marketing geht

- Angeblicher float16-Bug in faster-whisper; Modell „tnfru/whisper-large-v3-german-ct2“; Sortformer-DER auf Deutsch.
- EU-AI-Act-Fristen (Art. 50) und Watermarking-Pflichten: Marketingmails sind kein Rechtsgutachten.
- Plattform-API-Felder und Limits (TikTok, Meta, LinkedIn) gegen die aktuelle Originaldokumentation.
- Zitierte Gerichtsaktenzeichen aus früheren Entwürfen.
