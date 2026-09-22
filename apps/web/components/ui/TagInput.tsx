"use client";

import { useId, useState, type KeyboardEvent } from "react";
import { cn } from "./cn";

interface TagInputProps {
  id: string;
  name: string;
  defaultValue?: string[];
  value?: string[];
  onChange?: (tags: string[]) => void;
  placeholder?: string;
  max?: number;
  className?: string;
}

/* Tag-Eingabe: Enter oder Komma fügt hinzu, Backspace entfernt das letzte. Werte gehen als versteckte Inputs mit. */
export function TagInput({ id, name, defaultValue = [], value, onChange, placeholder, max, className }: TagInputProps) {
  const [internal, setInternal] = useState<string[]>(defaultValue);
  const [draft, setDraft] = useState("");
  const listId = useId();
  const tags = value ?? internal;

  const update = (next: string[]) => {
    if (value === undefined) setInternal(next);
    onChange?.(next);
  };

  const commit = () => {
    const parts = draft
      .split(",")
      .map((p) => p.trim())
      .filter(Boolean);
    if (parts.length === 0) return;
    let next = [...tags];
    for (const p of parts) {
      if (!next.includes(p) && (max == null || next.length < max)) next.push(p);
    }
    next = next.slice(0, max ?? next.length);
    update(next);
    setDraft("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      commit();
    } else if (e.key === "Backspace" && draft === "" && tags.length > 0) {
      update(tags.slice(0, -1));
    }
  };

  const full = max != null && tags.length >= max;

  return (
    <div
      className={cn(
        "transition-soft flex min-h-12 flex-wrap items-center gap-2 rounded-inner border border-line bg-black/40 px-3 py-2 hover:border-line-strong focus-within:border-white/50",
        className,
      )}
    >
      <ul id={listId} className="contents" aria-label="Einträge">
        {tags.map((tag) => (
          <li key={tag} className="inline-flex h-8 items-center gap-1 rounded-pill border border-line-strong pl-3 pr-1 text-sm text-text">
            <span>{tag}</span>
            <button
              type="button"
              aria-label={`${tag} entfernen`}
              onClick={() => update(tags.filter((t) => t !== tag))}
              className="inline-flex h-6 w-6 items-center justify-center rounded-full text-text-2 hover:bg-white/10 hover:text-text"
            >
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
                <path d="M1.5 1.5l7 7M8.5 1.5l-7 7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
              </svg>
            </button>
            <input type="hidden" name={name} value={tag} />
          </li>
        ))}
      </ul>
      <input
        id={id}
        type="text"
        value={draft}
        disabled={full}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={commit}
        placeholder={full ? "Maximum erreicht" : placeholder ?? "Eingabe, dann Enter"}
        aria-describedby={listId}
        className="min-w-32 flex-1 bg-transparent py-1 text-[15px] text-text placeholder:text-text-3 focus:outline-none disabled:opacity-60"
      />
    </div>
  );
}
