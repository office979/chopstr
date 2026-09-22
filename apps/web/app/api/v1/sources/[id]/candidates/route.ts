import { getRepo } from "@/lib/repo";
import { apiRoute } from "@/lib/api/handler";
import { apiJson } from "@/lib/api/errors";
import { loadSource } from "@/lib/api/lookup";

export const dynamic = "force-dynamic";

export const GET = apiRoute<{ id: string }>("read", async (_request, { params }) => {
  const source = await loadSource(params.id);
  const repo = getRepo();
  const [candidates, count] = await Promise.all([repo.listCandidates(source.id), repo.countCandidates(source.id)]);
  return apiJson({ candidates, count });
});
