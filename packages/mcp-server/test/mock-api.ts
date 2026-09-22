/* Gemockter chopstr-API-Server (Node http) nach dem Vertrag in packages/schema/PHASE5.md.
 * Enthält bewusst keine echten Inhalte, nur synthetische Fixtures. */

import http from "node:http";
import type { AddressInfo } from "node:net";

export const MOCK_API_KEY = "chp_live_testkey_0000000000000000000000";

export interface RecordedRequest {
  method: string;
  path: string;
  query: Record<string, string>;
  body: unknown;
  headers: http.IncomingHttpHeaders;
}

export interface MockApi {
  url: string;
  requests: RecordedRequest[];
  counters: Record<string, number>;
  close: () => Promise<void>;
  reset: () => void;
}

function makeWords(): Array<{ text: string; start: number; end: number; prob: number; speaker: string; sentence_idx: number }> {
  const words: Array<{ text: string; start: number; end: number; prob: number; speaker: string; sentence_idx: number }> = [];
  const vocab = ["Preise", "im", "Handwerk", "sind", "seit", "Jahren", "ein", "Thema", "und", "viele", "Betriebe", "rechnen", "ihre", "Stunden", "nicht", "sauber", "durch", "das", "kostet", "Marge"];
  let t = 0;
  for (let i = 0; i < 300; i += 1) {
    const speaker = i < 120 ? "SPEAKER_00" : i < 200 ? "SPEAKER_01" : "SPEAKER_00";
    words.push({ text: `${vocab[i % vocab.length]}${i % 20 === 19 ? "." : ""}`, start: t, end: t + 0.4, prob: 0.95, speaker, sentence_idx: Math.floor(i / 20) });
    t += 0.5;
  }
  return words;
}

export const fixtures = {
  sources: [
    { id: "src_1", title: "Podcast Folge 12", status: "ready", duration_s: 3600, brand_profile_id: "bp_1", rights_status: "own", created_at: "2026-09-01T10:00:00Z" },
    { id: "src_2", title: "Keynote Handwerk", status: "analyzing", duration_s: 2400, brand_profile_id: "bp_1", rights_status: "licensed", created_at: "2026-09-02T10:00:00Z" },
  ],
  transcript: { id: "tv_1", source_id: "src_1", version: 3, language: "de", words: makeWords(), stats: { speaker_names: { SPEAKER_00: "Anna" } } },
  candidates: [
    {
      id: "cand_1", source_id: "src_1", version: 1, start_s: 812.4, end_s: 850.6, first_sent: 130, last_sent: 138, structure: "payoff_first", total: 8.2, gate_passed: true,
      why: "Kernaussage in 38 Sekunden vollständig.", risk_flags: [], human_verdict: null,
      rubric: { text: "SPEAKER_00: Viele Betriebe rechnen ihre Stunden nicht sauber durch.", speakers: ["SPEAKER_00"], duration_s: 38.2, scores: { hook: { value: 8, weight: 0.3, evidence: "Viele Betriebe rechnen ihre Stunden nicht sauber durch" } }, suggested_title_card: "" },
      gates: { standalone: { passed: true, detail: "keine offenen Verweise" }, no_open_loop: { passed: true, detail: "ok" } },
      story_graph_flags: [],
    },
    {
      id: "cand_2", source_id: "src_1", version: 1, start_s: 1200, end_s: 1250, first_sent: 200, last_sent: 210, structure: "loop", total: 5.1, gate_passed: false,
      why: "Endet auf aber.", risk_flags: ["humor"], human_verdict: null,
      rubric: { text: "SPEAKER_01: Das kostet Marge, aber", speakers: ["SPEAKER_01"], duration_s: 50, scores: {}, is_humor: true },
      gates: { standalone: { passed: true, detail: "ok" }, no_open_loop: { passed: false, detail: "endet auf „aber“" } },
      story_graph_flags: [{ marker: "das heißt aber nicht", confirmed: true, reason: "spätere Einschränkung", repair: "extend" }],
    },
    { id: "cand_3", source_id: "src_1", version: 1, start_s: 100, end_s: 130, structure: "how_to_list", total: 7.0, gate_passed: true, why: "ok", risk_flags: [], human_verdict: "rejected", verdict_reason: "zu allgemein", rubric: { text: "x", scores: {} }, gates: {} },
  ],
  clips: [
    {
      id: "clip_1", source_id: "src_1", candidate_id: "cand_1", platform: "linkedin", aspect: "4:5", status: "rendered", duration_s: 38.2, width: 1080, height: 1350, fps: 25,
      guest_approval_required: false, loudness: { integrated_lufs: -16.1, true_peak_dbtp: -1.6, preset: "master" },
      provenance: { c2pa: "skipped", reason: "c2patool nicht installiert", ai_label_required: false, ai_features: [], source_credit: "Quelle: Anna", ad_label: null },
      cps_warnings: [], rendered_at: "2026-09-03T10:00:00Z",
      render_plan: { contract: "render_plan_v1", platform: "linkedin", aspect: "4:5", output: { width: 1080, height: 1350, fps: 25 }, segments: [{ start: 812.4, end: 850.6, role: "body" }], reframe: { strategy: "talking_head", detector: "yunet", faces_detected: true }, shots: [{}, {}], captions: { preset: "linkedin_static", cards: 14 }, title_card: null, hook_overlay: { text: "Stunden sauber rechnen", seconds: 3 }, audio: { preset: "master", lufs: -16, true_peak: -1.5 } },
      hook: { id: "hv_1", clip_id: "clip_1", version: 1, origin: "llm", pattern: "results_first", spoken_hook: "Viele Betriebe verschenken Marge, weil sie Stunden nicht rechnen", onscreen_hook: "Stunden sauber rechnen", variants: [{ pattern: "results_first", spoken: "Viele Betriebe verschenken Marge, weil sie Stunden nicht rechnen", onscreen: "Stunden sauber rechnen", lint_notes: [], claim_issues: [] }, { pattern: "contrarian", spoken: "Der Stundensatz ist nicht das Problem", onscreen: "Stundensatz ist nicht das Problem", lint_notes: [], claim_issues: [] }], post_captions: { linkedin: "Stunden sauber rechnen." }, cta: null, lint_notes: [], claim_issues: [] },
      media: { video_url: "https://media.example/renders/clip_1.mp4", poster_url: "https://media.example/renders/clip_1.jpg", srt_url: null, vtt_url: null },
    },
    { id: "clip_2", source_id: "src_1", candidate_id: "cand_1", platform: "tiktok", aspect: "9:16", status: "rendered", duration_s: 38.2, guest_approval_required: true, hook: null, render_plan: null, provenance: null, loudness: null, cps_warnings: ["Karte 3: 19 Zeichen/Sekunde"] },
    { id: "clip_3", source_id: "src_1", candidate_id: "cand_1", platform: "reels", aspect: "9:16", status: "failed", render_error: "ffmpeg ohne libass", hook: null },
  ],
  usage: { period_start: "2026-09-01", period_end: "2026-09-30", included_minutes: 720, used_source_minutes: 600, render_count: 12, overage_minutes: 0, overage_eur: 0, plan: "pro" },
};

function json(res: http.ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
}

function apiError(res: http.ServerResponse, status: number, code: string, message: string): void {
  json(res, status, { error: { code, message } });
}

export function startMockApi(): Promise<MockApi> {
  const requests: RecordedRequest[] = [];
  const counters: Record<string, number> = {};

  const server = http.createServer((req, res) => {
    const url = new URL(req.url ?? "/", "http://localhost");
    const chunks: Buffer[] = [];
    req.on("data", (c: Buffer) => chunks.push(c));
    req.on("end", () => {
      const raw = Buffer.concat(chunks).toString("utf8");
      let body: unknown = undefined;
      if (raw) {
        try {
          body = JSON.parse(raw);
        } catch {
          body = raw;
        }
      }
      const path = url.pathname.replace(/^\/api\/v1/, "");
      const query: Record<string, string> = {};
      url.searchParams.forEach((v, k) => (query[k] = v));
      requests.push({ method: req.method ?? "GET", path, query, body, headers: req.headers });
      counters[path] = (counters[path] ?? 0) + 1;

      if (path === "/slow") return; /* nie antworten: Timeout-Test */
      if (path === "/flaky") {
        if (counters[path]! < 3) return apiError(res, 503, "unavailable", "kurz nicht erreichbar");
        return json(res, 200, { ok: true, attempts: counters[path] });
      }
      if (path === "/always-500") return apiError(res, 500, "internal", "Datenbank weg");
      if (path === "/no-json") {
        res.writeHead(200, { "Content-Type": "text/html" });
        return res.end("<html>");
      }

      if (req.headers.authorization !== `Bearer ${MOCK_API_KEY}`) {
        return apiError(res, 401, "unauthorized", "Schlüssel ungültig");
      }
      if (path === "/quota") return apiError(res, 402, "quota_exceeded", "Kontingent für September aufgebraucht");
      if (path === "/forbidden") return apiError(res, 403, "scope_missing", "Scope write fehlt");
      if (path === "/rate") return apiError(res, 429, "rate_limited", "zu viele Anfragen");
      if (path === "/plain-error") return json(res, 400, { error: "nur ein String" });

      const m = (pattern: RegExp) => pattern.exec(path);
      let match: RegExpExecArray | null;

      if (req.method === "GET" && path === "/sources") return json(res, 200, { sources: fixtures.sources });
      if (req.method === "POST" && path === "/sources") {
        const b = (body ?? {}) as Record<string, unknown>;
        if (b.rights_confirmed !== true || !b.source_owner || !b.source_url) return apiError(res, 400, "rights_required", "rights_confirmed, source_owner und source_url sind Pflicht");
        return json(res, 201, { source: { id: "src_new", title: b.title, status: "uploading", rights_status: b.rights_status }, upload_token: "tok_x", tus_endpoint: "http://localhost:1080/files/" });
      }
      if ((match = m(/^\/sources\/([^/]+)$/)) && req.method === "GET") {
        const s = fixtures.sources.find((x) => x.id === match![1]);
        return s ? json(res, 200, s) : apiError(res, 404, "not_found", "Quelle nicht gefunden");
      }
      if ((match = m(/^\/sources\/([^/]+)\/transcript$/))) {
        if (match[1] !== "src_1") return apiError(res, 404, "not_found", "Kein Transkript vorhanden");
        return json(res, 200, fixtures.transcript);
      }
      if ((match = m(/^\/sources\/([^/]+)\/candidates$/))) return json(res, 200, { candidates: fixtures.candidates.filter((c) => c.source_id === match![1]) });
      if ((match = m(/^\/sources\/([^/]+)\/clips$/))) return json(res, 200, { clips: fixtures.clips.filter((c) => c.source_id === match![1]) });

      if ((match = m(/^\/candidates\/([^/]+)\/verdict$/)) && req.method === "POST") {
        const b = (body ?? {}) as Record<string, unknown>;
        const c = fixtures.candidates.find((x) => x.id === match![1]);
        if (!c) return apiError(res, 404, "not_found", "Kandidat nicht gefunden");
        if (b.verdict === "rejected" && !b.reason) return apiError(res, 400, "reason_required", "Beim Ablehnen ist ein Grund Pflicht");
        const platforms = Array.isArray(b.platforms) ? (b.platforms as string[]) : ["tiktok", "reels", "shorts", "linkedin"];
        const clips = b.verdict === "accepted" ? platforms.map((p, i) => ({ id: `clip_new_${i}`, platform: p, status: "draft" })) : [];
        return json(res, 200, { ok: true, candidate: { ...c, human_verdict: b.verdict, verdict_reason: b.reason ?? null }, clips, platforms });
      }
      if ((match = m(/^\/candidates\/([^/]+)\/revise$/)) && req.method === "POST") {
        const b = (body ?? {}) as Record<string, unknown>;
        const c = fixtures.candidates.find((x) => x.id === match![1]);
        if (!c) return apiError(res, 404, "not_found", "Kandidat nicht gefunden");
        return json(res, 200, { ok: true, candidate: { ...c, id: `${c.id}_v2`, version: 2, first_sent: b.first_sent ?? c.first_sent, last_sent: b.last_sent ?? c.last_sent, gate_passed: true, rubric: { ...c.rubric, parent_id: c.id, suggested_title_card: b.title_card ?? "" } } });
      }

      if ((match = m(/^\/clips\/([^/]+)$/)) && req.method === "GET") {
        const c = fixtures.clips.find((x) => x.id === match![1]);
        return c ? json(res, 200, c) : apiError(res, 404, "not_found", "Clip nicht gefunden");
      }
      if ((match = m(/^\/clips\/([^/]+)\/render$/)) && req.method === "POST") return json(res, 202, { ok: true, status: "rendering" });
      if ((match = m(/^\/clips\/([^/]+)\/hooks$/)) && req.method === "POST") {
        const b = (body ?? {}) as Record<string, unknown>;
        const c = fixtures.clips.find((x) => x.id === match![1]);
        if (!c) return apiError(res, 404, "not_found", "Clip nicht gefunden");
        return json(res, 200, { ok: true, hook: { id: "hv_2", clip_id: c.id, version: 2, origin: "manual", ...b, lint_notes: [], claim_issues: b.spoken_hook && /\d/.test(String(b.spoken_hook)) ? ["Zahl nicht im Clip"] : [] }, needs_render: c.status === "rendered" });
      }
      if ((match = m(/^\/clips\/([^/]+)\/guest-approval$/)) && req.method === "POST") {
        const b = (body ?? {}) as Record<string, unknown>;
        return json(res, 201, { approval: { id: "ga_1", clip_id: match[1], guest_name: b.guest_name, expires_at: "2026-10-06T10:00:00Z", decision: null }, link: "http://localhost:3000/freigabe/tok_guest" });
      }
      if ((match = m(/^\/clips\/([^/]+)\/publish$/)) && req.method === "POST") {
        const b = (body ?? {}) as Record<string, unknown>;
        const c = fixtures.clips.find((x) => x.id === match![1]);
        if (!c) return apiError(res, 404, "not_found", "Clip nicht gefunden");
        if (c.guest_approval_required) return apiError(res, 409, "guest_approval_missing", "Gast-Freigabe fehlt");
        if (!b.connection_id) return apiError(res, 400, "connection_required", "connection_id fehlt");
        return json(res, 201, { publication: { id: "pub_1", clip_id: c.id, connection_id: b.connection_id, status: b.scheduled_for ? "scheduled" : "publishing", scheduled_for: b.scheduled_for ?? null } });
      }
      if ((match = m(/^\/clips\/([^/]+)\/download$/))) {
        res.writeHead(302, { Location: "https://media.example/signed/clip.mp4" });
        return res.end();
      }
      if (path === "/usage") return json(res, 200, fixtures.usage);
      if (path === "/me") return json(res, 200, { workspace: { id: "ws_1", name: "Test" }, scopes: ["read", "write", "publish"] });
      return apiError(res, 404, "not_found", "Unbekannter Endpunkt");
    });
  });

  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address() as AddressInfo;
      resolve({
        url: `http://127.0.0.1:${port}/api/v1`,
        requests,
        counters,
        reset: () => {
          requests.length = 0;
          for (const k of Object.keys(counters)) delete counters[k];
        },
        close: () => new Promise((r) => { server.closeAllConnections(); server.close(() => r()); }),
      });
    });
  });
}
