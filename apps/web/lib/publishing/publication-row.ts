import { PLATFORM_LABELS } from "@/lib/clips/labels";
import type { Platform } from "@/lib/repo/types";

/* Eine Zeile je Publikation in „Gepostet“ (Review R1-04): Plattform, Link, letzte Zahl mit Zeitpunkt und
 * der Status in Klartext. Rein und ohne Server-Abhängigkeit, damit die Oberfläche und der Test dieselbe
 * Regel benutzen. Zeiten erscheinen in Wiener Zeit, unabhängig von der Zeitzone des Geräts. */

export interface RowPublication {
  id: string;
  platform: string;
  status: string;
  external_url: string | null;
  published_at: string | null;
  created_at: string;
  tracking?: "oauth" | "link" | "off";
  tracking_until?: string | null;
  next_snapshot_at?: string | null;
  link_check?: Record<string, unknown> | null;
}

export interface RowSnapshot {
  fetched_at: string;
  views: number | null;
  likes: number | null;
  error: string | null;
}

export interface RowFeedback {
  publication_id: string | null;
  views: number | null;
  follows: number | null;
  fetched_at?: string | null;
}

export interface PublicationRow {
  id: string;
  platform: string;
  url: string | null;
  /* „1.234 Aufrufe“; null, solange es keine Zahl gibt */
  number: string | null;
  /* „Stand 21.11. 18:00“ zur Zahl, falls der Zeitpunkt bekannt ist */
  numberAt: string | null;
  status: string | null;
  tone: "normal" | "attention";
  /* „Nicht mehr messen“ anbieten (nur laufend verfolgte Links) */
  canStop: boolean;
  /* „Zahlen eintragen“ anbieten (nur ohne automatische Messung und ohne Zahl) */
  canEnterNumbers: boolean;
}

/* Eingetragene Links speichern die Plattform des Links (youtube, x …), alle anderen das Schnittformat */
const LINK_LABELS: Record<string, string> = { youtube: "YouTube", tiktok: "TikTok", instagram: "Instagram", x: "X", linkedin: "LinkedIn" };
const READER_PLATFORMS = new Set(["youtube", "x"]);

export function platformName(p: string): string {
  return PLATFORM_LABELS[p as Platform] ?? LINK_LABELS[p] ?? p;
}

const TZ = "Europe/Vienna";
const dayFmt = new Intl.DateTimeFormat("de-AT", { day: "2-digit", month: "2-digit", timeZone: TZ });
const timeFmt = new Intl.DateTimeFormat("de-AT", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: TZ });

/* „21.11.“ */
export function shortDay(iso: string): string {
  return `${dayFmt.format(new Date(iso)).replace(/\.$/, "")}.`;
}

/* „21.11. 18:00“ */
export function shortStamp(iso: string): string {
  return `${shortDay(iso)} ${timeFmt.format(new Date(iso))}`;
}

/* Tausenderpunkt wie „1.234“ (de-AT setzt ein schmales Leerzeichen) */
function count(n: number): string {
  return n.toLocaleString("de-DE");
}

export function publicationRow(p: RowPublication, snaps: { latest: RowSnapshot | null; last: RowSnapshot | null } | undefined, feedback: RowFeedback | undefined, now: number): PublicationRow {
  const label = platformName(p.platform);
  const latest = snaps?.latest ?? null;
  const last = snaps?.last ?? null;

  let number: string | null = null;
  let numberAt: string | null = null;
  if (latest && (latest.views != null || latest.likes != null)) {
    number = latest.views != null ? `${count(latest.views)} Aufrufe` : `${count(latest.likes as number)} Gefällt mir`;
    numberAt = `Stand ${shortStamp(latest.fetched_at)}`;
  } else if (feedback && feedback.views != null) {
    number = `${count(feedback.views)} Aufrufe` + (feedback.follows != null ? `, ${count(feedback.follows)} neue Folgende` : "");
    numberAt = feedback.fetched_at ? `Stand ${shortStamp(feedback.fetched_at)}` : null;
  }

  const tracking = p.tracking ?? "oauth";
  const stopped = (p.link_check?.stopped ?? null) as { reason?: string } | null;
  const until = p.tracking_until ? Date.parse(p.tracking_until) : NaN;
  const lastFailed = Boolean(last?.error) && (!latest || last!.fetched_at > latest.fetched_at);

  let status: string | null = null;
  let tone: PublicationRow["tone"] = "normal";
  if (tracking === "off") {
    status = "Wird nicht mehr gemessen";
  } else if (tracking === "link") {
    if (stopped?.reason === "nicht_gefunden") {
      status = "Wird nicht mehr gemessen: Beitrag nicht gefunden";
      tone = "attention";
    } else if (p.next_snapshot_at) {
      if (lastFailed) {
        status = "Letzte Messung fehlgeschlagen";
        tone = "attention";
      } else status = Number.isFinite(until) ? `Wird gemessen bis ${shortDay(p.tracking_until as string)}` : "Wird gemessen";
    } else if (Number.isFinite(until) && until <= now) {
      status = `Gemessen bis ${shortDay(p.tracking_until as string)}`;
    } else if (READER_PLATFORMS.has(p.platform)) {
      status = `Zahlen für ${label} sind noch nicht eingerichtet`;
    } else if (lastFailed) {
      status = "Letzte Messung fehlgeschlagen";
      tone = "attention";
    } else {
      status = `Wird nicht gemessen: ${label} braucht ein verbundenes Konto`;
    }
  } else if (p.status === "failed") {
    status = "Veröffentlichung fehlgeschlagen";
    tone = "attention";
  } else if (p.status === "scheduled" || p.status === "publishing") {
    status = "Eingeplant";
  }

  return {
    id: p.id,
    platform: label,
    url: p.external_url && /^https:\/\//.test(p.external_url) ? p.external_url : null,
    number,
    numberAt,
    status,
    tone,
    canStop: tracking === "link" && !stopped && Boolean(p.next_snapshot_at || (Number.isFinite(until) && until > now)),
    /* Von Hand nur, solange nichts automatisch misst: auch ein TikTok-Link ohne Verbindung bekommt so Zahlen */
    canEnterNumbers: number == null && (p.status === "manual" || p.status === "published") && !(tracking === "link" && p.next_snapshot_at),
  };
}
