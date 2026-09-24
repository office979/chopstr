-- chopstr · Migration 0010 · Wellenform für die Zeitleiste
--
-- Die Zeitleiste soll Schnitte an hörbaren Pausen erlauben. Dafür braucht sie die Lautstärke über
-- die Zeit, und zwar in echt: die vorhandene Heatmap hat ein Ein-Sekunden-Raster und ist für
-- Schnitte zu grob (eine Sprechpause dauert zwei Zehntel).
--
-- Gespeichert wird eine JSON-Datei im Ablageort `derived`, erzeugt aus derselben Audiospur, die
-- auch die Analyse benutzt (signals.wellenform, 25 Werte je Sekunde, 0 bis 255). Hier steht nur
-- ihr Schlüssel, damit die Oberfläche sie ohne Umweg findet.

alter table sources add column if not exists waveform_key text;

insert into schema_migrations(version) values ('0010_wellenform') on conflict do nothing;
