"use client";

import { useId, useRef, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Field";
import { cn } from "@/components/ui/cn";
import type { Aspect, GuestDecision as Decision, Platform } from "@/lib/repo/types";
import { PLATFORM_LABELS, formatClipDuration } from "@/lib/clips/labels";
import { DECISION_LABELS } from "@/lib/guest/approval";
import { formatDate, formatDateTime } from "@/lib/format";

export interface GuestView {
  guest_name: string | null;
  message: string | null;
  decision: Decision | null;
  comment: string | null;
  decided_at: string | null;
  expires_at: string | null;
  expired: boolean;
  workspace_name: string;
  source_title: string;
  platform: Platform;
  aspect: Aspect;
  title_card: string | null;
  duration_s: number | null;
  video_url: string | null;
  poster_url: string | null;
  onscreen_hook: string | null;
  spoken_hook: string | null;
  post_caption: string | null;
}

interface ApiResponse {
  error?: string;
  code?: string;
  approval?: { decision: Decision | null; comment: string | null; decided_at: string | null };
}

/* Drei Entscheidungen: Freigeben, Fehlerhaft (Kommentar Pflicht), Ablehnen (Kommentar Pflicht).
 *
 * „Fehlerhaft" hiess hier „Änderungen wünschen". Im Team steht an der Karte aber „Fehlerhaft" -
 * zwei Wörter für dieselbe Antwort, und wer beide Seiten sieht, hält sie für zwei Dinge. Der Wert
 * in der Datenbank bleibt ``changes``: er ist seit der ersten Fassung so und sagt dasselbe.
 *
 * Ein Wunsch hängt fast immer an einer Stelle: „das Ende passt nicht", „hier fehlt ein Schnitt".
 * Bis hierher ging nur der Satz mit, nicht die Stelle - und wer ihn las, suchte sie von Hand.
 * Deshalb wird beim Schreiben die Stelle mitgenommen, an der das Video gerade steht. Der Gast
 * muss dafür nichts tun ausser anhalten. */
export function GuestDecision({ token, view }: { token: string; view: GuestView }) {
  const [mode, setMode] = useState<Exclude<Decision, "approved"> | null>(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<{ decision: Decision; comment: string | null; decided_at: string | null } | null>(
    view.decision ? { decision: view.decision, comment: view.comment, decided_at: view.decided_at } : null,
  );
  const commentId = useId();
  /* Die Stelle, an der das Video steht, während der Wunsch geschrieben wird. */
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [stelle, setStelle] = useState<number | null>(null);
  const [stelleMitschicken, setStelleMitschicken] = useState(true);

  const send = async (decision: Decision) => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/freigabe/${token}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          decision,
          comment: decision === "approved" ? "" : comment,
          comment_at_s: decision === "changes" && stelleMitschicken ? stelle : null,
        }),
      });
      const data = (await res.json()) as ApiResponse;
      if (!res.ok) throw new Error(data.error ?? "Entscheidung konnte nicht gespeichert werden");
      setDone({ decision, comment: decision === "approved" ? null : comment, decided_at: data.approval?.decided_at ?? new Date().toISOString() });
      setMode(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Entscheidung konnte nicht gespeichert werden");
    } finally {
      setBusy(false);
    }
  };

  const portrait = view.aspect === "9:16" || view.aspect === "4:5";

  return (
    <div className="grid gap-5 md:grid-cols-[minmax(0,320px)_minmax(0,1fr)] md:items-start">
      <GlassCard padding="sm" className="flex flex-col gap-3">
        <div
          className="relative mx-auto w-full overflow-hidden rounded-inner border border-line bg-black"
          style={{ aspectRatio: view.aspect.replace(":", " / "), maxWidth: portrait ? 300 : undefined }}
        >
          {view.video_url ? (
            <video
              ref={videoRef}
              src={view.video_url}
              poster={view.poster_url ?? undefined}
              controls
              playsInline
              preload="metadata"
              onTimeUpdate={(e) => setStelle(Math.round(e.currentTarget.currentTime * 10) / 10)}
              className="h-full w-full object-contain"
            />
          ) : view.poster_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={view.poster_url} alt={`Poster ${PLATFORM_LABELS[view.platform]}`} className="h-full w-full object-cover" />
          ) : (
            <div
              aria-hidden="true"
              className="flex h-full w-full flex-col items-center justify-center gap-2 p-4 text-center"
              style={{ background: "radial-gradient(ellipse at 50% 30%, rgba(91,140,255,0.22) 0%, rgba(27,26,98,0.3) 40%, rgba(0,0,0,0) 75%), #0a0a13" }}
            >
              <span className="text-sm text-text-2">Video folgt nach dem Render</span>
              {view.onscreen_hook && <span className="rounded-[8px] bg-white px-3 py-2 text-sm font-semibold text-black">{view.onscreen_hook}</span>}
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 px-1 text-xs text-text-2">
          <span className="flex gap-1.5">
            <Badge className="h-6 px-2.5 text-[11px]">{PLATFORM_LABELS[view.platform]}</Badge>
            <Badge className="h-6 px-2 font-mono text-[11px]">{view.aspect}</Badge>
          </span>
          <span className="font-mono tabular-nums">{formatClipDuration(view.duration_s)}</span>
        </div>
      </GlassCard>

      <div className="flex flex-col gap-5">
        <GlassCard padding="lg" className="flex flex-col gap-5">
          <div>
            <p className="text-sm text-text-2">{view.workspace_name} bittet um deine Freigabe</p>
            <h1 className="mt-1 text-2xl font-semibold tracking-[var(--tracking-display)] sm:text-3xl">{view.title_card ?? view.source_title}</h1>
            {view.title_card && <p className="mt-1 text-sm text-text-2">Aus „{view.source_title}“</p>}
          </div>
          {view.message && (
            <p className="rounded-inner border border-line px-4 py-3 text-[15px] text-text">
              <span className="block text-xs uppercase tracking-wide text-text-2">Nachricht{view.guest_name ? ` an ${view.guest_name}` : ""}</span>
              {view.message}
            </p>
          )}
          <dl className="grid gap-4 sm:grid-cols-2">
            <div>
              <dt className="text-xs uppercase tracking-wide text-text-2">On-Screen-Hook</dt>
              <dd className="mt-1 text-[15px] text-text">{view.onscreen_hook ?? <span className="text-text-3">noch keiner</span>}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-text-2">Satz zum Sagen</dt>
              <dd className="mt-1 text-[15px] text-text">{view.spoken_hook ?? <span className="text-text-3">noch keiner</span>}</dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-xs uppercase tracking-wide text-text-2">Post-Text ({PLATFORM_LABELS[view.platform]})</dt>
              <dd className="mt-1 whitespace-pre-wrap text-[15px] text-text">{view.post_caption ?? <span className="text-text-3">noch keiner</span>}</dd>
            </div>
          </dl>
        </GlassCard>

        <GlassCard padding="lg" className="flex flex-col gap-4">
          {done ? (
            <div role="status" className="flex flex-col gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={done.decision === "approved" ? "ok" : done.decision === "rejected" ? "danger" : "neutral"}>{DECISION_LABELS[done.decision]}</Badge>
                {done.decided_at && <span className="text-sm text-text-2">am {formatDateTime(done.decided_at)}</span>}
              </div>
              {done.comment && <p className="text-[15px] text-text">{done.comment}</p>}
              <p className="text-sm text-text-2">
                {view.decision ? "Diese Freigabe wurde bereits entschieden. Für eine neue Entscheidung braucht es einen neuen Link." : "Danke. Das Team wurde informiert, du kannst diese Seite schließen."}
              </p>
            </div>
          ) : view.expired ? (
            <p role="alert" className="text-[15px] text-attention">
              Dieser Link ist seit {formatDate(view.expires_at)} abgelaufen. Bitte {view.workspace_name} um einen neuen Link.
            </p>
          ) : (
            <>
              <div>
                <h2 className="text-lg font-medium">Deine Entscheidung</h2>
                <p className="mt-1 text-sm text-text-2">
                  Du bist im Clip zu sehen oder zu hören. Erst mit deiner Freigabe darf er veröffentlicht werden.
                  {view.expires_at ? ` Der Link gilt bis ${formatDate(view.expires_at)}.` : ""}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => void send("approved")} disabled={busy}>
                  {busy && mode === null ? "Wird gespeichert" : "Freigeben"}
                </Button>
                <Button variant="ghost" onClick={() => setMode("changes")} aria-pressed={mode === "changes"} disabled={busy}>
                  Fehlerhaft
                </Button>
                <Button variant="danger" onClick={() => setMode("rejected")} aria-pressed={mode === "rejected"} disabled={busy}>
                  Ablehnen
                </Button>
              </div>
              {mode && (
                <form
                  className="flex flex-col gap-3 rounded-inner border border-line p-4"
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (comment.trim()) void send(mode);
                  }}
                >
                  <label htmlFor={commentId} className="text-sm font-medium">
                    {mode === "changes" ? "Was stimmt nicht?" : "Warum lehnst du ab?"} <span className="text-text-2">(Pflicht)</span>
                  </label>
                  <Textarea id={commentId} value={comment} onChange={(e) => setComment(e.target.value)} placeholder={mode === "changes" ? "z. B. Bitte diesen Satz herausnehmen." : "z. B. Ich möchte in diesem Kontext nicht zitiert werden."} />
                  {/* Die Stelle geht mit. Der Gast muss dafür nichts tun ausser anhalten, und das
                      Team muss sie später nicht suchen. Abschaltbar, denn manche Rückmeldung gilt
                      dem ganzen Clip. */}
                  {mode === "changes" && stelle != null && stelle > 0 && (
                    <label className="flex items-center gap-2 text-sm text-text-2">
                      <input
                        type="checkbox"
                        checked={stelleMitschicken}
                        onChange={(e) => setStelleMitschicken(e.target.checked)}
                        className="h-4 w-4 cursor-pointer rounded border border-line-strong bg-black/40 accent-white"
                      />
                      Auf die Stelle bei {sekunden(stelle)} beziehen
                    </label>
                  )}
                  <div className="flex flex-wrap justify-end gap-2">
                    <Button type="button" variant="ghost" size="sm" onClick={() => setMode(null)} disabled={busy}>
                      Abbrechen
                    </Button>
                    <Button type="submit" size="sm" variant={mode === "rejected" ? "danger" : "primary"} className={cn(mode === "rejected" && "border border-danger/50")} disabled={busy || !comment.trim()}>
                      {busy ? "Wird gespeichert" : mode === "changes" ? "Als fehlerhaft melden" : "Ablehnung senden"}
                    </Button>
                  </div>
                </form>
              )}
              {error && (
                <p role="alert" className="text-sm text-attention">
                  {error}
                </p>
              )}
            </>
          )}
        </GlassCard>
      </div>
    </div>
  );
}

/* Eine Sekundenangabe, wie sie ein Mensch sagt: 0:07, 1:24. */
function sekunden(s: number): string {
  const ganz = Math.floor(s);
  return `${Math.floor(ganz / 60)}:${String(ganz % 60).padStart(2, "0")}`;
}
