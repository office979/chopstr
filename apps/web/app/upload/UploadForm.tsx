"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type DragEvent, type FormEvent } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Field, Input, Select, Checkbox } from "@/components/ui/Field";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { cn } from "@/components/ui/cn";
import { formatBytes } from "@/lib/format";
import type { Platform, RightsStatus } from "@/lib/repo/types";
import { createDemoProject } from "./actions";

interface Props {
  profiles: { id: string; name: string; platform: Platform }[];
  maxBytes: number;
  tusEndpoint: string;
  demoUpload: boolean;
  /* direct: POST /api/uploads/direct (lokaler Testmodus ohne tusd), tus: fortsetzbarer tus-Upload */
  uploadMode?: "tus" | "direct";
}

type Phase = "form" | "uploading" | "finishing" | "done" | "error";

class UploadTokenError extends Error {}
/* Fehler der direkten Route (Kontingent, Rolle, Validierung): anzeigen, nicht simulieren */
class DirectUploadError extends Error {}

const RIGHTS_TEXT = "Ich darf dieses Video bearbeiten und veröffentlichen.";

const ACCEPT = "video/mp4,video/quicktime,video/x-matroska,video/webm,audio/mpeg,audio/wav,audio/x-m4a,.mp4,.mov,.mkv,.webm,.mp3,.wav,.m4a";

/* Eine Box, vier Dinge: Name, Stil, Video, Haken. Alles andere (wem das Video gehört, Quellenangabe)
 * liegt hinter „Mehr anzeigen“ — es betrifft wenige und darf den Weg nicht verlängern.
 *
 * Die Felder aus dem Fenster laufen über React-State, nicht über FormData: der Dialog hängt per
 * Portal an document.body und gehört damit nicht mehr zum <form>. */
export function UploadForm({ profiles, maxBytes, tusEndpoint, demoUpload, uploadMode = "tus" }: Props) {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [rights, setRights] = useState<RightsStatus>("own");
  const [sourceOwner, setSourceOwner] = useState("");
  const [sourceTitle, setSourceTitle] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [phase, setPhase] = useState<Phase>("form");
  const [progress, setProgress] = useState(0);
  const [note, setNote] = useState<string>("");
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
    if (!confirmed) errs.rights_confirmed = "Setz den Haken, sonst geht es nicht weiter.";
    if (rights === "third_party" && !sourceOwner.trim()) {
      errs.source_owner = "Schreib dazu, von wem das Video ist.";
    }
    return errs;
  };

  const collect = (fd: FormData) => ({
    title: String(fd.get("title") ?? "").trim(),
    brand_profile_id: String(fd.get("brand_profile_id") ?? "") || null,
    source_owner: sourceOwner.trim(),
    source_title: sourceTitle.trim(),
    source_url: sourceUrl.trim(),
  });

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
    setNote("Zum Ausprobieren: Dein Video wird nicht wirklich gespeichert.");
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
    /* Zielgruppe, Wünsche, Plattform und Sprecherzahl werden nicht mehr erhoben. Der Server
     * behandelt sie als optional: fehlende Felder werden zu null beziehungsweise undefined. */
    const metadata: Record<string, string> = {
      upload_token: uploadToken,
      brand_profile_id: data.brand_profile_id ?? "",
      title: data.title,
      filename: file.name,
      filetype: file.type || "application/octet-stream",
      rights_status: rights,
      rights_confirmed: "true",
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
    /* Fehlt die Quellenangabe, steht sie hinter „Mehr anzeigen“ — dann geht das Fenster auf, sonst
     * sucht jemand einen Fehler, den er gar nicht sehen kann. */
    if (errs.source_owner) setDetailsOpen(true);
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

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate aria-busy={busy}>
      <GlassCard padding="lg" className="flex flex-col gap-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name" htmlFor="title" required error={errors.title}>
            <Input id="title" name="title" placeholder="z. B. Podcast Folge 13" required disabled={busy} />
          </Field>
          <Field label="Stil" htmlFor="brand_profile_id">
            <Select id="brand_profile_id" name="brand_profile_id" defaultValue={profiles[0]?.id ?? ""} disabled={busy}>
              {profiles.length === 0 && <option value="">Noch keiner angelegt</option>}
              {profiles.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        <Field label="Video" htmlFor="file" required error={errors.file} hint={`Video oder Audio, maximal ${formatBytes(maxBytes)}.`}>
          <div
            onDragOver={(e) => {
              e.preventDefault();
              if (!busy) setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={busy ? undefined : onDrop}
            className={cn(
              "transition-soft flex flex-col items-center justify-center gap-2 rounded-inner border border-dashed px-6 py-6 text-center",
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
                <p className="text-sm text-text-2">{formatBytes(file.size)}</p>
              </>
            ) : (
              <p className="text-text">Datei hierher ziehen</p>
            )}
            <Button type="button" variant="ghost" size="sm" onClick={() => fileInputRef.current?.click()} disabled={busy}>
              {file ? "Andere Datei wählen" : "Datei auswählen"}
            </Button>
          </div>
        </Field>

        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
            <label className="flex cursor-pointer items-start gap-3">
              <Checkbox
                id="rights_confirmed"
                name="rights_confirmed"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
                disabled={busy}
                required
              />
              <span className="text-sm text-text">{RIGHTS_TEXT}</span>
            </label>
            <button
              type="button"
              onClick={() => setDetailsOpen(true)}
              disabled={busy}
              className="transition-soft text-sm text-text-2 underline-offset-4 hover:text-text hover:underline disabled:opacity-60"
            >
              Mehr anzeigen
            </button>
          </div>
          {errors.rights_confirmed && (
            <p className="text-sm text-attention" role="alert">
              {errors.rights_confirmed}
            </p>
          )}
        </div>

        {/* Beim Absenden nur der eine Balken. Was danach kommt, steht auf der nächsten Seite; hier
         * wäre es eine Liste mit Dingen, die noch gar nicht laufen. */}
        {phase !== "form" && (
          <div aria-live="polite" className="flex flex-col gap-2 border-t border-line pt-4">
            <div className="flex justify-between text-sm">
              <span className="font-medium text-text">
                {phase === "finishing" || phase === "done" ? "Fast fertig" : phase === "error" ? "Es hat nicht geklappt" : "Wird hochgeladen"}
              </span>
              <span className="font-mono text-text-2">{progress} %</span>
            </div>
            <div
              className="h-1 w-full overflow-hidden rounded-pill bg-white/10"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={progress}
              aria-label="Upload"
            >
              <div className="transition-soft h-full rounded-pill bg-text" style={{ width: `${progress}%` }} />
            </div>
            {note && <p className={cn("text-sm", phase === "error" ? "text-attention" : "text-text-2")}>{note}</p>}
          </div>
        )}
      </GlassCard>

      <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
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

      <Modal
        open={detailsOpen}
        onClose={() => setDetailsOpen(false)}
        title="Wem gehört das Video?"
        description="Voreingestellt ist: es ist deins. Nur wenn du daraus zitierst, brauchen wir eine Quelle."
      >
        <div className="flex flex-col gap-5">
          <Field label="Wem gehört das Video?" htmlFor="rights_status">
            <Select id="rights_status" value={rights} onChange={(e) => setRights(e.target.value as RightsStatus)} disabled={busy}>
              <option value="own">Mir selbst</option>
              <option value="licensed">Jemand anderem, ich habe die Erlaubnis</option>
              <option value="third_party">Jemand anderem, ich zitiere nur daraus</option>
            </Select>
          </Field>
          {rights === "third_party" && (
            <>
              <Field label="Urheber oder Quelle" htmlFor="source_owner" required error={errors.source_owner}>
                <Input id="source_owner" value={sourceOwner} onChange={(e) => setSourceOwner(e.target.value)} disabled={busy} />
              </Field>
              <Field label="Titel des Originals" htmlFor="source_title">
                <Input id="source_title" value={sourceTitle} onChange={(e) => setSourceTitle(e.target.value)} disabled={busy} />
              </Field>
              <Field label="URL" htmlFor="source_url">
                <Input id="source_url" type="url" placeholder="https://" value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} disabled={busy} />
              </Field>
            </>
          )}
          <div className="flex justify-end">
            <Button type="button" onClick={() => setDetailsOpen(false)}>
              Übernehmen
            </Button>
          </div>
        </div>
      </Modal>
    </form>
  );
}
