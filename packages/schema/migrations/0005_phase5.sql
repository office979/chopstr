-- chopstr · Migration 0005 · Phase 5: API-Schlüssel, Webhooks, Outbox, Publishing-Verbindungen,
-- Decision Log, Performance-Feedback, Hook-Muster-Statistik, Experimente, Serien, Wochenreports.
-- Vertrag: packages/schema/PHASE5.md

-- ------------------------------------------------------------------------------------------------
-- API und Webhooks
-- ------------------------------------------------------------------------------------------------
create table api_keys (
  id           uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  name         text not null,
  key_prefix   text not null,                 -- erste 8 Zeichen nach chp_live_
  key_hash     text not null unique,          -- sha256 des vollständigen Schlüssels
  scopes       text[] not null default '{read}',
  created_by   uuid references users(id) on delete set null,
  last_used_at timestamptz,
  expires_at   timestamptz,
  revoked_at   timestamptz,
  created_at   timestamptz not null default now()
);
create index api_keys_workspace_idx on api_keys(workspace_id);

create table webhook_endpoints (
  id           uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  url          text not null,
  secret       text not null,
  events       text[] not null default '{}',
  active       boolean not null default true,
  created_by   uuid references users(id) on delete set null,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create trigger webhook_endpoints_updated before update on webhook_endpoints for each row execute function set_updated_at();

create table outbox_events (
  id           bigserial primary key,
  workspace_id uuid not null references workspaces(id) on delete cascade,
  event        text not null,
  entity       text,
  entity_id    uuid,
  payload      jsonb not null default '{}'::jsonb,
  created_at   timestamptz not null default now(),
  processed_at timestamptz
);
create index outbox_events_pending_idx on outbox_events(processed_at) where processed_at is null;

create table webhook_deliveries (
  id              uuid primary key default gen_random_uuid(),
  endpoint_id     uuid not null references webhook_endpoints(id) on delete cascade,
  outbox_id       bigint references outbox_events(id) on delete set null,
  event           text not null,
  payload         jsonb not null,
  attempt         int not null default 0,
  status          text not null default 'pending' check (status in ('pending', 'delivered', 'failed')),
  response_code   int,
  error           text,
  next_attempt_at timestamptz not null default now(),
  delivered_at    timestamptz,
  created_at      timestamptz not null default now()
);
create index webhook_deliveries_pending_idx on webhook_deliveries(next_attempt_at) where status = 'pending';

-- ------------------------------------------------------------------------------------------------
-- Publishing
-- ------------------------------------------------------------------------------------------------
create table platform_connections (
  id                  uuid primary key default gen_random_uuid(),
  workspace_id        uuid not null references workspaces(id) on delete cascade,
  brand_profile_id    uuid references brand_profiles(id) on delete set null,
  platform            text not null check (platform in ('tiktok', 'instagram', 'youtube', 'linkedin', 'manual')),
  account_label       text not null,
  external_account_id text,
  credentials         text,                   -- AES-256-GCM, base64; nie im Klartext
  capabilities        jsonb not null default '{}'::jsonb,
  status              text not null default 'connected' check (status in ('connected', 'expired', 'revoked')),
  connected_by        uuid references users(id) on delete set null,
  expires_at          timestamptz,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
create index platform_connections_ws_idx on platform_connections(workspace_id);
create trigger platform_connections_updated before update on platform_connections for each row execute function set_updated_at();

alter table publications
  add column if not exists workspace_id       uuid references workspaces(id) on delete cascade,
  add column if not exists connection_id      uuid references platform_connections(id) on delete set null,
  add column if not exists status             text not null default 'manual'
    check (status in ('scheduled', 'publishing', 'published', 'failed', 'manual')),
  add column if not exists scheduled_for      timestamptz,
  add column if not exists caption            text,
  add column if not exists title              text,
  add column if not exists external_url       text,
  add column if not exists error              text,
  add column if not exists metrics_fetched_at timestamptz,
  add column if not exists temporal_workflow_id text,
  add column if not exists created_by         uuid,
  add column if not exists created_at         timestamptz not null default now();
create index if not exists publications_clip_idx on publications(clip_id);
create index if not exists publications_ws_idx on publications(workspace_id);

-- ------------------------------------------------------------------------------------------------
-- Decision Log, Performance, Lernschleife
-- ------------------------------------------------------------------------------------------------
create table decision_log (
  id               uuid primary key default gen_random_uuid(),
  workspace_id     uuid not null references workspaces(id) on delete cascade,
  brand_profile_id uuid references brand_profiles(id) on delete set null,
  source_id        uuid references sources(id) on delete set null,
  candidate_id     uuid references candidates(id) on delete set null,
  clip_id          uuid references clips(id) on delete set null,
  decision_type    text not null check (decision_type in (
                     'candidate_proposed', 'candidate_scored', 'candidate_verdict', 'hook_selected',
                     'hook_variant_shown', 'caption_preset', 'reframe_strategy', 'publish')),
  features         jsonb not null default '{}'::jsonb,
  alternatives     jsonb not null default '[]'::jsonb,
  chosen           jsonb not null default '{}'::jsonb,
  actor_type       text not null default 'ai' check (actor_type in ('ai', 'user', 'system')),
  actor_id         uuid,
  model_id         text,
  prompt_version   text,
  created_at       timestamptz not null default now()
);
create index decision_log_ws_idx on decision_log(workspace_id, created_at desc);
create index decision_log_clip_idx on decision_log(clip_id);

create table performance_feedback (
  id                   uuid primary key default gen_random_uuid(),
  workspace_id         uuid not null references workspaces(id) on delete cascade,
  clip_id              uuid references clips(id) on delete set null,
  publication_id       uuid references publications(id) on delete cascade,
  platform             text not null,
  metric_window        text not null check (metric_window in ('6h', '48h', '7d', 'manual')),
  views                bigint,
  likes                bigint,
  comments             bigint,
  shares               bigint,
  saves                bigint,
  follows              bigint,
  avg_watch_time_s     real,
  retention_curve      jsonb,
  follows_per_1k       real,
  saves_per_1k         real,
  account_median_views real,
  outlier_score        real,
  reward               real,
  fetched_at           timestamptz not null default now(),
  unique (publication_id, metric_window)
);
create index performance_feedback_ws_idx on performance_feedback(workspace_id);

create table hook_pattern_stats (
  brand_profile_id uuid not null references brand_profiles(id) on delete cascade,
  pattern          text not null,
  shown            int not null default 0,
  chosen           int not null default 0,
  reward_sum       real not null default 0,
  reward_n         int not null default 0,
  updated_at       timestamptz not null default now(),
  primary key (brand_profile_id, pattern)
);

create table experiments (
  id             uuid primary key default gen_random_uuid(),
  workspace_id   uuid not null references workspaces(id) on delete cascade,
  candidate_id   uuid references candidates(id) on delete set null,
  hypothesis     text,
  status         text not null default 'draft' check (status in ('draft', 'running', 'decided')),
  winner_clip_id uuid references clips(id) on delete set null,
  min_exposure   int not null default 1000,
  confidence     real,
  decided_at     timestamptz,
  created_by     uuid,
  created_at     timestamptz not null default now()
);

create table series (
  id               uuid primary key default gen_random_uuid(),
  workspace_id     uuid not null references workspaces(id) on delete cascade,
  brand_profile_id uuid references brand_profiles(id) on delete set null,
  name             text not null,
  description      text,
  cadence          text not null default 'weekly' check (cadence in ('weekly', 'biweekly', 'monthly', 'none')),
  rules            jsonb not null default '{}'::jsonb,
  active           boolean not null default true,
  created_by       uuid,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
create trigger series_updated before update on series for each row execute function set_updated_at();

alter table clips
  add column if not exists experiment_id    uuid references experiments(id) on delete set null,
  add column if not exists variant          text check (variant in ('A', 'B')),
  add column if not exists series_id        uuid references series(id) on delete set null,
  add column if not exists series_index     int,
  add column if not exists reframe_override text check (reframe_override in ('talking_head', 'two_speakers', 'neutral', 'slide_pip'));

create table weekly_reports (
  id           uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  week_start   date not null,
  report       jsonb not null,
  sent_at      timestamptz,
  created_at   timestamptz not null default now(),
  unique (workspace_id, week_start)
);

-- Opt-out Wochenreport, Publishing-Freischaltung im Plan
alter table workspaces add column if not exists weekly_report_enabled boolean not null default true;
update plans set features = features || '{"publishing": true, "api": true}'::jsonb where code in ('pro', 'agency', 'sovereign');
update plans set features = features || '{"publishing": false, "api": true}'::jsonb where code = 'starter';

-- ------------------------------------------------------------------------------------------------
-- RLS
-- ------------------------------------------------------------------------------------------------
alter table api_keys             enable row level security;
alter table webhook_endpoints    enable row level security;
alter table outbox_events        enable row level security;
alter table webhook_deliveries   enable row level security;
alter table platform_connections enable row level security;
alter table decision_log         enable row level security;
alter table performance_feedback enable row level security;
alter table hook_pattern_stats   enable row level security;
alter table experiments          enable row level security;
alter table series               enable row level security;
alter table weekly_reports       enable row level security;

create policy ws_api_keys on api_keys using (workspace_id = app_workspace_id()) with check (workspace_id = app_workspace_id());
create policy ws_webhooks on webhook_endpoints using (workspace_id = app_workspace_id()) with check (workspace_id = app_workspace_id());
create policy ws_outbox on outbox_events using (workspace_id = app_workspace_id()) with check (workspace_id = app_workspace_id());
create policy ws_deliveries on webhook_deliveries
  using (exists (select 1 from webhook_endpoints e where e.id = webhook_deliveries.endpoint_id and e.workspace_id = app_workspace_id()));
create policy ws_connections on platform_connections using (workspace_id = app_workspace_id()) with check (workspace_id = app_workspace_id());
create policy ws_decision_log on decision_log using (workspace_id = app_workspace_id()) with check (workspace_id = app_workspace_id());
create policy ws_performance on performance_feedback using (workspace_id = app_workspace_id()) with check (workspace_id = app_workspace_id());
create policy ws_hook_stats on hook_pattern_stats
  using (exists (select 1 from brand_profiles b where b.id = hook_pattern_stats.brand_profile_id and b.workspace_id = app_workspace_id()));
create policy ws_experiments on experiments using (workspace_id = app_workspace_id()) with check (workspace_id = app_workspace_id());
create policy ws_series on series using (workspace_id = app_workspace_id()) with check (workspace_id = app_workspace_id());
create policy ws_weekly_reports on weekly_reports using (workspace_id = app_workspace_id());

insert into schema_migrations(version) values ('0005_phase5') on conflict do nothing;
