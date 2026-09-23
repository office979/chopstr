-- chopstr · Migration 0007 · Untertitel-Stil: Wort-Presets erlauben, Vorgabe aufheben
--
-- Zwei Fehler in einer Spalte:
--
-- 1. Die Prüfliste kannte die wortweisen Presets nicht (`tiktok_words`, `reels_words`,
--    `shorts_words`). Sie existieren seit der Umstellung auf Kurzformat im Worker
--    (captions_de.PRESETS), konnten aber nie in einem Markenprofil stehen — die Spalte hätte
--    den Wert abgelehnt.
--
-- 2. `not null default 'linkedin_static'` bedeutet, dass JEDES Profil diesen Wert trägt, auch
--    wenn nie jemand ihn gewählt hat. Der Renderer behandelt einen gesetzten Wert aber als
--    ausdrückliche Entscheidung und lässt ihn auf der Standardplattform gewinnen
--    (activities/render.py, caption_preset_for). Ergebnis: hochkante Clips bekamen den ruhigen
--    LinkedIn-Stil mit mehreren Wörtern in zwei Zeilen, obwohl wortweise Untertitel erwartet
--    werden — und niemand konnte das abstellen.
--
-- NULL heißt ab jetzt: keine ausdrückliche Wahl, der Renderer entscheidet nach Format.
-- Hochkant (9:16) wird wortweise, quer bleibt beim bisherigen Plattform-Default.

alter table brand_profiles alter column caption_preset drop not null;
alter table brand_profiles alter column caption_preset drop default;

alter table brand_profiles drop constraint if exists brand_profiles_caption_preset_check;
alter table brand_profiles
  add constraint brand_profiles_caption_preset_check
  check (caption_preset is null or caption_preset in (
    'tiktok_bold', 'reels_clean', 'shorts_clean', 'linkedin_static', 'corporate_third',
    'tiktok_words', 'reels_words', 'shorts_words'
  ));

-- Bestandsprofile: 'linkedin_static' war der Spaltenvorgabewert, keine Entscheidung. Die Oberfläche
-- bot bis heute ausschließlich mehrwortige Presets an, eine bewusste Wahl für diesen Stil im
-- Hochformat konnte es also gar nicht geben. Deshalb zurück auf NULL.
update brand_profiles set caption_preset = null where caption_preset = 'linkedin_static';

insert into schema_migrations(version) values ('0007_caption_preset_portrait') on conflict do nothing;
