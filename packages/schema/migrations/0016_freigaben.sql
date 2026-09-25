-- Eine Freigabe ist ein Paket von Clips mit EINEM Link.
--
-- Bisher hing jede Freigabe an genau einem Clip und hatte ihr eigenes Token. Wer zwölf Clips
-- abzeichnen lassen wollte, verschickte zwölf Links - und die Person, die zusagen soll, klickte
-- sich zwölfmal durch dieselbe Seite. Gefragt wird aber einmal: „schaust du bitte drüber, ob das
-- so raus darf."
--
-- Deshalb hier eine Klammer darum. Der Link ist das Token DIESER Zeile; die Urteile bleiben je
-- Clip in guest_approvals, denn die Person entscheidet je Clip. So bleibt auch alles Bestehende
-- gültig: ein guest_approval ohne freigabe_id ist eine Einzelfreigabe von früher.
--
-- WARUM DIE NUMMER NICHT IN DER ADRESSE STEHT. Die Nummer ist fortlaufend und damit erratbar.
-- Stünde sie in der Adresse, könnte jeder von "Freigabe 3" auf "Freigabe 4" schliessen und die
-- Clips eines fremden Kunden ansehen - ohne Anmeldung, denn dieser Link IST der Zugang. Die
-- Nummer ist deshalb der Name nach innen, das Token der Weg von aussen.

create table if not exists freigaben (
  id           uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  -- Fortlaufend je Arbeitsbereich, damit „Freigabe 7" für den Kunden eine Zahl ist, mit der er
  -- etwas anfangen kann - und nicht eine Kennung aus 32 Zeichen.
  nummer       bigint not null,
  name         text not null,
  token        text not null unique,
  -- Beides freiwillig: der Link lässt sich auch von Hand weitergeben.
  guest_email  text,
  message      text,
  expires_at   timestamptz,
  created_by   uuid references users(id) on delete set null,
  created_at   timestamptz not null default now(),
  unique (workspace_id, nummer)
);

create index if not exists freigaben_ws_idx on freigaben (workspace_id, created_at desc);

alter table guest_approvals add column if not exists freigabe_id uuid references freigaben(id) on delete cascade;
create index if not exists guest_approvals_freigabe_idx on guest_approvals (freigabe_id);

comment on table freigaben is
  'Ein Paket von Clips mit einem Link. Die Urteile stehen je Clip in guest_approvals.';
comment on column freigaben.nummer is
  'Fortlaufend je Arbeitsbereich. Nur Name, nicht Adresse - sie waere erratbar.';
comment on column guest_approvals.freigabe_id is
  'Zu welchem Paket gehoert dieses Urteil? NULL = Einzelfreigabe aus der Zeit davor.';

alter table freigaben enable row level security;

create policy ws_freigaben on freigaben
  using (workspace_id = app_workspace_id()) with check (workspace_id = app_workspace_id());
