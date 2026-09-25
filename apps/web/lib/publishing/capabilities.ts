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

/* Welche Erfolgskennzahl diese Plattform überhaupt liefern kann.
 *
 * Der A/B-Test misst die Folgequote: wie viele Leute folgen dir nach diesem Clip. Das ist die
 * richtige Frage - und die Tabelle oben sagt, dass genau sie auf TikTok, Instagram und LinkedIn
 * gar nicht beantwortet wird (``follow_attribution: false``). Ein Test, der auf eine Zahl wartet,
 * die nie kommt, wartet für immer, und die Oberfläche versprach bis hierher trotzdem
 * „Folgequote".
 *
 * Fehlt eine Zahl, heisst das nicht null. Es heisst, dass diese Plattform sie nicht herausgibt.
 * Der Unterschied entscheidet darüber, ob ein Test „läuft noch" oder „lässt sich hier nicht
 * automatisch entscheiden".
 */
export type ErfolgKennzahl = "follows" | "saves" | "likes" | "keine";

export const ERFOLG_LABEL: Record<ErfolgKennzahl, string> = {
  follows: "Folgequote",
  saves: "Save-Quote",
  likes: "Like-Quote",
  keine: "keine vergleichbare Zahl",
};

export interface ErfolgWahl {
  kennzahl: ErfolgKennzahl;
  /* Liefert die Plattform sie sicher, oder nur unter Umständen? */
  sicher: boolean;
  /* Kann diese Plattform überhaupt Aufrufe melden? Ohne sie ist keine Quote zu bilden. */
  aufrufeMoeglich: boolean;
  satz: string;
}

function moeglich(v: CapabilityValue): boolean {
  return v === true || v === "conditional";
}

export function erfolgKennzahlFuer(caps: Capabilities, plattformName: string): ErfolgWahl {
  const aufrufeMoeglich = moeglich(caps.views);
  const kennzahl: ErfolgKennzahl = moeglich(caps.follow_attribution)
    ? "follows"
    : moeglich(caps.saves)
      ? "saves"
      : moeglich(caps.likes)
        ? "likes"
        : "keine";
  const sicher =
    kennzahl === "follows"
      ? caps.follow_attribution === true
      : kennzahl === "saves"
        ? caps.saves === true
        : kennzahl === "likes"
          ? caps.likes === true
          : false;

  if (!aufrufeMoeglich) {
    return {
      kennzahl,
      sicher: false,
      aufrufeMoeglich,
      satz: `${plattformName} meldet keine Aufrufe. Ohne sie lässt sich keine Quote bilden; trag die Zahlen von Hand ein, dann rechnet chopstr damit.`,
    };
  }
  if (kennzahl === "keine") {
    return { kennzahl, sicher: false, aufrufeMoeglich, satz: `${plattformName} gibt keine Zahl heraus, mit der sich zwei Fassungen vergleichen lassen.` };
  }
  if (kennzahl === "follows") {
    return {
      kennzahl,
      sicher,
      aufrufeMoeglich,
      satz: sicher
        ? `Gewertet wird die Folgequote: neue Folgende je 1.000 Aufrufe.`
        : `Gewertet wird die Folgequote, sofern ${plattformName} sie im Einzelfall herausgibt.`,
    };
  }
  return {
    kennzahl,
    sicher,
    aufrufeMoeglich,
    satz: `${plattformName} ordnet neue Folgende keinem einzelnen Beitrag zu. Gewertet wird deshalb die ${ERFOLG_LABEL[kennzahl]}.`,
  };
}
