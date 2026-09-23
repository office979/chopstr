import { describe, expect, it } from "vitest";
import { PIPELINE_STEPS, RENDER_STEP, STATUS_LABELS, isTerminalStatus } from "@/lib/pipeline";
import type { SourceStatus } from "@/lib/repo/types";

/* Fest verdrahtete Liste aller SourceStatus-Werte: schlägt an, sobald der Typ erweitert wird,
 * ohne dass Labels oder Endzustände mitgezogen wurden. */
const ALLE_STATUS: SourceStatus[] = [
  "uploading",
  "uploaded",
  "ingesting",
  "transcribing",
  "analyzing",
  "scoring",
  "ready",
  "failed",
  "deleted",
];

const ENDZUSTAENDE: SourceStatus[] = ["ready", "failed", "deleted"];

describe("isTerminalStatus", () => {
  it("meldet genau ready, failed und deleted als Endzustand", () => {
    for (const status of ALLE_STATUS) {
      expect(isTerminalStatus(status), `Status ${status}`).toBe(ENDZUSTAENDE.includes(status));
    }
  });

  it("behandelt laufende Zustände nicht als Endzustand", () => {
    expect(isTerminalStatus("uploading")).toBe(false);
    expect(isTerminalStatus("transcribing")).toBe(false);
    expect(isTerminalStatus("scoring")).toBe(false);
  });

  it("erkennt die Endzustände einzeln", () => {
    expect(isTerminalStatus("ready")).toBe(true);
    expect(isTerminalStatus("failed")).toBe(true);
    expect(isTerminalStatus("deleted")).toBe(true);
  });
});

describe("STATUS_LABELS", () => {
  it("hat für jeden SourceStatus einen nicht leeren Text", () => {
    for (const status of ALLE_STATUS) {
      const label = STATUS_LABELS[status];
      expect(label, `Label für ${status}`).toBeTypeOf("string");
      expect(label.trim().length, `Label für ${status}`).toBeGreaterThan(0);
    }
  });

  it("enthält genau die bekannten Status und keine zusätzlichen Schlüssel", () => {
    expect(Object.keys(STATUS_LABELS).sort()).toEqual([...ALLE_STATUS].sort());
  });

  it("vergibt für jeden Status einen eigenen Text", () => {
    const texte = Object.values(STATUS_LABELS);
    expect(new Set(texte).size).toBe(texte.length);
  });
});

describe("PIPELINE_STEPS", () => {
  it("listet die Schritte in Anzeige-Reihenfolge und ohne doppelte Schlüssel", () => {
    expect(PIPELINE_STEPS.map((s) => s.key)).toEqual([
      "probe_and_extract",
      "transcribe_de",
      "diarize",
      "fuse_and_nlp",
      "detect_candidates",
    ]);
  });

  it("hat aufsteigende Phasen und überall Label und Beschreibung", () => {
    let letztePhase = 0;
    for (const step of PIPELINE_STEPS) {
      expect(step.phase, `Phase von ${step.key}`).toBeGreaterThanOrEqual(letztePhase);
      letztePhase = step.phase;
      expect(step.label.length, `Label von ${step.key}`).toBeGreaterThan(0);
      expect(step.description.length, `Beschreibung von ${step.key}`).toBeGreaterThan(0);
    }
  });

  it("führt den Render-Schritt getrennt von der Quellen-Pipeline", () => {
    expect(RENDER_STEP.key).toBe("render");
    expect(RENDER_STEP.phase).toBe(3);
    expect(PIPELINE_STEPS.map((s) => s.key)).not.toContain("render");
  });
});
