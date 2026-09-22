"use client";

import { useId, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { StatusCheck } from "@/components/ui/StatusCheck";
import { Input, Textarea } from "@/components/ui/Field";
import { cn } from "@/components/ui/cn";
import type { Candidate, Clip, Platform, ReviseCandidateInput } from "@/lib/repo/types";
import { PLATFORMS, PLATFORM_LABELS } from "@/lib/clips/labels";
import { PLATFORM_ASPECT } from "@/lib/clips/presets";
import { GATE_LABELS, GATE_ORDER } from "@/lib/candidates/gates";
import { RUBRIC_LABELS, RUBRIC_ORDER, VERDICT_LABELS, formatSeconds, structureLabel } from "@/lib/candidates/labels";
import { TITLE_CARD_MAX_WORDS, titleCardWords } from "@/lib/candidates/revise";
import { formatTimecode } from "@/lib/format";
import { StoryGraph } from "./StoryGraph";
import Link from "next/link";

interface Props {
  candidate: Candidate;
  sourceId: string;
  maxSentence: number;
  busy: boolean;
  rejectOpen: boolean;
  onRejectOpen: (open: boolean) => void;
  acceptOpen: boolean;
  onAcceptOpen: (open: boolean) => void;
  /* Standard-Plattform des Markenprofils: vorausgewählt, hervorgehoben, immer dabei */
  defaultPlatform: Platform;
  /* Clips dieses Kandidaten (nach dem Annehmen) */
  clips: Clip[];
  onAccept: (platforms: Platform[]) => void;
  onReject: (reason: string) => void;
  onRevise: (input: ReviseCandidateInput) => void;
}

type Panel = "extend" | "shorten" | "title" | null;

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 className="mb-3 text-xs uppercase tracking-wide text-text-2">{children}</h3>;
}

/* Detail: Begründung, Rubrik, Pflichtkriterien, Story-Graph, Aktionen */
export function CandidateDetail({
  candidate: c,
  sourceId,
  maxSentence,
  busy,
  rejectOpen,
  onRejectOpen,
  acceptOpen,
  onAcceptOpen,
  defaultPlatform,
  clips,
  onAccept,
  onReject,
  onRevise,
}: Props) {
  const [reason, setReason] = useState("");
  const [panel, setPanel] = useState<Panel>(null);
  const [titleCard, setTitleCard] = useState(c.rubric.suggested_title_card ?? "");
  const [targets, setTargets] = useState<Platform[]>(PLATFORMS);
  const reasonId = useId();
  const titleId = useId();
  const targetsId = useId();
  const firstClip = clips[0] ?? null;

  const toggleTarget = (p: Platform) => {
    if (p === defaultPlatform) return;
    setTargets((cur) => (cur.includes(p) ? cur.filter((x) => x !== p) : PLATFORMS.filter((x) => x === p || cur.includes(x))));
  };
  const submitAccept = () => {
    const chosen = PLATFORMS.filter((p) => targets.includes(p) || p === defaultPlatform);
    onAccept(chosen);
  };

  const first = c.first_sent ?? 0;
  const last = c.last_sent ?? 0;
  const canExtendFront = first > 0;
  const canExtendBack = last < maxSentence;
  const canShorten = last > first;
  const titleWords = titleCardWords(titleCard);
  const titleTooLong = titleWords.length > TITLE_CARD_MAX_WORDS;
  const titleUnchanged = titleWords.join(" ") === (c.rubric.suggested_title_card ?? "").trim();
  const stale = c.rubric.scores_stale === true;

  const togglePanel = (p: Panel) => setPanel((cur) => (cur === p ? null : p));

  const submitReject = () => {
    const text = reason.trim();
    if (!text) return;
    onReject(text);
    setReason("");
  };

  return (
    <GlassCard padding="lg" className="flex flex-col gap-7">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm text-text-2">Kandidat, Version {c.version}</p>
          <h2 className="mt-1 text-xl font-medium">{structureLabel(c.structure)}</h2>
          <p className="mt-1 font-mono text-xs text-text-3">
            {c.model_id ?? "unbekanntes Modell"}
            {c.prompt_version ? ` · ${c.prompt_version}` : ""}
            {" · "}
            {formatTimecode(c.start_s)} bis {formatTimecode(c.end_s)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {stale && <Badge tone="attention">Scores veraltet</Badge>}
          {c.human_verdict && c.human_verdict !== "edited" && (
            <Badge tone={c.human_verdict === "accepted" ? "ok" : "neutral"}>{VERDICT_LABELS[c.human_verdict]}</Badge>
          )}
        </div>
      </div>

      <section>
        <SectionTitle>Warum dieser Clip?</SectionTitle>
        <p className="text-[16px] leading-relaxed text-text">{c.why ?? "Keine Begründung hinterlegt."}</p>
        {c.rubric.proposal_why && <p className="mt-2 text-sm text-text-2">Vorschlag der Story-Engine: {c.rubric.proposal_why}</p>}
        {stale && (
          <p className="mt-3 rounded-inner border border-attention/50 bg-attention/10 px-4 py-3 text-sm text-text">
            Die Grenzen wurden im Review geändert. Rubrik und Gesamtwert stammen vom ursprünglichen Ausschnitt, prüfe den
            neuen Text selbst.
          </p>
        )}
        {c.human_verdict === "rejected" && c.verdict_reason && (
          <p className="mt-3 text-sm text-text-2">Grund der Ablehnung: „{c.verdict_reason}“</p>
        )}
      </section>

      <section>
        <SectionTitle>Rubrik</SectionTitle>
        <ol className="flex flex-col gap-4">
          {RUBRIC_ORDER.map((key) => {
            const s = c.rubric.scores?.[key];
            if (!s) return null;
            const pct = Math.max(0, Math.min(100, (s.value / 10) * 100));
            return (
              <li key={key} className="flex flex-col gap-1.5">
                <div className="grid grid-cols-[6.5rem_minmax(0,1fr)_2rem_3.5rem] items-center gap-3">
                  <span className="text-sm text-text">{RUBRIC_LABELS[key]}</span>
                  <div
                    className="h-1.5 w-full overflow-hidden rounded-pill bg-line-mute"
                    role="meter"
                    aria-label={`${RUBRIC_LABELS[key]} ${s.value} von 10`}
                    aria-valuemin={0}
                    aria-valuemax={10}
                    aria-valuenow={s.value}
                  >
                    <div className={cn("h-full rounded-pill bg-text", stale && "opacity-50")} style={{ width: `${pct}%` }} />
                  </div>
                  <span className="text-right font-mono text-sm tabular-nums text-text">{s.value}</span>
                  <span className="text-right font-mono text-xs tabular-nums text-text-2">
                    ×{s.weight.toLocaleString("de-AT", { minimumFractionDigits: 2 })}
                  </span>
                </div>
                {s.evidence && <p className="pl-0 text-sm text-text-2 sm:pl-[6.5rem]">„{s.evidence}“</p>}
              </li>
            );
          })}
        </ol>
      </section>

      <section>
        <SectionTitle>Pflichtkriterien</SectionTitle>
        <ul className="flex flex-col gap-3">
          {GATE_ORDER.map((key) => {
            const g = c.gates?.[key];
            if (!g) return null;
            const failed = g.passed === false;
            const unavailable = g.available === false;
            return (
              <li key={key} className="flex items-start gap-3">
                <StatusCheck state={failed ? "error" : "done"} size={26} label={`${GATE_LABELS[key]}: ${failed ? "nicht erfüllt" : "erfüllt"}`} />
                <div className="min-w-0">
                  <p className={cn("text-sm font-medium", failed ? "text-attention" : "text-text")}>{GATE_LABELS[key]}</p>
                  <p className={cn("text-sm", failed ? "text-attention" : "text-text-2")}>
                    {g.detail}
                    {unavailable && !failed && <span className="text-text-3"> (nicht geprüft, kein Blocker)</span>}
                  </p>
                </div>
              </li>
            );
          })}
        </ul>
      </section>

      {c.story_graph_flags.length > 0 && (
        <section>
          <SectionTitle>Story-Graph</SectionTitle>
          <div className="flex flex-col gap-5">
            {c.story_graph_flags.map((f, i) => (
              <div key={`${f.sentence_idx}-${i}`} className="rounded-inner border border-attention/40 bg-attention/5 p-4">
                <StoryGraph first={first} last={last} flag={f} />
                <p className="mt-2 text-sm text-text">
                  <span className="text-attention">{formatSeconds(f.seconds_after)} nach dem Clip:</span> „{f.text}“
                </p>
                <p className="mt-1 text-sm text-text-2">{f.reason}</p>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <Badge tone="attention">
                    {f.confirmed === true ? "Bestätigt durch Sprachmodell" : f.confirmed === false ? "Nicht bestätigt" : "Heuristik-Treffer, Mensch prüft"}
                  </Badge>
                  <Badge>{f.repair === "extend" ? "Reparatur: verlängern" : "Reparatur: Text einblenden"}</Badge>
                  <span className="text-sm text-text-2">{f.suggestion}</span>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {f.repair === "extend" && f.sentence_idx > last && (
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy}
                      onClick={() => onRevise({ first_sent: first, last_sent: f.sentence_idx })}
                    >
                      Bis Satz {f.sentence_idx} verlängern
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" disabled={busy} onClick={() => setPanel("title")}>
                    Einschränkung als Titelkarte
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="border-t border-line pt-6">
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => onAcceptOpen(!acceptOpen)} disabled={busy || c.human_verdict === "accepted"} aria-expanded={acceptOpen} aria-controls={targetsId}>
            Annehmen
          </Button>
          <Button variant="ghost" onClick={() => onRejectOpen(!rejectOpen)} disabled={busy || c.human_verdict === "rejected"} aria-expanded={rejectOpen}>
            Ablehnen
          </Button>
          <Button variant="ghost" onClick={() => togglePanel("extend")} disabled={busy || (!canExtendFront && !canExtendBack)} aria-expanded={panel === "extend"}>
            Verlängern
          </Button>
          <Button variant="ghost" onClick={() => togglePanel("shorten")} disabled={busy || !canShorten} aria-expanded={panel === "shorten"}>
            Kürzen
          </Button>
          <Button variant="ghost" onClick={() => togglePanel("title")} disabled={busy} aria-expanded={panel === "title"}>
            Kontext ergänzen
          </Button>
          {firstClip ? (
            <Link
              href={`/projekte/${sourceId}/clips/${firstClip.id}/hooks`}
              className="transition-soft inline-flex h-11 items-center justify-center rounded-pill border border-line-strong px-6 text-[15px] font-medium text-text hover:border-white/40 hover:bg-white/5"
            >
              Umschreiben
            </Link>
          ) : (
            <span className="inline-flex items-center gap-2">
              <Button variant="ghost" disabled title="Hook-Studio: erst annehmen, dann umschreiben">
                Umschreiben
              </Button>
              <span className="text-xs text-text-3">Hook-Studio nach dem Annehmen</span>
            </span>
          )}
        </div>

        {clips.length > 0 && (
          <p className="mt-3 text-sm text-text-2">
            {clips.length} {clips.length === 1 ? "Clip" : "Clips"} angelegt ({clips.map((k) => PLATFORM_LABELS[k.platform]).join(", ")}).{" "}
            <Link href={`/projekte/${sourceId}/clips`} className="text-text underline-offset-4 hover:underline">
              Zur Clip-Übersicht
            </Link>
          </p>
        )}

        {acceptOpen && c.human_verdict !== "accepted" && (
          <div id={targetsId} className="mt-4 flex flex-col gap-3 rounded-inner border border-line p-4" role="group" aria-label="Ziele wählen">
            <p className="text-sm font-medium text-text">
              Wohin soll der Clip? <span className="text-text-2">(je Ziel ein Render)</span>
            </p>
            <div className="flex flex-wrap gap-2">
              {PLATFORMS.map((p) => {
                const active = targets.includes(p) || p === defaultPlatform;
                const isDefault = p === defaultPlatform;
                return (
                  <button
                    key={p}
                    type="button"
                    onClick={() => toggleTarget(p)}
                    aria-pressed={active}
                    aria-disabled={isDefault || undefined}
                    title={isDefault ? "Standard-Plattform des Markenprofils, immer dabei" : undefined}
                    className={cn(
                      "transition-soft inline-flex h-9 items-center gap-2 rounded-pill border px-3.5 text-sm",
                      active ? "border-white/40 bg-white/10 text-text" : "border-line text-text-2 hover:border-line-strong hover:text-text",
                      isDefault && "glass-selected",
                    )}
                  >
                    {PLATFORM_LABELS[p]}
                    <span className="font-mono text-[11px] text-text-3">{PLATFORM_ASPECT[p]}</span>
                    {isDefault && <span className="text-[11px] uppercase tracking-wide text-ai-soft">Standard</span>}
                  </button>
                );
              })}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" onClick={submitAccept} disabled={busy}>
                Annehmen für {PLATFORMS.filter((p) => targets.includes(p) || p === defaultPlatform).length} Ziele
              </Button>
              <Button size="sm" variant="ghost" onClick={() => onAcceptOpen(false)}>
                Abbrechen
              </Button>
            </div>
          </div>
        )}

        {busy && (
          <p className="mt-3 text-sm text-text-2" role="status" aria-live="polite">
            Neue Version wird angelegt
          </p>
        )}

        {rejectOpen && c.human_verdict !== "rejected" && (
          <div className="mt-4 flex flex-col gap-3 rounded-inner border border-line p-4">
            <label htmlFor={reasonId} className="text-sm font-medium text-text">
              Warum passt der Clip nicht? <span className="text-text-2">(Pflicht, kurz)</span>
            </label>
            <Textarea
              id={reasonId}
              autoFocus
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Zum Beispiel: Zahl ohne Quelle, passt nicht zur Zielgruppe, Ton zu flapsig"
              maxLength={500}
              className="min-h-20"
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submitReject();
                if (e.key === "Escape") onRejectOpen(false);
              }}
            />
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={submitReject} disabled={!reason.trim() || busy}>
                Ablehnung speichern
              </Button>
              <Button size="sm" variant="ghost" onClick={() => onRejectOpen(false)}>
                Abbrechen
              </Button>
            </div>
          </div>
        )}

        {panel === "extend" && (
          <div className="mt-4 flex flex-wrap items-center gap-2 rounded-inner border border-line p-4" role="group" aria-label="Verlängern">
            <span className="mr-2 text-sm text-text-2">Um einen Satz verlängern:</span>
            <Button size="sm" variant="ghost" disabled={!canExtendFront || busy} onClick={() => onRevise({ first_sent: first - 1, last_sent: last })}>
              Vorn (Satz {first - 1})
            </Button>
            <Button size="sm" variant="ghost" disabled={!canExtendBack || busy} onClick={() => onRevise({ first_sent: first, last_sent: last + 1 })}>
              Hinten (Satz {last + 1})
            </Button>
          </div>
        )}

        {panel === "shorten" && (
          <div className="mt-4 flex flex-wrap items-center gap-2 rounded-inner border border-line p-4" role="group" aria-label="Kürzen">
            <span className="mr-2 text-sm text-text-2">Um einen Satz kürzen:</span>
            <Button size="sm" variant="ghost" disabled={!canShorten || busy} onClick={() => onRevise({ first_sent: first + 1, last_sent: last })}>
              Vorn (ab Satz {first + 1})
            </Button>
            <Button size="sm" variant="ghost" disabled={!canShorten || busy} onClick={() => onRevise({ first_sent: first, last_sent: last - 1 })}>
              Hinten (bis Satz {last - 1})
            </Button>
          </div>
        )}

        {panel === "title" && (
          <div className="mt-4 flex flex-col gap-3 rounded-inner border border-line p-4">
            <label htmlFor={titleId} className="text-sm font-medium text-text">
              Titelkarte <span className="text-text-2">(Kontext, höchstens {TITLE_CARD_MAX_WORDS} Wörter)</span>
            </label>
            <Input
              id={titleId}
              autoFocus
              value={titleCard}
              onChange={(e) => setTitleCard(e.target.value)}
              placeholder="Zum Beispiel: Gilt für Vertrieb, nicht für Pflege"
              aria-invalid={titleTooLong || undefined}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !titleTooLong && !titleUnchanged) onRevise({ first_sent: first, last_sent: last, title_card: titleCard });
                if (e.key === "Escape") setPanel(null);
              }}
            />
            <div className="flex flex-wrap items-center gap-3">
              <span className={cn("font-mono text-xs tabular-nums", titleTooLong ? "text-attention" : "text-text-2")}>
                {titleWords.length} von {TITLE_CARD_MAX_WORDS} Wörtern
              </span>
              <Button size="sm" disabled={titleTooLong || titleUnchanged || busy} onClick={() => onRevise({ first_sent: first, last_sent: last, title_card: titleCard })}>
                Titelkarte speichern
              </Button>
              {c.rubric.suggested_title_card && (
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => onRevise({ first_sent: first, last_sent: last, title_card: "" })}>
                  Entfernen
                </Button>
              )}
            </div>
          </div>
        )}
      </section>
    </GlassCard>
  );
}
