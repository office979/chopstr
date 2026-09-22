import { cn } from "./cn";
import type { FormState } from "@/lib/auth/form";

/* Ergebnis einer Server Action: Erfolg in Weiß, Fehler in Orange (Mensch muss prüfen), Hinweis grau */
export function FormNotice({ state, className }: { state: FormState; className?: string }) {
  if (!state.message && !state.hint) return null;
  return (
    <div className={cn("flex flex-col gap-1", className)} role={state.ok ? "status" : "alert"} aria-live="polite">
      {state.message && <p className={cn("text-sm", state.ok ? "text-text" : "text-attention")}>{state.message}</p>}
      {state.hint && <p className="font-mono text-xs text-text-2">{state.hint}</p>}
    </div>
  );
}
