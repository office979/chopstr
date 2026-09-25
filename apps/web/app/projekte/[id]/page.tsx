import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ id: string }> };

/* Diese Seite gibt es nicht mehr, ihre Adresse schon.
 *
 * Sie zeigte den Fortschritt der Analyse: fünf Häkchen mit Zeitstempeln, „Der Computer ist
 * fertig". Solange gerechnet wird, ist das die Antwort auf die einzige Frage, die jemand hat -
 * wie lange noch. Danach war es ein Datenblatt über einen abgeschlossenen Vorgang, und man musste
 * trotzdem darüber, um zu den Clips zu kommen: ein Klick auf das Video führte hierher, und von
 * hier noch einmal weiter.
 *
 * Der Fortschritt steht jetzt in der Clip-Liste, solange es keine Clips gibt, und verschwindet
 * von selbst, sobald welche da sind. Hier bleibt nur die Weiterleitung, damit alte Links und
 * Lesezeichen weiter funktionieren.
 */
export default async function ProjectPage({ params }: Props) {
  const { id } = await params;
  redirect(`/projekte/${id}/clips`);
}
