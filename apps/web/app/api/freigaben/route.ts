import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { requireApiRole } from "@/lib/auth/guard";
import { isEmail, normalizeEmail, randomToken } from "@/lib/auth/tokens";
import { appBaseUrl } from "@/lib/auth/url";
import { getQuota } from "@/lib/billing/quota";
import { GUEST_APPROVAL_TTL_MS } from "@/lib/guest/approval";
import { sendGuestApprovalMail } from "@/lib/guest/mail";

export const dynamic = "force-dynamic";

interface Body {
  name?: unknown;
  clip_ids?: unknown;
  guest_email?: unknown;
  message?: unknown;
}

/* Eine Freigabe anlegen: ein Paket von Clips mit EINEM Link.
 *
 * Vorher gab es nur die Freigabe je Clip. Wer zwölf Clips abzeichnen lassen wollte, verschickte
 * zwölf Links, und die Person klickte sich zwölfmal durch dieselbe Seite.
 *
 * Die E-Mail ist FREIWILLIG. Der Link entsteht immer und steht sofort im Fenster zum Kopieren -
 * viele schicken ihn ohnehin über WhatsApp oder Slack. Ist eine Adresse dabei, geht zusätzlich
 * eine Mail hinaus.
 */
export async function POST(request: NextRequest) {
  const auth = await requireApiRole("guest_approval.request");
  if (auth instanceof Response) return auth;
  const repo = getRepo();

  const quota = await getQuota(repo);
  if (!quota.plan?.features?.guest_approval) {
    return Response.json(
      {
        error: `Freigaben sind im Tarif ${quota.plan?.name ?? "Starter"} nicht enthalten. Ab Pro verfügbar.`,
        code: "plan_gate",
        href: "/einstellungen/abrechnung",
      },
      { status: 403 },
    );
  }

  let body: Body;
  try {
    body = (await request.json()) as Body;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }

  const clipIds = Array.isArray(body.clip_ids) ? body.clip_ids.filter((x): x is string => typeof x === "string") : [];
  if (clipIds.length === 0) return Response.json({ error: "Keine Clips angegeben." }, { status: 400 });
  const guestEmail = normalizeEmail(body.guest_email);
  if (guestEmail && !isEmail(guestEmail)) return Response.json({ error: "Die E-Mail-Adresse ist ungültig." }, { status: 400 });
  const message = typeof body.message === "string" ? body.message.trim().slice(0, 1000) : "";

  /* Nur Clips aus dem eigenen Arbeitsbereich, und nur solche mit fertiger Datei: einen Link auf
   * ein Video zu verschicken, das es noch nicht gibt, heisst jemanden auf eine leere Seite zu
   * schicken. */
  const clips = [];
  for (const id of clipIds) {
    const clip = await repo.getClip(id);
    if (clip && clip.file_key) clips.push(clip);
  }
  if (clips.length === 0) {
    return Response.json({ error: "Von diesen Clips gibt es noch keine fertige Datei." }, { status: 400 });
  }

  const name = typeof body.name === "string" && body.name.trim() ? body.name.trim().slice(0, 120) : "";
  const token = randomToken(32);
  const expiresAt = new Date(Date.now() + GUEST_APPROVAL_TTL_MS).toISOString();
  /* Je Clip ein eigenes Token: die Person entscheidet je Clip, und die bestehende
   * Entscheidungs-Route arbeitet auf dem Clip-Token. */
  const clipTokens: Record<string, string> = {};
  for (const c of clips) clipTokens[c.id] = randomToken(32);

  const { freigabe, approvals } = await repo.createFreigabe({
    /* Leer heisst: die Ablage vergibt „Freigabe <laufende Nummer>". Die Nummer kennt erst sie. */
    name,
    clipIds: clips.map((c) => c.id),
    guest_email: guestEmail || null,
    message,
    token,
    expires_at: expiresAt,
    clipTokens,
  });
  const link = `${await appBaseUrl()}/freigabe/${token}`;

  let mail = { delivered: false, logged: false };
  if (guestEmail) {
    mail = await sendGuestApprovalMail({
      to: guestEmail,
      guestName: freigabe.name,
      requestedBy: auth.displayName,
      workspaceName: auth.workspaceName,
      sourceTitle: `${clips.length} ${clips.length === 1 ? "Clip" : "Clips"}`,
      message,
      link,
      expiresAt,
    });
  }

  await repo.audit({
    action: "guest_approval.requested",
    entity: "freigaben",
    entity_id: freigabe.id,
    payload: {
      clips: clips.length,
      guest_email: guestEmail || null,
      expires_at: expiresAt,
      mail_delivered: mail.delivered,
      mail_logged: mail.logged,
    },
  });

  return Response.json({ ok: true, freigabe, approvals, link, mail }, { status: 201 });
}

/* GET: die Freigaben dieses Arbeitsbereichs, für die Seite „Meine Freigaben". */
export async function GET() {
  const auth = await requireApiRole("guest_approval.request");
  if (auth instanceof Response) return auth;
  const freigaben = await getRepo().listFreigaben();
  return Response.json({ freigaben });
}
