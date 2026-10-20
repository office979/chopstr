"use client";

import { useId, useState } from "react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import type { Candidate, Clip } from "@/lib/repo/types";
import {
  REVIEW_STATE_LABEL,
  evidenceSpans,
  qualityScore,
  reviewState,
  riskWords,
  spanText,
  titleCardRepair,
  verdictView,
  type ReviewStateKind,
} from "@/lib/candidates/review";

/* Der Freigabeteil einer Karte in der Kandidatenliste (docs/decisions/051-kandidatenliste-freigabe.md):
 * Warum dieser Clip, Belegstellen, Flags, Ergebnisklasse mit Gründen, Haltegrund, eine Qualitätszahl
 * und die drei Entscheidungen Annehmen, Ablehnen, Flag an Redaktion. Gerechnet wird in
 * lib/candidates/review.ts; hier steht nur, was davon zu sehen ist. */

const CLASS_TONE: Record<ReviewStateKind, "ok" | "attention" | "danger"> = {
  passed: "ok",
  uncertain: "attention",
  blocked: "danger",
};

type DialogKind = "reject" | "flag" | "override";

const DIALOG: Record<DialogKind, { title: string; description: string; label: string; placeholder: string; action: string }> = {
  reject: {
    title: "Vorschlag ablehnen",
    description: "Ein kurzer Grund ist Pflicht. Er hilft, die nächsten Vorschläge besser zu machen.",
    label: "Warum nicht?",
    placeholder: "Pointe fehlt, Einstieg ohne Zusammenhang",
    action: "Ablehnen",
  },
  flag: {
    title: "An die Redaktion geben",
    description: "Für Fälle, die du nicht allein entscheiden willst. Der Vorschlag bleibt offen und wird nicht veröffentlicht, bis jemand annimmt.",
    label: "Kommentar",
    placeholder: "Stimmt die Zahl? Bitte gegen das Original prüfen.",
    action: "An Redaktion geben",
  },
  override: {
    title: "Trotz Befund annehmen",
    description: "Die Prüfung hält diesen Vorschlag für nicht freigabefähig. Annehmen geht nur mit einer Begründung; sie wird mit dem Urteil gespeichert.",
    label: "Warum trotz Befund?",
    placeholder: "Einschränkung steht im Beitragstext, mit Redaktion abgesprochen",
    action: "Trotzdem annehmen",
  },
};

interface Props {
  sourceId: string;
  candidate: Candidate;
  canVerdict: boolean;
  /* Eine Stelle im Quellvideo ansehen (Sekunden). */
  onShow: (sourceTime: number) => void;
  onDecided: (candidate: Candidate, clips: Clip[], message: string) => void;
  onError: (message: string) => void;
}

export function CandidateReview({ sourceId, candidate, canVerdict, onShow, onDecided, onError }: Props) {
  const [dialog, setDialog] = useState<DialogKind | null>(null);
  const [text, setText] = useState("");
  const [atS, setAtS] = useState("");
  const [busy, setBusy] = useState(false);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const textId = useId();
  const atId = useId();

  const review = reviewState(candidate);
  const quality = qualityScore(candidate);
  const verdict = verdictView(candidate);
  const evidence = evidenceSpans(candidate);
  const flags = riskWords(candidate);
  const repair = titleCardRepair(candidate.rubric);
  const why = candidate.why?.trim() || null;
  const replaced = verdict.status === "replaced";

  const send = async (body: Record<string, unknown>, done: string) => {
    setBusy(true);
    try {
      const res = await fetch(`/api/projects/${sourceId}/candidates/${candidate.id}/verdict`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = (await res.json()) as { error?: string; candidate?: Candidate; clips?: Clip[] };
      if (!res.ok || !data.candidate) throw new Error(data.error ?? "Das Urteil ließ sich nicht speichern");
      onDecided(data.candidate, data.clips ?? [], done);
      setDialog(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Das Urteil ließ sich nicht speichern";
      if (dialog) setFieldError(message);
      else onError(message);
    } finally {
      setBusy(false);
    }
  };

  const open = (kind: DialogKind) => {
    setText("");
    setAtS("");
    setFieldError(null);
    setDialog(kind);
  };

  const accept = () => {
    if (review.state === "blocked") open("override");
    else void send({ verdict: "accepted" }, "Angenommen.");
  };

  const confirm = () => {
    if (!dialog) return;
    const value = text.trim();
    if (!value) {
      setFieldError("Dieses Feld ist Pflicht.");
      return;
    }
    if (dialog === "reject") void send({ verdict: "rejected", reason: value }, "Abgelehnt.");
    if (dialog === "override") void send({ verdict: "accepted", override_reason: value }, "Trotz Befund angenommen.");
    if (dialog === "flag") {
      const raw = atS.trim().replace(",", ".");
      const n = raw === "" ? null : Number(raw);
      if (n != null && (!Number.isFinite(n) || n < 0)) {
        setFieldError("Die Sekunde muss eine Zahl ab 0 sein.");
        return;
      }
      void send({ verdict: "revise", reason: value, ...(n != null ? { at_s: n } : {}) }, "An die Redaktion gegeben.");
    }
  };

  return (
    <div className="flex flex-col gap-2">
      {/* Warum dieser Clip: ein Satz (Regel 12). Fehlt er, steht das da, statt still zu fehlen. */}
      <p className="text-sm text-text">
        <span className="text-text-3">Warum dieser Clip? </span>
        {why ?? "Zu diesem Vorschlag ist keine Begründung gespeichert."}
      </p>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <Badge tone={CLASS_TONE[review.state]}>{REVIEW_STATE_LABEL[review.state]}</Badge>
        {quality && (
          <span className="font-mono text-xs tabular-nums text-text-2" title="Gesamtwert der Richtlinie, keine Reichweitenprognose">
            {quality.text}
          </span>
        )}
        {flags.map((f) => (
          <span key={f.key} title={f.title} className="inline-flex h-6 items-center rounded-pill border border-line px-2.5 text-[12px] text-text-2">
            {f.word}
          </span>
        ))}
      </div>

      {/* Belegstellen: ein Klick zeigt die Stelle. */}
      {evidence.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span className="text-text-3">Belegstellen</span>
          {evidence.map((e) => (
            <button
              key={e.kind}
              type="button"
              onClick={() => onShow(e.span.start_s)}
              className="text-text-2 underline underline-offset-4 hover:text-text"
            >
              {e.label} {spanText(e.span)}
            </button>
          ))}
        </div>
      )}

      {/* Gründe der Ergebnisklasse, je mit Quellstelle (Regel 14). */}
      {review.reasons.length > 0 && (
        <ul className="flex flex-col gap-1 text-sm text-text-2">
          {review.reasons.map((r, i) => (
            <li key={`${r.code}-${i}`} className="flex flex-wrap items-baseline gap-x-2">
              <span>{r.text}</span>
              {r.source_span && (
                <button
                  type="button"
                  onClick={() => onShow(r.source_span!.start_s)}
                  className="text-xs text-text-3 underline underline-offset-4 hover:text-text"
                >
                  Quelle {spanText(r.source_span)}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {repair && (
        <p className="text-sm text-text-2">
          <span className="text-text-3">Reparatur: </span>Titelkarte „{repair.text}“
        </p>
      )}

      {/* Das Urteil und sein Grund. Den Haltegrund verlangt P27 sichtbar an der Karte. */}
      <p className="text-sm text-text-2">
        <span className="text-text-3">Urteil: </span>
        {verdict.label}
        {verdict.reason && !review.reasons.some((r) => r.text === verdict.reason) ? `. ${verdict.reason}` : ""}
      </p>

      {canVerdict && !replaced && (
        <div className="flex flex-wrap items-center gap-2">
          {verdict.status !== "accepted" && (
            <Button size="sm" variant={review.state === "blocked" ? "ghost" : "primary"} disabled={busy} onClick={accept}>
              {review.state === "blocked" ? "Trotz Befund annehmen" : "Annehmen"}
            </Button>
          )}
          {verdict.status !== "rejected" && (
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => open("reject")}>
              Ablehnen
            </Button>
          )}
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => open("flag")}>
            An Redaktion
          </Button>
        </div>
      )}

      <Modal
        open={dialog != null}
        onClose={() => !busy && setDialog(null)}
        title={dialog ? DIALOG[dialog].title : ""}
        description={dialog ? DIALOG[dialog].description : undefined}
      >
        {dialog && (
          <div className="flex flex-col gap-4">
            {dialog === "override" && review.reasons.length > 0 && (
              <ul className="flex list-disc flex-col gap-1 pl-5 text-sm text-text-2">
                {review.reasons.map((r, i) => (
                  <li key={`${r.code}-${i}`}>{r.text}</li>
                ))}
              </ul>
            )}
            <label className="flex flex-col gap-1.5" htmlFor={textId}>
              <span className="text-sm text-text">{DIALOG[dialog].label}</span>
              <textarea
                id={textId}
                rows={3}
                maxLength={500}
                required
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={DIALOG[dialog].placeholder}
                className="transition-soft rounded-inner border border-line bg-black/40 px-4 py-2.5 text-[15px] text-text placeholder:text-text-3 hover:border-line-strong focus:border-white/50 focus:outline-none"
              />
            </label>
            {dialog === "flag" && (
              <label className="flex flex-col gap-1.5" htmlFor={atId}>
                <span className="text-sm text-text">Sekunde im Clip (freiwillig)</span>
                <input
                  id={atId}
                  inputMode="decimal"
                  value={atS}
                  onChange={(e) => setAtS(e.target.value)}
                  placeholder="12"
                  className="transition-soft w-32 rounded-inner border border-line bg-black/40 px-4 py-2.5 text-[15px] text-text placeholder:text-text-3 hover:border-line-strong focus:border-white/50 focus:outline-none"
                />
              </label>
            )}
            {fieldError && (
              <p className="text-sm text-attention" role="alert">
                {fieldError}
              </p>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <Button variant="ghost" onClick={() => setDialog(null)} disabled={busy}>
                Abbrechen
              </Button>
              <Button variant={dialog === "reject" ? "danger" : "primary"} onClick={confirm} disabled={busy}>
                {busy ? "Wird gespeichert" : DIALOG[dialog].action}
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
