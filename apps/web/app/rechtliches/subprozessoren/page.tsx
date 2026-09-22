import Link from "next/link";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { getRepo } from "@/lib/repo";
import { getSession } from "@/lib/session";
import { filterSubprocessors, loadLegalDoc } from "@/lib/legal/docs";
import { Markdown } from "@/lib/legal/Markdown";
import { LegalShell } from "../LegalShell";

export const dynamic = "force-dynamic";
export const metadata = { title: "Subprozessoren" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

/* Subprozessor-Liste je Tarif: Standard (mit AWS Bedrock EU und Supabase) oder Sovereign (ohne US-Anbieter) */
export default async function SubprocessorsPage({ searchParams }: { searchParams: SearchParams }) {
  const doc = loadLegalDoc("subprozessoren");
  const q = await searchParams;
  const session = await getSession();
  const workspace = session ? await getRepo().getWorkspace() : null;
  const requested = q.tarif === "sovereign" ? "sovereign" : q.tarif === "standard" ? "standard" : q.tarif === "alle" ? null : undefined;
  const tier = requested === undefined ? (workspace?.tier ?? null) : requested;
  const markdown = doc ? filterSubprocessors(doc.markdown, tier) : "";

  const aside = (
    <GlassCard padding="lg" className="flex flex-col gap-3">
      <h2 className="text-lg font-medium">Tarif</h2>
      {workspace && (
        <p className="text-sm text-text-2">
          Dein Workspace läuft im Tarif <Badge className="ml-1">{workspace.tier === "sovereign" ? "Sovereign" : "Standard"}</Badge>
        </p>
      )}
      <div className="flex flex-wrap gap-2 text-sm">
        {(
          [
            ["standard", "Standard"],
            ["sovereign", "Sovereign"],
            ["alle", "Beide"],
          ] as const
        ).map(([value, label]) => (
          <Link
            key={value}
            href={`/rechtliches/subprozessoren?tarif=${value}`}
            className={`transition-soft rounded-pill border px-3 py-1.5 ${(tier ?? "alle") === value ? "border-white/40 bg-white/10 text-text" : "border-line text-text-2 hover:text-text"}`}
          >
            {label}
          </Link>
        ))}
      </div>
      <p className="text-xs text-text-2">Änderungen an der Liste werden mindestens 30 Tage vorab per E-Mail angekündigt (AVV, Abschnitt 5).</p>
    </GlassCard>
  );

  return (
    <LegalShell current="subprozessoren" doc={doc} title="Subprozessoren" eyebrow="Rechtliches · Anlage zum AVV" aside={aside}>
      {doc && <Markdown source={markdown} />}
    </LegalShell>
  );
}
