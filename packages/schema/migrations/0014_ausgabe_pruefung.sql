-- Die technische Prüfung der fertigen Datei.
--
-- Bis hierher endete der Renderlauf so: ffprobe misst Dauer, Breite, Höhe und Bilder pro Sekunde,
-- die vier Zahlen werden in die Zeile geschrieben, und danach steht ``status = 'rendered'``. Ohne
-- jeden Vergleich. Ob die gemessene Dauer zur geplanten passt, ob überhaupt eine Tonspur drin ist,
-- ob die Untertitel im Bild gelandet sind: nichts davon wurde gefragt. Eine stumme Datei, eine
-- Datei mit schwarzem Bild und eine Datei ohne Untertitel sahen für chopstr aus wie eine fertige.
--
-- ``export_checks`` ist das Ergebnis dieser Prüfung, eine Liste aus
-- ``{pruefung, ergebnis, text, gemessen}``. ``ergebnis = 'fehler'`` verhindert, dass die Fassung
-- heruntergeladen oder veröffentlicht wird (packages/schema/ausgabe_regeln_v1.json, Regel
-- ``technik_fehler``). ``hinweis`` verhindert nichts, steht aber an der Karte.
--
-- NULL heisst: nicht geprüft. Das gilt für alle Videos aus der Zeit vor dieser Prüfung. Sie
-- nachträglich zu sperren wäre eine Behauptung über etwas, das niemand gemessen hat.

alter table clips add column if not exists export_checks jsonb;

comment on column clips.export_checks is
  'Technische Prüfung der fertigen Datei: [{pruefung, ergebnis, text, gemessen}]. NULL = nicht geprüft.';
