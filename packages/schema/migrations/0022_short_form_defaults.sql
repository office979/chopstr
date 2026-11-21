-- Short-Form zuerst: TikTok statt LinkedIn als Spaltenvorgabe.
--
-- chopstr ersetzt Clipping-Agenturen für Formate, Shows, Podcasts, Interviews und Streams. Der Standard ist
-- deshalb TikTok (danach Reels und Shorts), nicht mehr LinkedIn. LinkedIn bleibt im CHECK und damit wählbar.
--
-- Nur die Vorgabe für neue Zeilen ändert sich. Bestehende Markenprofile und Clips werden nicht umgeschrieben:
-- ein vorhandenes 'linkedin' kann eine bewusste Wahl sein, und ein Clip trägt die Plattform, für die er
-- geschnitten wurde. `alter column ... set default` ändert nur den Katalog, keine Daten, und braucht nur
-- kurz ACCESS EXCLUSIVE ohne Tabellenumschreibung.

alter table brand_profiles alter column default_platform set default 'tiktok';
alter table clips alter column platform set default 'tiktok';
