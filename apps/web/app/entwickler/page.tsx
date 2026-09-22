import Link from "next/link";
import { PageShell } from "@/components/layout/PageShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { ButtonLink } from "@/components/ui/Button";
import { requirePageRole } from "@/lib/session";
import { appBaseUrl } from "@/lib/auth/url";
import { ENDPOINTS } from "@/lib/api/openapi";
import { WEBHOOK_EVENTS } from "@/lib/repo/types-api";

export const dynamic = "force-dynamic";
export const metadata = { title: "Entwickler" };

function Code({ children }: { children: string }) {
  return (
    <pre className="overflow-x-auto rounded-inner border border-line bg-black/50 px-4 py-3 font-mono text-[13px] leading-relaxed text-text">
      <code>{children}</code>
    </pre>
  );
}

/* Entwicklerseite (api.manage): Kurzdoku der öffentlichen API, OpenAPI-Link, Beispiele curl, Python, MCP. */
export default async function DeveloperPage() {
  const session = await requirePageRole("api.manage");
  const base = await appBaseUrl();
  const api = `${base}/api/v1`;
  const key = "chp_live_…";

  const curl = `# Workspace und Scopes des Schlüssels
curl -s ${api}/me -H "Authorization: Bearer ${key}"

# Quellen und Kandidaten
curl -s ${api}/sources -H "Authorization: Bearer ${key}"
curl -s ${api}/sources/<source_id>/candidates -H "Authorization: Bearer ${key}"

# Kandidat annehmen (Clips für TikTok und LinkedIn)
curl -s -X POST ${api}/candidates/<candidate_id>/verdict \\
  -H "Authorization: Bearer ${key}" -H "Content-Type: application/json" \\
  -d '{"verdict":"accepted","platforms":["tiktok","linkedin"]}'

# Clip mit Medien-URLs, Download (302; 409 ohne Gast-Freigabe)
curl -s ${api}/clips/<clip_id> -H "Authorization: Bearer ${key}"
curl -sI ${api}/clips/<clip_id>/download -H "Authorization: Bearer ${key}"

# Quelle per URL anlegen (Rechte bestätigt, Urheber und URL sind Pflicht)
curl -s -X POST ${api}/sources \\
  -H "Authorization: Bearer ${key}" -H "Content-Type: application/json" \\
  -d '{"title":"Keynote","rights_confirmed":true,"rights_status":"licensed","source_owner":"Anna Beispiel","source_url":"https://example.com/keynote.mp4","upload":"url"}'`;

  const python = `import requests

API = "${api}"
HEADERS = {"Authorization": "Bearer ${key}"}

def get(path, **params):
    r = requests.get(f"{API}{path}", headers=HEADERS, params=params, timeout=30)
    if not r.ok:
        err = r.json().get("error", {})
        raise RuntimeError(f"{r.status_code} {err.get('code')}: {err.get('message')}")
    return r.json()

sources = get("/sources")["sources"]
ready = [s for s in sources if s["status"] == "ready"]
for source in ready:
    candidates = get(f"/sources/{source['id']}/candidates")["candidates"]
    best = [c for c in candidates if c["gate_passed"] and c["human_verdict"] is None][:3]
    for c in best:
        print(source["title"], c["id"], c["total"], c["why"])

# Ablehnen braucht einen Grund (Lernsignal)
requests.post(f"{API}/candidates/<candidate_id>/verdict", headers=HEADERS,
              json={"verdict": "rejected", "reason": "zu allgemein"}, timeout=30).raise_for_status()`;

  const mcpDesktop = `{
  "mcpServers": {
    "chopstr": {
      "command": "npx",
      "args": ["-y", "chopstr-mcp"],
      "env": {
        "CHOPSTR_API_URL": "${api}",
        "CHOPSTR_API_KEY": "${key}"
      }
    }
  }
}`;

  const mcpCode = `claude mcp add chopstr -e CHOPSTR_API_KEY=${key} -e CHOPSTR_API_URL=${api} -- npx -y chopstr-mcp

# Lokaler Pfad im Monorepo
claude mcp add chopstr -e CHOPSTR_API_KEY=${key} -e CHOPSTR_API_URL=${api} -- node /pfad/zu/chopstr/packages/mcp-server/dist/cli.js`;

  const webhookVerify = `import hmac, hashlib, time

def verify(secret: str, body: bytes, header: str, tolerance_s: int = 300) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    ts = int(parts.get("t", "0"))
    if abs(time.time() - ts) > tolerance_s:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts.get("v1", ""))`;

  const grouped = new Map<string, typeof ENDPOINTS>();
  for (const e of ENDPOINTS) grouped.set(e.tag, [...(grouped.get(e.tag) ?? []), e]);

  return (
    <PageShell backgroundWord="API" lightTone="ai">
      <PageHeader
        eyebrow={`Workspace · ${session.workspaceName}`}
        title="Entwickler"
        description="Öffentliche API, Webhooks und MCP-Server. Die KI schlägt vor, ein Mensch gibt frei: jede schreibende Aktion braucht einen Schlüssel mit passendem Scope, und nichts wird ohne Freigabe veröffentlicht."
        actions={
          <>
            <ButtonLink href="/einstellungen/api" variant="primary" size="sm">
              Schlüssel verwalten
            </ButtonLink>
            <ButtonLink href="/einstellungen/webhooks" variant="ghost" size="sm">
              Webhooks
            </ButtonLink>
          </>
        }
      />

      <div className="flex flex-col gap-5">
        <GlassCard padding="lg" className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-medium">Grundlagen</h2>
            <Badge tone="ai">OpenAPI 3.1</Badge>
          </div>
          <dl className="grid gap-3 text-sm sm:grid-cols-[180px_1fr]">
            <dt className="text-text-2">Basis-URL</dt>
            <dd className="font-mono text-text">{api}</dd>
            <dt className="text-text-2">Auth</dt>
            <dd className="text-text">
              Header <code className="font-mono text-xs">Authorization: Bearer chp_live_…</code>. Schlüssel unter{" "}
              <Link href="/einstellungen/api" className="underline underline-offset-4">
                Einstellungen, API
              </Link>{" "}
              anlegen; Scopes read, write, publish, admin.
            </dd>
            <dt className="text-text-2">Fehler</dt>
            <dd className="text-text">
              <code className="font-mono text-xs">{'{ "error": { "code": "not_found", "message": "Quelle nicht gefunden." } }'}</code>, Meldungen auf Deutsch. 401 Schlüssel, 402 Kontingent oder Plan, 403 Scope, 409 Zustand (zum Beispiel Gast-Freigabe fehlt), 429 Rate-Limit.
            </dd>
            <dt className="text-text-2">Rate-Limit</dt>
            <dd className="text-text">
              600 Anfragen pro Minute je Schlüssel, Header <code className="font-mono text-xs">X-RateLimit-Remaining</code> und <code className="font-mono text-xs">Retry-After</code>.
            </dd>
            <dt className="text-text-2">Antwortformen</dt>
            <dd className="text-text">
              Listen unter <code className="font-mono text-xs">sources</code>, <code className="font-mono text-xs">candidates</code>, <code className="font-mono text-xs">clips</code>; Einzelobjekte unter{" "}
              <code className="font-mono text-xs">source</code>, <code className="font-mono text-xs">candidate</code>, <code className="font-mono text-xs">clip</code> (mit <code className="font-mono text-xs">media</code> und{" "}
              <code className="font-mono text-xs">hook</code>), <code className="font-mono text-xs">publication</code>, <code className="font-mono text-xs">approval</code> plus <code className="font-mono text-xs">link</code>.
            </dd>
            <dt className="text-text-2">Spezifikation</dt>
            <dd>
              <a href="/api/v1/openapi.json" className="font-mono text-sm text-text underline underline-offset-4" target="_blank" rel="noreferrer">
                /api/v1/openapi.json
              </a>
            </dd>
          </dl>
        </GlassCard>

        <GlassCard padding="lg" className="flex flex-col gap-4">
          <h2 className="text-lg font-medium">Endpunkte</h2>
          <div className="grid gap-5 md:grid-cols-2">
            {[...grouped.entries()].map(([tag, list]) => (
              <div key={tag}>
                <h3 className="mb-2 text-sm font-medium text-text-2">{tag}</h3>
                <ul className="flex flex-col gap-1.5 text-sm">
                  {list.map((e) => (
                    <li key={`${e.method} ${e.path}`} className="flex flex-wrap items-baseline gap-2">
                      <span className="w-14 shrink-0 font-mono text-[11px] uppercase text-text-3">{e.method}</span>
                      <code className="font-mono text-xs text-text">{e.path}</code>
                      <span className="text-text-2">{e.summary}</span>
                      <Badge className="h-5 px-2 text-[10px]">{e.scope}</Badge>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </GlassCard>

        <GlassCard padding="lg" className="flex flex-col gap-4">
          <h2 className="text-lg font-medium">curl</h2>
          <Code>{curl}</Code>
        </GlassCard>

        <GlassCard padding="lg" className="flex flex-col gap-4">
          <h2 className="text-lg font-medium">Python (requests)</h2>
          <Code>{python}</Code>
        </GlassCard>

        <GlassCard padding="lg" className="flex flex-col gap-4">
          <div>
            <h2 className="text-lg font-medium">MCP-Server</h2>
            <p className="mt-1 text-sm text-text-2">
              Paket <code className="font-mono text-xs">@chopstr/mcp-server</code> (<code className="font-mono text-xs">chopstr-mcp</code>): verbindet Claude Desktop, Claude Code und andere MCP-Clients mit dieser API. Schreibende Tools verlangen{" "}
              <code className="font-mono text-xs">confirm: true</code>; ohne Bestätigung gibt es nur eine Vorschau. Für die meisten Fälle reicht ein Schlüssel mit read und write, publish nur für Veröffentlichungen, admin nie.
            </p>
          </div>
          <h3 className="text-sm font-medium text-text-2">Claude Desktop (claude_desktop_config.json)</h3>
          <Code>{mcpDesktop}</Code>
          <h3 className="text-sm font-medium text-text-2">Claude Code</h3>
          <Code>{mcpCode}</Code>
          <p className="text-sm text-text-2">
            Tools: list_sources, get_source, create_source_from_url, get_transcript, list_candidates, accept_candidate, reject_candidate, revise_candidate, list_clips, get_clip, render_clip, write_hooks, request_guest_approval, publish_clip, get_usage. Resources: chopstr://sources/{"{id}"}/transcript, chopstr://clips/{"{id}"}/render-plan.
          </p>
        </GlassCard>

        <GlassCard padding="lg" className="flex flex-col gap-4">
          <div>
            <h2 className="text-lg font-medium">Webhooks</h2>
            <p className="mt-1 text-sm text-text-2">
              POST mit JSON <code className="font-mono text-xs">{'{ id, event, created_at, data }'}</code>, Header <code className="font-mono text-xs">X-Chopstr-Event</code>, <code className="font-mono text-xs">X-Chopstr-Delivery</code> und{" "}
              <code className="font-mono text-xs">X-Chopstr-Signature: t=&lt;unix&gt;,v1=&lt;hex&gt;</code> (HMAC-SHA256 über <code className="font-mono text-xs">&lt;t&gt;.&lt;body&gt;</code>). Antworte mit 2xx; sonst Wiederholung nach 1, 5, 30, 120 und 720 Minuten.
            </p>
          </div>
          <p className="flex flex-wrap gap-1.5">
            {WEBHOOK_EVENTS.map((e) => (
              <code key={e} className="rounded-md bg-white/[0.06] px-2 py-0.5 font-mono text-[11px] text-text-2">
                {e}
              </code>
            ))}
          </p>
          <h3 className="text-sm font-medium text-text-2">Signatur prüfen (Python)</h3>
          <Code>{webhookVerify}</Code>
        </GlassCard>
      </div>
    </PageShell>
  );
}
