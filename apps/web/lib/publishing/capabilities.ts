import type { Capabilities, CapabilityKey, CapabilityValue, ConnectionPlatform, MetricSet } from "@/lib/repo/types-publishing";

/* Capability Flags je Provider (Master 8.2): was ein Connector garantiert liefert. Metriken werden nur so weit
 * übernommen, wie der Connector sie garantiert: `true` immer, `conditional` nur wenn der Abruf einen Wert liefert,
 * `false` und `unknown` bleiben null. Die Werte sind gegen die aktuelle Plattform-Dokumentation zu prüfen (CON-007).
 * Ohne Server-Abhängigkeiten, auch im Client nutzbar. */

export const CAPABILITY_KEYS: CapabilityKey[] = [
  "views",
  "likes",
  "comments",
  "shares",
  "saves",
  "avg_watch_time",
  "retention_curve",
  "follow_attribution",
  "publish",
  "schedule",
];

export const CAPABILITY_LABELS: Record<CapabilityKey, string> = {
  views: "Views",
  likes: "Likes",
  comments: "Kommentare",
  shares: "Shares",
  saves: "Saves",
  avg_watch_time: "Mittlere Sehdauer",
  retention_curve: "Retention-Kurve",
  follow_attribution: "Folge-Attribution",
  publish: "Veröffentlichen",
  schedule: "Zeitplanung",
};

export const CAPABILITY_VALUE_LABELS: Record<string, string> = {
  true: "ja",
  false: "nein",
  conditional: "bedingt",
  unknown: "unbekannt",
};

export function capabilityLabel(v: CapabilityValue): string {
  return CAPABILITY_VALUE_LABELS[String(v)] ?? "unbekannt";
}

/* Standard-Flags je Plattform. TODO verify against current docs (CON-007). */
export const DEFAULT_CAPABILITIES: Record<ConnectionPlatform, Capabilities> = {
  tiktok: {
    views: true,
    likes: true,
    comments: true,
    shares: true,
    saves: "unknown",
    avg_watch_time: "conditional",
    retention_curve: false,
    follow_attribution: false,
    publish: true,
    schedule: true,
  },
  instagram: {
    views: true,
    likes: true,
    comments: true,
    shares: true,
    saves: true,
    avg_watch_time: "conditional",
    retention_curve: false,
    follow_attribution: false,
    publish: true,
    schedule: true,
  },
  youtube: {
    views: true,
    likes: true,
    comments: true,
    shares: "conditional",
    saves: false,
    avg_watch_time: "conditional",
    retention_curve: "conditional",
    follow_attribution: "conditional",
    publish: true,
    schedule: true,
  },
  linkedin: {
    views: "conditional",
    likes: true,
    comments: true,
    shares: true,
    saves: false,
    avg_watch_time: false,
    retention_curve: false,
    follow_attribution: false,
    publish: true,
    schedule: true,
  },
  manual: {
    views: "conditional",
    likes: "conditional",
    comments: "conditional",
    shares: "conditional",
    saves: "conditional",
    avg_watch_time: "conditional",
    retention_curve: false,
    follow_attribution: "conditional",
    publish: false,
    schedule: false,
  },
};

export function isCapabilityValue(v: unknown): v is CapabilityValue {
  return v === true || v === false || v === "conditional" || v === "unknown";
}

export function normalizeCapabilities(raw: unknown, platform: ConnectionPlatform): Capabilities {
  const base = { ...DEFAULT_CAPABILITIES[platform] };
  if (raw && typeof raw === "object") {
    for (const k of CAPABILITY_KEYS) {
      const v = (raw as Record<string, unknown>)[k];
      if (isCapabilityValue(v)) base[k] = v;
    }
  }
  return base;
}

const METRIC_TO_CAPABILITY: Record<keyof MetricSet, CapabilityKey> = {
  views: "views",
  likes: "likes",
  comments: "comments",
  shares: "shares",
  saves: "saves",
  follows: "follow_attribution",
  avg_watch_time_s: "avg_watch_time",
  retention_curve: "retention_curve",
};

export const EMPTY_METRICS: MetricSet = {
  views: null,
  likes: null,
  comments: null,
  shares: null,
  saves: null,
  follows: null,
  avg_watch_time_s: null,
  retention_curve: null,
};

/* Nur garantierte Felder durchlassen (Capability Flags); alles andere null */
export function maskMetrics(raw: Partial<MetricSet> | null | undefined, caps: Capabilities): MetricSet {
  const out: MetricSet = { ...EMPTY_METRICS };
  if (!raw) return out;
  for (const key of Object.keys(METRIC_TO_CAPABILITY) as (keyof MetricSet)[]) {
    const flag = caps[METRIC_TO_CAPABILITY[key]];
    const value = raw[key];
    if (value == null) continue;
    if (flag === true || flag === "conditional") {
      (out as unknown as Record<string, unknown>)[key] = value;
    }
  }
  return out;
}
