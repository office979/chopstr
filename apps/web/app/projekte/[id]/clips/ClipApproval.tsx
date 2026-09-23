"use client";

import Link from "next/link";
import { useCallback, useId, useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Field, Input, Textarea } from "@/components/ui/Field";
import { guestTone } from "@/components/clips/GuestApprovalDialog";
import type { GuestApproval } from "@/lib/repo/types";
import { GUEST_STATUS_LABELS, guestStatus } from "@/lib/guest/approval";
import { formatDate, formatDateTime } from "@/lib/format";

interface Props {
  sourceId: string;
  clipId: string;
  clipLabel: string;
  guestApprovalRequired: boolean;
  current: GuestApproval | null;
  /* Rolle guest_approval.request */
  canRequest: boolean;
  /* Plan-Gate plans.features.guest_approval */
  planAllows: boolean;
  planName: string;
  onRequested?: (approval: GuestApproval, link: string) => void;
}

interface ApiResponse {
  error?: string;
  approval?: GuestApproval;
  link?: string;
  mail?: { delivered: boolean; logged: boolean };
}

/* Freigabe je Clip-Karte: Status als Plakette, die Handlung als reines Zeichen (Person mit Plus).
 * Auf der Clip-Seite gibt es keine Textknöpfe mehr; das Hook-Studio benutzt weiter GuestApprovalDialog. */
export function ClipApproval({ sourceId, clipId, clipLabel, guestApprovalRequired, current, canRequest, planAllows, planName, onRequested }: Props) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(current?.guest_name ?? "");
  const [email, setEmail] = useState(current?.guest_email ?? "");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [gateNotice, setGateNotice] = useState(false);
  const [result, setResult] = useState<{ approval: GuestApproval; link: string; mail: ApiResponse["mail"] } | null>(null);
  const [copied, setCopied] = useState(false);
  const nameId = useId();
  const emailId = useId();
  const messageId = useId();

  const status = guestStatus({ guest_approval_required: guestApprovalRequired }, current ?? undefined);
  /* Ein Zeichen, drei Bedeutungen. Der Titel sagt, was passiert, damit der Knopf ohne Text trägt. */
  const actionLabel = status === "pending" ? "Neuen Freigabe-Link erstellen" : status === "none" ? "Jemanden um Freigabe bitten" : "Erneut um Freigabe bitten";

  const openDialog = () => {
    if (!planAllows) {
      setGateNotice(true);
      return;
    }
    setResult(null);
    setError(null);
    setOpen(true);
  };

  const submit = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/projects/${sourceId}/clips/${clipId}/guest-approval`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ guest_name: name, guest_email: email, message }),
      });
      const data = (await res.json()) as ApiResponse;
      if (!res.ok || !data.approval || !data.link) throw new Error(data.error ?? "Freigabe konnte nicht angefordert werden");
      setResult({ approval: data.approval, link: data.link, mail: data.mail });
      onRequested?.(data.approval, data.link);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Freigabe konnte nicht angefordert werden");
    } finally {
      setBusy(false);
    }
  }, [sourceId, clipId, name, email, message, onRequested]);

  const copy = async (link: string) => {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        {status !== "none" && <Badge tone={guestTone(status)}>{GUEST_STATUS_LABELS[status]}</Badge>}
        {canRequest && (
          <button
            type="button"
            onClick={openDialog}
            title={actionLabel}
            aria-label={actionLabel}
            className="transition-soft inline-flex h-9 w-9 items-center justify-center rounded-pill border border-line-strong text-text-2 hover:border-white/40 hover:bg-white/5 hover:text-text"
          >
            <IconUserPlus />
          </button>
        )}
        {status !== "none" && current && (
          <span className="text-xs text-text-2">
            {current.guest_name ?? "Gast"}
            {current.decided_at ? ` · ${formatDateTime(current.decided_at)}` : current.expires_at ? ` · gültig bis ${formatDate(current.expires_at)}` : ""}
          </span>
        )}
      </div>
      {current?.comment && (current.decision === "changes" || current.decision === "rejected") && (
        <p className="rounded-[12px] border border-line px-3 py-2 text-xs text-text">
          <span className="text-text-2">Kommentar des Gastes: </span>
          {current.comment}
        </p>
      )}
      {gateNotice && !planAllows && (
        <p role="status" className="rounded-[12px] border border-line px-3 py-2 text-xs text-text-2">
          Im Tarif {planName} kannst du niemanden um Freigabe bitten.{" "}
          <Link href="/einstellungen/abrechnung" className="text-text underline-offset-4 hover:underline">
            Tarif ab Pro wählen
          </Link>
        </p>
      )}

      <Modal open={open} onClose={() => setOpen(false)} title="Jemanden um Freigabe bitten" description={`${clipLabel}: Die Person bekommt einen Link, sieht den Clip mit Text und sagt Ja oder Nein. Ohne Konto. Der Link gilt 14 Tage.`}>
        {result ? (
          <div className="flex flex-col gap-4">
            <p className="text-sm text-text">
              Link erstellt für {result.approval.guest_name}.{" "}
              {result.mail?.delivered ? "Die E-Mail ist unterwegs." : result.mail?.logged ? "Kein SMTP: Die E-Mail wurde in der Serverkonsole ausgegeben." : "Ohne E-Mail: Bitte den Link selbst weitergeben."}
            </p>
            <div className="flex flex-col gap-2 rounded-inner border border-line p-3">
              <span className="break-all font-mono text-xs text-text-2">{result.link}</span>
              <div className="flex gap-2">
                <Button size="sm" onClick={() => copy(result.link)}>
                  {copied ? "Kopiert" : "Link kopieren"}
                </Button>
                <a href={result.link} target="_blank" rel="noreferrer" className="transition-soft inline-flex h-9 items-center rounded-pill border border-line-strong px-4 text-sm text-text hover:bg-white/5">
                  Öffnen
                </a>
              </div>
            </div>
            <p className="text-xs text-text-2">Das Herunterladen bleibt gesperrt, bis der Gast freigibt.</p>
            <div className="flex justify-end">
              <Button variant="ghost" onClick={() => setOpen(false)}>
                Fertig
              </Button>
            </div>
          </div>
        ) : (
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
            noValidate
          >
            <Field label="Name des Gastes" htmlFor={nameId} required>
              <Input id={nameId} value={name} onChange={(e) => setName(e.target.value)} placeholder="z. B. Maria Berger" autoComplete="off" />
            </Field>
            <Field label="E-Mail" htmlFor={emailId} hint="Optional. Ohne E-Mail gibst du den Link selbst weiter.">
              <Input id={emailId} type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="gast@beispiel.at" autoComplete="off" />
            </Field>
            <Field label="Nachricht" htmlFor={messageId} hint="Steht auf der Freigabeseite.">
              <Textarea id={messageId} value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Kurz sagen, worum es geht und bis wann du eine Antwort brauchst." />
            </Field>
            {error && (
              <p role="alert" className="text-sm text-attention">
                {error}
              </p>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
                Abbrechen
              </Button>
              <Button type="submit" disabled={busy || name.trim().length < 2}>
                {busy ? "Wird erstellt" : "Link erstellen"}
              </Button>
            </div>
          </form>
        )}
      </Modal>
    </div>
  );
}

/* Person mit Plus, im Stil der Seitenleisten-Zeichen: 20 px, 1,75 px Strich, currentColor, keine Füllung */
function IconUserPlus() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="10" cy="8" r="4" />
      <path d="M3 21a7 7 0 0 1 11.2-5.6" />
      <path d="M18 14v6" />
      <path d="M15 17h6" />
    </svg>
  );
}
