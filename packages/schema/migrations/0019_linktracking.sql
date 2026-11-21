-- Link-Tracking und Messreihen (Linktest-API, Lieferung B).
--
-- Bisher gab es Messwerte nur in festen Fenstern (performance_feedback: 6h, 48h, 7d) und nur für
-- Publikationen, die chopstr selbst über eine OAuth-Verbindung gepostet hat. Wer einen Clip von Hand
-- postet und nur den Link einträgt, bekam nie automatische Zahlen.
--
-- Hier kommt zweierlei dazu:
--   1. metric_snapshots: eine Zeitreihe je Publikation. Jeder Abruf ist eine Zeile, auch ein
--      fehlgeschlagener (dann mit error). Die festen Fenster bleiben; der Worker schreibt sie weiter,
--      sobald eine Messung das Alter 6h, 48h oder 7d zum ersten Mal überschreitet.
--   2. publications.tracking: woher die Zahlen kommen. 'oauth' ist das bisherige Verhalten,
--      'link' heisst: nur der öffentliche Link ist bekannt, gelesen wird über öffentliche Schnittstellen
--      (YouTube Data API, X API) oder über eine verbundene Plattform, falls der Beitrag ihr gehört.
--      'off' schaltet das Messen ab.
--
-- next_snapshot_at ist der Zeitplan: NULL heisst „nichts mehr zu tun". Bestehende Publikationen
-- bekommen NULL und werden also nicht plötzlich abgefragt.

create table if not exists metric_snapshots (
  id               uuid primary key default gen_random_uuid(),
  workspace_id     uuid not null references workspaces(id) on delete cascade,
  publication_id   uuid not null references publications(id) on delete cascade,
  fetched_at       timestamptz not null default now(),
  age_s            integer,                 -- Sekunden seit published_at
  source           text not null check (source in ('oauth', 'public_api', 'scraper', 'manual')),
  views            bigint,
  engaged_views    bigint,
  likes            bigint,
  comments         bigint,
  shares           bigint,
  saves            bigint,
  follows          bigint,
  reach            bigint,
  avg_watch_time_s real,
  skip_rate        real,
  retention_curve  jsonb,
  raw              jsonb,
  error            text
);

create index if not exists metric_snapshots_pub_idx on metric_snapshots (publication_id, fetched_at);
create index if not exists metric_snapshots_ws_idx on metric_snapshots (workspace_id, fetched_at desc);

alter table publications
  add column if not exists tracking         text not null default 'oauth' check (tracking in ('oauth', 'link', 'off')),
  add column if not exists tracking_until   timestamptz,
  add column if not exists next_snapshot_at timestamptz,
  add column if not exists link_check       jsonb;

-- Fällige Messungen für den Worker (local_worker.process_metrics)
create index if not exists publications_next_snapshot_idx on publications (next_snapshot_at)
  where next_snapshot_at is not null and tracking <> 'off';
-- Doppelte Links erkennen: derselbe Beitrag soll nicht zweimal gezählt werden
create index if not exists publications_external_idx on publications (platform, external_id)
  where external_id is not null;

-- X als Messquelle (nur Messwerte, kein Posten). Die Spalte hatte einen CHECK aus 0005.
alter table platform_connections drop constraint if exists platform_connections_platform_check;
alter table platform_connections add constraint platform_connections_platform_check
  check (platform in ('tiktok', 'instagram', 'youtube', 'linkedin', 'manual', 'x'));

comment on table metric_snapshots is
  'Zeitreihe der Messwerte je Publikation. Eine Zeile je Abruf, Fehler stehen in error.';
comment on column metric_snapshots.source is
  'oauth = verbundenes Konto, public_api = öffentliche Plattform-API, scraper = Drittanbieter (nicht im Sovereign-Tarif), manual = von Hand.';
comment on column publications.tracking is
  'Woher die Messwerte kommen: oauth (bisher), link (nur öffentlicher Link) oder off.';
comment on column publications.next_snapshot_at is
  'Nächste fällige Messung. NULL = keine weitere Messung geplant.';
comment on column publications.link_check is
  'Ergebnis des Linktests beim Eintragen (Prüfungen und Hinweise).';

alter table metric_snapshots enable row level security;

create policy ws_metric_snapshots on metric_snapshots
  using (workspace_id = app_workspace_id()) with check (workspace_id = app_workspace_id());
