import postgres, { type Sql, type TransactionSql } from "postgres";
import type { Session } from "@/lib/session";

/* Postgres-Verbindung (porsager/postgres). Nur serverseitig verwenden.
 * Jede Fach-Transaktion setzt den Mandantenkontext für Row Level Security:
 *   set local app.workspace_id, set local app.actor_id
 * (über set_config(..., true), das entspricht SET LOCAL und ist parametrisierbar). */

declare global {
  var __chopstrSql: Sql | undefined;
}

export function getSql(): Sql {
  const url = process.env.DATABASE_URL;
  if (!url) {
    throw new Error("DATABASE_URL ist nicht gesetzt (Demo-Modus aktiv)");
  }
  if (!globalThis.__chopstrSql) {
    globalThis.__chopstrSql = postgres(url, {
      max: 5,
      idle_timeout: 30,
      prepare: false,
      transform: { undefined: null },
    });
  }
  return globalThis.__chopstrSql;
}

export type Tx = TransactionSql;

export async function withContext<T>(session: Session, fn: (tx: Tx) => Promise<T>): Promise<T> {
  const sql = getSql();
  return sql.begin(async (tx) => {
    await tx`select set_config('app.workspace_id', ${session.workspaceId}, true)`;
    await tx`select set_config('app.actor_id', ${session.actorId}, true)`;
    return fn(tx);
  }) as Promise<T>;
}
