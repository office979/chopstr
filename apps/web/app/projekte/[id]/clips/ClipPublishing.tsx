"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Field, Input, Select, Textarea, Checkbox } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { cn } from "@/components/ui/cn";
import type { Clip, HookVersion } from "@/lib/repo/types";
import type { ClipExtras, MetricSet, PerformanceFeedback, PlatformConnection, Publication, ReframeOverride, Series } from "@/lib/repo/types-publishing";
import type { GateReason } from "@/lib/publishing/gates";
import type { VariationResult } from "@/lib/series/variation";
import { CONNECTION_PLATFORM_LABELS, PUBLICATION_STATUS_LABELS, connectionPlatformFor } from "@/lib/publishing/platforms";
import { PLATFORM_LABELS } from "@/lib/clips/labels";
import { formatDateTime } from "@/lib/format";

export interface ClipPublishingProps {
  sourceId: string;
  clip: Clip;
  extras: ClipExtras;
  gates: GateReason[];
  connections: PlatformConnection[];
  series: Series[];
  initialPublications: Publication[];
  initialFeedback: PerformanceFeedback[];
  canPublish: boolean;
  canSeries: boolean;
  canRender: boolean;
  onExtras?: (extras: ClipExtras) => void;
  onRerender?: () => void;
}

interface ApiError {
  error?: string;
}

const REFRAME_OPTIONS: { value: "" | ReframeOverride; label: string }[] = [
  { value: "", label: "Automatisch" },
  { value: "talking_head", label: "Talking Head" },
  { value: "two_speakers", label: "Zwei Sprecher" },
  { value: "neutral", label: "Neutral" },
  { value: "slide_pip", label: "Folie + Sprecher" },
];

const STRATEGY_LABELS: Record<string, string> = { talking_head: "ein Sprecher", two_speakers: "zwei Sprecher", neutral: "neutraler Crop", slide_pip: "Folie mit Sprecher im Bild" };

function metricValue(v: number | null | undefined, digits = 0): string {
  return v == null ? "nicht verfügbar" : v.toLocaleString("de-AT", { maximumFractionDigits: digits });
}

function toLocalInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/* Metriken je Fenster: publications.metrics (at_6h ...) zuerst, sonst performance_feedback-Zeilen */
function windowsFor(p: Publication, feedback: PerformanceFeedback[]): { window: string; metrics: Partial<MetricSet> | null }[] {
  const rows = feedback.filter((f) => f.publication_id === p.id);
  const out: { window: string; metrics: Partial<MetricSet> | null }[] = [];
  for (const [key, w] of [
    ["at_6h", "6h"],
    ["at_48h", "48h"],
    ["at_7d", "7d"],
  ] as const) {
    const fromPub = p.metrics?.[key] ?? null;
    const fromFb = rows.find((f) => f.metric_window === w);
    out.push({ window: w, metrics: fromPub ?? (fromFb ? { views: fromFb.views, likes: fromFb.likes, comments: fromFb.comments, shares: fromFb.shares, saves: fromFb.saves, follows: fromFb.follows, avg_watch_time_s: fromFb.avg_watch_time_s } : null) });
  }
  const manual = rows.find((f) => f.metric_window === "manual");
  if (manual) out.push({ window: "manuell", metrics: { views: manual.views, likes: manual.likes, comments: manual.comments, shares: manual.shares, saves: manual.saves, follows: manual.follows, avg_watch_time_s: manual.avg_watch_time_s } });
  return out;
}

/* Veröffentlichen, Publikationen, Serie zuordnen und Bildausschnitt je Clip-Karte (Phase 5b und 5c) */
export function ClipPublishing({ sourceId, clip, extras, gates, connections, series, initialPublications, initialFeedback, canPublish, canSeries, canRender, onExtras, onRerender }: ClipPublishingProps) {
  const [publications, setPublications] = useState(initialPublications);
  const [feedback, setFeedback] = useState(initialFeedback);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string; href?: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  /* Veröffentlichen-Dialog */
  const [open, setOpen] = useState(false);
  /* Kein gateNotice-Schalter mehr: Die Liste der offenen Punkte steht dauerhaft da, sobald es welche gibt. */
  const [connectionId, setConnectionId] = useState("");
  const [title, setTitle] = useState(clip.title_card ?? "");
  const [caption, setCaption] = useState("");
  const [when, setWhen] = useState<"now" | "later">("now");
  const [scheduledFor, setScheduledFor] = useState(() => toLocalInput(new Date(Date.now() + 3_600_000).toISOString()));
  const [externalUrl, setExternalUrl] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [hookLoaded, setHookLoaded] = useState(false);
  const ids = { conn: useId(), title: useId(), caption: useId(), when: useId(), url: useId(), series: useId(), reframe: useId() };

  /* Serie */
  const [seriesId, setSeriesId] = useState(extras.series_id ?? "");
  const [warning, setWarning] = useState<VariationResult | null>(null);

  /* Reframe */
  const [reframe, setReframe] = useState<"" | ReframeOverride>(extras.reframe_override ?? "");

  /* Manuelle Metriken */
  const [metricsFor, setMetricsFor] = useState<Publication | null>(null);
  const [metricInput, setMetricInput] = useState<Record<string, string>>({});
  const [manualUrl, setManualUrl] = useState("");
  const [rescheduleFor, setRescheduleFor] = useState<Publication | null>(null);
  const [rescheduleAt, setRescheduleAt] = useState("");

  const eligible = connections.filter((c) => c.status === "connected" && (c.platform === "manual" || c.platform === connectionPlatformFor(clip.platform)));
  const effectiveConnectionId = connectionId || eligible[0]?.id || "";
  const chosen = eligible.find((c) => c.id === effectiveConnectionId) ?? null;
  const isManual = chosen?.platform === "manual";

  const openDialog = async () => {
    if (gates.length) return;
    setOpen(true);
    setConfirm(false);
    if (hookLoaded) return;
    try {
      const res = await fetch(`/api/projects/${sourceId}/clips/${clip.id}`);
      const data = (await res.json()) as ApiError & { hook?: HookVersion | null };
      if (res.ok && data.hook) {
        setCaption((cur) => cur || data.hook?.post_captions?.[clip.platform] || "");
        if (!title && data.hook.onscreen_hook) setTitle(data.hook.onscreen_hook);
      }
    } catch {
      /* Caption bleibt leer */
    } finally {
      setHookLoaded(true);
    }
  };

  const reload = async () => {
    try {
      const res = await fetch(`/api/projects/${sourceId}/clips/${clip.id}/publish`);
      const data = (await res.json()) as ApiError & { publications?: Publication[]; feedback?: PerformanceFeedback[] };
      if (res.ok) {
        setPublications(data.publications ?? []);
        setFeedback(data.feedback ?? []);
      }
    } catch {
      /* Liste bleibt */
    }
  };

  const publish = async () => {
    setBusy("publish");
    setMessage(null);
    try {
      const body = {
        connection_id: effectiveConnectionId,
        title,
        caption,
        scheduled_for: !isManual && when === "later" ? new Date(scheduledFor).toISOString() : null,
        external_url: isManual ? externalUrl : null,
        confirm,
      };
      const res = await fetch(`/api/projects/${sourceId}/clips/${clip.id}/publish`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const data = (await res.json()) as ApiError & { publication?: Publication; message?: string };
      if (!res.ok || !data.publication) throw new Error(data.error ?? "Veröffentlichen fehlgeschlagen");
      setPublications((prev) => [data.publication!, ...prev]);
      setOpen(false);
      setConfirm(false);
      setMessage({ tone: "ok", text: data.message ?? "Publikation angelegt." });
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : "Veröffentlichen fehlgeschlagen" });
    } finally {
      setBusy(null);
    }
  };

  const patchPublication = async (p: Publication, body: Record<string, unknown>, ok: string) => {
      setBusy(p.id);
      setMessage(null);
      try {
        const res = await fetch(`/api/publishing/publications/${p.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        const data = (await res.json()) as ApiError & { publication?: Publication };
        if (!res.ok || !data.publication) throw new Error(data.error ?? "Aktion fehlgeschlagen");
        setPublications((prev) => prev.map((x) => (x.id === p.id ? data.publication! : x)));
        setMessage({ tone: "ok", text: ok });
        setRescheduleFor(null);
      } catch (err) {
        setMessage({ tone: "error", text: err instanceof Error ? err.message : "Aktion fehlgeschlagen" });
      } finally {
        setBusy(null);
      }
  };

  const saveMetrics = async () => {
    if (!metricsFor) return;
    setBusy(metricsFor.id);
    setMessage(null);
    try {
      const res = await fetch(`/api/publishing/publications/${metricsFor.id}/metrics`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(metricInput) });
      const data = (await res.json()) as ApiError & { feedback?: PerformanceFeedback };
      if (!res.ok || !data.feedback) throw new Error(data.error ?? "Metriken konnten nicht gespeichert werden");
      setFeedback((prev) => [data.feedback!, ...prev.filter((f) => f.id !== data.feedback!.id)]);
      setMetricsFor(null);
      setMetricInput({});
      setMessage({ tone: "ok", text: "Metriken gespeichert (manuell)." });
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : "Metriken konnten nicht gespeichert werden" });
    } finally {
      setBusy(null);
    }
  };

  const assignSeries = async (targetId: string, force: boolean) => {
      setBusy("series");
      setMessage(null);
      try {
        if (!targetId) {
          if (!extras.series_id) return;
          const res = await fetch(`/api/series/${extras.series_id}/assign`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ clip_id: clip.id, remove: true }) });
          const data = (await res.json()) as ApiError & { extras?: ClipExtras };
          if (!res.ok || !data.extras) throw new Error(data.error ?? "Zuordnung konnte nicht gelöst werden");
          onExtras?.(data.extras);
          setMessage({ tone: "ok", text: "Serien-Zuordnung gelöst." });
          return;
        }
        const res = await fetch(`/api/series/${targetId}/assign`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ clip_id: clip.id, confirm: force }) });
        const data = (await res.json()) as ApiError & { ok?: boolean; warning?: VariationResult; extras?: ClipExtras; series?: Series };
        if (!res.ok) throw new Error(data.error ?? "Zuordnung fehlgeschlagen");
        if (!data.ok && data.warning) {
          setWarning(data.warning);
          return;
        }
        if (data.extras) onExtras?.(data.extras);
        setWarning(null);
        setMessage({ tone: "ok", text: `Serie „${data.series?.name ?? ""}“ zugeordnet.`, href: `/serien/${targetId}` });
      } catch (err) {
        setMessage({ tone: "error", text: err instanceof Error ? err.message : "Zuordnung fehlgeschlagen" });
        setSeriesId(extras.series_id ?? "");
      } finally {
        setBusy(null);
      }
  };

  const saveReframe = async (value: "" | ReframeOverride) => {
      setReframe(value);
      setBusy("reframe");
      setMessage(null);
      try {
        const res = await fetch(`/api/projects/${sourceId}/clips/${clip.id}/reframe`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reframe_override: value || null }) });
        const data = (await res.json()) as ApiError & { extras?: ClipExtras; needs_render?: boolean };
        if (!res.ok || !data.extras) throw new Error(data.error ?? "Bildausschnitt konnte nicht gespeichert werden");
        onExtras?.(data.extras);
        setMessage({ tone: "ok", text: data.needs_render ? "Bildausschnitt gespeichert. Klick auf „Änderungen übernehmen“, damit das Video neu gebaut wird." : "Bildausschnitt gespeichert. Wirkt, sobald das Video das nächste Mal gebaut wird." });
      } catch (err) {
        setMessage({ tone: "error", text: err instanceof Error ? err.message : "Bildausschnitt konnte nicht gespeichert werden" });
        setReframe(extras.reframe_override ?? "");
      } finally {
        setBusy(null);
      }
  };

  const plan = clip.render_plan as (NonNullable<Clip["render_plan"]> & { slide_region?: { confidence?: number } | null }) | null;
  const strategy = plan?.reframe.strategy ? STRATEGY_LABELS[plan.reframe.strategy] ?? plan.reframe.strategy : null;
  const slideConfidence = plan?.slide_region?.confidence;

  return (
    <div className="flex flex-col gap-3 border-t border-line pt-3">
      {/* Veröffentlichen */}
      <Modal open={open} onClose={() => busy !== "publish" && setOpen(false)} title="Veröffentlichen" description={`${PLATFORM_LABELS[clip.platform]} ${clip.aspect}. Die Publikation entsteht erst nach deiner Bestätigung.`}>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            void publish();
          }}
        >
          <Field label="Verbindung" htmlFor={ids.conn} required hint={eligible.length === 0 ? "Keine passende Verbindung. Lege unter Einstellungen eine an." : undefined}>
            <Select id={ids.conn} value={effectiveConnectionId} onChange={(e) => setConnectionId(e.target.value)} required disabled={eligible.length === 0}>
              {eligible.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.account_label} ({CONNECTION_PLATFORM_LABELS[c.platform]})
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Titel" htmlFor={ids.title}>
            <Input id={ids.title} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} />
          </Field>
          <Field label="Caption" htmlFor={ids.caption} hint={hookLoaded ? "Vorbelegt aus der Post-Caption der Hook-Version." : "Post-Caption wird geladen."}>
            <Textarea id={ids.caption} value={caption} onChange={(e) => setCaption(e.target.value)} maxLength={3000} className="min-h-28" />
          </Field>
          {isManual ? (
            <Field label="Post-URL" htmlFor={ids.url} hint="Optional jetzt, sonst nach dem Posten eintragen.">
              <Input id={ids.url} type="url" value={externalUrl} onChange={(e) => setExternalUrl(e.target.value)} placeholder="https://" />
            </Field>
          ) : (
            <div className="flex flex-col gap-2">
              <span className="text-sm font-medium">Zeitpunkt</span>
              <div className="flex flex-wrap gap-3 text-sm">
                <label className="flex items-center gap-2">
                  <input type="radio" name={ids.when} checked={when === "now"} onChange={() => setWhen("now")} /> Jetzt
                </label>
                <label className="flex items-center gap-2">
                  <input type="radio" name={ids.when} checked={when === "later"} onChange={() => setWhen("later")} /> Geplant
                </label>
              </div>
              {when === "later" && <Input type="datetime-local" value={scheduledFor} onChange={(e) => setScheduledFor(e.target.value)} aria-label="Geplanter Zeitpunkt" />}
            </div>
          )}
          <label className="flex items-start gap-3 rounded-inner border border-line-strong p-3 text-sm">
            <Checkbox checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
            <span>
              {isManual ? "Ich poste den Export selbst und trage Post-URL und Metriken von Hand ein." : `Ja, diesen Clip über ${chosen?.account_label ?? "die Verbindung"} veröffentlichen${when === "later" ? " (geplant)" : ""}.`}
            </span>
          </label>
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={busy === "publish"}>
              Abbrechen
            </Button>
            <Button type="submit" disabled={busy === "publish" || !confirm || !effectiveConnectionId}>
              {busy === "publish" ? "Wird angelegt" : isManual ? "Manuell anlegen" : when === "later" ? "Einplanen" : "Veröffentlichen"}
            </Button>
          </div>
        </form>
      </Modal>

      {/* Variations-Warnung */}
      <Modal open={warning != null} onClose={() => setWarning(null)} title="Zu ähnlich, Variante ziehen" description={warning?.message ?? undefined}>
        <ul className="mb-4 flex flex-col gap-1 text-sm text-text-2">
          {warning?.hits.map((h) => (
            <li key={h.clip_id}>
              Clip {h.clip_id.slice(0, 8)}: {h.matches.length} gleiche Merkmale
            </li>
          ))}
        </ul>
        <div className="flex flex-wrap justify-end gap-2">
          <Button
            variant="ghost"
            onClick={() => {
              setWarning(null);
              setSeriesId(extras.series_id ?? "");
            }}
          >
            Nicht zuordnen
          </Button>
          <Button onClick={() => assignSeries(seriesId, true)} disabled={busy === "series"}>
            Trotzdem zuordnen
          </Button>
        </div>
      </Modal>

      {/* Manuelle Metriken */}
      <Modal open={metricsFor != null} onClose={() => setMetricsFor(null)} title="Metriken eintragen" description="Werte aus der Plattform-Statistik. Leer lassen, was die Plattform nicht liefert.">
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            void saveMetrics();
          }}
        >
          <div className="grid grid-cols-2 gap-3">
            {(
              [
                ["views", "Views"],
                ["likes", "Likes"],
                ["comments", "Kommentare"],
                ["shares", "Shares"],
                ["saves", "Saves"],
                ["follows", "Neue Follower"],
                ["avg_watch_time_s", "Sehdauer (s)"],
              ] as const
            ).map(([key, label]) => (
              <label key={key} className="flex flex-col gap-1 text-sm">
                <span className="text-text-2">{label}</span>
                <Input inputMode="decimal" value={metricInput[key] ?? ""} onChange={(e) => setMetricInput((cur) => ({ ...cur, [key]: e.target.value }))} />
              </label>
            ))}
          </div>
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="ghost" onClick={() => setMetricsFor(null)}>
              Abbrechen
            </Button>
            <Button type="submit" disabled={busy != null}>
              Speichern
            </Button>
          </div>
        </form>
      </Modal>

      {/* Umplanen */}
      <Modal open={rescheduleFor != null} onClose={() => setRescheduleFor(null)} title="Umplanen" description="Neuer Zeitpunkt für die eingeplante Publikation.">
        <div className="flex flex-col gap-4">
          <Input type="datetime-local" value={rescheduleAt} onChange={(e) => setRescheduleAt(e.target.value)} aria-label="Neuer Zeitpunkt" />
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="ghost" onClick={() => setRescheduleFor(null)}>
              Abbrechen
            </Button>
            <Button onClick={() => rescheduleFor && patchPublication(rescheduleFor, { action: "reschedule", scheduled_for: new Date(rescheduleAt).toISOString() }, "Publikation umgeplant.")} disabled={busy != null || !rescheduleAt}>
              Umplanen
            </Button>
          </div>
        </div>
      </Modal>

      {message && (
        <p role="status" aria-live="polite" className={cn("text-xs", message.tone === "ok" ? "text-text" : "text-attention")}>
          {message.text}
          {message.href && (
            <>
              {" "}
              <Link href={message.href} className="underline-offset-4 hover:underline">
                Öffnen
              </Link>
            </>
          )}
        </p>
      )}

      {/* Bildausschnitt (5c) */}
      {canRender && (
        <div className="flex flex-col gap-1">
          <label htmlFor={ids.reframe} className="text-xs text-text-2">
            Bildausschnitt
          </label>
          <Select id={ids.reframe} value={reframe} onChange={(e) => saveReframe(e.target.value as "" | ReframeOverride)} disabled={busy === "reframe"} className="py-2 text-sm">
            {REFRAME_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </Select>
          {plan && (
            <p className="font-mono text-[11px] text-text-3">
              Erkannt: {strategy}
              {slideConfidence != null ? `, Folie ${Math.round(slideConfidence * 100)} %` : ""}
              {extras.reframe_override ? ` · überschrieben (${REFRAME_OPTIONS.find((o) => o.value === extras.reframe_override)?.label})` : ""}
            </p>
          )}
          {extras.reframe_override && onRerender && clip.status !== "rendering" && (
            <button type="button" onClick={onRerender} className="self-start text-xs text-text-2 underline-offset-4 hover:text-text hover:underline">
              Video mit diesem Bildausschnitt neu bauen
            </button>
          )}
        </div>
      )}

      {/* Serie */}
      {canSeries && (
        <div className="flex flex-col gap-1">
          <label htmlFor={ids.series} className="text-xs text-text-2">
            Serie zuordnen
          </label>
          <Select
            id={ids.series}
            value={seriesId}
            onChange={(e) => {
              setSeriesId(e.target.value);
              void assignSeries(e.target.value, false);
            }}
            disabled={busy === "series" || series.length === 0}
            className="py-2 text-sm"
          >
            <option value="">{series.length === 0 ? "Noch keine Serie angelegt" : "Keine Serie"}</option>
            {series.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </Select>
          {extras.series_id && (
            <Link href={`/serien/${extras.series_id}`} className="self-start text-[11px] text-text-3 underline-offset-4 hover:text-text hover:underline">
              Slot {extras.series_index ?? "?"} · Kalender öffnen
            </Link>
          )}
        </div>
      )}

      {/* Veröffentlichen */}
      {canPublish && (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <Button size="sm" onClick={openDialog} disabled={busy === "publish"}>
              Posten
            </Button>
          </div>
          {/* Kein Zähler-Badge mehr (docs/BEDIENKONZEPT.md, Abschnitt 5.7): Der Nutzer muss sehen,
              WAS fehlt und wohin er klickt, nicht WIE VIELE Bedingungen offen sind. */}
          {gates.length > 0 && (
            <div className="flex flex-col gap-1 rounded-[12px] border border-attention/50 bg-attention/10 px-3 py-2 text-xs text-text">
              <p className="font-medium text-attention">Noch nicht bereit zum Posten:</p>
              <ul className="flex flex-col gap-1" aria-label="Was noch fehlt">
                {gates.map((g) => (
                  <li key={g.code}>
                    {g.message}
                    {g.href && (
                      <>
                        {" "}
                        <Link href={g.href} className="font-medium underline-offset-4 hover:underline">
                          {g.code === "plan" ? "Zur Abrechnung" : g.code === "dpa" ? "Vertrag annehmen" : "Erledigen"}
                        </Link>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Publikationen */}
      {publications.length > 0 && (
        <ul className="flex flex-col gap-2" aria-label="Publikationen">
          {publications.map((p) => {
            const conn = connections.find((c) => c.id === p.connection_id);
            const windows = windowsFor(p, feedback);
            const hasAny = windows.some((w) => w.metrics != null);
            return (
              <li key={p.id} className="rounded-[12px] border border-line p-3 text-xs">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="flex flex-wrap items-center gap-1.5">
                    <Badge tone={p.status === "published" ? "ok" : p.status === "failed" ? "attention" : p.status === "manual" ? "neutral" : "ai"} className="h-6 px-2.5 text-[11px]">
                      {PUBLICATION_STATUS_LABELS[p.status]}
                    </Badge>
                    <span className="text-text-2">{conn ? `${conn.account_label} (${CONNECTION_PLATFORM_LABELS[conn.platform]})` : "Verbindung entfernt"}</span>
                  </span>
                  <span className="font-mono text-text-3">
                    {p.status === "scheduled" && p.scheduled_for ? `geplant ${formatDateTime(p.scheduled_for)}` : p.published_at ? formatDateTime(p.published_at) : formatDateTime(p.created_at)}
                  </span>
                </div>
                {p.external_url && (
                  <a href={p.external_url} target="_blank" rel="noreferrer" className="mt-1 block truncate text-text underline-offset-4 hover:underline">
                    {p.external_url}
                  </a>
                )}
                {p.error && <p className="mt-1 text-attention">{p.error}</p>}
                <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 font-mono text-[11px]">
                  {windows.map((w) => (
                    <div key={w.window} className="contents">
                      <dt className="text-text-3">{w.window}</dt>
                      <dd className={w.metrics ? "text-text" : "text-text-3"}>
                        {w.metrics
                          ? `${metricValue(w.metrics.views)} Views · ${metricValue(w.metrics.follows)} Folgen · ${metricValue(w.metrics.saves)} Saves · ${metricValue(w.metrics.likes)} Likes`
                          : p.status === "manual"
                            ? "von Hand eintragen"
                            : "nicht verfügbar"}
                      </dd>
                    </div>
                  ))}
                </dl>
                {!hasAny && p.status === "published" && <p className="mt-1 text-text-3">Metriken folgen 6 h, 48 h und 7 Tage nach der Veröffentlichung.</p>}
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {p.status === "scheduled" && (
                    <>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 px-3 text-xs"
                        onClick={() => {
                          setRescheduleFor(p);
                          setRescheduleAt(toLocalInput(p.scheduled_for ?? new Date().toISOString()));
                        }}
                        disabled={busy === p.id}
                      >
                        Umplanen
                      </Button>
                      <Button size="sm" variant="danger" className="h-7 px-3 text-xs" onClick={() => window.confirm("Eingeplante Publikation abbrechen?") && patchPublication(p, { action: "cancel" }, "Publikation abgebrochen.")} disabled={busy === p.id}>
                        Abbrechen
                      </Button>
                    </>
                  )}
                  {p.status === "manual" && (
                    <>
                      {!p.external_url && (
                        <form
                          className="flex flex-wrap items-center gap-1.5"
                          onSubmit={(e) => {
                            e.preventDefault();
                            void patchPublication(p, { action: "manual_url", external_url: manualUrl }, "Post-URL gespeichert.");
                          }}
                        >
                          <Input type="url" value={manualUrl} onChange={(e) => setManualUrl(e.target.value)} placeholder="https://" className="h-7 w-52 px-3 py-1 text-xs" aria-label="Post-URL" required />
                          <Button type="submit" size="sm" variant="ghost" className="h-7 px-3 text-xs" disabled={busy === p.id}>
                            Post-URL speichern
                          </Button>
                        </form>
                      )}
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 px-3 text-xs"
                        onClick={() => {
                          setMetricsFor(p);
                          setMetricInput({});
                        }}
                      >
                        Metriken eintragen
                      </Button>
                    </>
                  )}
                  {p.status === "published" && (
                    <Button size="sm" variant="ghost" className="h-7 px-3 text-xs" onClick={reload}>
                      Aktualisieren
                    </Button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
