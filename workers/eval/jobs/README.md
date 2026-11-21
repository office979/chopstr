# Trainings-Jobs (`train_job_v1`)

Eine Datei je Langform, angelegt mit `python -m eval.train job create` (siehe `docs/TRAINING-WORKFLOW.md`).
Nur Metadaten: Quelle als Dateiname, Pfad im Repo oder URL mit sha256 und Cache-Referenz, Briefing, Gold-IDs.
Absolute Pfade, Medien und Transkripte liegen nur im Cache `.local/eval-cache/<cache_ref>/` (gitignored).
