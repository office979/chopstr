-- chopstr · Migration 0003 · Phase 4: Nutzer, Sitzungen, Einladungen, Rollen-Scope, Abrechnung nach Stunden,
-- AVV, Lösch-Workflow, CI-Assets, Markenprofil-Historie. Vertrag: packages/schema/PHASE4.md

-- ------------------------------------------------------------------------------------------------
-- Nutzer und Sitzungen (eigene Auth, tarifunabhängig: Supabase-Postgres oder Hetzner)
-- ------------------------------------------------------------------------------------------------
create table users (
  id             uuid primary key default gen_random_uuid(),
  email          text not null unique,
  email_verified_at timestamptz,
  password_hash  text,                        -- Argon2id; null = nur Einladung/Magic-Link
  display_name   text,
  locale         text not null default 'de-AT',
  last_login_at  timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
create trigger users_updated before update on users for each row execute function set_updated_at();

create table sessions (
  id           text primary key,              -- zufällig, 32 Bytes base64url; Cookie hält nur die ID
  user_id      uuid not null references users(id) on delete cascade,
  workspace_id uuid references workspaces(id) on delete set null, -- aktiver Workspace der Sitzung
  expires_at   timestamptz not null,
  ip           inet,
  user_agent   text,
  created_at   timestamptz not null default now()
);
create index sessions_user_idx on sessions(user_id);
create index sessions_expires_idx on sessions(expires_at);

create table login_tokens (                   -- Magic-Link und Passwort-Reset
  token      text primary key,
  user_id    uuid not null references users(id) on delete cascade,
  purpose    text not null check (purpose in ('magic_link', 'password_reset', 'verify_email')),
  expires_at timestamptz not null,
  used_at    timestamptz,
  created_at timestamptz not null default now()
);

-- Rollen-Scope: Mandanten (client) sehen nur ihre Marke
alter table workspace_members
  add column if not exists brand_profile_id uuid references brand_profiles(id) on delete set null,
  add column if not exists invited_by uuid,
  add column if not exists accepted_at timestamptz;
-- Bestehende Mitglieder (Phase 0 bis 3 hatten keine users-Tabelle) bekommen einen Nutzer-Datensatz,
-- sonst scheitert der Fremdschlüssel. Platzhalter-E-Mail, bis sich die Person anmeldet.
insert into users (id, email, display_name)
  select m.user_id, coalesce(m.email, m.user_id::text || '@unbekannt.local'), m.display_name
  from workspace_members m
  where not exists (select 1 from users u where u.id = m.user_id)
on conflict (email) do nothing;
alter table workspace_members
  drop constraint if exists workspace_members_user_id_fkey;
alter table workspace_members
  add constraint workspace_members_user_id_fkey foreign key (user_id) references users(id) on delete cascade;

create table workspace_invites (
  token            text primary key,
  workspace_id     uuid not null references workspaces(id) on delete cascade,
  email            text not null,
  role             text not null check (role in ('admin', 'editor', 'reviewer', 'client')),
  brand_profile_id uuid references brand_profiles(id) on delete set null,
  invited_by       uuid references users(id) on delete set null,
  expires_at       timestamptz not null,
  accepted_at      timestamptz,
  created_at       timestamptz not null default now()
);
create index workspace_invites_ws_idx on workspace_invites(workspace_id);

-- ------------------------------------------------------------------------------------------------
-- Abrechnung nach Stunden Quellmaterial (E9: keine Credits)
-- ------------------------------------------------------------------------------------------------
create table plans (
  code                 text primary key,     -- starter | pro | agency | sovereign
  name                 text not null,
  monthly_eur          numeric(10, 2) not null,
  included_hours       numeric(6, 2) not null,     -- Stunden Quellmaterial pro Monat
  overage_eur_per_hour numeric(10, 2) not null,
  max_brand_profiles   int,                        -- null = unbegrenzt
  max_members          int,
  features             jsonb not null default '{}'::jsonb,
  active               boolean not null default true
);
insert into plans(code, name, monthly_eur, included_hours, overage_eur_per_hour, max_brand_profiles, max_members, features) values
  ('starter',   'Starter',   29.00,  4,  9.00, 1,  2,  '{"guest_approval": false, "sovereign": false}'),
  ('pro',       'Pro',       79.00, 12,  7.50, 3,  5,  '{"guest_approval": true,  "sovereign": false}'),
  ('agency',    'Agentur',  199.00, 40,  6.00, null, null, '{"guest_approval": true, "sovereign": false, "white_label": true}'),
  ('sovereign', 'Sovereign', 399.00, 40, 6.00, null, null, '{"guest_approval": true, "sovereign": true, "white_label": true}')
on conflict (code) do nothing;

create table subscriptions (
  id                       uuid primary key default gen_random_uuid(),
  workspace_id             uuid not null references workspaces(id) on delete cascade,
  plan_code                text not null references plans(code),
  provider                 text not null default 'manual' check (provider in ('manual', 'stripe', 'mollie')),
  provider_customer_id     text,
  provider_subscription_id text,
  status                   text not null default 'trialing'
                           check (status in ('trialing', 'active', 'past_due', 'canceled', 'paused')),
  current_period_start     timestamptz,
  current_period_end       timestamptz,
  trial_ends_at            timestamptz,
  cancel_at_period_end     boolean not null default false,
  billing_email            text,
  billing_address          jsonb,               -- {company, street, zip, city, country, vat_id}
  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now()
);
create unique index subscriptions_workspace_idx on subscriptions(workspace_id);
create trigger subscriptions_updated before update on subscriptions for each row execute function set_updated_at();

create table usage_periods (
  id                   uuid primary key default gen_random_uuid(),
  workspace_id         uuid not null references workspaces(id) on delete cascade,
  period_start         date not null,
  period_end           date not null,
  included_minutes     numeric(10, 2) not null,
  used_source_minutes  numeric(10, 2) not null default 0,   -- aus job_costs (ingest) summiert
  render_count         int not null default 0,
  llm_input_tokens     bigint not null default 0,
  llm_output_tokens    bigint not null default 0,
  overage_minutes      numeric(10, 2) not null default 0,
  overage_eur          numeric(10, 2) not null default 0,
  closed_at            timestamptz,
  unique (workspace_id, period_start)
);

create table billing_events (                 -- Webhooks und manuelle Buchungen, idempotent über provider_event_id
  id                uuid primary key default gen_random_uuid(),
  workspace_id      uuid references workspaces(id) on delete set null,
  provider          text not null,
  provider_event_id text unique,
  type              text not null,
  payload           jsonb,
  received_at       timestamptz not null default now()
);

-- ------------------------------------------------------------------------------------------------
-- AVV / DPA und Löschworkflow (DSGVO)
-- ------------------------------------------------------------------------------------------------
create table dpa_acceptances (
  id             uuid primary key default gen_random_uuid(),
  workspace_id   uuid not null references workspaces(id) on delete cascade,
  dpa_version    text not null,               -- z. B. 2026-09
  accepted_by    uuid references users(id) on delete set null,
  accepted_at    timestamptz not null default now(),
  ip             inet,
  company        text,
  representative text
);
create index dpa_acceptances_ws_idx on dpa_acceptances(workspace_id);

create table deletion_jobs (
  id            uuid primary key default gen_random_uuid(),
  workspace_id  uuid not null references workspaces(id) on delete cascade,
  entity        text not null check (entity in ('source', 'clip', 'brand_profile', 'workspace')),
  entity_id     uuid not null,
  reason        text not null check (reason in ('user_request', 'retention', 'workspace_deleted', 'gdpr_request')),
  requested_by  uuid,
  status        text not null default 'queued' check (status in ('queued', 'running', 'done', 'failed')),
  keys_deleted  jsonb not null default '[]'::jsonb,   -- Löschnachweis: Objektspeicher-Keys
  rows_deleted  jsonb not null default '{}'::jsonb,   -- {transcript_versions: 3, candidates: 12, ...}
  error         text,
  requested_at  timestamptz not null default now(),
  finished_at   timestamptz
);
create index deletion_jobs_status_idx on deletion_jobs(status);

alter table workspaces
  add column if not exists deletion_requested_at timestamptz,
  add column if not exists deletion_scheduled_for timestamptz;   -- 30 Tage Karenz

-- ------------------------------------------------------------------------------------------------
-- CI-Manager: Assets (Fonts, Logos) und Markenprofil-Historie
-- ------------------------------------------------------------------------------------------------
create table brand_assets (
  id               uuid primary key default gen_random_uuid(),
  workspace_id     uuid not null references workspaces(id) on delete cascade,
  brand_profile_id uuid not null references brand_profiles(id) on delete cascade,
  kind             text not null check (kind in ('font', 'logo', 'lower_third_bg', 'watermark')),
  name             text not null,
  storage_key      text not null,            -- derived: brand/<profile>/<kind>/<hash>.<ext>
  mime_type        text,
  size_bytes       bigint,
  sha256           text,
  font_family      text,                     -- bei kind = font: Familienname aus der Datei
  font_weight      int,
  license_note     text,                     -- Nutzer bestätigt Lizenz (Audit)
  uploaded_by      uuid,
  created_at       timestamptz not null default now()
);
create index brand_assets_profile_idx on brand_assets(brand_profile_id);

create table brand_profile_versions (
  id               uuid primary key default gen_random_uuid(),
  brand_profile_id uuid not null references brand_profiles(id) on delete cascade,
  version          int not null,
  snapshot         jsonb not null,           -- vollständige Zeile vor der Änderung
  changed_by       uuid,
  changed_at       timestamptz not null default now(),
  unique (brand_profile_id, version)
);

-- Gast-Freigabe: Ablauf und Anzeige-Daten
alter table guest_approvals
  add column if not exists guest_name text,
  add column if not exists requested_by uuid,
  add column if not exists message text,        -- Nachricht an den Gast
  add column if not exists viewed_at timestamptz;

-- ------------------------------------------------------------------------------------------------
-- RLS für die neuen Tabellen
-- ------------------------------------------------------------------------------------------------
alter table users              enable row level security;
alter table sessions           enable row level security;
alter table login_tokens       enable row level security;
alter table workspace_invites  enable row level security;
alter table subscriptions      enable row level security;
alter table usage_periods      enable row level security;
alter table billing_events     enable row level security;
alter table dpa_acceptances    enable row level security;
alter table deletion_jobs      enable row level security;
alter table brand_assets       enable row level security;
alter table brand_profile_versions enable row level security;
alter table plans              enable row level security;

-- users/sessions/login_tokens: nur die Auth-Schicht (Rolle chopstr_auth, BYPASSRLS) liest sie;
-- die App-Rolle sieht Nutzer nur über ihre Mitgliedschaft im aktiven Workspace.
create policy users_in_workspace on users
  using (exists (select 1 from workspace_members m where m.user_id = users.id and m.workspace_id = app_workspace_id()));
create policy sessions_none on sessions using (false);
create policy login_tokens_none on login_tokens using (false);
create policy plans_read on plans for select using (true);
create policy ws_invites on workspace_invites
  using (workspace_id = app_workspace_id()) with check (workspace_id = app_workspace_id());
create policy ws_subscriptions on subscriptions using (workspace_id = app_workspace_id());
create policy ws_usage on usage_periods using (workspace_id = app_workspace_id());
create policy ws_billing_events on billing_events using (workspace_id = app_workspace_id());
create policy ws_dpa on dpa_acceptances using (workspace_id = app_workspace_id());
create policy ws_deletion on deletion_jobs using (workspace_id = app_workspace_id());
create policy ws_brand_assets on brand_assets using (workspace_id = app_workspace_id());
create policy ws_brand_versions on brand_profile_versions
  using (exists (select 1 from brand_profiles b where b.id = brand_profile_versions.brand_profile_id and b.workspace_id = app_workspace_id()));

-- Mandanten-Scope: client-Mitglieder sehen nur Quellen ihrer Marke
create or replace function app_brand_scope() returns uuid
language sql stable as $$
  select nullif(current_setting('app.brand_scope', true), '')::uuid
$$;
drop policy if exists ws_sources on sources;
create policy ws_sources on sources
  using (workspace_id = app_workspace_id() and (app_brand_scope() is null or brand_profile_id = app_brand_scope()))
  with check (workspace_id = app_workspace_id() and (app_brand_scope() is null or brand_profile_id = app_brand_scope()));

insert into schema_migrations(version) values ('0003_auth_billing') on conflict do nothing;
