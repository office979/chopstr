import "server-only";
import { isDevelopment } from "@/lib/auth/cookies";

/* E-Mail-Versand über SMTP (nodemailer, SMTP_URL und MAIL_FROM). Ohne SMTP_URL in der Entwicklung wird die
 * Nachricht samt Link in der Serverkonsole ausgegeben; die UI zeigt dann den Hinweis
 * „Link wurde in der Serverkonsole ausgegeben“ (MailResult.logged). */

export interface MailMessage {
  to: string;
  subject: string;
  text: string;
  /* Link, der in der Konsole hervorgehoben wird */
  link?: string;
}

export interface MailResult {
  delivered: boolean;
  logged: boolean;
}

export async function sendMail(message: MailMessage): Promise<MailResult> {
  const smtpUrl = process.env.SMTP_URL;
  const from = process.env.MAIL_FROM ?? "chopstr <no-reply@chopstr.local>";

  if (!smtpUrl) {
    if (!isDevelopment()) {
      console.error(`[mail] SMTP_URL fehlt, Nachricht an ${message.to} (${message.subject}) nicht zugestellt`);
    }
    console.info(
      [
        "",
        `[mail] (kein SMTP) An: ${message.to}`,
        `[mail] Betreff: ${message.subject}`,
        ...message.text.split("\n").map((line) => `[mail] ${line}`),
        message.link ? `[mail] LINK: ${message.link}` : null,
        "",
      ]
        .filter((l) => l != null)
        .join("\n"),
    );
    return { delivered: false, logged: true };
  }

  const nodemailer = await import("nodemailer");
  const transport = nodemailer.createTransport(smtpUrl);
  await transport.sendMail({ from, to: message.to, subject: message.subject, text: message.text });
  return { delivered: true, logged: false };
}
