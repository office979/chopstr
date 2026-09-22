import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { requireApiRole } from "@/lib/auth/guard";
import type { PostCaptions, SaveHookInput } from "@/lib/repo/types";
import { PLATFORMS, isHookPattern } from "@/lib/clips/labels";
import { clipFeatures, recordDecision } from "@/lib/decision-log";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string; clipId: string }> };

interface HookBody {
  spoken_hook?: unknown;
  onscreen_hook?: unknown;
  pattern?: unknown;
  post_captions?: unknown;
  cta?: unknown;
}

const MAX_HOOK_CHARS = 300;
const MAX_CAPTION_CHARS = 3000;

function text(v: unknown, max: number): string {
  return typeof v === "string" ? v.trim().slice(0, max) : "";
}

/* POST: neue manuelle Hook-Version (origin manual) aus dem Hook-Studio. Linter und Claim-Check laufen im Repository. */
export async function POST(request: NextRequest, { params }: Params) {
  const auth = await requireApiRole("hook.edit");
  if (auth instanceof Response) return auth;
  const { id, clipId } = await params;
  const repo = getRepo();
  const clip = await repo.getClip(clipId);
  if (!clip || clip.source_id !== id) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });

  let body: HookBody;
  try {
    body = (await request.json()) as HookBody;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }

  const spoken = text(body.spoken_hook, MAX_HOOK_CHARS);
  const onscreen = text(body.onscreen_hook, MAX_HOOK_CHARS);
  if (!spoken && !onscreen) {
    return Response.json({ error: "Gesprochener oder On-Screen-Hook darf nicht leer sein" }, { status: 400 });
  }
  const captions: PostCaptions = {};
  if (body.post_captions && typeof body.post_captions === "object") {
    const raw = body.post_captions as Record<string, unknown>;
    for (const p of PLATFORMS) {
      if (typeof raw[p] === "string") captions[p] = text(raw[p], MAX_CAPTION_CHARS);
    }
  }
  const input: SaveHookInput = {
    spoken_hook: spoken,
    onscreen_hook: onscreen,
    pattern: isHookPattern(body.pattern) ? body.pattern : null,
    post_captions: captions,
    cta: text(body.cta, MAX_HOOK_CHARS),
  };

  const version = await repo.saveHook(clipId, input);
  /* Decision Log (A3): gewählter Hook mit Muster, verworfene Varianten als Alternativen */
  const source = await repo.getSource(id);
  const shownVariants = [...(await repo.listHookVersions(clipId))].reverse().find((v) => v.variants.length > 0)?.variants ?? [];
  await recordDecision({
    decision_type: "hook_selected",
    actor_type: "user",
    brand_profile_id: source?.brand_profile_id ?? null,
    source_id: id,
    candidate_id: clip.candidate_id,
    clip_id: clipId,
    features: { ...clipFeatures(clip, version), patterns: shownVariants.map((v) => v.pattern), version: version.version, lint_notes: version.lint_notes.length, claim_issues: version.claim_issues.length },
    alternatives: shownVariants.filter((v) => v.spoken !== spoken || v.onscreen !== onscreen).map((v) => ({ pattern: v.pattern, spoken: v.spoken })),
    chosen: { pattern: version.pattern, spoken: version.spoken_hook, onscreen: version.onscreen_hook, cta: version.cta },
  });
  await repo.audit({
    action: "hook.saved",
    entity: "hook_versions",
    entity_id: version.id,
    payload: {
      source_id: id,
      clip_id: clipId,
      version: version.version,
      pattern: version.pattern,
      lint_notes: version.lint_notes.length,
      claim_issues: version.claim_issues.length,
    },
  });
  return Response.json({ ok: true, hook: version, needs_render: clip.status === "rendered" || clip.status === "exported" });
}
