import { apiRoute } from "@/lib/api/handler";
import { apiJson } from "@/lib/api/errors";
import { loadCandidate } from "@/lib/api/lookup";

export const dynamic = "force-dynamic";

/* Kandidat mit Rubrik, Gates, Story-Graph-Flags und Risiko-Flags */
export const GET = apiRoute<{ id: string }>("read", async (_request, { params }) => {
  const { candidate } = await loadCandidate(params.id);
  return apiJson({ candidate });
});
