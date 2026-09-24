-- Der Prüfstand eines Clips: hat ein Mensch ihn angesehen und was hat er entschieden?
--
-- Bisher gab es nur den technischen Zustand (draft, rendering, rendered, failed). Der sagt, ob
-- eine Datei da ist, aber nicht, ob jemand sie haben will. In der Übersicht stand deshalb
-- "Fertig" an Clips, die niemand geprüft hatte, und "Verwerfen" gab es nur als endgültiges
-- Löschen mit Löschauftrag: eine Entscheidung, die man nicht zurücknehmen kann.
--
-- 'offen'      niemand hat entschieden
-- 'bereit'     geprüft und zum Veröffentlichen freigegeben
-- 'verworfen'  aussortiert, bleibt aber da und lässt sich zurückholen
--
-- Das Löschen bleibt, was es war: endgültig, mit Nachweis (clips.status = 'deleted').

alter table clips
  add column if not exists review text not null default 'offen';

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'clips_review_check') then
    alter table clips add constraint clips_review_check check (review in ('offen', 'bereit', 'verworfen'));
  end if;
end $$;

-- Die Übersicht filtert danach, und zwar je Projekt.
create index if not exists clips_source_review_idx on clips (source_id, review);
