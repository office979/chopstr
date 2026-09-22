import { NextResponse, type NextRequest } from "next/server";
import { isDemoMode } from "@/lib/env";
import { getRepo } from "@/lib/repo";
import { getAuthUser } from "@/lib/session";
import { endSession } from "@/lib/auth/service";

export const dynamic = "force-dynamic";

/* POST /abmelden: Sitzung löschen, Cookie leeren, zur Anmeldung. Im Demo-Modus nur Umleitung. */
export async function POST(request: NextRequest) {
  const target = new URL("/anmelden", request.nextUrl.origin);
  if (isDemoMode()) return NextResponse.redirect(new URL("/", request.nextUrl.origin), { status: 303 });
  const me = await getAuthUser();
  await endSession();
  if (me) {
    await getRepo().auditAs({ workspace_id: me.activeWorkspaceId, actor_id: me.userId }, { action: "auth.logout", entity: "users", entity_id: me.userId });
  }
  return NextResponse.redirect(target, { status: 303 });
}
