-- chopstr · Migration 0002 · Phase 3: Render-Ergebnisse, Provenienz, Hook-Varianten
-- Ergänzt clips und hook_versions um die Felder, die render_pack schreibt (Vertrag: packages/schema/CLIPS.md).

alter table clips
  add column if not exists destination   text,                          -- Zielplattform des Renders (tiktok | reels | shorts | linkedin)
  add column if not exists duration_s    real,
  add column if not exists width         int,
  add column if not exists height        int,
  add column if not exists fps           real,
  add column if not exists loudness      jsonb,                          -- {integrated_lufs, true_peak_dbtp, preset}
  add column if not exists provenance    jsonb not null default '{}'::jsonb, -- {c2pa: signed|skipped|failed, reason, ai_label_required, source_credit}
  add column if not exists vtt_key       text,
  add column if not exists poster_key    text,
  add column if not exists render_error  text,
  add column if not exists rendered_at   timestamptz;

create index if not exists clips_candidate_idx on clips(candidate_id);
create index if not exists clips_status_idx on clips(status);

alter table hook_versions
  add column if not exists variants jsonb not null default '[]'::jsonb;  -- alle fünf Hook-Varianten [{pattern, spoken, onscreen, lint_notes, claim_issues}]

insert into schema_migrations(version) values ('0002_clips_render') on conflict do nothing;
