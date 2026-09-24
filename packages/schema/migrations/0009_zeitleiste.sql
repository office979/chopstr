-- chopstr · Migration 0009 · Zeitleiste: Einzelbilder und Entscheidungen von Hand
--
-- Zwei Ergaenzungen an clips, beide fuer die Zeitleiste im Clip-Editor:
--
-- 1. filmstrip_key — ein einziges JPG mit vielen kleinen Einzelbildern nebeneinander, ueber die
--    ganze Laenge des Clips verteilt. Bewusst eine Datei und nicht hundert: die Zeitleiste soll
--    sofort dastehen und nicht nachladen, waehrend jemand daran schiebt. filmstrip_meta haelt,
--    was die Oberflaeche zum Rechnen braucht (wie viele Bilder, wie breit, wie hoch), damit sie
--    das Bild nicht erst laden und vermessen muss.
--
-- 2. zeitmarken — Entscheidungen von Hand, als Liste von {"ab_s": 12.4, "x": 2582}: ab dieser
--    Sekunde soll die Person an der Bildstelle x zu sehen sein, bis zur naechsten Marke.
--
--    Ueber die Bildstelle und nicht ueber einen Index oder eine Shot-Nummer, weil beides sich
--    verschiebt: findet die Erkennung beim naechsten Lauf eine Person mehr oder weniger, zeigte
--    der Clip auf einmal jemand anderen. Eine Bildstelle bleibt eine Bildstelle, und der Renderer
--    rastet sie auf das naechstgelegene erkannte Gesicht ein.
--
--    Eine Marke schlaegt die Automatik. Wer von Hand entscheidet, will nicht ueberstimmt werden.

alter table clips
  add column if not exists filmstrip_key  text,
  add column if not exists filmstrip_meta jsonb,
  add column if not exists zeitmarken     jsonb not null default '[]'::jsonb;

insert into schema_migrations(version) values ('0009_zeitleiste') on conflict do nothing;
