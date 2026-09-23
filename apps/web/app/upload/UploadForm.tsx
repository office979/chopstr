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
  maxBytes: number;
  tusEndpoint: string;
  demoUpload: boolean;
  /* direct: POST /api/uploads/direct (lokaler Testmodus ohne tusd), tus: fortsetzbarer tus-Upload */
  uploadMode?: "tus" | "direct";
  /* Ohne Temporal holt der lokale Worker die Quelle per Polling ab */
  localWorker?: boolean;
}

type Phase = "form" | "uploading" | "finishing" | "done" | "error";

class UploadTokenError extends Error {}
/* Fehler der direkten Route (Kontingent, Rolle, Validierung): anzeigen, nicht simulieren */
class DirectUploadError extends Error {}

const RIGHTS_TEXT =
  "Ich bestätige: Ich darf dieses Video bearbeiten und veröffentlichen.";

const ACCEPT = "video/mp4,video/quicktime,video/x-matroska,video/webm,audio/mpeg,audio/wav,audio/x-m4a,.mp4,.mov,.mkv,.webm,.mp3,.wav,.m4a";

export function UploadForm({ profiles, maxBytes, tusEndpoint, demoUpload, uploadMode = "tus", localWorker = false }: Props) {
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
    if (!String(fd.get("title") ?? "").trim()) errs.title = "Gib dem Video einen Namen.";
    if (!file) errs.file = "Wähle eine Datei aus.";
    if (!confirmed) errs.rights_confirmed = "Setz unten den Haken, sonst geht es nicht weiter.";
    if (rights === "third_party" && !String(fd.get("source_owner") ?? "").trim()) {
      errs.source_owner = "Schreib dazu, von wem das Video ist.";
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

  /* Upload-Token vom Server (prüft Rolle und Stundenkontingent); der tusd-Hook verifiziert die Signatur */
  const fetchUploadToken = async (brandProfileId: string | null): Promise<string> => {
    const res = await fetch("/api/uploads/token", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ brand_profile_id: brandProfileId }),
    });
    const json = (await res.json().catch(() => ({}))) as { upload_token?: string; error?: string };
    if (!res.ok || !json.upload_token) {
      throw new UploadTokenError(json.error ?? `Upload-Token konnte nicht geholt werden (${res.status}).`);
    }
    return json.upload_token;
  };

  const realUpload = async (data: ReturnType<typeof collect>, clientRef: string) => {
    if (!file) return;
    const uploadToken = await fetchUploadToken(data.brand_profile_id);
    const { Upload } = await import("tus-js-client");
    const metadata: Record<string, string> = {
      upload_token: uploadToken,
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

  /* Lokaler Testmodus: multipart per XMLHttpRequest (Fortschritt über upload.onprogress), Datei als letztes Feld */
  const directUpload = async (data: ReturnType<typeof collect>, clientRef: string): Promise<string> => {
    if (!file) throw new DirectUploadError("Bitte eine Datei auswählen.");
    const fd = new FormData();
    fd.append("client_ref", clientRef);
    fd.append("brand_profile_id", data.brand_profile_id ?? "");
    fd.append("title", data.title);
    fd.append("rights_status", rights);
    fd.append("rights_confirmed", "true");
    fd.append("expected_speakers", data.expected_speakers != null ? String(data.expected_speakers) : "");
    fd.append("brief_audience", data.brief_audience);
    fd.append("brief_wanted", data.brief_wanted);
    fd.append("brief_exclude", data.brief_exclude);
    fd.append("platform", data.platform);
    if (rights === "third_party") {
      fd.append("source_owner", data.source_owner);
      fd.append("source_title", data.source_title);
      fd.append("source_url", data.source_url);
    }
    fd.append("file", file, file.name);

    return new Promise<string>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/uploads/direct");
      xhr.responseType = "json";
      xhr.upload.onprogress = (ev) => {
        if (ev.lengthComputable) setProgress(Math.min(100, Math.round((ev.loaded / ev.total) * 100)));
      };
      xhr.upload.onload = () => {
        setProgress(100);
        setPhase("finishing");
      };
      xhr.onload = () => {
        const body = (xhr.response ?? {}) as { source_id?: string; error?: string };
        if (xhr.status >= 200 && xhr.status < 300 && body.source_id) resolve(body.source_id);
        else reject(new DirectUploadError(body.error ?? `Upload fehlgeschlagen (${xhr.status}).`));
      };
      xhr.onerror = () => reject(new DirectUploadError("Verbindung zum Server abgebrochen. Läuft der Dev-Server noch?"));
      xhr.onabort = () => reject(new DirectUploadError("Upload abgebrochen."));
      abortRef.current = { abort: () => xhr.abort() };
      xhr.send(fd);
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
    if (uploadMode === "direct") {
      try {
        const sourceId = await directUpload(data, clientRef);
        setPhase("done");
        router.push(`/projekte/${sourceId}`);
      } catch (err) {
        setPhase("error");
        setNote(err instanceof Error ? err.message : String(err));
      }
      return;
    }

    try {
      await realUpload(data, clientRef);
      setPhase("done");
      router.push(`/projekte/${clientRef}`);
    } catch (err) {
      /* Endpoint nicht erreichbar: auf Simulation ausweichen, damit die App bedienbar bleibt.
       * Token-Fehler (403 Rolle, 402 Kontingent) werden angezeigt, nicht simuliert. */
      const message = err instanceof Error ? err.message : String(err);
      const unreachable = !(err instanceof UploadTokenError) && /failed to fetch|network|ECONNREFUSED|Load failed|tus: failed to create upload/i.test(message);
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
        <h2 className="text-lg font-medium">Dein Video</h2>
        <Field label="Wie soll es heißen?" htmlFor="title" required error={errors.title}>
          <Input id="title" name="title" placeholder="z. B. Podcast Folge 13: Preise im Handwerk" required disabled={busy} />
        </Field>
        <Field label="Aussehen" htmlFor="brand_profile_id" hint="Bestimmt Farben, Schrift und wie die Untertitel aussehen.">
          <Select id="brand_profile_id" name="brand_profile_id" defaultValue={profiles[0]?.id ?? ""} disabled={busy}>
            {profiles.length === 0 && <option value="">Noch keines angelegt</option>}
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
        </Field>

        <Field
          label="Datei"
          htmlFor="file"
          required
          error={errors.file}
          hint={`Video oder Audio, maximal ${formatBytes(maxBytes)}. ${uploadMode === "direct" ? "Der Upload läuft in einem Stück." : "Der Upload ist fortsetzbar."}`}
        >
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
        <h2 className="text-lg font-medium">Darfst du das Video verwenden?</h2>
        <Field label="Wem gehört das Video?" htmlFor="rights_status">
          <Select id="rights_status" name="rights_status" value={rights} onChange={(e) => setRights(e.target.value as RightsStatus)} disabled={busy}>
            <option value="own">Mir selbst</option>
            <option value="licensed">Jemand anderem, ich habe die Erlaubnis</option>
            <option value="third_party">Jemand anderem, ich zitiere nur daraus</option>
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
        <h2 className="text-lg font-medium">Wünsche</h2>
        <p className="-mt-2 text-sm text-text-2">
          Kannst du leer lassen. Wenn du etwas einträgst, sucht der Computer gezielter.
        </p>
        <div className="grid gap-5 sm:grid-cols-2">
          <Field label="Wie viele Personen sprechen?" htmlFor="expected_speakers" hint="Hilft beim Auseinanderhalten der Stimmen.">
            <Input id="expected_speakers" name="expected_speakers" type="number" min={1} max={12} defaultValue={2} disabled={busy} />
          </Field>
          <Field label="Wo soll es hin?" htmlFor="platform">
            <Select id="platform" name="platform" defaultValue={profiles[0]?.platform ?? "linkedin"} disabled={busy}>
              <option value="linkedin">LinkedIn</option>
              <option value="tiktok">TikTok</option>
              <option value="reels">Instagram Reels</option>
              <option value="shorts">YouTube Shorts</option>
            </Select>
          </Field>
        </div>
        <Field label="Wer soll das sehen?" htmlFor="brief_audience">
          <Input id="brief_audience" name="brief_audience" placeholder="z. B. Geschäftsführung im Mittelstand" disabled={busy} />
        </Field>
        <Field label="Was muss unbedingt rein?" htmlFor="brief_wanted">
          <Textarea id="brief_wanted" name="brief_wanted" placeholder="z. B. Zahlen zu Vakanzkosten, klare Thesen" disabled={busy} />
        </Field>
        <Field label="Was soll auf keinen Fall rein?" htmlFor="brief_exclude">
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
                  <span className="ml-2 text-text-2">
                    {localWorker && !demoUpload ? "läuft gleich" : "startet nach dem Hochladen"}
                  </span>
                </div>
              </li>
            ))}
          </ol>
          {note && <p className={cn("mt-4 text-sm", phase === "error" ? "text-attention" : "text-text-2")}>{note}</p>}
          {phase === "finishing" && (
            <p className="mt-4 text-sm text-text-2">
              {uploadMode === "direct" ? "Datei ist da, wird gerade geprüft und angelegt" : "Wird angelegt"}
            </p>
          )}
        </GlassCard>
      )}

      <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
        {/* Hier stand, wie der Server eingerichtet ist (tusd, Temporal, Zieladresse). Das hilft beim
         * Einrichten, nicht beim Hochladen, und ist für alle anderen nur Lärm. Übrig bleibt der eine
         * Satz, der wirklich etwas über das eigene Video sagt: zum Ausprobieren wird nichts gespeichert. */}
        <p className="text-sm text-text-2">
          {demoUpload ? "Zum Ausprobieren: Dein Video wird nicht wirklich gespeichert." : ""}
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
            {phase === "uploading" ? "Wird hochgeladen" : phase === "finishing" ? "Fast fertig" : "Los geht's"}
          </Button>
        </div>
      </div>
    </form>
  );
}
