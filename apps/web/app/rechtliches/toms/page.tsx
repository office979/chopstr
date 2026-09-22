import { loadLegalDoc } from "@/lib/legal/docs";
import { Markdown } from "@/lib/legal/Markdown";
import { LegalShell } from "../LegalShell";

export const dynamic = "force-dynamic";
export const metadata = { title: "TOMs" };

export default function TomsPage() {
  const doc = loadLegalDoc("toms");
  return (
    <LegalShell current="toms" doc={doc} title="Technische und organisatorische Maßnahmen" eyebrow="Rechtliches · Anlage zum AVV">
      {doc && <Markdown source={doc.markdown} />}
    </LegalShell>
  );
}
