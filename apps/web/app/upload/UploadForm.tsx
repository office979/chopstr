"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type DragEvent, type FormEvent } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Field, Input, Select, Textarea, Checkbox } from "@/components/ui/Field";
import { Button } from "@/components/ui/Button";
import { StatusCheck, type StatusCheckState } from "@/components/ui/StatusCheck";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/components/ui/cn";
import { formatBytes } from "@/lib/format";
import { PIPELINE_STEPS } from "@/lib/pipeline";
import type { Platform, RightsStatus } from "@/lib/repo/types";
import { createDemoProject } from "./actions";

interface Props {
  profiles: { id: string; name: string; platform: Platform }[];
  workspaceId: string;
  maxBytes: number;
  tusEndpoint: string;
  demoUpload: boolean;
}

type Phase = "form" | "uploading" | "finishing" | "done" | "error";

const RIGHTS_TEXT =
  "Ich bestätige, dass ich die Rechte an diesem Material besitze oder eine Lizenz habe, es zu bearbeiten und zu veröffentlichen.";

const ACCEPT = "video/mp4,video/quicktime,video/x-matroska,video/webm,audio/mpeg,audio/wav,audio/x-m4a,.mp4,.mov,.mkv,.webm,.mp3,.wav,.m4a";

export function UploadForm({ profiles, workspaceId, maxBytes, tusEndpoint, demoUpload }: Props) {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [rights, setRights] = useState<RightsStatus>("own");
  const [confirmed, setConfirmed] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [phase, setPhase] = useState<Phase>("form");
  const [progress, setProgress] = useState(0);
  const [note, setNote] = useState<string>("");
  const [simulated, setSimulated] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<{ abort: () => void } | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const chooseFile = (f: File | null) => {
    if (!f) return;
    if (f.size > maxBytes) {
      setErrors((e) => ({ ...e, file: `Datei zu groß (${formatBytes(f.size)}). Maximal ${formatBytes(maxBytes)}.` }));
      setFile(null);
      return;
    }
    setErrors((e) => {
      const rest = { ...e };
      delete rest.file;
      return rest;
    });
    setFile(f);
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    chooseFile(e.dataTransfer.files?.[0] ?? null);
  };

  const validate = (fd: FormData): Record<string, string> => {
    const errs: Record<string, string> = {};
    if (!String(fd.get("title") ?? "").trim()) errs.title = "Bitte einen Titel angeben.";
    if (!file) errs.file = "Bitte eine Datei auswählen.";
    if (!confirmed) errs.rights_confirmed = "Ohne Bestätigung der Rechte ist kein Upload möglich.";
    if (rights === "third_party" && !String(fd.get("source_owner") ?? "").trim()) {
      errs.source_owner = "Bei Fremdmaterial ist die Quellenangabe Pflicht.";
    }
    return errs;
  };

  const collect = (fd: FormData) => {
    const platform = String(fd.get("platform") ?? "") as Platform | "";
    const expectedRaw = Number(fd.get("expected_speakers"));
    return {
      title: String(fd.get("title") ?? "").trim(),
      brand_profile_id: String(fd.get("brand_profile_id") ?? "") || null,
      expected_speakers: Number.isFinite(expectedRaw) && expectedRaw > 0 ? Math.round(expectedRaw) : null,
      brief_audience: String(fd.get("brief_audience") ?? "").trim(),
      brief_wanted: String(fd.get("brief_wanted") ?? "").trim(),
      brief_exclude: String(fd.get("brief_exclude") ?? "").trim(),
      platform,
      source_owner: String(fd.get("source_owner") ?? "").trim(),
      source_title: String(fd.get("source_title") ?? "").trim(),
      source_url: String(fd.get("source_url") ?? "").trim(),
    };
  };

  const finishDemo = async (data: ReturnType<typeof collect>) => {
    if (!file) return;
    setPhase("finishing");
    const result = await createDemoProject({
      ...data,
      filename: file.name,
      filetype: file.type || "application/octet-stream",
      size_bytes: file.size,
      rights_status: rights,
      rights_confirmed: confirmed,
    });
    if ("error" in result) {
      setPhase("error");
      setNote(result.error);
      return;
    }
    setPhase("done");
    router.push(`/projekte/${result.id}`);
  };

  const simulateUpload = async (data: ReturnType<typeof collect>) => {
    setSimulated(true);
    setNote("Demo-Modus: Der Upload wird simuliert, es wird keine Datei übertragen.");
    let cancelled = false;
    abortRef.current = { abort: () => (cancelled = true) };
    for (let p = 0; p <= 100 && !cancelled; p += 4) {
      setProgress(p);
      await new Promise((r) => setTimeout(r, 70));
    }
    if (!cancelled) await finishDemo(data);
  };

  const realUpload = async (data: ReturnType<typeof collect>, clientRef: string) => {
    if (!file) return;
    const { Upload } = await import("tus-js-client");
    const metadata: Record<string, string> = {
      workspace_id: workspaceId,
      brand_profile_id: data.brand_profile_id ?? "",
      title: data.title,
      filename: file.name,
      filetype: file.type || "application/octet-stream",
      rights_status: rights,
      rights_confirmed: "true",
      expected_speakers: data.expected_speakers != null ? String(data.expected_speakers) : "",
      brief_audience: data.brief_audience,
      brief_wanted: data.brief_wanted,
      brief_exclude: data.brief_exclude,
      platform: data.platform,
      client_ref: clientRef,
    };
    if (rights === "third_party") {
      metadata.source_owner = data.source_owner;
      metadata.source_title = data.source_title;
      metadata.source_url = data.source_url;
    }

    await new Promise<void>((resolve, reject) => {
      const upload = new Upload(file, {
        endpoint: tusEndpoint,
        chunkSize: 8 * 1024 * 1024,
        retryDelays: [0, 1000, 3000, 5000],
        metadata,
        onError: (err) => reject(err),
        onProgress: (sent, total) => setProgress(Math.round((sent / total) * 100)),
        onSuccess: () => resolve(),
      });
      abortRef.current = { abort: () => void upload.abort() };
      upload.start();
    });
  };

  const onSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const errs = validate(fd);
    setErrors(errs);
    if (Object.keys(errs).length > 0 || !file) return;

    const data = collect(fd);
    setPhase("uploading");
    setProgress(0);
    setNote("");

    if (demoUpload) {
      await simulateUpload(data);
      return;
    }

    const clientRef = globalThis.crypto.randomUUID();
    try {
      await realUpload(data, clientRef);
      setPhase("done");
      router.push(`/projekte/${clientRef}`);
    } catch (err) {
      /* Endpoint nicht erreichbar: auf Simulation ausweichen, damit die App bedienbar bleibt */
      const message = err instanceof Error ? err.message : String(err);
      const unreachable = /failed to fetch|network|ECONNREFUSED|Load failed|tus: failed to create upload/i.test(message);
      if (unreachable) {
        await simulateUpload(data);
      } else {
        setPhase("error");
        setNote(message);
      }
    }
  };

  const busy = phase === "uploading" || phase === "finishing" || phase === "done";
  const uploadState: StatusCheckState = phase === "error" ? "error" : phase === "done" || phase === "finishing" ? "done" : phase === "uploading" ? "active" : "idle";

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-5" noValidate aria-busy={busy}>
      <GlassCard padding="lg" className="flex flex-col gap-5">
        <h2 className="text-lg font-medium">Material</h2>
        <Field label="Titel" htmlFor="title" required error={errors.title}>
          <Input id="title" name="title" placeholder="z. B. Podcast Folge 13: Preise im Handwerk" required disabled={busy} />
        </Field>
        <Field label="Markenprofil" htmlFor="brand_profile_id" hint="Steuert Anrede, Wörterbuch und Caption-Stil.">
          <Select id="brand_profile_id" name="brand_profile_id" defaultValue={profiles[0]?.id ?? ""} disabled={busy}>
            {profiles.length === 0 && <option value="">Kein Markenprofil angelegt</option>}
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
        </Field>

        <Field label="Datei" htmlFor="file" required error={errors.file} hint={`Video oder Audio, maximal ${formatBytes(maxBytes)}. Der Upload ist fortsetzbar.`}>
          <div
            onDragOver={(e) => {
              e.preventDefault();
              if (!busy) setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={busy ? undefined : onDrop}
            className={cn(
              "transition-soft flex flex-col items-center justify-center gap-3 rounded-inner border border-dashed px-6 py-8 text-center",
              dragging ? "border-white/70 bg-white/5" : "border-line-strong",
              file && "border-solid",
            )}
          >
            <input
              ref={fileInputRef}
              id="file"
              name="file"
              type="file"
              accept={ACCEPT}
              className="sr-only"
              disabled={busy}
              onChange={(e) => chooseFile(e.target.files?.[0] ?? null)}
            />
            {file ? (
              <>
                <p className="font-medium text-text">{file.name}</p>
                <p className="text-sm text-text-2">
                  {formatBytes(file.size)} · {file.type || "Typ unbekannt"}
                </p>
              </>
            ) : (
              <>
                <p className="text-text">Datei hierher ziehen</p>
                <p className="text-sm text-text-2">oder</p>
              </>
            )}
            <Button type="button" variant="ghost" size="sm" onClick={() => fileInputRef.current?.click()} disabled={busy}>
              {file ? "Andere Datei wählen" : "Datei auswählen"}
            </Button>
          </div>
        </Field>
      </GlassCard>

      <GlassCard padding="lg" className="flex flex-col gap-5">
        <h2 className="text-lg font-medium">Rechte</h2>
        <Field label="Rechtestatus" htmlFor="rights_status">
          <Select id="rights_status" name="rights_status" value={rights} onChange={(e) => setRights(e.target.value as RightsStatus)} disabled={busy}>
            <option value="own">Eigenes Material</option>
            <option value="licensed">Lizenziert</option>
            <option value="third_party">Fremdmaterial (Zitat, § 63 UrhG)</option>
          </Select>
        </Field>
        {rights === "third_party" && (
          <div className="grid gap-5 sm:grid-cols-2">
            <Field label="Urheber oder Quelle" htmlFor="source_owner" required error={errors.source_owner}>
              <Input id="source_owner" name="source_owner" disabled={busy} />
            </Field>
            <Field label="Titel des Originals" htmlFor="source_title">
              <Input id="source_title" name="source_title" disabled={busy} />
            </Field>
            <Field label="URL" htmlFor="source_url" className="sm:col-span-2">
              <Input id="source_url" name="source_url" type="url" placeholder="https://" disabled={busy} />
            </Field>
          </div>
        )}
        <div className="flex flex-col gap-2">
          <label className="flex cursor-pointer items-start gap-3">
            <Checkbox
              id="rights_confirmed"
              name="rights_confirmed"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
              disabled={busy}
              aria-describedby="rights_confirmed_hint"
              required
            />
            <span className="text-[15px] text-text">{RIGHTS_TEXT}</span>
          </label>
          {errors.rights_confirmed ? (
            <p className="text-sm text-attention" role="alert">
              {errors.rights_confirmed}
            </p>
          ) : (
            <p id="rights_confirmed_hint" className="text-sm text-text-2">
              Die Bestätigung wird mit Zeitstempel im Audit-Log gespeichert.
            </p>
          )}
        </div>
      </GlassCard>

      <GlassCard padding="lg" className="flex flex-col gap-5">
        <h2 className="text-lg font-medium">Redaktions-Briefing</h2>
        <div className="grid gap-5 sm:grid-cols-2">
          <Field label="Erwartete Sprecher" htmlFor="expected_speakers" hint="Hilft der Sprechertrennung.">
            <Input id="expected_speakers" name="expected_speakers" type="number" min={1} max={12} defaultValue={2} disabled={busy} />
          </Field>
          <Field label="Plattform" htmlFor="platform">
            <Select id="platform" name="platform" defaultValue={profiles[0]?.platform ?? "linkedin"} disabled={busy}>
              <option value="linkedin">LinkedIn</option>
              <option value="tiktok">TikTok</option>
              <option value="reels">Instagram Reels</option>
              <option value="shorts">YouTube Shorts</option>
            </Select>
          </Field>
        </div>
        <Field label="Zielgruppe" htmlFor="brief_audience">
          <Input id="brief_audience" name="brief_audience" placeholder="z. B. Geschäftsführung im Mittelstand" disabled={busy} />
        </Field>
        <Field label="Gewünschte Momente" htmlFor="brief_wanted" hint="Was soll auf jeden Fall in die Clips?">
          <Textarea id="brief_wanted" name="brief_wanted" placeholder="z. B. Zahlen zu Vakanzkosten, klare Thesen" disabled={busy} />
        </Field>
        <Field label="Ausschlüsse" htmlFor="brief_exclude" hint="Was darf nicht in die Clips?">
          <Textarea id="brief_exclude" name="brief_exclude" placeholder="z. B. Smalltalk am Anfang, Werbeblock" disabled={busy} />
        </Field>
      </GlassCard>

      {phase !== "form" && (
        <GlassCard padding="lg" selected={phase === "uploading"} aria-live="polite">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg font-medium">Fortschritt</h2>
            {simulated && <Badge tone="ai">Demo</Badge>}
          </div>
          <ol className="flex flex-col gap-4">
            <li className="flex items-center gap-4">
              <StatusCheck state={uploadState} size={32} />
              <div className="flex-1">
                <div className="flex justify-between text-sm">
                  <span className="font-medium text-text">Upload</span>
                  <span className="font-mono text-text-2">{progress} %</span>
                </div>
                <div className="mt-2 h-1 w-full overflow-hidden rounded-pill bg-white/10" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress} aria-label="Upload-Fortschritt">
                  <div className="transition-soft h-full rounded-pill bg-text" style={{ width: `${progress}%` }} />
                </div>
              </div>
            </li>
            {PIPELINE_STEPS.map((step) => (
              <li key={step.key} className={cn("flex items-center gap-4", step.phase === 2 && "opacity-50")}>
                <StatusCheck state="idle" size={32} />
                <div className="text-sm">
                  <span className="font-medium text-text">{step.label}</span>
                  <span className="ml-2 text-text-2">{step.phase === 2 ? "kommt in Phase 2" : "startet nach dem Upload"}</span>
                </div>
              </li>
            ))}
          </ol>
          {note && <p className={cn("mt-4 text-sm", phase === "error" ? "text-attention" : "text-text-2")}>{note}</p>}
          {phase === "finishing" && <p className="mt-4 text-sm text-text-2">Projekt wird angelegt</p>}
        </GlassCard>
      )}

      <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-text-2">
          {demoUpload ? "Demo-Modus aktiv: kein tusd, kein Temporal. Das Projekt entsteht im Speicher." : "Ziel: " + tusEndpoint}
        </p>
        <div className="flex gap-2">
          {phase === "uploading" && (
            <Button
              type="button"
              variant="danger"
              onClick={() => {
                abortRef.current?.abort();
                setPhase("form");
                setProgress(0);
              }}
            >
              Abbrechen
            </Button>
          )}
          <Button type="submit" disabled={busy || !confirmed}>
            {phase === "uploading" ? "Wird hochgeladen" : phase === "finishing" ? "Wird angelegt" : "Hochladen"}
          </Button>
        </div>
      </div>
    </form>
  );
}
