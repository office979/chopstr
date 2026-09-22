import "server-only";
import { isDemoMode } from "@/lib/env";
import { demoRepo } from "@/lib/repo/demo";
import { postgresRepo } from "@/lib/repo/postgres";
import type { Repo } from "@/lib/repo/types";

/* Repository-Auswahl: Postgres, wenn DATABASE_URL gesetzt ist, sonst In-Memory-Demo.
 * Der Postgres-Treiber verbindet erst beim ersten Zugriff (lib/db.ts), im Demo-Modus nie. */
export function getRepo(): Repo {
  return isDemoMode() ? demoRepo : postgresRepo;
}

export type { Repo };
