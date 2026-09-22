import { getRepo } from "@/lib/repo";
import { apiRoute } from "@/lib/api/handler";
import { apiJson } from "@/lib/api/errors";
import { serializeWorkspace } from "@/lib/api/serializers";

export const dynamic = "force-dynamic";

export const GET = apiRoute("read", async (_request, { auth }) => {
  const workspace = await getRepo().getWorkspace();
  return apiJson({
    workspace: serializeWorkspace(workspace),
    scopes: auth.scopes,
    role: auth.role,
    key: { id: auth.key.id, name: auth.key.name, key_prefix: auth.key.key_prefix, expires_at: auth.key.expires_at, last_used_at: auth.key.last_used_at },
  });
});
