/* Gemeinsamer Zustand für Formulare mit Server Actions (useActionState) */
export interface FormState {
  ok: boolean;
  message: string;
  errors: Record<string, string>;
  /* Zusatzhinweis, z. B. „Link wurde in der Serverkonsole ausgegeben“ */
  hint?: string;
}

export const initialFormState: FormState = { ok: false, message: "", errors: {} };

export function field(formData: FormData, name: string, max = 200): string {
  const v = formData.get(name);
  return typeof v === "string" ? v.trim().slice(0, max) : "";
}

export const CONSOLE_LINK_HINT = "Link wurde in der Serverkonsole ausgegeben (kein SMTP konfiguriert).";
