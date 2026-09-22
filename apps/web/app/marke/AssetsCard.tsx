"use client";

import { useId, useRef, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Field, Select, Checkbox } from "@/components/ui/Field";
import { Toggle } from "@/components/ui/Toggle";
import { Modal } from "@/components/ui/Modal";
import { cn } from "@/components/ui/cn";
import { fontFaceCss } from "@/components/clips/SilentPreview";
import type { BrandAsset, BrandAssetKind, BrandCI } from "@/lib/repo/types";
import { ASSET_KIND_LABELS, LICENSE_TEXT, allowedExtensions, extensionOf, fontFormat, maxBytesFor, validateAssetFile } from "@/lib/brand/assets";
import { formatBytes } from "@/lib/format";

interface Props {
  profileId: string | null;
  assets: BrandAsset[];
  ci: BrandCI;
  canUpload: boolean;
}

interface ApiResponse {
  error?: string;
  field?: string;
  asset?: BrandAsset;
  storage?: string;
  references_cleared?: boolean;
}

const UPLOAD_KINDS: { kind: BrandAssetKind; hint: string }[] = [
  { kind: "font", hint: "TTF, OTF oder WOFF2, max. 5 MB. Familienname und Gewicht werden aus der Datei gelesen." },
  { kind: "logo", hint: "SVG oder PNG, max. 2 MB. PNG mit Transparenz für das Wasserzeichen; SVG nur für die Vorschau." },
  { kind: "lower_third_bg", hint: "SVG oder PNG, max. 2 MB. Hintergrund der Bauchbinde." },
];

function assetUrl(profileId: string, asset: BrandAsset): string {
  return `/api/brand/${profileId}/assets/${asset.id}`;
}

/* Karte „Assets“ im Markenprofil: Upload (Lizenz-Checkbox Pflicht), Liste mit Vorschau, Löschen, Auswahl der
 * Fonts, des Logos und des Wasserzeichens. Die Auswahl geht als Felder mit „Speichern“ in brand_profiles.ci. */
export function AssetsCard({ profileId, assets: initialAssets, ci, canUpload }: Props) {
  const [assets, setAssets] = useState<BrandAsset[]>(initialAssets);
  const [kind, setKind] = useState<BrandAssetKind>("font");
  const [file, setFile] = useState<File | null>(null);
  const [license, setLicense] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<BrandAsset | null>(null);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [primary, setPrimary] = useState(ci.fonts?.primary_asset_id ?? "");
  const [secondary, setSecondary] = useState(ci.fonts?.secondary_asset_id ?? "");
  const [logo, setLogo] = useState(ci.logo_asset_id ?? "");
  const [watermark, setWatermark] = useState(ci.watermark?.enabled ?? false);
  const fileRef = useRef<HTMLInputElement>(null);
  const kindId = useId();
  const fileId = useId();
  const licenseId = useId();
  const primaryId = useId();
  const secondaryId = useId();
  const logoId = useId();

  const fonts = assets.filter((a) => a.kind === "font");
  const logos = assets.filter((a) => a.kind === "logo");
  const others = assets.filter((a) => a.kind !== "font" && a.kind !== "logo");
  const fileProblem = file ? validateAssetFile(kind, file.name, file.size) : null;

  const upload = async () => {
    if (!profileId || !file) return;
    setBusy(true);
    setMessage(null);
    try {
      const form = new FormData();
      form.set("kind", kind);
      form.set("file", file);
      form.set("license", license ? "true" : "false");
      const res = await fetch(`/api/brand/${profileId}/assets`, { method: "POST", body: form });
      const data = (await res.json()) as ApiResponse;
      if (!res.ok || !data.asset) throw new Error(data.error ?? "Upload fehlgeschlagen");
      const asset = data.asset;
      setAssets((prev) => [...prev, asset]);
      setFile(null);
      setLicense(false);
      if (fileRef.current) fileRef.current.value = "";
      setMessage({
        tone: "ok",
        text: `${ASSET_KIND_LABELS[asset.kind]} „${asset.name}“ hochgeladen${asset.font_family ? ` (${asset.font_family}${asset.font_weight ? `, ${asset.font_weight}` : ""})` : ""}. ${data.storage === "memory" ? "Speicher: nur im Prozess (kein S3)." : "Speicher: S3."} Auswahl unten mit „Speichern“ übernehmen.`,
      });
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : "Upload fehlgeschlagen" });
    } finally {
      setBusy(false);
    }
  };

  const remove = async (asset: BrandAsset) => {
    if (!profileId) return;
    setBusy(true);
    setMessage(null);
    try {
      const res = await fetch(`/api/brand/${profileId}/assets`, { method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ asset_id: asset.id }) });
      const data = (await res.json()) as ApiResponse;
      if (!res.ok) throw new Error(data.error ?? "Löschen fehlgeschlagen");
      setAssets((prev) => prev.filter((a) => a.id !== asset.id));
      if (primary === asset.id) setPrimary("");
      if (secondary === asset.id) setSecondary("");
      if (logo === asset.id) setLogo("");
      setMessage({ tone: "ok", text: `„${asset.name}“ gelöscht.${data.references_cleared ? " Verweise im CI wurden gelöst (neuer Stand in der Historie)." : ""}` });
      setConfirmDelete(null);
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : "Löschen fehlgeschlagen" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <GlassCard padding="lg" className="flex flex-col gap-5">
      <div>
        <h2 className="text-lg font-medium">Assets</h2>
        <p className="mt-1 text-sm text-text-2">
          Eigene Schrift für Captions und Bauchbinde, Logo als Wasserzeichen. Der Worker lädt die Dateien aus dem EU-Objektspeicher; ohne Auswahl rendert er mit Inter.
        </p>
      </div>

      {!profileId ? (
        <p className="text-sm text-text-2">Bitte das Markenprofil zuerst speichern, dann kannst du Dateien hochladen.</p>
      ) : canUpload ? (
        <div className="flex flex-col gap-4 rounded-inner border border-line p-4">
          <div className="grid gap-4 sm:grid-cols-[200px_minmax(0,1fr)]">
            <Field label="Art" htmlFor={kindId}>
              <Select id={kindId} value={kind} onChange={(e) => setKind(e.target.value as BrandAssetKind)}>
                {UPLOAD_KINDS.map((k) => (
                  <option key={k.kind} value={k.kind}>
                    {ASSET_KIND_LABELS[k.kind]}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Datei" htmlFor={fileId} hint={UPLOAD_KINDS.find((k) => k.kind === kind)?.hint} error={fileProblem ?? undefined}>
              <input
                ref={fileRef}
                id={fileId}
                type="file"
                accept={allowedExtensions(kind)
                  .map((e) => `.${e}`)
                  .join(",")}
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="block w-full rounded-inner border border-line bg-black/40 px-4 py-2.5 text-sm text-text file:mr-3 file:rounded-pill file:border-0 file:bg-text file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-black"
              />
            </Field>
          </div>
          <label htmlFor={licenseId} className="flex cursor-pointer items-start gap-3 text-sm text-text">
            <Checkbox id={licenseId} checked={license} onChange={(e) => setLicense(e.target.checked)} />
            <span>{LICENSE_TEXT}</span>
          </label>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-xs text-text-2">
              {file ? `${file.name}, ${formatBytes(file.size)} von max. ${formatBytes(maxBytesFor(kind))}` : "Noch keine Datei gewählt."}
            </span>
            <Button type="button" size="sm" onClick={() => void upload()} disabled={busy || !file || !license || Boolean(fileProblem)}>
              {busy ? "Wird hochgeladen" : "Hochladen"}
            </Button>
          </div>
        </div>
      ) : (
        <p className="text-sm text-text-2">Upload ist für deine Rolle nicht freigegeben.</p>
      )}

      {message && (
        <p role="status" aria-live="polite" className={cn("text-sm", message.tone === "ok" ? "text-text" : "text-attention")}>
          {message.text}
        </p>
      )}

      {profileId && assets.length > 0 && (
        <ul className="flex flex-col gap-2" aria-label="Hochgeladene Assets">
          {[...fonts, ...logos, ...others].map((a) => {
            const url = assetUrl(profileId, a);
            const family = a.font_family ?? a.name;
            return (
              <li key={a.id} className="flex flex-col gap-3 rounded-inner border border-line p-3 sm:flex-row sm:items-center">
                {a.kind === "font" ? (
                  <>
                    <style>{fontFaceCss({ family: `asset-${a.id}`, url, format: fontFormat(extensionOf(a.storage_key)), weight: a.font_weight })}</style>
                    <p className="min-w-0 flex-1 truncate text-2xl leading-tight text-text" style={{ fontFamily: `"asset-${a.id}", Inter, sans-serif`, fontWeight: a.font_weight ?? 400 }}>
                      Sinntreu geschnitten, jede Auswahl erklärt.
                    </p>
                  </>
                ) : (
                  <div className="flex h-16 w-28 shrink-0 items-center justify-center overflow-hidden rounded-[10px] border border-line bg-[repeating-conic-gradient(#1a1a22_0%_25%,#0a0a13_0%_50%)] bg-[length:12px_12px] p-2">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={url} alt={a.name} className="max-h-full max-w-full object-contain" />
                  </div>
                )}
                <div className={cn("flex min-w-0 flex-col gap-1", a.kind !== "font" && "flex-1")}>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge className="h-6 px-2.5 text-[11px]">{ASSET_KIND_LABELS[a.kind]}</Badge>
                    <span className="truncate text-sm font-medium text-text">{a.kind === "font" ? family : a.name}</span>
                    {a.kind === "font" && a.font_weight && <span className="font-mono text-xs text-text-2">{a.font_weight}</span>}
                  </div>
                  <span className="font-mono text-xs text-text-3">
                    {a.name} · {formatBytes(a.size_bytes)} · {a.sha256 ? a.sha256.slice(0, 12) : ""}
                  </span>
                </div>
                {canUpload && (
                  <Button type="button" size="sm" variant="danger" onClick={() => setConfirmDelete(a)} disabled={busy}>
                    Löschen
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      )}

      <Modal
        open={confirmDelete != null}
        onClose={() => !busy && setConfirmDelete(null)}
        title={confirmDelete ? `„${confirmDelete.name}“ löschen` : "Asset löschen"}
        description="Die Datei wird aus dem Objektspeicher entfernt. Ist sie im CI ausgewählt, wird der Verweis gelöst und der vorherige Stand in der Historie gesichert."
      >
        <div className="flex flex-wrap justify-end gap-2">
          <Button type="button" variant="ghost" onClick={() => setConfirmDelete(null)} disabled={busy}>
            Abbrechen
          </Button>
          <Button type="button" variant="danger" className="border border-danger/50" onClick={() => confirmDelete && void remove(confirmDelete)} disabled={busy}>
            {busy ? "Wird gelöscht" : "Löschen"}
          </Button>
        </div>
      </Modal>

      <div className="grid gap-5 border-t border-line pt-5 sm:grid-cols-2">
        <Field label="Primärfont" htmlFor={primaryId} hint="Captions und Hook-Overlay. Ohne Auswahl: Inter.">
          <Select id={primaryId} name="ci_primary_font" value={primary} onChange={(e) => setPrimary(e.target.value)} disabled={fonts.length === 0}>
            <option value="">Inter (Standard)</option>
            {fonts.map((f) => (
              <option key={f.id} value={f.id}>
                {f.font_family ?? f.name}
                {f.font_weight ? ` ${f.font_weight}` : ""}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Sekundärfont" htmlFor={secondaryId} hint="Bauchbinde und Titelkarte.">
          <Select id={secondaryId} name="ci_secondary_font" value={secondary} onChange={(e) => setSecondary(e.target.value)} disabled={fonts.length === 0}>
            <option value="">Wie Primärfont</option>
            {fonts.map((f) => (
              <option key={f.id} value={f.id}>
                {f.font_family ?? f.name}
                {f.font_weight ? ` ${f.font_weight}` : ""}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Logo" htmlFor={logoId} hint="Für das Wasserzeichen nutzt der Worker PNG; SVG nur in der Vorschau.">
          <Select id={logoId} name="ci_logo" value={logo} onChange={(e) => setLogo(e.target.value)} disabled={logos.length === 0}>
            <option value="">Kein Logo</option>
            {logos.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </Select>
        </Field>
        <div className="flex items-center">
          <Toggle
            checked={watermark}
            onChange={setWatermark}
            name="ci_watermark_enabled"
            label="Wasserzeichen im Render"
            description={logo ? "Logo unten in der Safe Zone." : "Erst ein Logo wählen."}
            disabled={!logo}
          />
        </div>
      </div>
    </GlassCard>
  );
}
