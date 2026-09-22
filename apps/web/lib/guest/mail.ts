import "server-only";
import { sendMail, type MailResult } from "@/lib/auth/mail";

/* E-Mail an den Gast mit dem Freigabe-Link (oder Konsole ohne SMTP) */
export async function sendGuestApprovalMail(args: {
  to: string;
  guestName: string;
  requestedBy: string;
  workspaceName: string;
  sourceTitle: string;
  message: string;
  link: string;
  expiresAt: string;
}): Promise<MailResult> {
  const until = new Date(args.expiresAt).toLocaleDateString("de-AT", { day: "2-digit", month: "2-digit", year: "numeric" });
  const text = [
    `Hallo ${args.guestName},`,
    "",
    `${args.requestedBy} (${args.workspaceName}) bittet dich um die Freigabe eines Clips aus „${args.sourceTitle}“.`,
    "",
    args.message ? `Nachricht: ${args.message}` : null,
    args.message ? "" : null,
    `Clip ansehen und entscheiden: ${args.link}`,
    "",
    `Der Link ist bis ${until} gültig. Du brauchst kein Konto.`,
    "",
    "chopstr · EU-verarbeitet · Mensch gibt frei",
  ]
    .filter((l) => l != null)
    .join("\n");
  return sendMail({ to: args.to, subject: `Freigabe angefragt: Clip aus „${args.sourceTitle}“`, text, link: args.link });
}
