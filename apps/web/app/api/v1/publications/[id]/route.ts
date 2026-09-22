import { getApiRepo } from "@/lib/repo/api";
import { apiRoute } from "@/lib/api/handler";
import { apiJson, notFound } from "@/lib/api/errors";
import { serializePublication } from "@/lib/api/serializers";

export const dynamic = "force-dynamic";

export const GET = apiRoute<{ id: string }>("publish", async (_request, { params }) => {
  const publication = await getApiRepo().getPublication(params.id);
  if (!publication) throw notFound("Publikation nicht gefunden.");
  return apiJson({ publication: serializePublication(publication) });
});
