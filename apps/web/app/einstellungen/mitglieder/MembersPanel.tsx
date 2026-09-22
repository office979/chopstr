"use client";

import { useActionState, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Field, Input, Select } from "@/components/ui/Field";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { FormNotice } from "@/components/ui/FormNotice";
import { initialFormState } from "@/lib/auth/form";
import { ROLE_DESCRIPTIONS, ROLE_LABELS, type Role } from "@/lib/auth/permissions";
import { formatDate, formatDateTime } from "@/lib/format";
import type { WorkspaceInvite, WorkspaceMember } from "@/lib/repo/types";
import { inviteMemberAction, removeMemberAction, revokeInviteAction, updateMemberAction } from "../actions";

interface Props {
  members: WorkspaceMember[];
  invites: WorkspaceInvite[];
  brands: { id: string; name: string }[];
  assignable: Role[];
  canManage: boolean;
  myUserId: string;
  myRole: Role;
  /* Basis-URL für Einladungslinks (vom Server, damit SSR und Client übereinstimmen) */
  baseUrl: string;
}

export function MembersPanel({ members, invites, brands, assignable, canManage, myUserId, myRole, baseUrl }: Props) {
  return (
    <div className="flex flex-col gap-5">
      {canManage && <InviteCard brands={brands} assignable={assignable} />}
      <GlassCard padding="lg" className="flex flex-col gap-4">
        <h2 className="text-lg font-medium">Mitglieder</h2>
        <ul className="divide-y divide-line">
          {members.map((m) => (
            <MemberRow key={m.user_id} member={m} brands={brands} assignable={assignable} canManage={canManage} isMe={m.user_id === myUserId} myRole={myRole} />
          ))}
        </ul>
      </GlassCard>
      {invites.length > 0 && (
        <GlassCard padding="lg" className="flex flex-col gap-4">
          <h2 className="text-lg font-medium">Offene Einladungen</h2>
          <ul className="divide-y divide-line">
            {invites.map((i) => (
              <InviteRow key={i.token} invite={i} canManage={canManage} baseUrl={baseUrl} />
            ))}
          </ul>
        </GlassCard>
      )}
    </div>
  );
}

function InviteCard({ brands, assignable }: { brands: { id: string; name: string }[]; assignable: Role[] }) {
  const [state, action, pending] = useActionState(inviteMemberAction, initialFormState);
  const [role, setRole] = useState<Role>(assignable.includes("editor") ? "editor" : assignable[0] ?? "reviewer");
  return (
    <form action={action} noValidate>
      <GlassCard padding="lg" className="flex flex-col gap-5">
        <h2 className="text-lg font-medium">Einladen</h2>
        <div className="grid gap-5 sm:grid-cols-2">
          <Field label="E-Mail" htmlFor="invite_email" required error={state.errors.email}>
            <Input id="invite_email" name="email" type="email" placeholder="name@firma.at" required />
          </Field>
          <Field label="Rolle" htmlFor="invite_role" error={state.errors.role} hint={ROLE_DESCRIPTIONS[role]}>
            <Select id="invite_role" name="role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
              {assignable.map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABELS[r]}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label="Marke"
            htmlFor="invite_brand"
            error={state.errors.brand_profile_id}
            required={role === "client"}
            hint={role === "client" ? "Kunden sehen nur Projekte dieser Marke." : "Optional."}
            className="sm:col-span-2"
          >
            <Select id="invite_brand" name="brand_profile_id" defaultValue={role === "client" ? brands[0]?.id ?? "" : ""}>
              <option value="">Keine Bindung</option>
              {brands.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <FormNotice state={state} />
        <div>
          <Button type="submit" disabled={pending}>
            {pending ? "Wird gesendet" : "Einladung senden"}
          </Button>
        </div>
      </GlassCard>
    </form>
  );
}

interface MemberRowProps {
  member: WorkspaceMember;
  brands: { id: string; name: string }[];
  assignable: Role[];
  canManage: boolean;
  isMe: boolean;
  myRole: Role;
}

function MemberRow({ member, brands, assignable, canManage, isMe, myRole }: MemberRowProps) {
  const [updateState, update, updating] = useActionState(updateMemberAction, initialFormState);
  const [removeState, remove, removing] = useActionState(removeMemberAction, initialFormState);
  const [role, setRole] = useState<Role>(member.role);
  const locked = !canManage || isMe || member.role === "owner" || (myRole === "admin" && member.role === "admin") || !assignable.includes(member.role);
  const state = removeState.message ? removeState : updateState;
  return (
    <li className="flex flex-col gap-3 py-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <p className="truncate font-medium text-text">
            {member.display_name ?? member.email}
            {isMe && <span className="ml-2 text-xs text-text-2">(du)</span>}
          </p>
          <p className="truncate text-sm text-text-2">
            {member.email}
            {member.last_login_at ? ` · zuletzt ${formatDateTime(member.last_login_at)}` : " · noch nie angemeldet"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={member.role === "owner" ? "ok" : "neutral"}>{ROLE_LABELS[member.role]}</Badge>
          {member.role === "client" && <Badge>{member.brand_profile_name ?? "ohne Marke"}</Badge>}
          {!member.accepted_at && <Badge tone="attention">Einladung offen</Badge>}
        </div>
      </div>
      {!locked && (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <form action={update} className="flex flex-1 flex-col gap-3 sm:flex-row sm:items-end">
            <input type="hidden" name="user_id" value={member.user_id} />
            <Field label="Rolle" htmlFor={`role_${member.user_id}`} className="flex-1">
              <Select id={`role_${member.user_id}`} name="role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
                {assignable.map((r) => (
                  <option key={r} value={r}>
                    {ROLE_LABELS[r]}
                  </option>
                ))}
              </Select>
            </Field>
            {role === "client" && (
              <Field label="Marke" htmlFor={`brand_${member.user_id}`} className="flex-1">
                <Select id={`brand_${member.user_id}`} name="brand_profile_id" defaultValue={member.brand_profile_id ?? brands[0]?.id ?? ""}>
                  {brands.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name}
                    </option>
                  ))}
                </Select>
              </Field>
            )}
            <Button type="submit" variant="ghost" size="sm" disabled={updating} className="h-11">
              {updating ? "Wird gespeichert" : "Rolle speichern"}
            </Button>
          </form>
          <form action={remove}>
            <input type="hidden" name="user_id" value={member.user_id} />
            <Button type="submit" variant="danger" size="sm" disabled={removing} className="h-11">
              Entfernen
            </Button>
          </form>
        </div>
      )}
      <FormNotice state={state} />
    </li>
  );
}

function InviteRow({ invite, canManage, baseUrl }: { invite: WorkspaceInvite; canManage: boolean; baseUrl: string }) {
  const [state, action, pending] = useActionState(revokeInviteAction, initialFormState);
  const link = `${baseUrl}/einladung/${invite.token}`;
  return (
    <li className="flex flex-col gap-2 py-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <p className="truncate font-medium text-text">{invite.email}</p>
        <p className="text-sm text-text-2">
          {ROLE_LABELS[invite.role]}
          {invite.brand_profile_name ? ` · ${invite.brand_profile_name}` : ""} · gültig bis {formatDate(invite.expires_at)}
        </p>
        <p className="mt-1 truncate font-mono text-xs text-text-3" title={link}>
          {link}
        </p>
        <FormNotice state={state} />
      </div>
      {canManage && (
        <form action={action}>
          <input type="hidden" name="token" value={invite.token} />
          <Button type="submit" variant="danger" size="sm" disabled={pending}>
            Zurückziehen
          </Button>
        </form>
      )}
    </li>
  );
}
