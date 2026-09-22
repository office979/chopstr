"use client";

import { useId, useState } from "react";
import { Input } from "./Field";
import { cn } from "./cn";
import { contrastVerdict, formatRatio, normalizeHex } from "@/lib/color";

interface ColorFieldProps {
  id: string;
  name: string;
  label: string;
  defaultValue?: string;
  hint?: string;
  error?: string;
  disabled?: boolean;
}

/* Hex-Feld mit Farbvorschau und WCAG-AA-Prüfung gegen Weiß und Schwarz (4,5 : 1 für normalen Text) */
export function ColorField({ id, name, label, defaultValue = "", hint, error, disabled }: ColorFieldProps) {
  const [value, setValue] = useState(defaultValue);
  const hintId = useId();
  const hex = normalizeHex(value);
  const verdict = hex ? contrastVerdict(hex) : null;
  const invalid = value.trim() !== "" && !hex;

  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="text-sm font-medium text-text">
        {label}
      </label>
      <div className="flex items-center gap-3">
        <span
          aria-hidden="true"
          className="flex h-12 w-12 shrink-0 items-center justify-center rounded-inner border border-line-strong font-mono text-xs"
          style={{ background: hex ?? "transparent", color: verdict?.textOn === "white" ? "#fff" : "#000" }}
        >
          {hex ? "Aa" : ""}
        </span>
        <Input
          id={id}
          name={name}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="#020cf5"
          spellCheck={false}
          autoComplete="off"
          disabled={disabled}
          aria-invalid={invalid || Boolean(error) || undefined}
          aria-describedby={hintId}
          className="font-mono"
        />
      </div>
      <p id={hintId} className={cn("text-sm", error || invalid ? "text-attention" : "text-text-2")} role={error || invalid ? "alert" : undefined}>
        {error
          ? error
          : invalid
            ? "Bitte einen Hex-Wert wie #020cf5 angeben."
            : verdict
              ? `Text auf dieser Fläche: Weiß ${formatRatio(verdict.white)} ${verdict.aaOnWhite ? "(AA)" : "(unter AA)"}, Schwarz ${formatRatio(verdict.black)} ${verdict.aaOnBlack ? "(AA)" : "(unter AA)"}.`
              : (hint ?? "Hex-Wert, zum Beispiel #020cf5.")}
      </p>
      {verdict && !verdict.aaOnWhite && !verdict.aaOnBlack && (
        <p className="text-sm text-attention">Weder auf Weiß noch auf Schwarz AA-lesbar. Für Captions und Bauchbinde nur als Akzent nutzen.</p>
      )}
    </div>
  );
}
