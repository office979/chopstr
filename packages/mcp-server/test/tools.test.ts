import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { connectClient, textOf } from "./helpers.js";
import { startMockApi, type MockApi } from "./mock-api.js";

let mock: MockApi;
let ctx: Awaited<ReturnType<typeof connectClient>>;

beforeAll(async () => {
  mock = await startMockApi();
  ctx = await connectClient(mock.url);
});
afterAll(async () => {
  await ctx.close();
  await mock.close();
});
beforeEach(() => mock.reset());

const WRITE_TOOLS = ["create_source_from_url", "accept_candidate", "reject_candidate", "revise_candidate", "render_clip", "write_hooks", "request_guest_approval", "publish_clip"];
const ALL_TOOLS = ["list_sources", "get_source", "create_source_from_url", "get_transcript", "list_candidates", "accept_candidate", "reject_candidate", "revise_candidate", "list_clips", "get_clip", "render_clip", "write_hooks", "request_guest_approval", "publish_clip", "get_usage"];

describe("Registrierung", () => {
  it("bietet alle Tools aus dem Vertrag mit deutschen Beschreibungen", async () => {
    const { tools } = await ctx.client.listTools();
    const names = tools.map((t) => t.name).sort();
    expect(names).toEqual([...ALL_TOOLS].sort());
    for (const t of tools) {
      expect(t.description ?? "").not.toMatch(/[–—]/);
      expect(t.description ?? "").toMatch(/[äöüß]|quelle|clip|kandidat|kontingent/i);
    }
    for (const name of WRITE_TOOLS) {
      const tool = tools.find((t) => t.name === name)!;
      expect(Object.keys((tool.inputSchema as { properties?: Record<string, unknown> }).properties ?? {})).toContain("confirm");
      expect(tool.annotations?.readOnlyHint).toBe(false);
    }
  });

  it("bietet Resources und Prompts", async () => {
    const { resourceTemplates } = await ctx.client.listResourceTemplates();
    expect(resourceTemplates.map((r) => r.uriTemplate).sort()).toEqual(["chopstr://clips/{id}/render-plan", "chopstr://sources/{id}/transcript"]);
    const { resources } = await ctx.client.listResources();
    expect(resources.map((r) => r.uri)).toContain("chopstr://usage");
    const { prompts } = await ctx.client.listPrompts();
    expect(prompts.map((p) => p.name).sort()).toEqual(["hook_brief", "review_session"]);
  });
});

describe("Lesende Tools", () => {
  it("list_sources liefert Resümee und JSON-Anhang", async () => {
    const result = await ctx.call("list_sources");
    expect(result.isError).toBeFalsy();
    expect(textOf(result)).toContain("2 Quelle(n)");
    expect(textOf(result)).toContain("Podcast Folge 12");
    expect((result.structuredContent as { sources: unknown[] }).sources).toHaveLength(2);
  });

  it("list_sources filtert nach Status und begrenzt", async () => {
    const result = await ctx.call("list_sources", { status: "ready", limit: 1 });
    expect((result.structuredContent as { total: number }).total).toBe(1);
    expect(mock.requests[0]?.query.status).toBe("ready");
  });

  it("get_source zeigt Details, 404 wird übersetzt", async () => {
    const ok = await ctx.call("get_source", { source_id: "src_1" });
    expect(textOf(ok)).toContain("Podcast Folge 12");
    const missing = await ctx.call("get_source", { source_id: "nope" });
    expect(missing.isError).toBe(true);
    expect(textOf(missing)).toMatch(/Nicht gefunden/);
  });

  it("get_transcript ohne Fenster liefert Kurzfassung mit Sprechern, Dauer, 200 Wörtern und Hinweis", async () => {
    const result = await ctx.call("get_transcript", { source_id: "src_1" });
    const text = textOf(result);
    expect(text).toContain("300 Wörter");
    expect(text).toContain("2 Sprecher");
    expect(text).toContain("Anna (SPEAKER_00)");
    expect(text).toContain("SPEAKER_01");
    expect(text).toMatch(/Fenster mit start_s und end_s/);
    const sc = result.structuredContent as { preview: string; preview_truncated: boolean; duration_s: number; windowed: boolean };
    expect(sc.preview.split(/\s+/)).toHaveLength(200);
    expect(sc.preview_truncated).toBe(true);
    expect(sc.duration_s).toBe(150);
    expect(sc.windowed).toBe(false);
  });

  it("get_transcript mit Fenster liefert nur die Wörter im Ausschnitt mit Timecodes", async () => {
    const result = await ctx.call("get_transcript", { source_id: "src_1", start_s: 60, end_s: 70 });
    const sc = result.structuredContent as { word_count: number; text: string };
    expect(sc.word_count).toBe(20);
    expect(sc.text).toMatch(/^\[1:00\] SPEAKER_01: /);
    expect(textOf(result)).toContain("1:00 bis 1:10");
    const bad = await ctx.call("get_transcript", { source_id: "src_1", start_s: 70, end_s: 60 });
    expect(textOf(bad)).toMatch(/end_s muss größer/);
  });

  it("list_candidates filtert nach gate_passed und verdict", async () => {
    const all = await ctx.call("list_candidates", { source_id: "src_1" });
    expect((all.structuredContent as { total: number }).total).toBe(3);
    expect(textOf(all)).toMatch(/cand_1 {2}Score 8,2/);
    const gated = await ctx.call("list_candidates", { source_id: "src_1", gate_passed: true, verdict: "open" });
    const sc = gated.structuredContent as { candidates: Array<{ id: string }> };
    expect(sc.candidates.map((c) => c.id)).toEqual(["cand_1"]);
    const rejected = await ctx.call("list_candidates", { source_id: "src_1", verdict: "rejected" });
    expect((rejected.structuredContent as { candidates: Array<{ id: string }> }).candidates.map((c) => c.id)).toEqual(["cand_3"]);
    const failed = await ctx.call("list_candidates", { source_id: "src_1", gate_passed: false });
    expect(textOf(failed)).toContain("Flags humor");
    expect((failed.structuredContent as { candidates: Array<{ failed_gates: string[] }> }).candidates[0]?.failed_gates[0]).toMatch(/no_open_loop/);
  });

  it("list_clips und get_clip zeigen Status, Hook, Lautheit, Provenienz, Render-Plan", async () => {
    const list = await ctx.call("list_clips", { source_id: "src_1" });
    expect(textOf(list)).toContain("3 Clip(s)");
    expect(textOf(list)).toContain("Gast-Freigabe nötig");
    expect(textOf(list)).toContain("ffmpeg ohne libass");
    const clip = await ctx.call("get_clip", { clip_id: "clip_1" });
    const text = textOf(clip);
    expect(text).toContain("-16,1 LUFS");
    expect(text).toContain("C2PA skipped");
    expect(text).toContain("Reframe talking_head");
    expect(text).toContain("results_first");
    const sc = clip.structuredContent as { media: { video: string }; render_plan: { shots: number }; hook: { variants: unknown[] } };
    expect(sc.media.video).toContain("clip_1.mp4");
    expect(sc.render_plan.shots).toBe(2);
    expect(sc.hook.variants).toHaveLength(2);
  });

  it("get_usage rechnet Minuten in Stunden um und warnt ab 80 Prozent", async () => {
    const result = await ctx.call("get_usage");
    expect(textOf(result)).toContain("10,0 von 12,0 Stunden (83 %)");
    expect(textOf(result)).toMatch(/über 80 %/);
  });
});

describe("Bestätigungspflicht", () => {
  it("accept_candidate ohne confirm liefert Vorschau und ruft die API nicht auf", async () => {
    const result = await ctx.call("accept_candidate", { candidate_id: "cand_1", platforms: ["linkedin"] });
    expect(result.isError).toBeFalsy();
    expect(textOf(result)).toMatch(/^Vorschau/);
    expect(textOf(result)).toContain("confirm: true");
    expect((result.structuredContent as { preview: boolean }).preview).toBe(true);
    expect(mock.requests).toHaveLength(0);
  });

  it("accept_candidate mit confirm sendet das Urteil und nennt die Clips", async () => {
    const result = await ctx.call("accept_candidate", { candidate_id: "cand_1", platforms: ["linkedin", "tiktok"], confirm: true });
    expect(textOf(result)).toContain("angenommen");
    expect(textOf(result)).toContain("linkedin: Clip clip_new_0");
    expect(mock.requests[0]).toMatchObject({ method: "POST", path: "/candidates/cand_1/verdict", body: { verdict: "accepted", platforms: ["linkedin", "tiktok"] } });
  });

  it("reject_candidate verlangt einen Grund und confirm", async () => {
    const noReason = await ctx.call("reject_candidate", { candidate_id: "cand_1", confirm: true });
    expect(noReason.isError).toBe(true);
    expect(mock.requests).toHaveLength(0);
    const preview = await ctx.call("reject_candidate", { candidate_id: "cand_1", reason: "zu allgemein" });
    expect(textOf(preview)).toMatch(/^Vorschau/);
    expect(mock.requests).toHaveLength(0);
    const done = await ctx.call("reject_candidate", { candidate_id: "cand_1", reason: "zu allgemein", confirm: true });
    expect(textOf(done)).toContain("abgelehnt");
    expect(mock.requests[0]?.body).toEqual({ verdict: "rejected", reason: "zu allgemein" });
  });

  it("revise_candidate prüft Titelkarte und legt neue Version an", async () => {
    const tooLong = await ctx.call("revise_candidate", { candidate_id: "cand_1", title_card: "eins zwei drei vier fünf sechs sieben acht neun", confirm: true });
    expect(textOf(tooLong)).toMatch(/höchstens 8/);
    expect(mock.requests).toHaveLength(0);
    const preview = await ctx.call("revise_candidate", { candidate_id: "cand_1", last_sent: 140 });
    expect(textOf(preview)).toMatch(/^Vorschau/);
    const done = await ctx.call("revise_candidate", { candidate_id: "cand_1", last_sent: 140, title_card: "Preise im Handwerk", confirm: true });
    expect(textOf(done)).toContain("Version 2");
    expect(mock.requests.at(-1)?.body).toEqual({ last_sent: 140, title_card: "Preise im Handwerk" });
  });

  it("render_clip ohne confirm ist eine Vorschau, mit confirm ein POST", async () => {
    await ctx.call("render_clip", { clip_id: "clip_1" });
    expect(mock.requests).toHaveLength(0);
    const done = await ctx.call("render_clip", { clip_id: "clip_1", confirm: true });
    expect(textOf(done)).toContain("rendering");
    expect(mock.requests[0]?.path).toBe("/clips/clip_1/render");
  });

  it("create_source_from_url verlangt rights_confirmed und confirm", async () => {
    const base = { title: "Neu", source_url: "https://example.org/v.mp4", source_owner: "Anna" };
    const noRights = await ctx.call("create_source_from_url", { ...base, rights_confirmed: false, confirm: true });
    expect(textOf(noRights)).toMatch(/rights_confirmed/);
    expect(mock.requests).toHaveLength(0);
    const preview = await ctx.call("create_source_from_url", { ...base, rights_confirmed: true });
    expect(textOf(preview)).toMatch(/^Vorschau/);
    expect(mock.requests).toHaveLength(0);
    const done = await ctx.call("create_source_from_url", { ...base, rights_confirmed: true, confirm: true });
    expect(textOf(done)).toContain("src_new");
    expect(mock.requests[0]?.body).toMatchObject({ upload: "url", rights_confirmed: true, source_owner: "Anna", source_url: "https://example.org/v.mp4" });
  });

  it("request_guest_approval liefert Link", async () => {
    const preview = await ctx.call("request_guest_approval", { clip_id: "clip_2", guest_name: "Max" });
    expect(textOf(preview)).toMatch(/^Vorschau/);
    const done = await ctx.call("request_guest_approval", { clip_id: "clip_2", guest_name: "Max", guest_email: "max@example.org", confirm: true });
    expect(textOf(done)).toContain("/freigabe/tok_guest");
    expect(mock.requests.at(-1)).toMatchObject({ path: "/clips/clip_2/guest-approval", body: { guest_name: "Max", guest_email: "max@example.org" } });
  });

  it("publish_clip: Vorschau, dann Veröffentlichung, 409 ohne Gast-Freigabe übersetzt", async () => {
    const preview = await ctx.call("publish_clip", { clip_id: "clip_1", connection_id: "conn_1", scheduled_for: "2099-01-01T09:00:00+01:00" });
    expect(textOf(preview)).toMatch(/^Vorschau/);
    expect(mock.requests).toHaveLength(0);
    const done = await ctx.call("publish_clip", { clip_id: "clip_1", connection_id: "conn_1", scheduled_for: "2099-01-01T09:00:00+01:00", confirm: true });
    expect(textOf(done)).toContain("pub_1");
    expect(textOf(done)).toContain("scheduled");
    const blocked = await ctx.call("publish_clip", { clip_id: "clip_2", connection_id: "conn_1", confirm: true });
    expect(blocked.isError).toBe(true);
    expect(textOf(blocked)).toMatch(/Gast-Freigabe/);
    const past = await ctx.call("publish_clip", { clip_id: "clip_1", connection_id: "conn_1", scheduled_for: "2000-01-01T09:00:00Z", confirm: true });
    expect(textOf(past)).toMatch(/Vergangenheit/);
  });
});

describe("write_hooks", () => {
  it("Vorschau zeigt Varianten und Prüfergebnis, speichert nichts", async () => {
    const result = await ctx.call("write_hooks", { clip_id: "clip_1", spoken_hook: "Stunden sauber rechnen, sonst geht Marge verloren", onscreen_hook: "Stunden sauber rechnen" });
    expect(textOf(result)).toMatch(/^Vorschau/);
    expect(textOf(result)).toContain("Wortlimits eingehalten");
    expect(textOf(result)).toContain("KI-Varianten");
    expect(mock.requests.map((r) => r.method)).toEqual(["GET"]);
  });

  it("meldet Wortlimit-Verstöße und speichert nicht", async () => {
    const result = await ctx.call("write_hooks", {
      clip_id: "clip_1",
      spoken_hook: "eins zwei drei vier fünf sechs sieben acht neun zehn elf zwölf dreizehn",
      onscreen_hook: "eins zwei drei vier fünf sechs sieben acht neun zehn",
      confirm: true,
    });
    const sc = result.structuredContent as { saved: boolean; violations: Array<{ field: string; words: number }> };
    expect(sc.saved).toBe(false);
    expect(sc.violations.map((v) => `${v.field}:${v.words}`)).toEqual(["spoken_hook:13", "onscreen_hook:10"]);
    expect(textOf(result)).toContain("13 Wörter, erlaubt sind höchstens 12");
    expect(textOf(result)).toContain("10 Wörter, erlaubt sind höchstens 9");
    expect(mock.requests).toHaveLength(0);
  });

  it("speichert bei gültigen Hooks und meldet Claim-Hinweise und Re-Render", async () => {
    const result = await ctx.call("write_hooks", { clip_id: "clip_1", spoken_hook: "40 Prozent Marge weg, weil Stunden fehlen", onscreen_hook: "Marge weg", pattern: "results_first", confirm: true });
    const sc = result.structuredContent as { saved: boolean; needs_render: boolean };
    expect(sc.saved).toBe(true);
    expect(sc.needs_render).toBe(true);
    expect(textOf(result)).toContain("Version 2");
    expect(textOf(result)).toContain("Zahl nicht im Clip");
    expect(textOf(result)).toMatch(/Re-Render/);
    expect(mock.requests[0]).toMatchObject({ method: "POST", path: "/clips/clip_1/hooks", body: { spoken_hook: "40 Prozent Marge weg, weil Stunden fehlen", pattern: "results_first" } });
  });
});

describe("Resources und Prompts", () => {
  it("liest das Transkript als Text mit Sprechern und Timecodes", async () => {
    const result = await ctx.client.readResource({ uri: "chopstr://sources/src_1/transcript" });
    const text = (result.contents[0] as { text: string }).text;
    expect(text).toMatch(/^Transkript Quelle src_1, Version 3/);
    expect(text).toContain("[0:00] Anna:");
    expect(text).toContain("[1:00] SPEAKER_01:");
  });

  it("liest Render-Plan und Kontingent als JSON", async () => {
    const plan = await ctx.client.readResource({ uri: "chopstr://clips/clip_1/render-plan" });
    expect(JSON.parse((plan.contents[0] as { text: string }).text).contract).toBe("render_plan_v1");
    const usage = await ctx.client.readResource({ uri: "chopstr://usage" });
    expect(JSON.parse((usage.contents[0] as { text: string }).text).included_minutes).toBe(720);
  });

  it("Prompts enthalten die Regeln", async () => {
    const review = await ctx.client.getPrompt({ name: "review_session", arguments: { source_id: "src_1" } });
    const reviewText = (review.messages[0]?.content as { text: string }).text;
    expect(reviewText).toContain("src_1");
    for (const rule of ["Eigenständigkeit", "Sinntreue", "Keine Zahl ohne Beleg", "Humor ist immer Mensch"]) expect(reviewText).toContain(rule);
    const brief = await ctx.client.getPrompt({ name: "hook_brief", arguments: { address: "sie", country: "AT", platform: "linkedin", clip_text: "Text" } });
    const briefText = (brief.messages[0]?.content as { text: string }).text;
    expect(briefText).toContain("Anrede: sie. Land: AT. Plattform: linkedin.");
    expect(briefText).toContain("max. 12 Wörter");
    expect(briefText).toContain("CLIP:\nText");
  });
});
