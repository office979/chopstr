import type { NextRequest } from "next/server";
import { apiRoute } from "@/lib/api/handler";
import { apiJson } from "@/lib/api/errors";
import { delegate } from "@/lib/api/delegate";
import { loadSource } from "@/lib/api/lookup";
import { serializeSource } from "@/lib/api/serializers";
import { DELETE as deleteProject } from "@/app/api/projects/[id]/route";

export const dynamic = "force-dynamic";

type P = { id: string };

export const GET = apiRoute<P>("read", async (_request, { params }) => {
  const source = await loadSource(params.id);
  return apiJson({ source: serializeSource(source) });
});

/* DELETE: gleiche Logik wie die Web-App (Löschauftrag, DeletionWorkflow); der Schlüssel ersetzt die Titel-Bestätigung */
export const DELETE = apiRoute<P>("write", async (request: NextRequest, { params }) => {
  const source = await loadSource(params.id);
  return delegate(deleteProject, request, { id: source.id }, { method: "DELETE", body: { confirm_title: source.title } });
});
