-- Getrennte Audiospuren einer Quelle (Lane P1, Launch Phase 1).
--
-- Mehrspuraufnahmen (ein Mikrofon je Sprecher, mehrere Audiostreams im Container) sind die beste Quelle
-- fuer die Sprecherzuordnung: ohne Modell, mit Ueberlappung. Bisher mischte der Ingest die Standardspur
-- auf Mono und warf die Trennung weg (ingest.extract_audio). Mit SPEAKERS_MULTITRACK=1 legt der Ingest
-- zusaetzlich jede Spur als 16-kHz-Mono-WAV ab (ingest.extract_track) und schreibt hier deren Keys.
--
-- audio_key bleibt das Mono-Mix fuer ASR und Export. Die Spuren dienen der Sprecherzuordnung
-- (diarizer_id multitrack_energy); sie ersetzen das Ausgangsaudio nie (Master-Prompt Regel 10).
-- Geschrieben wird nur, wenn alle Spuren dieselbe Startzeit haben (ingest.common_time_base, Regel 16).
--
-- NULL heisst: eine Spur oder Schalter aus. Eine Liste mit weniger als zwei Keys kommt nicht vor.

alter table sources add column if not exists audio_tracks jsonb;

comment on column sources.audio_tracks is
  'Keys der einzelnen Audiospuren im Derived-Bucket (16 kHz Mono, Containerreihenfolge, Spur i = SPEAKER_i).
   NULL = eine Spur oder SPEAKERS_MULTITRACK aus. audio_key bleibt das Mono-Mix.';
