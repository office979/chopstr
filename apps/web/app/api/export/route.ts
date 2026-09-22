import { strToU8, zipSync } from "fflate";
import { getRepo } from "@/lib/repo";
import { requireApiRole } from "@/lib/auth/guard";

export const dynamic = "force-dynamic";

/* GET: Datenexport (Art. 15/20 DSGVO, PHASE4.md Abschnitt 7) als ZIP mit JSON je Tabelle des Workspace und
 * media-keys.json (Objektspeicher-Keys). Rolle export.read (owner, admin). Audit workspace.exported. */
export async function GET() {
  const auth = await requireApiRole("export.read");
  if (auth instanceof Response) return auth;
  const repo = getRepo();
  const data = await repo.exportWorkspace();
  const stamp = new Date().toISOString();
  const json = (v: unknown) => strToU8(JSON.stringify(v, null, 2));
  const files: Record<string, Uint8Array> = {
    "README.txt": strToU8(
      [
        `chopstr Datenexport, Workspace ${data.workspace.name} (${data.workspace.id})`,
        `Erstellt ${stamp} von ${auth.email}`,
        "",
        "Eine JSON-Datei je Tabelle. media-keys.json listet die Objektspeicher-Keys (Rohmaterial, Proxys, Renderings, Captions, CI-Assets);",
        "die Dateien selbst liegen im EU-Objektspeicher und sind nicht Teil dieses Archivs.",
        "Abo ohne Anbieter-IDs (provider_customer_id, provider_subscription_id).",
      ].join("\n"),
    ),
    "workspaces.json": json([data.workspace]),
    "brand_profiles.json": json(data.brand_profiles),
    "brand_assets.json": json(data.brand_assets),
    "brand_profile_versions.json": json(data.brand_profile_versions),
    "sources.json": json(data.sources),
    "transcript_versions.json": json(data.transcript_versions),
    "candidates.json": json(data.candidates),
    "clips.json": json(data.clips),
    "hook_versions.json": json(data.hook_versions),
    "caption_versions.json": json(data.caption_versions),
    "guest_approvals.json": json(data.guest_approvals.map((g) => ({ ...g, token: undefined }))),
    "audit_log.json": json(data.audit_log),
    "job_costs.json": json(data.job_costs),
    "usage_periods.json": json(data.usage_periods),
    "subscriptions.json": json(data.subscription ? [data.subscription] : []),
    "dpa_acceptances.json": json(data.dpa_acceptances),
    "deletion_jobs.json": json(data.deletion_jobs),
    "media-keys.json": json(data.media_keys),
  };
  const zip = zipSync(files, { level: 6, mtime: new Date() });
  await repo.audit({
    action: "workspace.exported",
    entity: "workspaces",
    entity_id: data.workspace.id,
    payload: { files: Object.keys(files).length, sources: data.sources.length, clips: data.clips.length, media_keys: data.media_keys.length, bytes: zip.byteLength },
  });
  const name = `chopstr-export-${data.workspace.slug}-${stamp.slice(0, 10)}.zip`;
  return new Response(zip as unknown as BodyInit, {
    headers: {
      "Content-Type": "application/zip",
      "Content-Disposition": `attachment; filename="${name}"`,
      "Content-Length": String(zip.byteLength),
      "Cache-Control": "no-store",
    },
  });
}
