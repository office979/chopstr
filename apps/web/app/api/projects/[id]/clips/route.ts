import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { requireApiSession } from "@/lib/auth/guard";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

/* GET: alle Clips eines Projekts (nach Erstellung sortiert) plus Zähler */
export async function GET(_request: NextRequest, { params }: Params) {
  const auth = await requireApiSession();
  if (auth instanceof Response) return auth;
  const { id } = await params;
  const repo = getRepo();
  const source = await repo.getSource(id);
  if (!source) return Response.json({ error: "Projekt nicht gefunden" }, { status: 404 });
  const [clips, count] = await Promise.all([repo.listClips(id), repo.countClips(id)]);
  return Response.json({ clips, count });
}
