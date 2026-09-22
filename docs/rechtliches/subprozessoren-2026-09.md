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
