"use client";

import { useActionState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Field, Input } from "@/components/ui/Field";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { FormNotice } from "@/components/ui/FormNotice";
import { initialFormState } from "@/lib/auth/form";
import { formatDateTime } from "@/lib/format";
import type { SessionRow } from "@/lib/repo/types";
import { changePasswordAction, revokeOtherSessionsAction, revokeSessionAction } from "../actions";

interface Props {
  sessions: SessionRow[];
  currentSessionId: string | null;
  hasPassword: boolean;
  demo: boolean;
}

/* Browser aus dem User-Agent grob benennen */
function describeAgent(ua: string | null): string {
  if (!ua) return "Unbekannter Client";
  const browser = /Edg\//.test(ua) ? "Edge" : /Chrome\//.test(ua) ? "Chrome" : /Safari\//.test(ua) ? "Safari" : /Firefox\//.test(ua) ? "Firefox" : /curl\//.test(ua) ? "curl" : "Browser";
  const os = /Mac OS X/.test(ua) ? "macOS" : /Windows/.test(ua) ? "Windows" : /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iOS" : /Linux/.test(ua) ? "Linux" : "";
  return os ? `${browser} auf ${os}` : browser;
}

export function SecurityPanel({ sessions, currentSessionId, hasPassword, demo }: Props) {
  const [pwState, changePassword, changing] = useActionState(changePasswordAction, initialFormState);
  const [othersState, revokeOthers, revokingOthers] = useActionState(revokeOtherSessionsAction, initialFormState);
  const others = sessions.filter((s) => s.id !== currentSessionId);
  return (
    <div className="flex flex-col gap-5">
      <GlassCard padding="lg" className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-medium">Aktive Sitzungen</h2>
          {others.length > 0 && (
            <form action={revokeOthers}>
              <Button type="submit" variant="ghost" size="sm" disabled={revokingOthers || demo}>
                Alle anderen abmelden
              </Button>
            </form>
          )}
        </div>
        <FormNotice state={othersState} />
        {sessions.length === 0 ? (
          <p className="text-sm text-text-2">{demo ? "Im Demo-Modus gibt es keine Sitzungen." : "Keine aktiven Sitzungen."}</p>
        ) : (
          <ul className="divide-y divide-line">
            {sessions.map((s) => (
              <SessionRowItem key={s.id} session={s} current={s.id === currentSessionId} demo={demo} />
            ))}
          </ul>
        )}
      </GlassCard>

      <form action={changePassword} noValidate>
        <GlassCard padding="lg" className="flex flex-col gap-5">
          <h2 className="text-lg font-medium">{hasPassword ? "Passwort ändern" : "Passwort setzen"}</h2>
          {hasPassword && (
            <Field label="Aktuelles Passwort" htmlFor="current_password" required error={pwState.errors.current_password}>
              <Input id="current_password" name="current_password" type="password" autoComplete="current-password" disabled={demo} />
            </Field>
          )}
          <div className="grid gap-5 sm:grid-cols-2">
            <Field label="Neues Passwort" htmlFor="password" required error={pwState.errors.password} hint="Mindestens 10 Zeichen, Buchstaben und eine Ziffer.">
              <Input id="password" name="password" type="password" autoComplete="new-password" disabled={demo} />
            </Field>
            <Field label="Wiederholen" htmlFor="password_confirm" required error={pwState.errors.password_confirm}>
              <Input id="password_confirm" name="password_confirm" type="password" autoComplete="new-password" disabled={demo} />
            </Field>
          </div>
          <FormNotice state={pwState} />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-text-2">Nach der Änderung werden alle anderen Sitzungen beendet.</p>
            <Button type="submit" disabled={changing || demo}>
              {changing ? "Wird gespeichert" : "Passwort speichern"}
            </Button>
          </div>
        </GlassCard>
      </form>
    </div>
  );
}

function SessionRowItem({ session, current, demo }: { session: SessionRow; current: boolean; demo: boolean }) {
  const [state, action, pending] = useActionState(revokeSessionAction, initialFormState);
  return (
    <li className="flex flex-col gap-2 py-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-2 font-medium text-text">
          {describeAgent(session.user_agent)}
          {current && <Badge tone="ok">Diese Sitzung</Badge>}
        </p>
        <p className="text-sm text-text-2">
          Angemeldet {formatDateTime(session.created_at)} · läuft ab {formatDateTime(session.expires_at)}
          {session.ip ? ` · ${session.ip}` : ""}
        </p>
        <FormNotice state={state} />
      </div>
      {!current && (
        <form action={action}>
          <input type="hidden" name="session_id" value={session.id} />
          <Button type="submit" variant="danger" size="sm" disabled={pending || demo}>
            Abmelden
          </Button>
        </form>
      )}
    </li>
  );
}
