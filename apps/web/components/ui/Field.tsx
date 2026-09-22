import type { ComponentProps, ReactNode } from "react";
import { cn } from "./cn";

const control =
  "transition-soft w-full rounded-inner border border-line bg-black/40 px-4 py-3 text-[15px] text-text placeholder:text-text-3 hover:border-line-strong focus:border-white/50 focus:outline-none disabled:opacity-60";

interface FieldProps {
  label: string;
  htmlFor: string;
  hint?: ReactNode;
  error?: string;
  required?: boolean;
  children: ReactNode;
  className?: string;
}

/* Feld mit sichtbarem Label, optionalem Hinweis und Fehlertext */
export function Field({ label, htmlFor, hint, error, required, children, className }: FieldProps) {
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <label htmlFor={htmlFor} className="text-sm font-medium text-text">
        {label}
        {required && <span className="ml-1 text-text-2" aria-hidden="true">*</span>}
      </label>
      {children}
      {hint && !error && <p className="text-sm text-text-2">{hint}</p>}
      {error && (
        <p className="text-sm text-attention" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export function Input({ className, ...rest }: ComponentProps<"input">) {
  return <input className={cn(control, className)} {...rest} />;
}

export function Textarea({ className, ...rest }: ComponentProps<"textarea">) {
  return <textarea className={cn(control, "min-h-24 resize-y", className)} {...rest} />;
}

export function Select({ className, children, ...rest }: ComponentProps<"select">) {
  return (
    <div className="relative">
      <select className={cn(control, "appearance-none pr-10", className)} {...rest}>
        {children}
      </select>
      <svg
        aria-hidden="true"
        className="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2 text-text-2"
        width="14"
        height="14"
        viewBox="0 0 16 16"
        fill="none"
      >
        <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  );
}

export function Checkbox({ className, ...rest }: ComponentProps<"input">) {
  return (
    <input
      type="checkbox"
      className={cn(
        "mt-0.5 h-5 w-5 shrink-0 cursor-pointer appearance-none rounded-md border border-line-strong bg-black/40 checked:border-white checked:bg-text",
        "bg-center bg-no-repeat checked:bg-[url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none'%3E%3Cpath d='M3.5 8.5l3 3 6-7' stroke='%23000' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E\")]",
        className,
      )}
      {...rest}
    />
  );
}
