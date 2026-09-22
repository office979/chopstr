import type { JsonSchema } from "@/lib/api/validate";
import type { ApiScope } from "@/lib/repo/types-api";
import { WEBHOOK_EVENTS } from "@/lib/repo/types-api";

/* Zentrale Definition der öffentlichen API /api/v1 (PHASE5.md, 5a). Daraus entstehen das OpenAPI-3.1-Dokument
 * unter /api/v1/openapi.json und die Body-Prüfung in den Handlern (lib/api/validate.ts, readJsonBody mit
 * requestSchema()). Neue Endpunkte bitte hier eintragen, nicht nur als Route. */

export const API_VERSION = "1.0.0";
export const API_TITLE = "chopstr API";

const PLATFORMS = ["tiktok", "reels", "shorts", "linkedin"] as const;
const HOOK_PATTERNS = ["identity_call", "contrarian", "open_loop", "results_first", "mistake_warning"] as const;

const uuid: JsonSchema = { type: "string", format: "uuid" };
const idParam = (name: string, description: string) => ({ name, in: "path" as const, required: true as const, description, schema: { type: "string" } });

export const SCHEMAS: Record<string, JsonSchema> = {
  Error: {
    type: "object",
    required: ["error"],
    properties: {
      error: {
        type: "object",
        required: ["code", "message"],
        properties: { code: { type: "string", example: "not_found" }, message: { type: "string", example: "Quelle nicht gefunden" } },
      },
    },
  },
  Brief: {
    type: "object",
    description: "Briefing für Kandidatenauswahl und Copy",
    properties: {
      audience: { type: "string", maxLength: 500 },
      wanted: { type: "string", maxLength: 500 },
      exclude: { type: "string", maxLength: 500 },
      platform: { type: "string", enum: PLATFORMS },
      is_ad: { type: "boolean", description: "Bezahlte Partnerschaft: Clips erhalten ein Werbelabel" },
      import_url: { type: "string", format: "uri", description: "Nur bei upload = url: Quelle des Ingests (setzt der Server)" },
    },
    additionalProperties: true,
  },
  CreateSource: {
    type: "object",
    required: ["title", "rights_confirmed", "upload"],
    properties: {
      title: { type: "string", minLength: 1, maxLength: 200 },
      brand_profile_id: { type: ["string", "null"], format: "uuid" },
      rights_status: { type: "string", enum: ["own", "licensed", "third_party"], default: "own" },
      rights_confirmed: { type: "boolean", const: true, description: "Muss true sein: Rechte für Schnitt und Veröffentlichung liegen vor" },
      source_owner: { type: ["string", "null"], maxLength: 200, description: "Urheber oder Rechteinhaber; Pflicht bei upload = url" },
      source_title: { type: ["string", "null"], maxLength: 200 },
      source_url: { type: ["string", "null"], format: "uri", description: "Öffentliche Video-URL; Pflicht bei upload = url" },
      expected_speakers: { type: ["integer", "null"], minimum: 1, maximum: 12 },
      brief: { $ref: "#/components/schemas/Brief" },
      upload: { type: "string", enum: ["tus", "url"], description: "tus: Datei anschließend per tus hochladen (upload_token, tus_endpoint); url: Ingest per Download" },
    },
    additionalProperties: false,
  },
  Verdict: {
    type: "object",
    required: ["verdict"],
    properties: {
      verdict: { type: "string", enum: ["accepted", "rejected"] },
      reason: { type: "string", maxLength: 500, description: "Pflicht bei rejected (Lernsignal)" },
      platforms: { type: "array", items: { type: "string", enum: PLATFORMS }, minItems: 1, description: "Zielplattformen bei accepted, Standard alle vier" },
    },
    additionalProperties: false,
  },
  Revise: {
    type: "object",
    properties: {
      first_sent: { type: "integer", minimum: 0 },
      last_sent: { type: "integer", minimum: 0 },
      title_card: { type: "string", maxLength: 120, description: "Titelkarte, höchstens 8 Wörter" },
    },
    additionalProperties: false,
  },
  SaveHook: {
    type: "object",
    properties: {
      spoken_hook: { type: "string", maxLength: 300 },
      onscreen_hook: { type: "string", maxLength: 300 },
      pattern: { type: ["string", "null"], enum: [...HOOK_PATTERNS, null] },
      post_captions: { type: "object", properties: Object.fromEntries(PLATFORMS.map((p) => [p, { type: "string", maxLength: 3000 }])) },
      cta: { type: "string", maxLength: 300 },
    },
    additionalProperties: false,
  },
  GuestApprovalRequest: {
    type: "object",
    required: ["guest_name"],
    properties: {
      guest_name: { type: "string", minLength: 2, maxLength: 120 },
      guest_email: { type: ["string", "null"], format: "email" },
      message: { type: "string", maxLength: 1000 },
    },
    additionalProperties: false,
  },
  Publish: {
    type: "object",
    required: ["connection_id"],
    properties: {
      connection_id: uuid,
      scheduled_for: { type: ["string", "null"], format: "date-time", description: "ISO 8601 mit Zeitzone; leer = sofort" },
      caption: { type: ["string", "null"], maxLength: 3000 },
      title: { type: ["string", "null"], maxLength: 200 },
    },
    additionalProperties: false,
  },
  CreateBrandProfile: {
    type: "object",
    required: ["name"],
    properties: {
      name: { type: "string", minLength: 2, maxLength: 120 },
      address: { type: "string", enum: ["du", "sie"], default: "du" },
      country: { type: "string", enum: ["DE", "AT", "CH"], default: "AT" },
      gender_mode: { type: "string", enum: ["neutral", "paarform", "doppelpunkt", "stern", "keine"], default: "neutral" },
      asr_variant: { type: "string", enum: ["de", "de-CH"], default: "de" },
      default_platform: { type: "string", enum: PLATFORMS, default: "linkedin" },
      caption_preset: { type: "string", enum: ["tiktok_bold", "reels_clean", "shorts_clean", "linkedin_static", "corporate_third"], default: "linkedin_static" },
      tone_adjectives: { type: "array", items: { type: "string", maxLength: 40 }, maxItems: 3 },
      brand_vocab: { type: "array", items: { type: "string", maxLength: 80 }, maxItems: 500 },
      protected_terms: { type: "array", items: { type: "string", maxLength: 80 }, maxItems: 500 },
      banned_phrases: { type: "array", items: { type: "string", maxLength: 120 }, maxItems: 500 },
      ci: { type: "object", additionalProperties: true },
      caption_style: { type: "object", additionalProperties: true },
    },
    additionalProperties: false,
  },
  CreateWebhook: {
    type: "object",
    required: ["url", "events"],
    properties: {
      url: { type: "string", format: "uri", description: "Nur https, kein privater oder lokaler Host" },
      events: { type: "array", items: { type: "string", enum: WEBHOOK_EVENTS }, minItems: 1 },
      active: { type: "boolean", default: true },
    },
    additionalProperties: false,
  },
  Source: {
    type: "object",
    properties: {
      id: uuid,
      title: { type: "string" },
      status: { type: "string", enum: ["uploading", "uploaded", "ingesting", "transcribing", "analyzing", "scoring", "ready", "failed", "deleted"] },
      status_message: { type: ["string", "null"] },
      duration_s: { type: ["number", "null"] },
      brand_profile_id: { type: ["string", "null"] },
      rights_status: { type: "string" },
      source_owner: { type: ["string", "null"] },
      source_url: { type: ["string", "null"] },
      brief: { $ref: "#/components/schemas/Brief" },
      created_at: { type: "string", format: "date-time" },
      updated_at: { type: "string", format: "date-time" },
    },
  },
  Transcript: {
    type: "object",
    properties: {
      id: uuid,
      source_id: uuid,
      version: { type: "integer" },
      language: { type: "string" },
      asr_variant: { type: ["string", "null"] },
      words: {
        type: "array",
        items: {
          type: "object",
          properties: {
            text: { type: "string" },
            text_norm: { type: ["string", "null"], description: "Standarddeutsche Form (Schweizerdeutsch-Beta), nur bei sicherer Entsprechung" },
            start: { type: "number" },
            end: { type: "number" },
            prob: { type: "number" },
            speaker: { type: "string" },
            filler: { type: ["string", "null"] },
            negation: { type: "boolean" },
            sentence_idx: { type: "integer" },
          },
        },
      },
      stats: { type: "object", additionalProperties: true, description: "word_count, speakers, speaker_names, dialect { variant, confidence, markers }" },
    },
  },
  Candidate: {
    type: "object",
    description: "Kandidat nach packages/schema/CANDIDATES.md (candidates_v1) mit Rubrik, Gates, Story-Graph-Flags",
    properties: {
      id: uuid,
      source_id: uuid,
      version: { type: "integer" },
      start_s: { type: "number" },
      end_s: { type: "number" },
      first_sent: { type: ["integer", "null"] },
      last_sent: { type: ["integer", "null"] },
      structure: { type: ["string", "null"] },
      total: { type: ["number", "null"] },
      gate_passed: { type: "boolean" },
      why: { type: ["string", "null"] },
      rubric: { type: "object", additionalProperties: true },
      gates: { type: "object", additionalProperties: true },
      story_graph_flags: { type: "array", items: { type: "object", additionalProperties: true } },
      risk_flags: { type: "array", items: { type: "string" } },
      human_verdict: { type: ["string", "null"], enum: ["accepted", "rejected", "edited", null] },
      verdict_reason: { type: ["string", "null"] },
    },
  },
  Media: {
    type: "object",
    properties: {
      video_url: { type: ["string", "null"] },
      poster_url: { type: ["string", "null"] },
      srt_url: { type: ["string", "null"] },
      vtt_url: { type: ["string", "null"] },
    },
  },
  Hook: {
    type: "object",
    properties: {
      id: uuid,
      clip_id: uuid,
      version: { type: "integer" },
      spoken_hook: { type: ["string", "null"] },
      onscreen_hook: { type: ["string", "null"] },
      pattern: { type: ["string", "null"] },
      variants: { type: "array", items: { type: "object", additionalProperties: true } },
      post_captions: { type: "object", additionalProperties: true },
      cta: { type: ["string", "null"] },
      lint_notes: { type: "array", items: { type: "string" } },
      claim_issues: { type: "array", items: { type: "string" } },
      origin: { type: "string", enum: ["llm", "manual"] },
    },
  },
  Clip: {
    type: "object",
    description: "Clip nach packages/schema/CLIPS.md (clips_v1); media enthält die Medien-URLs",
    properties: {
      id: uuid,
      source_id: uuid,
      candidate_id: { type: ["string", "null"] },
      platform: { type: "string", enum: PLATFORMS },
      aspect: { type: "string" },
      status: { type: "string", enum: ["draft", "approved", "rendering", "rendered", "exported", "failed", "deleted"] },
      guest_approval_required: { type: "boolean" },
      duration_s: { type: ["number", "null"] },
      render_plan: { type: ["object", "null"], additionalProperties: true },
      loudness: { type: ["object", "null"], additionalProperties: true },
      provenance: { type: ["object", "null"], additionalProperties: true },
      cps_warnings: { type: "array", items: { type: "string" } },
      render_error: { type: ["string", "null"] },
      media: { $ref: "#/components/schemas/Media" },
      hook: { $ref: "#/components/schemas/Hook" },
      guest_approval: { type: ["object", "null"], additionalProperties: true },
    },
  },
  GuestApproval: {
    type: "object",
    properties: {
      id: uuid,
      clip_id: uuid,
      guest_name: { type: ["string", "null"] },
      guest_email: { type: ["string", "null"] },
      expires_at: { type: ["string", "null"] },
      decision: { type: ["string", "null"], enum: ["approved", "rejected", "changes", null] },
      decided_at: { type: ["string", "null"] },
    },
  },
  Publication: {
    type: "object",
    properties: {
      id: uuid,
      clip_id: uuid,
      connection_id: { type: ["string", "null"] },
      platform: { type: "string" },
      status: { type: "string", enum: ["scheduled", "publishing", "published", "failed", "manual"] },
      scheduled_for: { type: ["string", "null"] },
      caption: { type: ["string", "null"] },
      title: { type: ["string", "null"] },
      external_url: { type: ["string", "null"] },
      error: { type: ["string", "null"] },
      published_at: { type: ["string", "null"] },
      metrics: { type: ["object", "null"], additionalProperties: true },
    },
  },
  BrandProfile: { type: "object", additionalProperties: true, description: "Markenprofil (brand_profiles)" },
  Webhook: {
    type: "object",
    properties: {
      id: uuid,
      url: { type: "string" },
      events: { type: "array", items: { type: "string" } },
      active: { type: "boolean" },
      created_at: { type: "string" },
    },
  },
  Usage: {
    type: "object",
    properties: {
      period_start: { type: ["string", "null"] },
      period_end: { type: ["string", "null"] },
      included_minutes: { type: "number" },
      used_source_minutes: { type: "number" },
      render_count: { type: "integer" },
      overage_minutes: { type: "number" },
      overage_eur: { type: "number" },
      plan: { type: ["string", "null"] },
      allow_overage: { type: "boolean" },
      exhausted: { type: "boolean" },
    },
  },
  Me: {
    type: "object",
    properties: {
      workspace: { type: "object", properties: { id: uuid, name: { type: "string" }, slug: { type: "string" }, plan: { type: "string" }, tier: { type: "string" }, data_region: { type: "string" } } },
      scopes: { type: "array", items: { type: "string", enum: ["read", "write", "publish", "admin"] } },
      role: { type: "string" },
      key: { type: "object", properties: { id: uuid, name: { type: "string" }, key_prefix: { type: "string" }, expires_at: { type: ["string", "null"] } } },
    },
  },
};

export interface QueryParam {
  name: string;
  in: "query";
  required?: boolean;
  description: string;
  schema: JsonSchema;
}

export interface EndpointDef {
  method: "get" | "post" | "delete";
  path: string;
  operationId: string;
  summary: string;
  description?: string;
  scope: ApiScope;
  tag: string;
  params?: { name: string; in: "path"; required: true; description: string; schema: JsonSchema }[];
  query?: QueryParam[];
  /* Name eines Schemas aus SCHEMAS */
  requestBody?: string;
  responses: Record<string, { description: string; schema?: JsonSchema; contentType?: string }>;
}

const ref = (name: string): JsonSchema => ({ $ref: `#/components/schemas/${name}` });
const list = (key: string, name: string): JsonSchema => ({ type: "object", required: [key], properties: { [key]: { type: "array", items: ref(name) } } });
const single = (key: string, name: string, extra: Record<string, JsonSchema> = {}): JsonSchema => ({ type: "object", required: [key], properties: { [key]: ref(name), ...extra } });
const ERR = (description: string) => ({ description, schema: ref("Error") });

export const ENDPOINTS: EndpointDef[] = [
  {
    method: "get", path: "/sources", operationId: "listSources", summary: "Quellen auflisten", scope: "read", tag: "Quellen",
    query: [{ name: "status", in: "query", description: "Nur Quellen mit diesem Status", schema: { type: "string" } }, { name: "limit", in: "query", description: "Höchstzahl, Standard 100", schema: { type: "integer", minimum: 1, maximum: 500 } }],
    responses: { "200": { description: "Liste", schema: list("sources", "Source") } },
  },
  {
    method: "post", path: "/sources", operationId: "createSource", summary: "Quelle anlegen",
    description: "upload = tus: Antwort enthält upload_token und tus_endpoint; die Datei wird anschließend per tus mit den Metadaten upload_token, client_ref (= source.id), title und rights_confirmed = true hochgeladen. upload = url: nur mit rights_confirmed, source_owner und source_url; die Quelle entsteht mit Status uploading und brief.import_url, der Ingest startet über Temporal (Worker-Ingest per URL: offener Punkt, siehe README).",
    scope: "write", tag: "Quellen", requestBody: "CreateSource",
    responses: { "201": { description: "Angelegt", schema: single("source", "Source", { upload_token: { type: ["string", "null"] }, tus_endpoint: { type: ["string", "null"] }, tus_metadata: { type: ["object", "null"], additionalProperties: true }, workflow_id: { type: ["string", "null"] }, hint: { type: ["string", "null"] } }) }, "400": ERR("Rechte fehlen oder Eingaben ungültig"), "402": ERR("Kontingent erschöpft") },
  },
  { method: "get", path: "/sources/{id}", operationId: "getSource", summary: "Quelle anzeigen", scope: "read", tag: "Quellen", params: [idParam("id", "Quellen-ID")], responses: { "200": { description: "Quelle", schema: single("source", "Source") }, "404": ERR("Nicht gefunden") } },
  { method: "delete", path: "/sources/{id}", operationId: "deleteSource", summary: "Quelle löschen", description: "Setzt status = deleted, legt einen Löschauftrag an und startet den DeletionWorkflow (ohne Temporal führt der tägliche Retention-Lauf ihn aus).", scope: "write", tag: "Quellen", params: [idParam("id", "Quellen-ID")], responses: { "200": { description: "Löschung eingeplant", schema: { type: "object", properties: { ok: { type: "boolean" }, job: { type: "object", additionalProperties: true }, started: { type: "boolean" }, message: { type: "string" } } } }, "404": ERR("Nicht gefunden"), "409": ERR("Bereits gelöscht") } },
  { method: "get", path: "/sources/{id}/transcript", operationId: "getTranscript", summary: "Aktuelles Transkript", scope: "read", tag: "Quellen", params: [idParam("id", "Quellen-ID")], responses: { "200": { description: "Transkript", schema: single("transcript", "Transcript") }, "404": ERR("Kein Transkript") } },
  { method: "get", path: "/sources/{id}/candidates", operationId: "listCandidates", summary: "Kandidaten einer Quelle", description: "Aktuelle Versionen, Pflichtkriterien erfüllt zuerst, dann total absteigend.", scope: "read", tag: "Kandidaten", params: [idParam("id", "Quellen-ID")], responses: { "200": { description: "Liste", schema: { ...list("candidates", "Candidate"), properties: { candidates: { type: "array", items: ref("Candidate") }, count: { type: "object", additionalProperties: true } } } } } },
  { method: "get", path: "/sources/{id}/clips", operationId: "listClips", summary: "Clips einer Quelle", scope: "read", tag: "Clips", params: [idParam("id", "Quellen-ID")], query: [{ name: "status", in: "query", description: "Nur Clips mit diesem Status", schema: { type: "string" } }], responses: { "200": { description: "Liste", schema: { ...list("clips", "Clip"), properties: { clips: { type: "array", items: ref("Clip") }, count: { type: "object", additionalProperties: true } } } } } },
  { method: "get", path: "/sources/{id}/events", operationId: "sourceEvents", summary: "Pipeline-Ereignisse als SSE", description: "text/event-stream mit den Ereignissen hello, pipeline, status, done, error. Schließt bei ready oder failed.", scope: "read", tag: "Quellen", params: [idParam("id", "Quellen-ID")], query: [{ name: "after", in: "query", description: "Nur Ereignisse mit größerer ID", schema: { type: "integer" } }], responses: { "200": { description: "Ereignisstrom", contentType: "text/event-stream" } } },
  { method: "get", path: "/candidates/{id}", operationId: "getCandidate", summary: "Kandidat mit Rubrik, Gates und Flags", scope: "read", tag: "Kandidaten", params: [idParam("id", "Kandidaten-ID")], responses: { "200": { description: "Kandidat", schema: single("candidate", "Candidate") }, "404": ERR("Nicht gefunden") } },
  { method: "post", path: "/candidates/{id}/verdict", operationId: "candidateVerdict", summary: "Kandidat annehmen oder ablehnen", description: "accepted legt je Zielplattform einen Clip an und signalisiert den Render; rejected braucht einen Grund.", scope: "write", tag: "Kandidaten", params: [idParam("id", "Kandidaten-ID")], requestBody: "Verdict", responses: { "200": { description: "Urteil gespeichert", schema: { type: "object", properties: { ok: { type: "boolean" }, candidate: ref("Candidate"), clips: { type: "array", items: ref("Clip") }, platforms: { type: "array", items: { type: "string" } } } } }, "400": ERR("Grund fehlt"), "409": ERR("Kandidat wurde ersetzt") } },
  { method: "post", path: "/candidates/{id}/revise", operationId: "reviseCandidate", summary: "Verlängern, kürzen oder Titelkarte", description: "Legt eine neue Kandidaten-Version an (version + 1); die alte bekommt human_verdict = edited.", scope: "write", tag: "Kandidaten", params: [idParam("id", "Kandidaten-ID")], requestBody: "Revise", responses: { "200": { description: "Neue Version", schema: { type: "object", properties: { ok: { type: "boolean" }, candidate: ref("Candidate") } } }, "400": ERR("Grenzen ungültig") } },
  { method: "get", path: "/clips/{id}", operationId: "getClip", summary: "Clip mit Medien-URLs, Hook und Captions", scope: "read", tag: "Clips", params: [idParam("id", "Clip-ID")], responses: { "200": { description: "Clip", schema: single("clip", "Clip", { hook: ref("Hook"), media: ref("Media") }) }, "404": ERR("Nicht gefunden") } },
  { method: "get", path: "/clips/{id}/download", operationId: "downloadClip", summary: "Download (302 auf Medien-URL)", description: "409 mit code guest_approval_pending, solange eine verlangte Gast-Freigabe fehlt. Ein MP4-Download setzt den Clip auf exported.", scope: "read", tag: "Clips", params: [idParam("id", "Clip-ID")], query: [{ name: "kind", in: "query", description: "mp4 (Standard), srt, vtt oder poster", schema: { type: "string", enum: ["mp4", "srt", "vtt", "poster"] } }], responses: { "302": { description: "Umleitung auf die Datei" }, "404": ERR("Datei noch nicht verfügbar"), "409": ERR("Gast-Freigabe fehlt") } },
  { method: "post", path: "/clips/{id}/render", operationId: "renderClip", summary: "Render oder Re-Render anstoßen", scope: "write", tag: "Clips", params: [idParam("id", "Clip-ID")], responses: { "200": { description: "Angestoßen", schema: { type: "object", properties: { ok: { type: "boolean" }, status: { type: "string" }, clip: ref("Clip"), signaled: { type: "boolean" } } } }, "409": ERR("Wird gerade gerendert") } },
  { method: "post", path: "/clips/{id}/hooks", operationId: "saveHook", summary: "Manuelle Hook-Version speichern", description: "Linter und Claim-Check laufen serverseitig; Antwort enthält lint_notes und claim_issues sowie needs_render.", scope: "write", tag: "Clips", params: [idParam("id", "Clip-ID")], requestBody: "SaveHook", responses: { "200": { description: "Gespeichert", schema: { type: "object", properties: { ok: { type: "boolean" }, hook: ref("Hook"), needs_render: { type: "boolean" } } } } } },
  { method: "post", path: "/clips/{id}/guest-approval", operationId: "requestGuestApproval", summary: "Gast-Freigabe anfordern", description: "Link 14 Tage gültig; mit guest_email wird eine E-Mail versendet. Plan-Gate features.guest_approval.", scope: "write", tag: "Clips", params: [idParam("id", "Clip-ID")], requestBody: "GuestApprovalRequest", responses: { "201": { description: "Angefordert", schema: { type: "object", required: ["approval", "link"], properties: { approval: ref("GuestApproval"), link: { type: "string" } } } }, "403": ERR("Plan enthält keine Gast-Freigaben") } },
  { method: "post", path: "/clips/{id}/publish", operationId: "publishClip", summary: "Clip veröffentlichen oder planen", description: "Gates: Clip rendered, Kandidat accepted, Gast-Freigabe approved falls verlangt, AVV angenommen, Plan features.publishing (sonst 402). Legt eine Publikation an und startet PublishWorkflow publish-<id>; ohne Temporal bleibt sie scheduled.", scope: "publish", tag: "Publishing", params: [idParam("id", "Clip-ID")], requestBody: "Publish", responses: { "201": { description: "Publikation angelegt", schema: single("publication", "Publication", { workflow_started: { type: "boolean" }, hint: { type: ["string", "null"] } }) }, "402": ERR("Plan ohne Publishing"), "409": ERR("Gate nicht erfüllt") } },
  { method: "get", path: "/publications/{id}", operationId: "getPublication", summary: "Publikation anzeigen", scope: "publish", tag: "Publishing", params: [idParam("id", "Publikations-ID")], responses: { "200": { description: "Publikation", schema: single("publication", "Publication") }, "404": ERR("Nicht gefunden") } },
  { method: "get", path: "/brand-profiles", operationId: "listBrandProfiles", summary: "Markenprofile auflisten", scope: "read", tag: "Markenprofile", responses: { "200": { description: "Liste", schema: list("brand_profiles", "BrandProfile") } } },
  { method: "post", path: "/brand-profiles", operationId: "createBrandProfile", summary: "Markenprofil anlegen", scope: "write", tag: "Markenprofile", requestBody: "CreateBrandProfile", responses: { "201": { description: "Angelegt", schema: single("brand_profile", "BrandProfile") } } },
  { method: "get", path: "/webhooks", operationId: "listWebhooks", summary: "Webhook-Endpunkte auflisten", scope: "admin", tag: "Webhooks", responses: { "200": { description: "Liste", schema: list("webhooks", "Webhook") } } },
  { method: "post", path: "/webhooks", operationId: "createWebhook", summary: "Webhook-Endpunkt anlegen", description: "Das Secret (HMAC-SHA256, Header X-Chopstr-Signature: t=…,v1=…) erscheint nur in dieser Antwort.", scope: "admin", tag: "Webhooks", requestBody: "CreateWebhook", responses: { "201": { description: "Angelegt", schema: single("webhook", "Webhook", { secret: { type: "string" } }) }, "400": ERR("URL nicht erlaubt") } },
  { method: "delete", path: "/webhooks/{id}", operationId: "deleteWebhook", summary: "Webhook-Endpunkt löschen", scope: "admin", tag: "Webhooks", params: [idParam("id", "Endpunkt-ID")], responses: { "200": { description: "Gelöscht", schema: { type: "object", properties: { ok: { type: "boolean" } } } }, "404": ERR("Nicht gefunden") } },
  { method: "get", path: "/usage", operationId: "getUsage", summary: "Kontingent des laufenden Monats", scope: "read", tag: "Workspace", responses: { "200": { description: "Kontingent", schema: single("usage", "Usage") } } },
  { method: "get", path: "/me", operationId: "getMe", summary: "Workspace und Scopes des Schlüssels", scope: "read", tag: "Workspace", responses: { "200": { description: "Ich", schema: ref("Me") } } },
];

export function requestSchema(name: string): JsonSchema {
  const schema = SCHEMAS[name];
  if (!schema) throw new Error(`Unbekanntes Schema ${name}`);
  return schema;
}

export function resolveRef(ref: string): JsonSchema | undefined {
  const name = ref.replace("#/components/schemas/", "");
  return SCHEMAS[name];
}

function toOpenApiSchema(schema: JsonSchema): Record<string, unknown> {
  const out: Record<string, unknown> = { ...schema };
  delete out.nullable;
  if (schema.nullable && schema.type && !Array.isArray(schema.type)) out.type = [schema.type, "null"];
  if (schema.properties) out.properties = Object.fromEntries(Object.entries(schema.properties).map(([k, v]) => [k, toOpenApiSchema(v)]));
  if (schema.items) out.items = toOpenApiSchema(schema.items);
  if (schema.additionalProperties && typeof schema.additionalProperties === "object") out.additionalProperties = toOpenApiSchema(schema.additionalProperties);
  return out;
}

/* OpenAPI-3.1-Dokument; baseUrl ist die öffentliche Basis (APP_BASE_URL oder Request-Host) */
export function buildOpenApiDocument(baseUrl: string): Record<string, unknown> {
  const paths: Record<string, Record<string, unknown>> = {};
  for (const e of ENDPOINTS) {
    const op: Record<string, unknown> = {
      operationId: e.operationId,
      summary: e.summary,
      description: e.description,
      tags: [e.tag],
      security: [{ apiKey: [e.scope] }],
      "x-scope": e.scope,
      parameters: [...(e.params ?? []), ...(e.query ?? [])].map((p) => ({ ...p, schema: toOpenApiSchema(p.schema) })),
      responses: Object.fromEntries(
        Object.entries(e.responses).map(([status, r]) => [
          status,
          r.schema || r.contentType ? { description: r.description, content: { [r.contentType ?? "application/json"]: r.schema ? { schema: toOpenApiSchema(r.schema) } : {} } } : { description: r.description },
        ]),
      ),
    };
    if (e.requestBody) op.requestBody = { required: true, content: { "application/json": { schema: { $ref: `#/components/schemas/${e.requestBody}` } } } };
    for (const common of ["401", "403", "429"]) {
      const responses = op.responses as Record<string, unknown>;
      if (!responses[common]) {
        responses[common] = { description: common === "401" ? "Schlüssel fehlt, ungültig, abgelaufen oder widerrufen" : common === "403" ? "Scope fehlt" : "Rate-Limit erreicht (600/min je Schlüssel)", content: { "application/json": { schema: { $ref: "#/components/schemas/Error" } } } };
      }
    }
    paths[e.path] = { ...(paths[e.path] ?? {}), [e.method]: op };
  }
  return {
    openapi: "3.1.0",
    info: {
      title: API_TITLE,
      version: API_VERSION,
      description:
        "Öffentliche API von chopstr. Auth über Authorization: Bearer chp_live_… (Schlüssel unter /einstellungen/api). Fehler kommen als { error: { code, message } } auf Deutsch. Rate-Limit 600 Anfragen pro Minute je Schlüssel (Header X-RateLimit-Remaining). Listen liegen unter sources, candidates, clips, publications, webhooks; Einzelobjekte unter source, candidate, clip, hook, publication.",
      contact: { name: "chopstr", url: `${baseUrl}/entwickler` },
    },
    servers: [{ url: `${baseUrl}/api/v1` }],
    tags: [
      { name: "Quellen" },
      { name: "Kandidaten" },
      { name: "Clips" },
      { name: "Publishing" },
      { name: "Markenprofile" },
      { name: "Webhooks" },
      { name: "Workspace" },
    ],
    paths,
    components: {
      securitySchemes: { apiKey: { type: "http", scheme: "bearer", bearerFormat: "chp_live_…", description: "Scopes: read, write, publish, admin" } },
      schemas: Object.fromEntries(Object.entries(SCHEMAS).map(([k, v]) => [k, toOpenApiSchema(v)])),
    },
    "x-webhook-events": WEBHOOK_EVENTS,
  };
}
