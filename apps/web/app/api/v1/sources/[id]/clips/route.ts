import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { apiRoute } from "@/lib/api/handler";
import { apiJson } from "@/lib/api/errors";
import { loadSource } from "@/lib/api/lookup";
import { serializeClip } from "@/lib/api/serializers";

export const dynamic = "force-dynamic";

export const GET = apiRoute<{ id: string }>("read", async (request: NextRequest, { params }) => {
  const source = await loadSource(params.id);
  const repo = getRepo();
  const status = request.nextUrl.searchParams.get("status");
  const [clips, count] = await Promise.all([repo.listClips(source.id), repo.countClips(source.id)]);
  const visible = clips.filter((c) => c.status !== "deleted" && (!status || c.status === status));
  return apiJson({ clips: visible.map((c) => serializeClip(c)), count });
});
