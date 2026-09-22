/* Sitzungs-Cookie: nur die Sitzungs-ID, httpOnly, sameSite lax, secure außerhalb development, 30 Tage.
 * Die Datei hat keine Server-Abhängigkeiten, damit proxy.ts sie ebenfalls nutzen kann. */

export const SESSION_COOKIE = "chopstr_session";
export const SESSION_TTL_MS = 30 * 24 * 60 * 60 * 1000;
/* Gleitende Verlängerung: frühestens nach einem Tag wird expires_at neu gesetzt */
export const SESSION_REFRESH_AFTER_MS = 24 * 60 * 60 * 1000;

export function isDevelopment(): boolean {
  return (process.env.APP_ENV ?? process.env.NODE_ENV ?? "development") !== "production";
}

export function sessionCookieOptions(maxAgeMs: number = SESSION_TTL_MS) {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: !isDevelopment(),
    path: "/",
    maxAge: Math.floor(maxAgeMs / 1000),
  };
}
