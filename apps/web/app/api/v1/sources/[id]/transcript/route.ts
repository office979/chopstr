import { getRepo } from "@/lib/repo";
import { apiRoute } from "@/lib/api/handler";
import { apiJson, notFound } from "@/lib/api/errors";
import { loadSource } from "@/lib/api/lookup";
import { serializeTranscript } from "@/lib/api/serializers";

export const dynamic = "force-dynamic";

export const GET = apiRoute<{ id: string }>("read", async (_request, { params }) => {
  const source = await loadSource(params.id);
  const transcript = await getRepo().getCurrentTranscript(source.id);
  if (!transcript) throw notFound("Kein Transkript vorhanden.");
  return apiJson({ transcript: serializeTranscript(transcript) });
});
