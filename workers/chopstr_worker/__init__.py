"""chopstr Worker: Python-Pipeline für Ingest, deutsche ASR, Diarisierung und DACH-NLP.

Alle Verarbeitung findet in der EU statt (Residency-Guard in ``residency.py``).
Schwere Abhängigkeiten (faster-whisper, pyannote, torch, spaCy, OpenCV) werden nur innerhalb
von Funktionen importiert, damit Tests ohne GPU laufen.
"""

__version__ = "0.1.0"
