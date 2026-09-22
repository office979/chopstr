"use client";

import { useCallback, useId, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Field, Input, Select } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { cn } from "@/components/ui/cn";
import type { ConnectionPlatform, PlatformConnection } from "@/lib/repo/types-publishing";
import { CAPABILITY_KEYS, CAPABILITY_LABELS, capabilityLabel } from "@/lib/publishing/capabilities";
import { CONNECTION_PLATFORM_LABELS, CONNECTION_STATUS_LABELS } from "@/lib/publishing/platforms";
import { formatDateTime } from "@/lib/format";

interface Props {
  initialConnections: PlatformConnection[];
  providers: { platform: ConnectionPlatform; label: string; configured: boolean }[];
  brands: { id: string; name: string }[];
  notice: { tone: "ok" | "error"; text: string } | null;
  credentialsKey: boolean;
  demo: boolean;
}

interface ApiError {
  error?: string;
}

export function ConnectionsPanel({ initialConnections, providers, brands, notice, credentialsKey, demo }: Props) {
  const [connections, setConnections] = useState(initialConnections);
  const [message, setMessage] = useState(notice);
  const [manualOpen, setManualOpen] = useState(false);
  const [label, setLabel] = useState("");
  const [brand, setBrand] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [capsOpen, setCapsOpen] = useState<string | null>(null);
  const labelId = useId();
  const brandId = useId();

  const createManual = useCallback(async () => {
    setBusy("manual");
    setMessage(null);
    try {
      const res = await fetch("/api/publishing/connections", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account_label: label, brand_profile_id: brand || null }),
      });
      const data = (await res.json()) as ApiError & { connection?: PlatformConnection };
      if (!res.ok || !data.connection) throw new Error(data.error ?? "Anlegen fehlgeschlagen");
      setConnections((prev) => [...prev, data.connection!]);
      setManualOpen(false);
      setLabel("");
      setBrand("");
      setMessage({ tone: "ok", text: `Manuelle Verbindung „${data.connection.account_label}“ angelegt.` });
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : "Anlegen fehlgeschlagen" });
    } finally {
      setBusy(null);
    }
  }, [label, brand]);

  const assignBrand = useCallback(async (c: PlatformConnection, brandProfileId: string) => {
    setBusy(c.id);
    try {
      const res = await fetch(`/api/publishing/connections/${c.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_profile_id: brandProfileId || null }),
      });
      const data = (await res.json()) as ApiError & { connection?: PlatformConnection };
      if (!res.ok || !data.connection) throw new Error(data.error ?? "Speichern fehlgeschlagen");
      setConnections((prev) => prev.map((x) => (x.id === c.id ? data.connection! : x)));
      setMessage({ tone: "ok", text: "Marke zugeordnet." });
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : "Speichern fehlgeschlagen" });
    } finally {
      setBusy(null);
    }
  }, []);

  const revoke = useCallback(async (c: PlatformConnection) => {
    if (!window.confirm(`Verbindung „${c.account_label}“ trennen? Die Zugangsdaten werden gelöscht, laufende Publikationen schlagen fehl.`)) return;
    setBusy(c.id);
    try {
      const res = await fetch(`/api/publishing/connections/${c.id}`, { method: "DELETE" });
      const data = (await res.json()) as ApiError & { connection?: PlatformConnection };
      if (!res.ok || !data.connection) throw new Error(data.error ?? "Trennen fehlgeschlagen");
      setConnections((prev) => prev.map((x) => (x.id === c.id ? data.connection! : x)));
      setMessage({ tone: "ok", text: `Verbindung „${c.account_label}“ getrennt.` });
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : "Trennen fehlgeschlagen" });
    } finally {
      setBusy(null);
    }
  }, []);

  const active = connections.filter((c) => c.status !== "revoked");
  const revoked = connections.filter((c) => c.status === "revoked");

  return (
    <div className="flex flex-col gap-5">
      <Modal open={manualOpen} onClose={() => setManualOpen(false)} title="Manuelle Verbindung" description="Du lädst den Export herunter, postest selbst und trägst Post-URL und Metriken von Hand ein.">
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            void createManual();
          }}
        >
          <Field label="Konto-Bezeichnung" htmlFor={labelId} required hint="z. B. „LinkedIn Firmenseite“ oder „TikTok @placemedia“">
            <Input id={labelId} value={label} onChange={(e) => setLabel(e.target.value)} maxLength={120} required />
          </Field>
          <Field label="Marke" htmlFor={brandId} hint="Optional: Verbindung nur für diese Marke anzeigen.">
            <Select id={brandId} value={brand} onChange={(e) => setBrand(e.target.value)}>
              <option value="">Alle Marken</option>
              {brands.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </Select>
          </Field>
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="ghost" onClick={() => setManualOpen(false)} disabled={busy === "manual"}>
              Abbrechen
            </Button>
            <Button type="submit" disabled={busy === "manual" || label.trim().length < 2}>
              {busy === "manual" ? "Wird angelegt" : "Anlegen"}
            </Button>
          </div>
        </form>
      </Modal>

      {message && (
        <p role="status" aria-live="polite" className={cn("rounded-inner border px-4 py-3 text-sm", message.tone === "ok" ? "border-line text-text" : "border-attention/50 bg-attention/10 text-text")}>
          {message.text}
        </p>
      )}
      {!credentialsKey && !demo && (
        <p className="rounded-inner border border-attention/40 px-4 py-3 text-sm text-text-2">
          <span className="text-attention">CREDENTIALS_KEY fehlt.</span> OAuth-Zugangsdaten würden unverschlüsselt gespeichert (nur Entwicklung). In Produktion ist der Schlüssel Pflicht.
        </p>
      )}

      <GlassCard padding="lg">
        <h2 className="text-lg font-medium">Verbinden</h2>
        <p className="mt-1 text-sm text-text-2">Plattform-Konten per OAuth. Nicht konfigurierte Provider brauchen App-Zugangsdaten in der Umgebung.</p>
        <ul className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {providers.map((p) => (
            <li key={p.platform} className="flex flex-col gap-2 rounded-inner border border-line p-4">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium">{p.label}</span>
                {p.platform === "manual" ? (
                  <Badge tone="ok" className="h-6 px-2.5 text-[11px]">immer verfügbar</Badge>
                ) : p.configured ? (
                  <Badge tone="ok" className="h-6 px-2.5 text-[11px]">konfiguriert</Badge>
                ) : (
                  <Badge tone="attention" className="h-6 px-2.5 text-[11px]">nicht konfiguriert</Badge>
                )}
              </div>
              <p className="text-xs text-text-2">
                {p.platform === "manual"
                  ? "Export herunterladen, selbst posten, Post-URL und Metriken eintragen."
                  : p.platform === "tiktok"
                    ? "Content Posting API, Direct Post."
                    : p.platform === "instagram"
                      ? "Graph API, Reels über Business-Konto."
                      : p.platform === "youtube"
                        ? "Data API v3, Videos als Shorts."
                        : "Community Management API, Post als Mitglied."}
              </p>
              {p.platform === "manual" ? (
                <Button size="sm" variant="ghost" onClick={() => setManualOpen(true)} className="mt-auto self-start">
                  Manuelle Verbindung anlegen
                </Button>
              ) : (
                <a
                  href={`/api/publishing/oauth/${p.platform}/start`}
                  className={cn(
                    "transition-soft mt-auto inline-flex h-9 items-center self-start rounded-pill border px-4 text-sm font-medium",
                    p.configured ? "border-line-strong text-text hover:border-white/40 hover:bg-white/5" : "border-line text-text-2 hover:border-attention/60 hover:text-attention",
                  )}
                  title={p.configured ? `${p.label} verbinden` : "Nicht konfiguriert: der Start zeigt einen Hinweis"}
                >
                  Verbinden
                </a>
              )}
            </li>
          ))}
        </ul>
      </GlassCard>

      <GlassCard padding="lg">
        <h2 className="text-lg font-medium">Verbindungen</h2>
        {active.length === 0 ? (
          <p className="mt-2 text-sm text-text-2">Noch keine Verbindung. Lege eine manuelle Verbindung an oder verbinde ein Konto per OAuth.</p>
        ) : (
          <ul className="mt-4 flex flex-col gap-3">
            {active.map((c) => (
              <li key={c.id} className="rounded-inner border border-line p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">{c.account_label}</span>
                      <Badge className="h-6 px-2.5 text-[11px]">{CONNECTION_PLATFORM_LABELS[c.platform]}</Badge>
                      <Badge tone={c.status === "connected" ? "ok" : "attention"} className="h-6 px-2.5 text-[11px]">
                        {CONNECTION_STATUS_LABELS[c.status]}
                      </Badge>
                    </div>
                    <p className="mt-1 font-mono text-xs text-text-3">
                      {c.external_account_id ?? "ohne externe ID"} · seit {formatDateTime(c.created_at)}
                      {c.expires_at ? ` · Token bis ${formatDateTime(c.expires_at)}` : ""}
                      {c.platform !== "manual" ? (c.has_credentials ? " · Zugangsdaten verschlüsselt" : " · keine Zugangsdaten") : ""}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <label className="flex items-center gap-2 text-xs text-text-2">
                      Marke
                      <select
                        value={c.brand_profile_id ?? ""}
                        onChange={(e) => assignBrand(c, e.target.value)}
                        disabled={busy === c.id}
                        className="rounded-pill border border-line bg-black/40 px-3 py-1.5 text-xs text-text"
                        aria-label={`Marke für ${c.account_label}`}
                      >
                        <option value="">Alle Marken</option>
                        {brands.map((b) => (
                          <option key={b.id} value={b.id}>
                            {b.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <Button size="sm" variant="ghost" onClick={() => setCapsOpen(capsOpen === c.id ? null : c.id)} aria-expanded={capsOpen === c.id}>
                      Capabilities
                    </Button>
                    <Button size="sm" variant="danger" onClick={() => revoke(c)} disabled={busy === c.id}>
                      Trennen
                    </Button>
                  </div>
                </div>
                {capsOpen === c.id && (
                  <table className="mt-3 w-full text-xs" aria-label={`Capability Flags ${c.account_label}`}>
                    <tbody>
                      {CAPABILITY_KEYS.map((k) => (
                        <tr key={k} className="border-t border-line">
                          <th scope="row" className="py-1.5 pr-3 text-left font-normal text-text-2">
                            {CAPABILITY_LABELS[k]}
                          </th>
                          <td className={cn("py-1.5 font-mono", c.capabilities[k] === true ? "text-text" : c.capabilities[k] === false ? "text-text-3" : "text-attention")}>
                            {capabilityLabel(c.capabilities[k])}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </li>
            ))}
          </ul>
        )}
        {revoked.length > 0 && (
          <p className="mt-4 text-xs text-text-3">
            Getrennt: {revoked.map((c) => `${c.account_label} (${CONNECTION_PLATFORM_LABELS[c.platform]})`).join(", ")}
          </p>
        )}
      </GlassCard>
    </div>
  );
}
