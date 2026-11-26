import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ id: string; clipId: string }> };

/* Die Einzelbearbeitung eines Clips gibt es nicht mehr. Clips entstehen fertig; geändert wird der
 * Stil aller Clips eines Videos auf der Galerie. Alte Links führen dorthin. */
export default async function ClipPage({ params }: Props) {
  const { id } = await params;
  redirect(`/projekte/${id}/clips`);
}
