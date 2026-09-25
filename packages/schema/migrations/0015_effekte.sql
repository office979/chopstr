-- Effekte auf der Zeitachse des Clips.
--
-- Ein Zoom betont eine Aussage. Bisher konnte der Renderer nur EINEN langsamen Push-in über eine
-- ganze Einstellung (``motion.zoom_to``) - eine Grundbewegung, kein Mittel zur Betonung. Was
-- fehlte, war die Stelle: „hier, auf dieses Wort, für anderthalb Sekunden".
--
-- ``effekte`` ist eine Liste aus ``{art, ab_s, dauer_s}``. ``ab_s`` ist die Sekunde IM FERTIGEN
-- CLIP, nicht im Originalvideo - wie bei ``zeitmarken`` (Migration 0009). Wer den Schnitt ändert,
-- verschiebt damit auch die Effekte, und das ist richtig: sie hängen an dem, was gesagt wird.
--
-- NULL heisst: noch nie gesetzt. Dann legt der Renderlauf beim nächsten Clippen automatisch
-- welche an (pipeline/effekte.automatisch) und schreibt sie hierher. Eine leere Liste dagegen
-- heisst: der Mensch hat alle entfernt, und die Automatik hat das zu respektieren. Der
-- Unterschied zwischen „noch nichts" und „ausdrücklich nichts" ist der ganze Punkt dieser Spalte.

alter table clips add column if not exists effekte jsonb;

comment on column clips.effekte is
  'Effekte auf der Clip-Zeitachse: [{art, ab_s, dauer_s}]. NULL = noch nie gesetzt (Automatik läuft), [] = bewusst keine.';
