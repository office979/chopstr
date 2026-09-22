import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { requireApiSession } from "@/lib/auth/guard";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

/* GET: aktuelle Kandidaten-Versionen eines Projekts (Pflichtkriterien erfüllt zuerst, dann total absteigend) */
export async function GET(_request: NextRequest, { params }: Params) {
  const auth = await requireApiSession();
  if (auth instanceof Response) return auth;
  const { id } = await params;
  const repo = getRepo();
  const source = await repo.getSource(id);
  if (!source) return Response.json({ error: "Projekt nicht gefunden" }, { status: 404 });
  const [candidates, count] = await Promise.all([repo.listCandidates(id), repo.countCandidates(id)]);
  return Response.json({ candidates, count });
}
