import type { NextRequest } from "next/server";
import { apiRoute } from "@/lib/api/handler";
import { apiJson } from "@/lib/api/errors";
import { loadClip } from "@/lib/api/lookup";
import { readJsonBody } from "@/lib/api/validate";
import { requestSchema, resolveRef } from "@/lib/api/openapi";
import { clipFormatHint, runLinkCheck } from "@/lib/publishing/link-check";
import { linkCheckDeps } from "@/lib/publishing/link-check-server";

export const dynamic = "force-dynamic";

interface LinkTestBody {
  url: string;
  clip_id?: string | null;
}

/* Linktest: zerlegt den Link, liest öffentliche Messwerte (YouTube, X), prüft Besitz über die Verbindungen,
 * Dubletten und das Alter. Schreibt nichts. Ohne Schlüssel kommen „nicht konfiguriert“-Hinweise statt Zahlen. */
export const POST = apiRoute("read", async (request: NextRequest) => {
  const body = await readJsonBody<LinkTestBody>(request, requestSchema("LinkTest"), resolveRef);
  const clip = body.clip_id ? (await loadClip(body.clip_id)).clip : null;
  const result = await runLinkCheck(body.url, linkCheckDeps());
  const formatHint = clipFormatHint(result.platform, clip?.platform);
  if (formatHint) result.notes.push(formatHint);
  return apiJson({ ...result, clip_id: clip?.id ?? null });
});
