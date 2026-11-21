-- Doppelte verfolgte Links verhindern (Review R1-01).
--
-- Der Linktest prüfte Dubletten nur lesend vor dem Einfügen. Gleichzeitige Anfragen legten so denselben
-- Beitrag mehrmals an (doppelte Zahlen in /clips/{id}/performance, doppelte Messungen). Ab hier sichert
-- ein eindeutiger Teilindex das in der Datenbank ab; die Web-App fügt mit `on conflict do nothing` ein
-- und meldet 409 mit der vorhandenen Publikation.
--
-- Bestehende Zeilen werden nicht gelöscht oder umgeschrieben. Gibt es schon Dubletten, bricht die
-- Migration mit einer Meldung ab, statt Daten zu verändern; dann zuerst je Beitrag alle Zeilen bis auf
-- eine auf tracking = 'off' stellen. Auf der Hauptdatenbank gibt es vor dieser Migration keine Zeilen
-- mit tracking = 'link' (0019 ist dort neu), also nichts zu bereinigen.
--
-- Sperren: publications ist klein. Der Index braucht kurz SHARE (Schreiben wartet), der CHECK wird
-- `not valid` angelegt und danach validiert (SHARE UPDATE EXCLUSIVE, Lesen und Schreiben laufen weiter).
-- `create index concurrently` geht nicht, weil scripts/migrate.mjs jede Datei in einer Transaktion ausführt.

do $$
declare
  n integer;
begin
  select count(*) into n from (
    select 1 from publications
    where tracking = 'link' and external_id is not null
    group by workspace_id, platform, external_id having count(*) > 1
  ) d;
  if n > 0 then
    raise exception '0021: % Beiträge sind mehrfach mit tracking = link eingetragen. Bitte je Beitrag alle Zeilen bis auf eine auf tracking = off stellen und die Migration erneut starten.', n;
  end if;
end $$;

-- Verfolgte Links tragen immer einen Workspace (die Web-App setzt ihn beim Einfügen). Ohne diesen CHECK
-- würde eine Zeile mit workspace_id NULL am eindeutigen Index vorbeikommen.
alter table publications drop constraint if exists publications_link_workspace_check;
alter table publications add constraint publications_link_workspace_check
  check (tracking <> 'link' or workspace_id is not null) not valid;
alter table publications validate constraint publications_link_workspace_check;

create unique index if not exists publications_link_unique_idx
  on publications (workspace_id, platform, external_id)
  where tracking = 'link' and external_id is not null;

comment on index publications_link_unique_idx is
  'Ein Beitrag (Plattform und ID) wird je Workspace nur einmal als Link verfolgt. tracking = off zählt nicht.';
