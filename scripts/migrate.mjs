#!/usr/bin/env node
// chopstr · Migrationen aus packages/schema/migrations/*.sql anwenden.
// Aufruf: DATABASE_URL=postgres://... node scripts/migrate.mjs
// Jede Datei läuft in einer Transaktion; angewendete Versionen stehen in schema_migrations.
import { readdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const migrationsDir = path.resolve(here, "../packages/schema/migrations");

const url = process.env.DATABASE_URL;
if (!url) {
  console.error("DATABASE_URL fehlt. Beispiel: postgres://chopstr:chopstr@localhost:5432/chopstr");
  process.exit(1);
}

let postgres;
try {
  postgres = require("postgres");
} catch {
  console.error("Paket 'postgres' nicht gefunden. Erst `npm install` im Monorepo-Root ausführen.");
  process.exit(1);
}

const sql = postgres(url, { max: 1, onnotice: () => {} });

async function ensureRoles() {
  // App-Rolle unterliegt RLS, Worker-Rolle darf RLS umgehen. Braucht Superuser; sonst nur Hinweis.
  const roles = [
    ["chopstr_app", "NOBYPASSRLS"],
    ["chopstr_worker", "BYPASSRLS"],
  ];
  for (const [name, flag] of roles) {
    try {
      const exists = await sql`select 1 from pg_roles where rolname = ${name}`;
      if (exists.length === 0) {
        await sql.unsafe(`create role ${name} login ${flag}`);
        console.log(`Rolle ${name} angelegt (${flag}). Passwort setzen: alter role ${name} password '...';`);
      }
    } catch (err) {
      console.warn(`Rolle ${name} nicht angelegt (${err.message}). In Supabase/Hetzner manuell anlegen.`);
    }
  }
}

async function main() {
  await sql`create table if not exists schema_migrations (
    version text primary key,
    applied_at timestamptz not null default now()
  )`;
  const applied = new Set((await sql`select version from schema_migrations`).map((r) => r.version));
  const files = (await readdir(migrationsDir)).filter((f) => f.endsWith(".sql")).sort();

  for (const file of files) {
    const version = file.replace(/\.sql$/, "");
    if (applied.has(version)) {
      console.log(`  = ${version} (bereits angewendet)`);
      continue;
    }
    const body = await readFile(path.join(migrationsDir, file), "utf8");
    await sql.begin(async (tx) => {
      await tx.unsafe(body);
      await tx`insert into schema_migrations(version) values (${version}) on conflict do nothing`;
    });
    console.log(`  + ${version} angewendet`);
  }
  await ensureRoles();
  await sql.end();
  console.log("Migrationen fertig.");
}

main().catch(async (err) => {
  console.error("Migration fehlgeschlagen:", err.message);
  await sql.end();
  process.exit(1);
});
