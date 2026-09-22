# Risiken und Rückfragen (Stand 22.09.2026, nach Phase 0 + 1)

## Was vom Gerüst übernommen, geändert oder verworfen wurde

| Modul | Entscheidung | Begründung |
|---|---|---|
| `tasks.py` (RQ) | verworfen | E2: Temporal ab Phase 0. Kein zweites Job-System pflegen. |
| `temporal_workflow.py` | übernommen und ausgebaut | Aktivitäten für Phase 0/1 sind real implementiert, Freigabe-Signal bleibt. |
| `providers_llm.py` | übernommen, Residency-Guard verschärft | Jeder ausgehende HTTP-Aufruf läuft durch eine Host-Allowlist, nicht nur die Provider-Wahl. |
| `story_score.py` | umgebaut | Kein Bedrock-Client auf Modulebene, Prompts kommen versioniert aus `packages/prompts`. |
| `transcribe.py` | erweitert | Fenster mit Überlappung und Merge, Sprecher per Mehrheit über die Wortdauer, Zahlen erst nach dem Alignment. |
| `dach_nlp.py` | erweitert | Abkürzungen und Ordinalzahlen als Satzgrenzen-Ausnahmen; spaCy optional, damit Tests ohne Modell laufen. |
| `render.py` | geändert | Loudness-Default -16 LUFS / -1,5 dBTP (Master-Edition), -14 / -1 als Legacy-Preset. |
| `db/schema.sql` | ersetzt durch Migration 0001 | Versionierung, Workspace-Felder, Kostenlog, Pipeline-Events, RLS auf allen Tabellen. |
| übrige Pipeline-Module | übernommen, Imports lazy | Phase 2/3, hängen noch nicht in der Workflow-Kette. |

## Risiken mit Gegenmaßnahme

| Risiko | Wirkung | Gegenmaßnahme |
|---|---|---|
| ASR-Qualität bei Dialekt und schlechtem Audio | Caption-Fehler, Vertrauensverlust | Evaluations-Skript pro Dialekt, Marken-Wörterbuch, Konfidenz-Markierung im Editor, Schweizerdeutsch nur als Beta. |
| Modell-IDs und Lizenzen (primeline-Fine-Tune, pyannote community-1, CH-Modell) | Laufzeitfehler oder Lizenzbruch | Keine IDs im Code, nur ENV. Vor Produktion Lizenz und Hugging-Face-Nutzungsbedingungen prüfen. |
| GPU-Kosten und Latenz auf EU-Cloud | Unit Economics kippen | Kostenlog pro Job ab Tag 1, int8-Modelle, Audio-only für ASR, Proxy statt Original. |
| Temporal-Historie enthält Transkripte | Datenschutz | Self-hosted in der EU, kurze Retention, keine Transkripte in Telemetrie. |
| tusd-Hooks ohne signierten Header | Fremde Hook-Aufrufe | Secret im Hook-URL, internes Docker-Netz, später mTLS oder Signatur. |
| Docker-Stack wurde auf der Entwicklungsmaschine nicht gestartet (kein Docker installiert) | Compose-Fehler erst beim ersten Start sichtbar | CI-Job für Migration gegen Postgres vorhanden; ersten `docker compose up` auf einer Maschine mit Docker einplanen. |
| LLM-Bewertung bevorzugt elegante Formulierungen, sieht keine Mimik | Falsche Kandidaten | Heatmap-Signale und deterministische Gates vor dem LLM, Blindtest in Woche 8, Kill-Kriterien aus der Research. |
| Rechtsaussagen (AI Act Art. 50, C2PA-Pflichten, Werbekennzeichnung) | Falsche Produktlogik | Als Defaults mit Audit-Log umgesetzt, vor Launch juristisch verifizieren. |
| Generischer Output | Plattform-Abwertung, Markenschaden | Brand-Profile, Stil-Linter, keine Templates als Default, Variations-Prüfung in Phase 3. |
| Aufwand Phase 2 (Story-Engine) unterschätzt | Zeitplan rutscht | Concierge-Pilot mit 10 Videos parallel starten, Precision@5 messen, bevor UI-Feinschliff beginnt. |

## Rückfragen vor Phase 2 (maximal fünf)

1. **GPU-Anbieter:** Hetzner (dedizierte GPU), Scaleway oder RunPod EU? Entscheidet über Worker-Image und Kosten pro Stunde.
2. **Tarif zuerst:** Standard (Bedrock EU + Supabase) oder gleich Sovereign (Hetzner + Mistral EU)? Beides ist vorbereitet, aber der erste Echtlauf braucht einen konkreten LLM-Endpunkt und eine Modell-ID.
3. **Testmaterial:** Liegen 20 DE-, 5 AT- und 2 CH-Videos mit Redakteurs-Auswahl (Gold-Clips) vor? Ohne Gold-Daten gibt es keine WER- und Precision-Messung.
4. **Accounts:** AWS (Bedrock EU-Profil), Supabase-Projekt in eu-central-1, Hugging-Face-Token mit akzeptierten pyannote-Bedingungen. Welche existieren?
5. **Hosting der Web-App:** Vercel (EU-Region) oder eigener Container bei Hetzner? Betrifft Auth-Wahl in Phase 4 und die Upload-Route (tusd muss öffentlich erreichbar sein).
