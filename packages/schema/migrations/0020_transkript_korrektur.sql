-- Transkriptvorschläge (Lieferung A1): Korrekturen erst als Vorschlag, dann übernehmen oder ablehnen.
--
-- Falsch erkannte Namen, Zahlen und Fachwörter („Remover-Koffer“ statt „Rimowa-Koffer“) sollen korrigiert
-- werden, ohne die Wortzeiten zu zerstören und ohne dass eine Maschine still den Wortlaut ändert. Jede
-- vorgeschlagene Änderung ist hier eine Zeile mit Grund, Art und Sicherheit. Übernommen wird über den
-- bestehenden Speicherweg (transcript_corrections plus neue Version); nur mit dem Schalter
-- implementation.transcript.auto_fix übernimmt der Worker sichere Lexikon-Treffer selbst. Eine solche
-- Version trägt origin 'llm_correction'.

alter table transcript_versions drop constraint if exists transcript_versions_origin_check;
alter table transcript_versions add constraint transcript_versions_origin_check
  check (origin in ('asr', 'manual', 'vocab_correction', 'merge', 'llm_correction'));

create table if not exists transcript_suggestions (
  id                    uuid primary key default gen_random_uuid(),
  workspace_id          uuid not null references workspaces(id) on delete cascade,
  source_id             uuid not null references sources(id) on delete cascade,
  transcript_version_id uuid references transcript_versions(id) on delete cascade,
  word_index            int not null,
  -- Zusammenziehen zweier Wörter: span 2, das neue Wort bekommt start des ersten und end des letzten
  span                  int not null default 1 check (span between 1 and 3),
  old_text              text not null,
  new_text              text not null,
  reason                text,
  confidence            real check (confidence >= 0 and confidence <= 1),
  kind                  text not null default 'sonstiges'
                          check (kind in ('name', 'zahl', 'fachwort', 'grammatik', 'sonstiges')),
  status                text not null default 'offen' check (status in ('offen', 'angenommen', 'abgelehnt')),
  -- Woher der Vorschlag kommt: confusion (gelernte Verwechslung), lexicon (Wörterbuch, unscharf), llm
  origin                text not null default 'lexicon' check (origin in ('confusion', 'lexicon', 'llm')),
  created_at            timestamptz not null default now(),
  decided_at            timestamptz,
  decided_by            uuid references users(id) on delete set null
);

create index if not exists transcript_suggestions_source_idx on transcript_suggestions (source_id, status);
create index if not exists transcript_suggestions_version_idx on transcript_suggestions (transcript_version_id);

comment on table transcript_suggestions is
  'Vorgeschlagene Transkriptkorrekturen. Wortzeiten bleiben; übernommen wird über transcript_corrections.';
comment on column transcript_suggestions.confidence is
  'Sicherheit 0 bis 1. Zahlen ohne eindeutigen Kontext bleiben unter 0,5 und sind nur ein Hinweis.';

alter table transcript_suggestions enable row level security;

create policy ws_transcript_suggestions on transcript_suggestions
  using (workspace_id = app_workspace_id()) with check (workspace_id = app_workspace_id());
