/* Tools für Clips: Liste, Details, Render, Hooks, Gast-Freigabe. */

import { z } from "zod";
import { confirmSchema, guarded, idSchema, type ToolContext } from "./common.js";
import { formatDecimal, limitList, previewResult, textResult, truncationNote, unwrapList, unwrapObject } from "../format.js";
import { checkHookLimits, ONSCREEN_HOOK_MAX_WORDS, SPOKEN_HOOK_MAX_WORDS, styleNotes } from "../hooks.js";
import type { Clip, HookVersion, RenderPlan } from "../types.js";

export function clipPath(id: string): string {
  return `/clips/${encodeURIComponent(id)}`;
}

export async function fetchClip(api: ToolContext["api"], clipId: string): Promise<{ clip: Clip; hook: HookVersion | null; raw: Record<string, unknown> }> {
  const body = await api.get<unknown>(clipPath(clipId));
  const raw = (body && typeof body === "object" ? body : {}) as Record<string, unknown>;
  const clip = unwrapObject<Clip>(body, "clip");
  const hookRaw = (raw.hook ?? clip.hook ?? null) as HookVersion | null;
  return { clip, hook: hookRaw && typeof hookRaw === "object" ? hookRaw : null, raw };
}

export function renderPlanBrief(plan: RenderPlan | null | undefined): Record<string, unknown> | null {
  if (!plan) return null;
  return {
    contract: plan.contract ?? null,
    platform: plan.platform ?? null,
    aspect: plan.aspect ?? null,
    output: plan.output ?? null,
    segments: plan.segments ?? null,
    reframe_strategy: plan.reframe?.strategy ?? null,
    faces_detected: plan.reframe?.faces_detected ?? null,
    shots: Array.isArray(plan.shots) ? plan.shots.length : null,
    captions_preset: plan.captions?.preset ?? null,
    caption_cards: plan.captions?.cards ?? null,
    title_card: plan.title_card ?? null,
    hook_overlay: plan.hook_overlay ?? null,
    audio: plan.audio ?? null,
  };
}

function mediaUrls(clip: Clip, raw: Record<string, unknown>): Record<string, string | null> {
  const media = (raw.media ?? clip.media ?? null) as Record<string, string | null> | null;
  const pick = (...keys: string[]): string | null => {
    for (const k of keys) {
      const fromMedia = media?.[k];
      if (typeof fromMedia === "string") return fromMedia;
      const direct = (raw[k] ?? clip[k]) as unknown;
      if (typeof direct === "string") return direct;
    }
    return null;
  };
  return {
    video: pick("video_url", "file_url", "video", "mp4"),
    poster: pick("poster_url", "poster"),
    srt: pick("srt_url", "srt"),
    vtt: pick("vtt_url", "vtt"),
  };
}

function clipLine(c: Clip): string {
  const duration = c.duration_s ? `, ${formatDecimal(c.duration_s)} s` : "";
  const guest = c.guest_approval_required ? ", Gast-Freigabe nötig" : "";
  const err = c.status === "failed" && c.render_error ? ` Fehler: ${c.render_error}` : "";
  return `${c.id}  ${c.platform ?? "?"} ${c.aspect ?? ""}  [${c.status ?? "?"}${duration}${guest}]${err}`;
}

export function registerClipTools({ server, api }: ToolContext): void {
  server.registerTool(
    "list_clips",
    {
      title: "Clips auflisten",
      description: "Listet die Clips einer Quelle mit Plattform, Format, Status, Dauer und Hinweis auf verlangte Gast-Freigabe. Optional nach Status filtern (draft, rendering, rendered, exported, failed). Höchstens 50 Einträge.",
      inputSchema: {
        source_id: idSchema.describe("ID der Quelle"),
        status: z.string().optional().describe("Nur Clips mit diesem Status"),
        limit: z.number().int().min(1).max(50).optional().describe("Höchstzahl, Standard 50"),
      },
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async ({ source_id, status, limit }) =>
      guarded(async () => {
        const body = await api.get<unknown>(`/sources/${encodeURIComponent(source_id)}/clips`, { status });
        let clips = unwrapList<Clip>(body, "clips");
        if (status) clips = clips.filter((c) => !c.status || c.status === status);
        const t = limitList(clips, limit ?? 50);
        const summary = t.items.length === 0 ? "Keine Clips gefunden." : `${t.total} Clip(s) für Quelle ${source_id}:\n` + t.items.map(clipLine).join("\n") + truncationNote(t, "Clips");
        return textResult(summary, {
          source_id,
          total: t.total,
          truncated: t.truncated,
          clips: t.items.map((c) => ({
            id: c.id,
            candidate_id: c.candidate_id ?? null,
            platform: c.platform ?? null,
            aspect: c.aspect ?? null,
            status: c.status ?? null,
            duration_s: c.duration_s ?? null,
            guest_approval_required: c.guest_approval_required ?? false,
            render_error: c.render_error ?? null,
            rendered_at: c.rendered_at ?? null,
          })),
        });
      }),
  );

  server.registerTool(
    "get_clip",
    {
      title: "Clip anzeigen",
      description: "Details eines Clips: Status, Medien-URLs, aktueller Hook mit Varianten und Post-Texten, Lautheit, Provenienz (C2PA, KI-Kennzeichnung, Quellen-Credit, Werbelabel), Lesetempo-Warnungen und Kurzfassung des Render-Plans. Der vollständige Render-Plan liegt als Resource chopstr://clips/{id}/render-plan vor.",
      inputSchema: { clip_id: idSchema.describe("ID des Clips") },
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async ({ clip_id }) =>
      guarded(async () => {
        const { clip, hook, raw } = await fetchClip(api, clip_id);
        const media = mediaUrls(clip, raw);
        const loud = clip.loudness ? `${formatDecimal(clip.loudness.integrated_lufs ?? null)} LUFS, True Peak ${formatDecimal(clip.loudness.true_peak_dbtp ?? null)} dBTP (Preset ${clip.loudness.preset ?? "?"})` : "noch nicht gemessen";
        const prov = clip.provenance;
        const provText = prov
          ? `C2PA ${prov.c2pa ?? "?"}${prov.reason ? ` (${prov.reason})` : ""}, KI-Kennzeichnung ${prov.ai_label_required ? "nötig" : "nicht nötig"}${prov.source_credit ? `, Credit „${prov.source_credit}“` : ""}${prov.ad_label ? `, Werbelabel „${prov.ad_label}“` : ""}`
          : "keine Angaben";
        const plan = renderPlanBrief(clip.render_plan ?? null);
        const lines = [
          `Clip ${clip.id ?? clip_id}: ${clip.platform ?? "?"} ${clip.aspect ?? ""}, Status ${clip.status ?? "?"}${clip.duration_s ? `, ${formatDecimal(clip.duration_s)} s` : ""}${clip.width && clip.height ? `, ${clip.width}×${clip.height}` : ""}`,
          clip.render_error ? `Render-Fehler: ${clip.render_error}` : null,
          clip.guest_approval_required ? `Gast-Freigabe: verlangt${clip.guest_approval?.decision ? `, Entscheidung ${clip.guest_approval.decision}` : ", steht aus"}` : null,
          hook ? `Hook (Version ${hook.version ?? "?"}, ${hook.origin ?? "?"}, Muster ${hook.pattern ?? "?"}): gesprochen „${hook.spoken_hook ?? ""}“, im Bild „${hook.onscreen_hook ?? ""}“` : "Hook: noch keine Version",
          hook && (hook.claim_issues ?? []).length ? `Claim-Hinweise: ${(hook.claim_issues ?? []).join("; ")}` : null,
          hook && (hook.lint_notes ?? []).length ? `Linter: ${(hook.lint_notes ?? []).join("; ")}` : null,
          `Lautheit: ${loud}`,
          `Provenienz: ${provText}`,
          (clip.cps_warnings ?? []).length ? `Lesetempo: ${(clip.cps_warnings ?? []).join("; ")}` : null,
          plan ? `Render-Plan: Reframe ${plan.reframe_strategy ?? "?"}, Captions ${plan.captions_preset ?? "?"} (${plan.caption_cards ?? "?"} Karten), ${plan.title_card ? "Titelkarte" : "keine Titelkarte"}, ${plan.hook_overlay ? "Hook-Overlay" : "kein Hook-Overlay"}` : "Render-Plan: noch keiner",
          media.video ? `Video: ${media.video}` : null,
        ].filter((l): l is string => Boolean(l));
        return textResult(lines.join("\n"), {
          clip: {
            id: clip.id ?? clip_id,
            source_id: clip.source_id ?? null,
            candidate_id: clip.candidate_id ?? null,
            platform: clip.platform ?? null,
            aspect: clip.aspect ?? null,
            status: clip.status ?? null,
            duration_s: clip.duration_s ?? null,
            width: clip.width ?? null,
            height: clip.height ?? null,
            fps: clip.fps ?? null,
            title_card: clip.title_card ?? null,
            ad_label: clip.ad_label ?? null,
            guest_approval_required: clip.guest_approval_required ?? false,
            guest_approval: clip.guest_approval ?? null,
            render_error: clip.render_error ?? null,
            rendered_at: clip.rendered_at ?? null,
            cps_warnings: clip.cps_warnings ?? [],
            fidelity_warnings: clip.fidelity_warnings ?? [],
          },
          media,
          hook: hook
            ? {
                version: hook.version ?? null,
                origin: hook.origin ?? null,
                pattern: hook.pattern ?? null,
                spoken_hook: hook.spoken_hook ?? null,
                onscreen_hook: hook.onscreen_hook ?? null,
                cta: hook.cta ?? null,
                post_captions: hook.post_captions ?? {},
                variants: hook.variants ?? [],
                lint_notes: hook.lint_notes ?? [],
                claim_issues: hook.claim_issues ?? [],
              }
            : null,
          loudness: clip.loudness ?? null,
          provenance: clip.provenance ?? null,
          render_plan: plan,
        });
      }),
  );

  server.registerTool(
    "render_clip",
    {
      title: "Clip rendern",
      description: "Startet den Render oder Re-Render eines Clips (zum Beispiel nach einer neuen Hook-Version). Schreibende Aktion: nur mit confirm: true, sonst Vorschau.",
      inputSchema: { clip_id: idSchema.describe("ID des Clips"), confirm: confirmSchema },
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async ({ clip_id, confirm }) =>
      guarded(async () => {
        if (confirm !== true) {
          return previewResult("render_clip", `Render für Clip ${clip_id} starten. Ein bestehendes Ergebnis wird durch den neuen Render ersetzt.`, { clip_id });
        }
        const body = await api.post<unknown>(`${clipPath(clip_id)}/render`, {});
        const record = (body && typeof body === "object" ? body : {}) as Record<string, unknown>;
        const status = typeof record.status === "string" ? record.status : "rendering";
        return textResult(`Render für Clip ${clip_id} angestoßen (Status ${status}). Fortschritt mit get_clip prüfen.`, { clip_id, status, response: record });
      }),
  );

  server.registerTool(
    "write_hooks",
    {
      title: "Hooks schreiben",
      description:
        `Speichert eine manuelle Hook-Version für einen Clip: gesprochener Hook (höchstens ${SPOKEN_HOOK_MAX_WORDS} Wörter), On-Screen-Hook (höchstens ${ONSCREEN_HOOK_MAX_WORDS} Wörter), optional Muster, Post-Texte je Plattform und CTA. Ohne confirm liefert das Tool die vorhandenen KI-Varianten des Clips und das Prüfergebnis der Wortlimits als Vorschau. Verstöße gegen die Wortlimits werden gemeldet und nicht gespeichert. Jede Behauptung muss durch den Clip-Text gedeckt sein (keine Zahl ohne Beleg). Nach dem Speichern ist ein Re-Render nötig (render_clip).`,
      inputSchema: {
        clip_id: idSchema.describe("ID des Clips"),
        spoken_hook: z.string().max(300).optional().describe(`Gesprochener Hook, höchstens ${SPOKEN_HOOK_MAX_WORDS} Wörter`),
        onscreen_hook: z.string().max(300).optional().describe(`Text im Bild, höchstens ${ONSCREEN_HOOK_MAX_WORDS} Wörter`),
        pattern: z.enum(["identity_call", "contrarian", "open_loop", "results_first", "mistake_warning"]).optional().describe("Hook-Muster"),
        post_captions: z
          .object({ tiktok: z.string().max(3000).optional(), reels: z.string().max(3000).optional(), shorts: z.string().max(3000).optional(), linkedin: z.string().max(3000).optional() })
          .optional()
          .describe("Post-Texte je Plattform"),
        cta: z.string().max(300).optional().describe("Handlungsaufforderung"),
        confirm: confirmSchema,
      },
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async (input) =>
      guarded(async () => {
        const spoken = (input.spoken_hook ?? "").trim();
        const onscreen = (input.onscreen_hook ?? "").trim();
        const violations = checkHookLimits({ spoken_hook: spoken, onscreen_hook: onscreen });
        const notes = [...styleNotes(spoken).map((n) => `gesprochener Hook ${n}`), ...styleNotes(onscreen).map((n) => `On-Screen-Hook ${n}`)];

        if (input.confirm !== true) {
          const { hook } = await fetchClip(api, input.clip_id);
          const variantLines = (hook?.variants ?? []).map((v, i) => `  ${i + 1}. [${v.pattern ?? "?"}] gesprochen: „${v.spoken ?? ""}“ | im Bild: „${v.onscreen ?? ""}“${(v.claim_issues ?? []).length ? ` (Claim-Hinweis: ${(v.claim_issues ?? []).join("; ")})` : ""}`);
          const check = violations.length ? `Wortlimit verletzt:\n  ${violations.map((v) => v.message).join("\n  ")}` : spoken || onscreen ? "Wortlimits eingehalten." : "Noch kein Hook-Text angegeben.";
          const description = [
            `Manuelle Hook-Version für Clip ${input.clip_id} speichern.`,
            spoken ? `Gesprochen: „${spoken}“` : null,
            onscreen ? `Im Bild: „${onscreen}“` : null,
            check,
            notes.length ? `Stilhinweise: ${notes.join("; ")}` : null,
            hook ? `Aktuelle Version ${hook.version ?? "?"} (${hook.origin ?? "?"}): „${hook.spoken_hook ?? ""}“ / „${hook.onscreen_hook ?? ""}“` : "Noch keine Hook-Version vorhanden.",
            variantLines.length ? `KI-Varianten:\n${variantLines.join("\n")}` : null,
          ]
            .filter((l): l is string => Boolean(l))
            .join("\n");
          return previewResult("write_hooks", description, {
            clip_id: input.clip_id,
            input: { spoken_hook: spoken || null, onscreen_hook: onscreen || null, pattern: input.pattern ?? null, post_captions: input.post_captions ?? {}, cta: input.cta ?? null },
            limits: { spoken_max_words: SPOKEN_HOOK_MAX_WORDS, onscreen_max_words: ONSCREEN_HOOK_MAX_WORDS },
            violations,
            style_notes: notes,
            current_hook: hook ? { version: hook.version ?? null, origin: hook.origin ?? null, spoken_hook: hook.spoken_hook ?? null, onscreen_hook: hook.onscreen_hook ?? null } : null,
            variants: hook?.variants ?? [],
          });
        }

        if (!spoken && !onscreen) return textResult("Gesprochener oder On-Screen-Hook muss angegeben sein.", { error: "hook_required" });
        if (violations.length) {
          return textResult(`Nicht gespeichert. ${violations.map((v) => v.message).join(" ")} Bitte kürzen und erneut aufrufen.`, {
            saved: false,
            violations,
            limits: { spoken_max_words: SPOKEN_HOOK_MAX_WORDS, onscreen_max_words: ONSCREEN_HOOK_MAX_WORDS },
          });
        }
        const payload: Record<string, unknown> = { spoken_hook: spoken, onscreen_hook: onscreen };
        if (input.pattern) payload.pattern = input.pattern;
        if (input.post_captions) payload.post_captions = input.post_captions;
        if (input.cta) payload.cta = input.cta.trim();
        const body = await api.post<unknown>(`${clipPath(input.clip_id)}/hooks`, payload);
        const record = (body && typeof body === "object" ? body : {}) as Record<string, unknown>;
        const hook = unwrapObject<HookVersion>(record.hook ?? record, "hook");
        const lint = hook.lint_notes ?? [];
        const claims = hook.claim_issues ?? [];
        const needsRender = record.needs_render === true;
        return textResult(
          [
            `Hook-Version ${hook.version ?? "?"} für Clip ${input.clip_id} gespeichert.`,
            claims.length ? `Claim-Check: ${claims.join("; ")}` : "Claim-Check ohne Beanstandung.",
            lint.length ? `Linter: ${lint.join("; ")}` : null,
            notes.length ? `Stilhinweise: ${notes.join("; ")}` : null,
            needsRender ? "Der Clip war bereits gerendert: Re-Render mit render_clip nötig, damit der neue Hook im Video landet." : "Beim nächsten Render wird diese Version verwendet.",
          ]
            .filter((l): l is string => Boolean(l))
            .join("\n"),
          { saved: true, clip_id: input.clip_id, hook: hook as Record<string, unknown>, needs_render: needsRender, style_notes: notes },
        );
      }),
  );

  server.registerTool(
    "request_guest_approval",
    {
      title: "Gast-Freigabe anfordern",
      description:
        "Fordert für einen Clip die Freigabe der gezeigten Person an (Persönlichkeitsrecht). chopstr erzeugt einen Freigabe-Link (14 Tage gültig) und sendet ihn per E-Mail, falls eine Adresse angegeben ist. Bis zur Freigabe sind Export und Veröffentlichung gesperrt. Schreibende Aktion: nur mit confirm: true, sonst Vorschau.",
      inputSchema: {
        clip_id: idSchema.describe("ID des Clips"),
        guest_name: z.string().min(1).max(120).describe("Name der Person"),
        guest_email: z.string().email().optional().describe("E-Mail der Person, optional"),
        message: z.string().max(1000).optional().describe("Persönliche Nachricht an die Person"),
        confirm: confirmSchema,
      },
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true },
    },
    async ({ clip_id, guest_name, guest_email, message, confirm }) =>
      guarded(async () => {
        const payload = { guest_name: guest_name.trim(), guest_email: guest_email ?? null, message: (message ?? "").trim() };
        if (confirm !== true) {
          return previewResult("request_guest_approval", `Gast-Freigabe für Clip ${clip_id} bei ${payload.guest_name}${guest_email ? ` (${guest_email}, E-Mail wird versendet)` : " (kein Versand, Link zum Kopieren)"} anfordern.`, { clip_id, payload });
        }
        const body = await api.post<unknown>(`${clipPath(clip_id)}/guest-approval`, payload);
        const record = (body && typeof body === "object" ? body : {}) as Record<string, unknown>;
        const approval = unwrapObject<Record<string, unknown>>(record.approval ?? record, "approval");
        const link = typeof record.link === "string" ? record.link : typeof approval.link === "string" ? approval.link : typeof approval.url === "string" ? approval.url : null;
        return textResult(
          [`Gast-Freigabe für Clip ${clip_id} angefordert (${payload.guest_name}).`, link ? `Freigabe-Link: ${link}` : "Der Freigabe-Link steht in der Web-App bereit.", approval.expires_at ? `Gültig bis ${String(approval.expires_at)}.` : null, guest_email ? "E-Mail wurde versendet." : "Kein E-Mail-Versand: Link bitte selbst weitergeben."].filter((l): l is string => Boolean(l)).join("\n"),
          { clip_id, approval, link },
        );
      }),
  );
}
