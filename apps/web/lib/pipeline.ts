import type { PipelineStep, SourceStatus } from "@/lib/repo/types";

/* Pipeline-Schritte in Anzeige-Reihenfolge. Phase 2 (Kandidaten) ist seit dem Review aktiv. */
export interface PipelineStepDef {
  key: PipelineStep;
  label: string;
  description: string;
  phase: 1 | 2 | 3;
}

export const PIPELINE_STEPS: PipelineStepDef[] = [
  {
    key: "probe_and_extract",
    label: "Video wird vorbereitet",
    description: "Datei prüfen, Ton heraustrennen, Vorschau anlegen",
    phase: 1,
  },
  {
    key: "transcribe_de",
    label: "Der Computer hört zu",
    description: "Alles Gesprochene wird mitgeschrieben",
    phase: 1,
  },
  {
    key: "diarize",
    label: "Wer spricht wann",
    description: "Die Stimmen werden auseinandergehalten",
    phase: 1,
  },
  {
    key: "fuse_and_nlp",
    label: "Sätze werden sortiert",
    description: "Satzgrenzen, Füllwörter und Verneinungen erkennen",
    phase: 1,
  },
  {
    key: "detect_candidates",
    label: "Gute Stellen werden gesucht",
    description: "Die stärksten Momente finden und bewerten",
    phase: 2,
  },
];

/* Render-Schritt (Phase 3): erscheint nur auf der Clip-Seite, nicht in der Quellen-Pipeline */
export const RENDER_STEP: PipelineStepDef = {
  key: "render",
  label: "Clip wird erstellt",
  description: "Text, Bildausschnitt, Untertitel und Ton zusammensetzen",
  phase: 3,
};

export const STATUS_LABELS: Record<SourceStatus, string> = {
  uploading: "Wird hochgeladen",
  uploaded: "Hochgeladen",
  ingesting: "Wird vorbereitet",
  transcribing: "Computer hört zu",
  analyzing: "Computer sucht gute Stellen",
  scoring: "Computer bewertet die Stellen",
  ready: "Fertig",
  failed: "Etwas ist schiefgegangen",
  deleted: "Gelöscht",
};

export function isTerminalStatus(status: SourceStatus): boolean {
  return status === "ready" || status === "failed" || status === "deleted";
}
