import postgres, { type Sql, type TransactionSql } from "postgres";
import type { Session } from "@/lib/session";

/* Postgres-Verbindung (porsager/postgres). Nur serverseitig verwenden.
 *
 * Zwei Kontexte:
 *
 * 1. `withContext(session, fn)`: Fach-Transaktion mit Mandantenkontext für Row Level Security
 *      set local app.workspace_id, app.actor_id und (nur für die Rolle client) app.brand_scope
 *    über set_config(..., true), das entspricht SET LOCAL und ist parametrisierbar.
 *
 * 2. `withAuthContext(fn)`: Transaktion OHNE Mandantenkontext für die Auth-Tabellen users, sessions,
 *    login_tokens, workspace_invites (Annahme) und für die Registrierung (Workspace anlegen). Diese Tabellen
 *    haben RLS-Policies, die für die App-Rolle alles sperren (sessions_none, login_tokens_none).
 *
 * Rollen in Produktion (PHASE4.md, Abschnitt 1): `chopstr_auth` mit BYPASSRLS für withAuthContext und
 * `chopstr_app` (NOBYPASSRLS) für withContext, jeweils über eigene Verbindungs-URLs
 * (DATABASE_URL für die App-Rolle, DATABASE_AUTH_URL für die Auth-Rolle; fehlt DATABASE_AUTH_URL,
 * wird DATABASE_URL für beides genutzt). scripts/migrate.mjs legt die Rollen an. In der Entwicklung ist
 * die App-Verbindung Tabellen-Owner beziehungsweise Superuser, RLS greift dort nicht, die Trennung
 * ist damit nur dokumentiert, nicht erzwungen. */

declare global {
  var __chopstrSql: Sql | undefined;
  var __chopstrAuthSql: Sql | undefined;
}

function connect(url: string): Sql {
  return postgres(url, {
    max: 5,
    idle_timeout: 30,
    prepare: false,
    transform: { undefined: null },
  });
}

export function getSql(): Sql {
  const url = process.env.DATABASE_URL;
  if (!url) {
    throw new Error("DATABASE_URL ist nicht gesetzt (Demo-Modus aktiv)");
  }
  if (!globalThis.__chopstrSql) {
    globalThis.__chopstrSql = connect(url);
  }
  return globalThis.__chopstrSql;
}

/* Verbindung der Auth-Rolle (chopstr_auth, BYPASSRLS). Ohne DATABASE_AUTH_URL dieselbe wie die App. */
export function getAuthSql(): Sql {
  const url = process.env.DATABASE_AUTH_URL;
  if (!url) return getSql();
  if (!globalThis.__chopstrAuthSql) {
    globalThis.__chopstrAuthSql = connect(url);
  }
  return globalThis.__chopstrAuthSql;
}

export type Tx = TransactionSql;

export async function withContext<T>(session: Session, fn: (tx: Tx) => Promise<T>): Promise<T> {
  const sql = getSql();
  return sql.begin(async (tx) => {
    await tx`select set_config('app.workspace_id', ${session.workspaceId}, true)`;
    await tx`select set_config('app.actor_id', ${session.userId}, true)`;
    /* Mandanten-Scope: client sieht nur Quellen seiner Marke (Policy ws_sources, Migration 0003) */
    const scope = session.role === "client" && session.brandScope ? session.brandScope : "";
    await tx`select set_config('app.brand_scope', ${scope}, true)`;
    return fn(tx);
  }) as Promise<T>;
}

/* Auth-Tabellen: keine RLS-Variablen, Rolle chopstr_auth (siehe Kopfkommentar) */
export async function withAuthContext<T>(fn: (tx: Tx) => Promise<T>): Promise<T> {
  const sql = getAuthSql();
  return sql.begin(async (tx) => fn(tx)) as Promise<T>;
}
