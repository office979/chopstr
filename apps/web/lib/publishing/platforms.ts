import type { Platform } from "@/lib/repo/types";
import type { ConnectionPlatform, PublicationStatus } from "@/lib/repo/types-publishing";

/* Zuordnung Clip-Plattform ↔ Verbindungs-Plattform und deutsche Labels. Ohne Server-Abhängigkeiten. */

export function connectionPlatformFor(platform: Platform): ConnectionPlatform {
  if (platform === "reels") return "instagram";
  if (platform === "shorts") return "youtube";
  return platform;
}

export const CONNECTION_PLATFORM_LABELS: Record<ConnectionPlatform, string> = {
  manual: "Manuell",
  tiktok: "TikTok",
  instagram: "Instagram",
  youtube: "YouTube",
  linkedin: "LinkedIn",
};

export const PUBLICATION_STATUS_LABELS: Record<PublicationStatus, string> = {
  scheduled: "Eingeplant",
  publishing: "Wird veröffentlicht",
  published: "Veröffentlicht",
  failed: "Fehlgeschlagen",
  manual: "Manuell",
};

export const CONNECTION_STATUS_LABELS = { connected: "Verbunden", expired: "Abgelaufen", revoked: "Getrennt" } as const;
