import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Native Abhängigkeiten (gRPC, Postgres-Treiber) nicht bündeln
  serverExternalPackages: ["@temporalio/client", "postgres", "@node-rs/argon2", "nodemailer", "stripe", "fontkit", "@aws-sdk/client-s3"],
  // Keine automatisch erzeugten AGENTS.md/CLAUDE.md im App-Ordner
  agentRules: false,
};

export default nextConfig;
