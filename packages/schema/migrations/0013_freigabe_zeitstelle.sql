-- Eine Anmerkung des Kunden an einer bestimmten Stelle im Clip.
--
-- Bisher konnte ein Gast nur einen freien Text hinterlassen: "der Schnitt am Ende passt nicht".
-- Wer das liest, sucht die Stelle von Hand. Bei einem Clip von vierzig Sekunden geht das noch,
-- bei zwanzig Clips in einer Woche nicht mehr - und bei jeder Rueckfrage beginnt die Suche von
-- vorn.
--
-- ``comment_at_s`` ist die Sekunde IM FERTIGEN CLIP, nicht im Originalvideo. Der Gast sieht nur
-- den Clip; er kennt das lange Video nicht und koennte dessen Zeiten gar nicht nennen. Die
-- Umrechnung in die Quellzeit macht die Oberflaeche des Teams, die den Schnitt kennt.
--
-- NULL heisst: die Anmerkung gilt dem ganzen Clip. Das bleibt zulaessig, denn nicht jede
-- Rueckmeldung haengt an einer Stelle ("bitte auf Sie umstellen").

alter table guest_approvals add column if not exists comment_at_s double precision;

comment on column guest_approvals.comment_at_s is
  'Sekunde im fertigen Clip, auf die sich der Kommentar bezieht. NULL = ganzer Clip.';
