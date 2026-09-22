-- chopstr · Migration 0001 · Grundschema
-- Ziel: Postgres 15+ (Standard: Supabase eu-central-1, Sovereign: Hetzner). Row Level Security auf allen
-- Fachtabellen. Videos liegen NIE in Postgres, nur Objektspeicher-Keys.
-- Mandantenkontext: die App setzt pro Verbindung `set local app.workspace_id = '<uuid>'` (bzw. Supabase-JWT).

create extension if not exists pgcrypto;

-- ------------------------------------------------------------------------------------------------
-- Hilfsfunktionen
-- ------------------------------------------------------------------------------------------------
create or replace function app_workspace_id() returns uuid
language sql stable as $$
  select nullif(current_setting('app.workspace_id', true), '')::uuid
$$;

create or replace function app_actor_id() returns uuid
language sql stable as $$
  select nullif(current_setting('app.actor_id', true), '')::uuid
$$;

create or replace function set_updated_at() returns trigger
language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

-- ------------------------------------------------------------------------------------------------
-- Workspaces (Organisationen) und Mitglieder
-- ------------------------------------------------------------------------------------------------
create table workspaces (
  id                     uuid primary key default gen_random_uuid(),
  name                   text not null,
  slug                   text not null unique,
  plan                   text not null default 'starter',
  tier                   text not null default 'standard' check (tier in ('standard', 'sovereign')),
  data_region            text not null default 'eu-central-1',
  retention_days         int  not null default 30 check (retention_days between 1 and 3650),
  render_retention_days  int  not null default 90 check (render_retention_days between 1 and 3650),
  allow_us_subprocessors boolean not null default false,
  training_opt_in        boolean not null default false,   -- Kundendaten fließen NIE ohne Opt-in ins Training
  dpa_signed_at          timestamptz,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now()
);
create trigger workspaces_updated before update on workspaces for each row execute function set_updated_at();

create table workspace_members (
  workspace_id uuid not null references workspaces(id) on delete cascade,
  user_id      uuid not null,
  email        text,
  display_name text,
  role         text not null default 'editor'
               check (role in ('owner', 'admin', 'editor', 'reviewer', 'client')),
  created_at   timestamptz not null default now(),
  primary key (workspace_id, user_id)
);

-- ------------------------------------------------------------------------------------------------
-- Markenprofile (Brand Brain, Phase 1: Anrede, Land, Gendern, Wörterbuch, CI)
-- ------------------------------------------------------------------------------------------------
create table brand_profiles (
  id               uuid primary key default gen_random_uuid(),
  workspace_id     uuid not null references workspaces(id) on delete cascade,
  name             text not null,
  version          int  not null default 1,
  address          text not null default 'du'  check (address in ('du', 'sie')),
  country          text not null default 'AT'  check (country in ('DE', 'AT', 'CH')),
  gender_mode      text not null default 'neutral'
                   check (gender_mode in ('neutral', 'paarform', 'doppelpunkt', 'stern', 'keine')),
  asr_variant      text not null default 'de'  check (asr_variant in ('de', 'de-CH')),
  brand_vocab      text[] not null default '{}',        -- Eigennamen, Produkte, Personen (Hotwords + Nachkorrektur)
  protected_terms  text[] not null default '{}',        -- Austriazismen/Helvetismen: nie "korrigieren"
  banned_phrases   text[] not null default '{}',
  tone_adjectives  text[] not null default '{}',        -- max. 3, z. B. {ruhig, konkret, belegt}
  default_platform text not null default 'linkedin'
                   check (default_platform in ('tiktok', 'reels', 'shorts', 'linkedin')),
  caption_preset   text not null default 'linkedin_static'
                   check (caption_preset in ('tiktok_bold', 'reels_clean', 'shorts_clean', 'linkedin_static', 'corporate_third')),
  caption_style    jsonb not null default '{}'::jsonb,  -- Font, Farben, Highlight, Position
  ci               jsonb not null default '{}'::jsonb,  -- {colors:{primary,secondary,accent}, fonts:{primary_key,secondary_key}, logo_key, lower_third:{...}}
  learned_weights  jsonb,                               -- Rubrik-Gewichte aus Performance-/Freigabedaten (nur dieser Workspace)
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
create index brand_profiles_workspace_idx on brand_profiles(workspace_id);
create trigger brand_profiles_updated before update on brand_profiles for each row execute function set_updated_at();

-- ------------------------------------------------------------------------------------------------
-- Quellen (Longform-Assets) und Ingest-Metadaten
-- ------------------------------------------------------------------------------------------------
create table sources (
  id                  uuid primary key default gen_random_uuid(),
  workspace_id        uuid not null references workspaces(id) on delete cascade,
  brand_profile_id    uuid references brand_profiles(id) on delete set null,
  title               text not null,
  original_filename   text,
  mime_type           text,
  size_bytes          bigint,
  sha256              text,
  storage_key         text not null,                     -- Original, unverändert (Bucket: sources)
  audio_key           text,                              -- 16 kHz Mono WAV (Bucket: derived)
  proxy_key           text,                              -- 720p-Proxy / HLS-Playlist (Bucket: derived)
  duration_s          real,
  width               int,
  height              int,
  fps                 real,
  rights_status       text not null default 'own' check (rights_status in ('own', 'licensed', 'third_party')),
  rights_confirmed_at timestamptz,                       -- Rechte-Checkbox beim Upload (Audit-Eintrag)
  rights_confirmed_by uuid,
  source_owner        text,                              -- Quellenangabe bei Fremdmaterial (§ 63 UrhG)
  source_title        text,
  source_url          text,
  expected_speakers   int,
  brief               jsonb not null default '{}'::jsonb, -- {audience, wanted, exclude, platform}
  status              text not null default 'uploaded'
                      check (status in ('uploading', 'uploaded', 'ingesting', 'transcribing', 'analyzing',
                                        'scoring', 'ready', 'failed', 'deleted')),
  status_message      text,
  temporal_workflow_id text,
  delete_after        timestamptz,                       -- Löschfrist (Lifecycle + Löschnachweis)
  deleted_at          timestamptz,
  created_by          uuid,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
create index sources_workspace_idx on sources(workspace_id, created_at desc);
create index sources_status_idx on sources(status);
create trigger sources_updated before update on sources for each row execute function set_updated_at();

-- Live-Fortschritt der Pipeline (die UI liest diese Tabelle per SSE/Polling)
create table pipeline_events (
  id         bigserial primary key,
  source_id  uuid not null references sources(id) on delete cascade,
  step       text not null,   -- probe_and_extract | transcribe_de | diarize | heatmap | fuse_and_nlp | detect_candidates | render
  status     text not null check (status in ('started', 'progress', 'finished', 'failed', 'skipped')),
  progress   real check (progress between 0 and 1),
  message    text,
  payload    jsonb,
  at         timestamptz not null default now()
);
create index pipeline_events_source_idx on pipeline_events(source_id, id);

-- ------------------------------------------------------------------------------------------------
-- Transkripte: versioniert (wer, wann, welches Modell, automatisch oder manuell)
-- ------------------------------------------------------------------------------------------------
create table transcript_versions (
  id           uuid primary key default gen_random_uuid(),
  source_id    uuid not null references sources(id) on delete cascade,
  version      int  not null,
  origin       text not null check (origin in ('asr', 'manual', 'vocab_correction', 'merge')),
  asr_model_id text,
  asr_variant  text,
  diarizer_id  text,
  language     text not null default 'de',
  words        jsonb not null,              -- [{text,start,end,prob,speaker,filler,negation,sentence_idx}]
  stats        jsonb not null default '{}'::jsonb, -- {word_count, speakers, mean_prob, low_conf_ratio}
  created_by   uuid,                        -- null = System
  created_at   timestamptz not null default now(),
  unique (source_id, version)
);

create view transcripts_current as
  select distinct on (source_id) *
  from transcript_versions
  order by source_id, version desc;

-- Einzelne Korrekturen aus dem Editor (fließen ins Marken-Wörterbuch, ohne ASR-Neulauf)
create table transcript_corrections (
  id            uuid primary key default gen_random_uuid(),
  source_id     uuid not null references sources(id) on delete cascade,
  from_version  int  not null,
  word_index    int  not null,
  old_text      text not null,
  new_text      text not null,
  add_to_vocab  boolean not null default false,
  created_by    uuid,
  created_at    timestamptz not null default now()
);
create index transcript_corrections_source_idx on transcript_corrections(source_id);

-- ------------------------------------------------------------------------------------------------
-- Kandidaten (Phase 2), Clips, Hooks, Captions: versioniert
-- ------------------------------------------------------------------------------------------------
create table candidates (
  id                uuid primary key default gen_random_uuid(),
  source_id         uuid not null references sources(id) on delete cascade,
  version           int  not null default 1,
  segments          jsonb not null,           -- [{start,end,role}] in Abspielreihenfolge (Clips sind Kompositionen)
  start_s           real not null,
  end_s             real not null,
  first_sent        int,
  last_sent         int,
  structure         text check (structure in ('payoff_first', 'tension_first', 'hook_build_payoff',
                                              'decision_story', 'how_to_list', 'loop')),
  rubric            jsonb not null,           -- Scores 0–10 + wörtliche Belegzitate
  gates             jsonb not null default '{}'::jsonb, -- {standalone, fidelity, sentence_boundaries, no_open_loop}
  story_graph_flags jsonb not null default '[]'::jsonb, -- spätere Relativierungen
  risk_flags        jsonb not null default '[]'::jsonb, -- humor | sensitive_topic | claim | ad
  total             real,
  gate_passed       boolean not null default false,
  why               text,                    -- „Warum dieser Clip?“ in Klartext
  model_id          text,
  prompt_version    text,
  human_verdict     text check (human_verdict in ('accepted', 'rejected', 'edited')),
  verdict_reason    text,
  verdict_by        uuid,
  verdict_at        timestamptz,
  created_at        timestamptz not null default now()
);
create index candidates_source_idx on candidates(source_id, total desc);

create table clips (
  id                       uuid primary key default gen_random_uuid(),
  source_id                uuid not null references sources(id) on delete cascade,
  candidate_id             uuid references candidates(id) on delete set null,
  version                  int  not null default 1,
  platform                 text not null default 'linkedin'
                           check (platform in ('tiktok', 'reels', 'shorts', 'linkedin')),
  aspect                   text not null default '9:16' check (aspect in ('9:16', '4:5', '1:1', '16:9')),
  composition              jsonb not null,    -- [{start,end,role}] nach manuellem Trim / Füller-Cuts
  kept_ranges              jsonb,
  fidelity_warnings        jsonb not null default '[]'::jsonb,
  speaker_positions        jsonb,             -- {"SPEAKER_00":0,"SPEAKER_01":1} aus UI bestätigt
  render_plan              jsonb,             -- deterministischer Render-Plan (JSON)
  title_card               text,
  ad_label                 text,              -- "Anzeige" | "Werbung"
  ai_features              text[] not null default '{}',
  guest_approval_required  boolean not null default false,
  status                   text not null default 'draft'
                           check (status in ('draft', 'approved', 'rendering', 'rendered', 'exported', 'failed')),
  file_key                 text,
  srt_key                  text,
  cps_warnings             jsonb,
  created_by               uuid,
  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now()
);
create index clips_source_idx on clips(source_id);
create trigger clips_updated before update on clips for each row execute function set_updated_at();

create table hook_versions (
  id             uuid primary key default gen_random_uuid(),
  clip_id        uuid not null references clips(id) on delete cascade,
  version        int  not null,
  spoken_hook    text,
  onscreen_hook  text,
  pattern        text,   -- identity_call | contrarian | open_loop | results_first | mistake_warning | ...
  post_captions  jsonb not null default '{}'::jsonb, -- {tiktok:..., linkedin:...}
  cta            text,
  lint_notes     jsonb not null default '[]'::jsonb,
  claim_issues   jsonb not null default '[]'::jsonb,
  origin         text not null check (origin in ('llm', 'manual')),
  model_id       text,
  prompt_version text,
  created_by     uuid,
  created_at     timestamptz not null default now(),
  unique (clip_id, version)
);

create table caption_versions (
  id             uuid primary key default gen_random_uuid(),
  clip_id        uuid not null references clips(id) on delete cascade,
  version        int  not null,
  preset         text not null,
  cards          jsonb not null,   -- Karten mit Wortzeiten auf Ausgabe-Timeline
  ass_key        text,
  srt_key        text,
  cps_warnings   jsonb not null default '[]'::jsonb,
  origin         text not null check (origin in ('auto', 'manual')),
  created_by     uuid,
  created_at     timestamptz not null default now(),
  unique (clip_id, version)
);

-- ------------------------------------------------------------------------------------------------
-- Gast-Freigabe, Publikationen
-- ------------------------------------------------------------------------------------------------
create table guest_approvals (
  id          uuid primary key default gen_random_uuid(),
  clip_id     uuid not null references clips(id) on delete cascade,
  guest_email text,
  token       text not null unique,
  expires_at  timestamptz,
  decision    text check (decision in ('approved', 'rejected', 'changes')),
  comment     text,
  decided_at  timestamptz,
  created_at  timestamptz not null default now()
);

create table publications (
  id           uuid primary key default gen_random_uuid(),
  clip_id      uuid not null references clips(id) on delete cascade,
  platform     text not null,
  external_id  text,
  published_at timestamptz,
  metrics      jsonb,
  fetched_at   timestamptz
);

-- ------------------------------------------------------------------------------------------------
-- Kostenlog pro Job (Unit Economics) und Audit-Log (Nachweise)
-- ------------------------------------------------------------------------------------------------
create table job_costs (
  id                uuid primary key default gen_random_uuid(),
  workspace_id      uuid not null references workspaces(id) on delete cascade,
  source_id         uuid references sources(id) on delete set null,
  clip_id           uuid references clips(id) on delete set null,
  job_type          text not null,   -- ingest | asr | diarize | nlp | llm_propose | llm_score | render ...
  provider          text,            -- selfhost-eu | bedrock-eu | mistral-eu | gladia-eu
  model_id          text,
  source_minutes    real not null default 0,
  gpu_seconds       real not null default 0,
  cpu_seconds       real not null default 0,
  llm_input_tokens  int  not null default 0,
  llm_output_tokens int  not null default 0,
  storage_bytes     bigint not null default 0,
  estimated_eur     numeric(10, 4) not null default 0,
  created_at        timestamptz not null default now()
);
create index job_costs_workspace_idx on job_costs(workspace_id, created_at desc);

create table audit_log (
  id           bigserial primary key,
  workspace_id uuid,
  actor_id     uuid,
  actor_type   text not null default 'user' check (actor_type in ('user', 'system', 'guest')),
  action       text not null,   -- upload.created | rights.confirmed | transcript.corrected | candidate.accepted | export.created | source.deleted ...
  entity       text,
  entity_id    uuid,
  payload      jsonb,
  ip           inet,
  at           timestamptz not null default now()
);
create index audit_log_workspace_idx on audit_log(workspace_id, at desc);

-- ------------------------------------------------------------------------------------------------
-- Row Level Security: alle Fachtabellen, Isolation über app_workspace_id()
-- ------------------------------------------------------------------------------------------------
alter table workspaces             enable row level security;
alter table workspace_members      enable row level security;
alter table brand_profiles         enable row level security;
alter table sources                enable row level security;
alter table pipeline_events        enable row level security;
alter table transcript_versions    enable row level security;
alter table transcript_corrections enable row level security;
alter table candidates             enable row level security;
alter table clips                  enable row level security;
alter table hook_versions          enable row level security;
alter table caption_versions       enable row level security;
alter table guest_approvals        enable row level security;
alter table publications           enable row level security;
alter table job_costs              enable row level security;
alter table audit_log              enable row level security;

create policy ws_self on workspaces
  using (id = app_workspace_id());
create policy ws_members on workspace_members
  using (workspace_id = app_workspace_id());
create policy ws_brand_profiles on brand_profiles
  using (workspace_id = app_workspace_id()) with check (workspace_id = app_workspace_id());
create policy ws_sources on sources
  using (workspace_id = app_workspace_id()) with check (workspace_id = app_workspace_id());
create policy ws_pipeline_events on pipeline_events
  using (exists (select 1 from sources s where s.id = pipeline_events.source_id and s.workspace_id = app_workspace_id()));
create policy ws_transcripts on transcript_versions
  using (exists (select 1 from sources s where s.id = transcript_versions.source_id and s.workspace_id = app_workspace_id()));
create policy ws_corrections on transcript_corrections
  using (exists (select 1 from sources s where s.id = transcript_corrections.source_id and s.workspace_id = app_workspace_id()));
create policy ws_candidates on candidates
  using (exists (select 1 from sources s where s.id = candidates.source_id and s.workspace_id = app_workspace_id()));
create policy ws_clips on clips
  using (exists (select 1 from sources s where s.id = clips.source_id and s.workspace_id = app_workspace_id()));
create policy ws_hooks on hook_versions
  using (exists (select 1 from clips c join sources s on s.id = c.source_id
                 where c.id = hook_versions.clip_id and s.workspace_id = app_workspace_id()));
create policy ws_captions on caption_versions
  using (exists (select 1 from clips c join sources s on s.id = c.source_id
                 where c.id = caption_versions.clip_id and s.workspace_id = app_workspace_id()));
create policy ws_guest_approvals on guest_approvals
  using (exists (select 1 from clips c join sources s on s.id = c.source_id
                 where c.id = guest_approvals.clip_id and s.workspace_id = app_workspace_id()));
create policy ws_publications on publications
  using (exists (select 1 from clips c join sources s on s.id = c.source_id
                 where c.id = publications.clip_id and s.workspace_id = app_workspace_id()));
create policy ws_job_costs on job_costs
  using (workspace_id = app_workspace_id());
create policy ws_audit on audit_log
  using (workspace_id = app_workspace_id());

-- Worker und Migrationen laufen mit der Rolle `chopstr_worker` (BYPASSRLS), die App mit `chopstr_app`.
-- Beide Rollen legt scripts/migrate.mjs an, falls sie fehlen.

-- ------------------------------------------------------------------------------------------------
-- Migrationsverwaltung
-- ------------------------------------------------------------------------------------------------
create table if not exists schema_migrations (
  version    text primary key,
  applied_at timestamptz not null default now()
);
insert into schema_migrations(version) values ('0001_init') on conflict do nothing;
