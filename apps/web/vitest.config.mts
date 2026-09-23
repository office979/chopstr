import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const rootDir = dirname(fileURLToPath(import.meta.url));

/* Tests für die reinen Logikmodule unter lib/. Kein DOM nötig, also environment "node".
 * Der Alias "@/" spiegelt die paths-Einstellung aus tsconfig.json ("@/*" -> "./*").
 * "server-only" ist ein Marker-Paket, das beim Import außerhalb einer Server Component wirft;
 * Next.js lädt dafür über die react-server-Condition eine leere Datei, im Test übernimmt das der Stub. */
export default defineConfig({
  resolve: {
    alias: [
      { find: /^server-only$/, replacement: resolve(rootDir, "tests/stubs/server-only.ts") },
      { find: /^@\//, replacement: `${resolve(rootDir)}/` },
    ],
  },
  test: {
    include: ["tests/**/*.test.ts"],
    environment: "node",
  },
});
