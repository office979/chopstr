import { DEFAULT_CAPABILITIES } from "@/lib/publishing/capabilities";
import type { Provider } from "./types";

/* Manuelle Verbindung: immer verfügbar. Export herunterladen, selbst posten, Post-URL und Metriken von Hand eintragen.
 * Publikationen mit dieser Verbindung haben status = manual, der Worker ruft sie nie ab. */
export const manualProvider: Provider = {
  platform: "manual",
  label: "Manuell",
  configured: () => true,
  capabilities: () => ({ ...DEFAULT_CAPABILITIES.manual }),
  authorizeUrl() {
    throw new Error("Die manuelle Verbindung hat keinen OAuth-Flow.");
  },
  async exchangeCode() {
    throw new Error("Die manuelle Verbindung hat keinen OAuth-Flow.");
  },
  async refresh(creds) {
    return creds;
  },
  async publish() {
    return { status: "failed", external_id: null, external_url: null, error: "Manuelle Publikationen postest du selbst; trage danach die Post-URL ein." };
  },
  async fetchMetrics() {
    return {};
  },
};
