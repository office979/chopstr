# @chopstr/schema

Postgres-Schema für chopstr. Standard-Tarif: Supabase (eu-central-1, Frankfurt). Sovereign-Tarif: Postgres
bei Hetzner. Row Level Security auf allen Fachtabellen; Isolation über `app_workspace_id()`
(`set local app.workspace_id = '<uuid>'` pro Transaktion; in Supabase später über das JWT).

## Anwenden

```bash
DATABASE_URL=postgres://chopstr:chopstr@localhost:5432/chopstr npm run migrate
```

Das Skript `scripts/migrate.mjs` wendet alle noch nicht angewendeten Dateien aus `migrations/` in
Reihenfolge an und protokolliert sie in `schema_migrations`.

## Rollen

| Rolle | RLS | Verwendung |
|---|---|---|
| `chopstr_app` | unterliegt RLS | Web-App (Next.js Route-Handler, Server Actions) |
| `chopstr_worker` | `BYPASSRLS` | Temporal-Worker (schreiben Transkripte, Events, Kosten) |

## Grundsätze

- Videos nie in Postgres, nur Objektspeicher-Keys (`storage_key`, `audio_key`, `proxy_key`, `file_key`).
- Versionierung: `transcript_versions`, `hook_versions`, `caption_versions` (wer, wann, welches Modell,
  automatisch oder manuell). `candidates` tragen `model_id` und `prompt_version`.
- Workspace-Felder: `tier` (standard/sovereign), `data_region`, `retention_days`,
  `allow_us_subprocessors` (Default false), `training_opt_in` (Default false).
- Kostenlog `job_costs` pro Job: Quellminuten, GPU-/CPU-Sekunden, LLM-Tokens, Speicher, geschätzte €.
- Audit-Log: Uploads, Rechte-Bestätigungen, Korrekturen, Freigaben, Kennzeichnungen, Exporte, Löschungen.
- Löschkonzept: `sources.delete_after` + Objektspeicher-Lifecycle + `audit_log`-Eintrag `source.deleted`.

## Änderungen

Neue Migration = neue Datei `NNNN_beschreibung.sql`. Bestehende Migrationen werden nicht geändert.
