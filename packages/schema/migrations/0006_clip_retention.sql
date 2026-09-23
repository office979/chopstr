-- chopstr · Migration 0006 · Eigene Löschfrist für Renderings
--
-- Der AVV (docs/rechtliches/avv-2026-09.md) sagt zwei verschiedene Fristen zu: Rohmaterial
-- `workspaces.retention_days` (Standard 30), Renderings `workspaces.render_retention_days`
-- (Standard 90). Im Code gab es bisher nur die erste. Clips hingen am `on delete cascade` ihrer
-- Quelle und wurden mit ihr nach 30 Tagen entfernt — der zugesagte 90-Tage-Zeitraum war also nie
-- eingehalten. `render_retention_days` war eine Zahl, die in den Einstellungen verstellbar war, im
-- Vertrag erschien und nirgends wirkte.
--
-- Clips bekommen deshalb eine eigene Frist. Der Lösch-Workflow räumt sie unabhängig von der Quelle
-- ab (workers/chopstr_worker/activities/deletion.py).

alter table clips add column if not exists delete_after timestamptz;

-- Der Retention-Scan sucht fällige Clips; gelöschte interessieren ihn nicht mehr.
create index if not exists clips_delete_after_idx on clips (delete_after) where deleted_at is null;

-- Die Frist gehört an den Datensatz, nicht an den Aufrufer: Clips entstehen an zwei Stellen in der
-- Web-App (lib/repo/postgres.ts createClips, lib/repo/publishing.ts), und eine vergessene Stelle
-- wäre wieder ein stiller Vertragsbruch. `security definer`, weil der Nachschlag über `sources` und
-- `workspaces` geht und auf beiden Zeilensicherheit aktiv ist.
create or replace function clips_set_delete_after() returns trigger
language plpgsql security definer set search_path = pg_catalog, public as $$
begin
  if new.delete_after is null then
    select now() + make_interval(days => w.render_retention_days)
      into new.delete_after
      from sources s
      join workspaces w on w.id = s.workspace_id
     where s.id = new.source_id;
  end if;
  return new;
end $$;

drop trigger if exists clips_delete_after_trg on clips;
create trigger clips_delete_after_trg before insert on clips
  for each row execute function clips_set_delete_after();

-- Bestandsclips bekommen die Frist ab ihrer Erstellung, nicht ab jetzt: Ein drei Monate alter Clip
-- soll nicht durch die Migration 90 frische Tage geschenkt bekommen.
update clips c
   set delete_after = c.created_at + make_interval(days => w.render_retention_days)
  from sources s
  join workspaces w on w.id = s.workspace_id
 where c.source_id = s.id
   and c.delete_after is null
   and c.deleted_at is null;

insert into schema_migrations(version) values ('0006_clip_retention') on conflict do nothing;
