-- Musik unter dem Clip.
--
-- Ein Clip ohne Musik klingt nach Rohmaterial. Was hier steht, ist die Entscheidung des Menschen:
-- welches Stueck, welche Stelle daraus, wie laut. Der Renderer legt es danach unter die Sprache
-- (pipeline/musik.py).
--
-- WARUM EINE SPALTE UND KEINE TABELLE. Ein Clip hat genau ein Musikstueck oder keines. Eine
-- eigene Tabelle waere eine Zeile je Clip mit einem Fremdschluessel darauf - dieselbe Information,
-- nur mit einem Join davor.
--
-- NULL heisst „keine Musik". Ein Unterschied zwischen NULL und {} wird hier nicht gebraucht: bei
-- den Effekten war er noetig, weil eine Automatik die leere Liste ueberschreiben wuerde. Musik
-- setzt niemand von selbst - dafuer braeuchte es ein Sprachmodell, das den Text liest.

alter table clips add column if not exists musik jsonb;

comment on column clips.musik is
  'Musik unter dem Clip: {quelle, datei, name, ab_s, lautstaerke_db, ducking}. NULL = keine.
   ab_s ist die Sekunde IM STUECK, an der die Wiedergabe beginnt - nicht im Clip.';
