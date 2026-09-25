---
version: "2026-09"
status: Vorlage, vor Vertragsschluss aktualisieren
---

# Subprozessoren

## Tarif Standard

| Subprozessor | Zweck | Sitz | Verarbeitungsort |
|---|---|---|---|
| Supabase | Datenbank (Postgres), Auth-Daten | USA (Muttergesellschaft) | eu-central-1 (Frankfurt) |
| Amazon Web Services (Bedrock) | Sprachmodell für Vorschläge, Bewertung, Texte | USA | EU-Inference-Profil (EU-Regionen) |
| [EU-GPU-Anbieter, z. B. Hetzner oder Scaleway] | Transkription, Sprechererkennung, Rendering | DE / FR | Deutschland / Frankreich |
| [EU-Objektspeicher] | Speicherung von Rohmaterial und Renderings | EU | EU |
| [EU-SMTP-Anbieter] | Transaktions-E-Mails | EU | EU |
| Stripe | Zahlungsabwicklung (nur Rechnungsdaten, keine Videos) | USA / IE | EU-Entität Stripe Payments Europe |

## Website und Warteliste (chopstr.io)

Betrifft nicht das Produkt, sondern nur die öffentliche Warteseite.

| Subprozessor | Zweck | Sitz | Verarbeitungsort |
|---|---|---|---|
| GitHub | Auslieferung der statischen Seite (GitHub Pages), Server-Protokolle | USA | global (CDN) |
| Google Ireland Limited | Warteliste: E-Mail-Adressen in Google Sheets, Eintragung über Apps Script | IE | EU, Übermittlung an Google LLC (USA) nicht ausgeschlossen |

Rechtsgrundlage für die Eintragung ist die Einwilligung (Art. 6 Abs. 1 lit. a DSGVO), für die
Drittlandübermittlung der Angemessenheitsbeschluss zum EU-US Data Privacy Framework. Diese
Verarbeitung ist ausdrücklich vom EU-Versprechen des Produkts ausgenommen und wird auf
chopstr.io/datenschutz.html so benannt.

Hinweis: US-Konzernmütter unterliegen dem CLOUD Act. Dieses Restrisiko wird im Tarif Standard offengelegt.

## Tarif Sovereign

| Subprozessor | Zweck | Sitz | Verarbeitungsort |
|---|---|---|---|
| Hetzner | Datenbank, Objektspeicher, Worker | DE | Deutschland / Finnland |
| Mistral AI oder self-hosted Modell | Sprachmodell | FR | EU |
| Gladia (OVHcloud) | ASR-Fallback | FR | EU |
| [EU-SMTP-Anbieter] | Transaktions-E-Mails | EU | EU |
| Mollie | Zahlungsabwicklung | NL | EU |

Keine Subprozessoren mit Sitz oder Konzernmutter außerhalb der EU.
