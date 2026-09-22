import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Native Abhängigkeiten (gRPC, Postgres-Treiber) nicht bündeln
  serverExternalPackages: ["@temporalio/client", "postgres"],
  // Keine automatisch erzeugten AGENTS.md/CLAUDE.md im App-Ordner
  agentRules: false,
};

export default nextConfig;
