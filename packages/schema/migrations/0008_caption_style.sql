-- chopstr · Migration 0008 · Untertitel-Stil je Clip und gespeicherte Vorlagen
--
-- Bisher hing der Untertitel-Stil am Markenprofil: eine Entscheidung fuer alle Clips. In der Praxis
-- gehoert die Wahl an den einzelnen Clip. Derselbe Kunde will im Interview ruhige Zweizeiler und im
-- Ausschnitt fuer TikTok ein Wort in grossen Versalien.
--
-- Zwei Ergaenzungen:
--
-- 1. clips.caption_style — was fuer DIESEN Clip gilt. Leeres Objekt heisst: nichts eingestellt, es
--    bleibt beim Markenprofil und dem, was das Format vorgibt. Bewusst jsonb und keine Spalten:
--    der Renderer verwirft, was er nicht kennt (captions_de.style_anwenden), und zieht Zahlen in
--    ihren erlaubten Bereich. Eine neue Einstellung braucht damit keine Migration.
--
-- 2. caption_presets — was sich jemand als Vorlage merkt. Gehoert dem Workspace und nicht der
--    Person: in einer Agentur stellt einer den Stil ein und alle arbeiten damit weiter.

alter table clips add column if not exists caption_style jsonb not null default '{}'::jsonb;

create table if not exists caption_presets (
  id           uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  name         text not null,
  style        jsonb not null default '{}'::jsonb,
  created_by   uuid,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  constraint caption_presets_name_len check (char_length(btrim(name)) between 1 and 60)
);

-- Ein Name je Workspace. Zweimal „Podcast fett" waere in der Auswahl nicht zu unterscheiden.
create unique index if not exists caption_presets_workspace_name
  on caption_presets (workspace_id, lower(btrim(name)));

-- "create trigger if not exists" gibt es nicht; ohne das Entfernen bricht ein zweiter Lauf ab.
drop trigger if exists caption_presets_updated on caption_presets;
create trigger caption_presets_updated before update on caption_presets
  for each row execute function set_updated_at();

alter table caption_presets enable row level security;

drop policy if exists ws_caption_presets on caption_presets;
create policy ws_caption_presets on caption_presets
  using (workspace_id = app_workspace_id()) with check (workspace_id = app_workspace_id());

insert into schema_migrations(version) values ('0008_caption_style') on conflict do nothing;
