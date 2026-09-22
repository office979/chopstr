"use client";

import { cn } from "./cn";

interface ToggleProps {
  checked: boolean;
  onChange?: (next: boolean) => void;
  label: string;
  description?: string;
  disabled?: boolean;
  name?: string;
  className?: string;
}

/* Toggle: weiß (an) / schwarz (aus). Als Switch mit sichtbarem Label. */
export function Toggle({ checked, onChange, label, description, disabled, name, className }: ToggleProps) {
  return (
    <label className={cn("flex cursor-pointer items-start gap-3", disabled && "cursor-not-allowed opacity-70", className)}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange?.(!checked)}
        className={cn(
          "transition-soft relative mt-0.5 inline-flex h-6 w-11 shrink-0 items-center rounded-pill border",
          checked ? "border-white bg-text" : "border-line-strong bg-black",
        )}
      >
        <span
          className={cn(
            "transition-soft absolute top-[3px] h-4 w-4 rounded-full",
            checked ? "left-[23px] bg-black" : "left-[3px] bg-text",
          )}
        />
      </button>
      {name && <input type="hidden" name={name} value={checked ? "true" : "false"} />}
      <span className="flex flex-col">
        <span className="text-sm font-medium text-text">{label}</span>
        {description && <span className="text-sm text-text-2">{description}</span>}
      </span>
    </label>
  );
}
