-- Bildausschnitt-Marken von Clipzeit auf Quellzeit umstellen.
--
-- Bisher schrieb die Oberfläche "ab Sekunde x des fertigen Clips", der Renderer las aber
-- "ab Sekunde x der Quelle" (tracking.zeitmarken_anwenden vergleicht gegen die Zeitachse aus
-- reframe.abtasten, und die ist absolut). Eine Marke bei Clipsekunde 10 wirkte deshalb im
-- gebauten Video ab Quellsekunde 10, also meist über den ganzen Clip. Der Editor zeigte etwas
-- anderes als das Ergebnis.
--
-- Ab jetzt gilt überall Quellzeit. Bestehende Marken werden um den Anfang des Clips verschoben.
-- Clips ohne Komposition oder ohne Marken bleiben unberührt.

update clips
set zeitmarken = (
  select jsonb_agg(
    jsonb_set(marke, '{ab_s}', to_jsonb(round(((marke->>'ab_s')::numeric + anfang.start_s), 2)))
    order by (marke->>'ab_s')::numeric
  )
  from jsonb_array_elements(zeitmarken) as marke
)
from (select id as clip_id, ((composition->0->>'start')::numeric) as start_s from clips) as anfang
where clips.id = anfang.clip_id
  and anfang.start_s is not null
  and anfang.start_s > 0
  and jsonb_typeof(clips.zeitmarken) = 'array'
  and jsonb_array_length(clips.zeitmarken) > 0;
