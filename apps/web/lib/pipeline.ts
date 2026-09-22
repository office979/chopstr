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
    label: "Prüfung & Extraktion",
    description: "Datei prüfen, Audio extrahieren, Proxy rendern",
    phase: 1,
  },
  {
    key: "transcribe_de",
    label: "Transkription",
    description: "Deutsches ASR mit Wortzeiten und Konfidenzen",
    phase: 1,
  },
  {
    key: "diarize",
    label: "Sprechertrennung",
    description: "Wer spricht wann",
    phase: 1,
  },
  {
    key: "fuse_and_nlp",
    label: "Sprachanalyse",
    description: "dach_nlp: Sätze, Füllwörter, Verneinungen",
    phase: 1,
  },
  {
    key: "detect_candidates",
    label: "Kandidaten",
    description: "Story-Engine: Vorschlag, Rubrik, Story-Graph",
    phase: 2,
  },
];

/* Render-Schritt (Phase 3): erscheint nur auf der Clip-Seite, nicht in der Quellen-Pipeline */
export const RENDER_STEP: PipelineStepDef = {
  key: "render",
  label: "Render",
  description: "Copy, Reframe, Captions, Encode, Provenienz",
  phase: 3,
};

export const STATUS_LABELS: Record<SourceStatus, string> = {
  uploading: "Wird hochgeladen",
  uploaded: "Hochgeladen",
  ingesting: "Wird geprüft",
  transcribing: "Wird transkribiert",
  analyzing: "Wird analysiert",
  scoring: "Wird bewertet",
  ready: "Bereit",
  failed: "Fehlgeschlagen",
  deleted: "Gelöscht",
};

export function isTerminalStatus(status: SourceStatus): boolean {
  return status === "ready" || status === "failed" || status === "deleted";
}
