/* Entwicklungs-Session: genau ein Workspace, ein Akteur.
 * TODO (Phase 4): echte Authentifizierung (Supabase Auth / Passkeys), Workspace aus dem JWT lesen. */

export const DEV_WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";
export const DEV_ACTOR_ID = "22222222-2222-4222-8222-222222222222";

export interface Session {
  workspaceId: string;
  actorId: string;
}

export function getSession(): Session {
  return {
    workspaceId: process.env.DEV_WORKSPACE_ID ?? DEV_WORKSPACE_ID,
    actorId: process.env.DEV_ACTOR_ID ?? DEV_ACTOR_ID,
  };
}
